"""목표일이 2026 이상인 행의 정답값(2026 측정)이 격리·사후 검증(live) 밖에 저장되지 않음을 검사한다.

'정답 표' = 목표일 열(target_date)과 정답값 열(target_cells·target_log·target·y_true)이 함께 있는 표.
그런 표에서 목표일 ≥ 2026-01-01 이면서 정답값이 비어 있지 않은 행이 하나라도 있으면 실패한다.

검사 대상
- data/processed/ 아래 parquet·csv(실험 캐시 data/processed/exp/ 포함)
- submission_package/ 아래 parquet·csv·json
- dist/ 아래 zip 안의 parquet·csv·json
- git 추적 파일 중 parquet·csv·json
허용(live): data/processed/test_targets_DO_NOT_USE.parquet(격리 파일),
data/processed/posthoc_2026.parquet·posthoc_2026_v2.parquet(동결 모델 사후 검증 산출물, eval/live 통로).
제외: data/raw/(측정 시계열 원자료 — 2026 test 피처 계산에 필요한 입력이며 목표일 정렬 표가 아님),
마크다운 보고서(집계·서술).
"""

from __future__ import annotations

import io
import json
import subprocess
import zipfile
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = pd.Timestamp("2026-01-01")
VALUE_COLS = ("target_cells", "target_log", "target", "y_true")
ALLOWED = {
    "data/processed/test_targets_DO_NOT_USE.parquet",
    "data/processed/posthoc_2026.parquet",
    "data/processed/posthoc_2026_v2.parquet",
}
TABLE_SUFFIX = (".parquet", ".csv", ".json")


def offending_rows(df: pd.DataFrame) -> int:
    """목표일 ≥ 2026 이면서 정답값이 있는 행 수(정답 표가 아니면 0)."""
    dcol = (
        "target_date" if "target_date" in df.columns else ("base_date" if "base_date" in df.columns else None)
    )
    vcols = [c for c in VALUE_COLS if c in df.columns]
    if dcol is None or not vcols:
        return 0
    td = pd.to_datetime(df[dcol], errors="coerce")  # 기준일 ≥ 2026 이면 목표일도 2026 이후
    has = df[vcols].apply(pd.to_numeric, errors="coerce").notna().any(axis=1)
    return int(((td >= CUTOFF) & has).sum())


def _json_tables(obj: object) -> list[pd.DataFrame]:
    """JSON 안의 '딕셔너리 리스트'를 표로 모은다."""
    out: list[pd.DataFrame] = []
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            out.append(pd.DataFrame(obj))
        for x in obj:
            out += _json_tables(x)
    elif isinstance(obj, dict):
        for v in obj.values():
            out += _json_tables(v)
    return out


def check_bytes(name: str, data: bytes) -> int:
    """파일 내용(바이트)에서 위반 행 수를 센다."""
    low = name.lower()
    if low.endswith(".parquet"):
        schema = pq.read_schema(io.BytesIO(data)).names
        dcol = "target_date" if "target_date" in schema else ("base_date" if "base_date" in schema else None)
        if dcol is None or not any(c in schema for c in VALUE_COLS):
            return 0
        cols = [dcol, *[c for c in VALUE_COLS if c in schema]]
        return offending_rows(pd.read_parquet(io.BytesIO(data), columns=cols))
    if low.endswith(".csv"):
        head = data[:4096].decode("utf-8-sig", errors="ignore").splitlines()[:1]
        if not head or ("target_date" not in head[0] and "base_date" not in head[0]):
            return 0
        return offending_rows(pd.read_csv(io.BytesIO(data), encoding="utf-8-sig", low_memory=False))
    if low.endswith(".json"):
        try:
            obj = json.loads(data.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            return 0
        return sum(offending_rows(t) for t in _json_tables(obj))
    return 0


def check_path(p: Path) -> int:
    if p.suffix.lower() == ".parquet":  # 큰 parquet 은 스키마만 먼저 본다
        schema = pq.read_schema(p).names
        dcol = "target_date" if "target_date" in schema else ("base_date" if "base_date" in schema else None)
        if dcol is None or not any(c in schema for c in VALUE_COLS):
            return 0
        cols = [dcol, *[c for c in VALUE_COLS if c in schema]]
        return offending_rows(pd.read_parquet(p, columns=cols))
    return check_bytes(p.name, p.read_bytes())


def _rel(p: Path) -> str:
    return p.resolve().relative_to(ROOT).as_posix()


def _scan(paths: list[Path]) -> dict[str, int]:
    bad = {}
    for p in paths:
        rel = _rel(p)
        if rel in ALLOWED:
            continue
        n = check_path(p)
        if n:
            bad[rel] = n
    return bad


# ---------------------------------------------------------------- 검사 함수 자체의 단위 테스트
def test_detector_flags_2026_targets_only() -> None:
    df = pd.DataFrame(
        {
            "target_date": ["2025-12-30", "2026-01-05", "2026-05-11"],
            "target_cells": [1.0, 2.0, None],
            "pred_cells": [1, 1, 1],
        }
    )
    assert offending_rows(df) == 1
    assert offending_rows(df.drop(columns="target_cells")) == 0  # 예측만 있는 표(제출 파일 등)는 해당 없음
    bd = pd.DataFrame({"base_date": ["2026-05-04"], "target_cells": [10.0]})  # 목표일 열 없이 기준일만
    assert offending_rows(bd) == 1
    blob = json.dumps({"rows": df.to_dict(orient="records")}).encode()
    assert check_bytes("x.json", blob) == 1


# ---------------------------------------------------------------- 저장소·캐시·패키지·zip·git
def test_processed_and_caches() -> None:
    base = ROOT / "data" / "processed"
    if not base.exists():
        pytest.skip("data/processed 없음")
    files = [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in (".parquet", ".csv")]
    assert _scan(files) == {}


def test_submission_package() -> None:
    base = ROOT / "submission_package"
    if not base.exists():
        pytest.skip("submission_package 없음")
    files = [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in TABLE_SUFFIX]
    assert _scan(files) == {}


def test_dist_zips() -> None:
    zips = sorted((ROOT / "dist").rglob("*.zip")) if (ROOT / "dist").exists() else []
    if not zips:
        pytest.skip("dist zip 없음")
    bad = {}
    for zp in zips:
        with zipfile.ZipFile(zp) as z:
            for info in z.infolist():
                if info.is_dir() or not info.filename.lower().endswith(TABLE_SUFFIX):
                    continue
                n = check_bytes(info.filename, z.read(info))
                if n:
                    bad[f"{_rel(zp)}::{info.filename}"] = n
    assert bad == {}


def test_git_tracked_tables() -> None:
    r = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        pytest.skip("git 저장소 아님")
    files = [ROOT / f for f in r.stdout.splitlines() if f.lower().endswith(TABLE_SUFFIX)]
    files = [p for p in files if p.exists() and not _rel(p).startswith("data/raw/")]
    assert _scan(files) == {}
