"""비상안 T24 — 학습 스크립트(scripts/freeze_t24.py)와 사후 계산 모듈(eval.posthoc_t24)의 순수 함수 단위 테스트.

- 학습 행 규칙: T24 = 기준일·목표일 ≤ 2024-12-31, fold = 기준일 연도 ≤ 2024(목표일 2025-01-06 행 포함).
- 가드: 2025 행·test 분할·타깃 결측 차단, 저장소 본체(.git) 실행 차단.
- 동결 문서 초안(frozen_md)의 파일 표·제출 해시를 posthoc_t24.parse_frozen 이 그대로 읽는지,
  verify_frozen 이 레지스트리 current·파일 해시·제출 해시 불일치를 막는지(임시 레지스트리).
실제 데이터·모델·2026 정답은 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from algaecast.config import ROOT
from algaecast.eval import posthoc_t24 as P


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("freeze_t24", ROOT / "scripts" / "freeze_t24.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


F = _script()


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "station_id": ["HP", "HP", "HP"],
            "base_date": ["2024-12-23", "2024-12-30", "2025-01-06"],
            "target_date": ["2024-12-30", "2025-01-06", "2025-01-13"],
            "target_cells": [10.0, 0.0, 5.0],
            "split": ["train", "train", "valid"],
        }
    )


def test_t24_and_fold_masks() -> None:
    df = _rows()
    assert F.t24_mask(df).tolist() == [True, False, False]  # 목표일 2025 행은 T24 에서 빠진다
    assert F.fold_mask(df).tolist() == [True, True, False]  # Final 폴드는 기준일 연도만 본다


def test_guard_t24_blocks_2025_test_and_missing_target() -> None:
    df = _rows()
    F.guard_t24(df[F.t24_mask(df)])
    with pytest.raises(RuntimeError):
        F.guard_t24(df[F.fold_mask(df)])  # 목표일 2025-01-06
    ok = df.iloc[[0]].copy()
    with pytest.raises(RuntimeError):
        F.guard_t24(ok.assign(split="test"))
    with pytest.raises(RuntimeError):
        F.guard_t24(ok.assign(target_cells=np.nan))


@pytest.mark.parametrize("guard", [F.guard_workspace, P.guard_workspace])
def test_guard_workspace_refuses_repository(tmp_path: Path, guard) -> None:
    guard(tmp_path)  # 사본(.git 없음)은 통과
    (tmp_path / ".git").mkdir()
    with pytest.raises(SystemExit):
        guard(tmp_path)


def test_diff_stats_and_cqr_band() -> None:
    d = F.diff_stats(np.array([1.0, np.nan, 3.0]), np.array([1.5, 2.0, 3.0]))
    assert d == {"n": 2, "nan_mismatch": 1, "max_abs": 0.5}
    assert F.diff_stats(np.array([np.nan]), np.array([np.nan]))["max_abs"] == 0.0
    lo, hi = F.cqr_band(np.array([0.0, 99.0]), np.array([999.0, 9999.0]), 0.5)
    assert (lo >= 0).all()
    assert np.allclose(np.log10(hi + 1) - np.log10(np.array([999.0, 9999.0]) + 1), 0.5)
    assert np.isclose(np.log10(99.0 + 1) - np.log10(lo[1] + 1), 0.5)


# ---------------------------------------------------------------- 동결 문서 ↔ 사후 계산 대조
def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _fake_registry(tmp: Path) -> tuple[Path, list[dict], Path]:
    reg = tmp / "models"
    files, versions, current = [], [], {}
    for i, name in enumerate(("regression", "classifier", "quantile")):
        ver = f"20261026_12000{i}"
        d = reg / name / ver
        d.mkdir(parents=True)
        pkl, meta = f"model-{name}".encode(), json.dumps({"name": name, "version": ver}).encode()
        (d / "model.pkl").write_bytes(pkl)
        (d / "meta.json").write_bytes(meta)
        files.append(
            {
                "name": name,
                "version": ver,
                "sha256_model_pkl": _sha(pkl),
                "bytes_model_pkl": len(pkl),
                "sha256_meta_json": _sha(meta),
                "note": f"T24 {name}",
            }
        )
        versions.append({"name": name, "version": ver})
        current[name] = ver
    (reg / "registry.json").write_text(
        json.dumps({"current": current, "versions": versions}), encoding="utf-8"
    )
    sub = tmp / "submission_T24.csv"
    sub.write_bytes(b"\xef\xbb\xbfstation_id,base_date,target_date,pred_cells\nHP,2026-05-04,2026-05-11,1\n")
    return reg, files, sub


def _summary(files: list[dict], sub: Path) -> dict:
    return {
        "rule": F.T24_RULE,
        "frozen_at_kst": "2026-10-26 12:00:00",
        "train_regression": {
            "rule": F.T24_RULE,
            "n_rows": 2305,
            "base_date_min": "2012-04-02",
            "base_date_max": "2024-12-23",
            "target_date_max": "2024-12-30",
            "rows_by_site": {"HP": 430},
        },
        "site_thresholds": {"HP": 26.0},
        "weights": {"c1": 0.25, "c3": 0.25, "c2": 0.25, "cg": 0.25},
        "thresholds": {"clf_a": 0.58, "clf_b": 0.87},
        "operating_point": {"threshold": 0.46},
        "cqr": {"n_calib": 531, "qhat_log10": 0.1646},
        "files": files,
        "eval_2025": {"regression.rmse_log": 0.72},
        "eval_2025_v21_cache": {"regression.rmse_log": 0.71},
        "eval_2025_delta": {"regression.rmse_log": 0.01},
        "submission_T24": {
            "sha256_full": _sha(sub.read_bytes()),
            "vs_v21_median_abs_log10_diff": 0.06,
            "vs_v21_max_abs_log10_diff": 0.25,
        },
    }


def test_frozen_md_parsed_by_posthoc(tmp_path: Path) -> None:
    reg, files, sub = _fake_registry(tmp_path)
    md = F.frozen_md(_summary(files, sub))
    assert f"`{F.PLACEHOLDER}`" in md  # 동결 커밋 칸은 비워 둔다
    doc = P.parse_frozen(md)
    assert [(f["name"], f["version"], f["sha256_model_pkl"]) for f in doc["files"]] == [
        (f["name"], f["version"], f["sha256_model_pkl"]) for f in files
    ]
    assert doc["submission_sha256"] == _sha(sub.read_bytes())
    assert P.verify_frozen(md, reg_dir=reg, sub_path=sub)["files"] == doc["files"]


def test_verify_frozen_rejects_mismatch(tmp_path: Path) -> None:
    reg, files, sub = _fake_registry(tmp_path)
    md = F.frozen_md(_summary(files, sub))
    (reg / "quantile" / files[2]["version"] / "model.pkl").write_bytes(b"changed")
    with pytest.raises(SystemExit):
        P.verify_frozen(md, reg_dir=reg, sub_path=sub)
    reg2, files2, sub2 = _fake_registry(tmp_path / "b")
    md2 = F.frozen_md(_summary(files2, sub2))
    r = json.loads((reg2 / "registry.json").read_text(encoding="utf-8"))
    r["current"]["regression"] = "20261023_120818"  # current 가 v2.1 이면 중단
    (reg2 / "registry.json").write_text(json.dumps(r), encoding="utf-8")
    with pytest.raises(SystemExit):
        P.verify_frozen(md2, reg_dir=reg2, sub_path=sub2)
    reg3, files3, sub3 = _fake_registry(tmp_path / "c")
    md3 = F.frozen_md(_summary(files3, sub3))
    sub3.write_bytes(b"other")
    with pytest.raises(SystemExit):
        P.verify_frozen(md3, reg_dir=reg3, sub_path=sub3)


def test_parse_frozen_requires_three_rows() -> None:
    with pytest.raises(SystemExit):
        P.verify_frozen("| regression | 20261026_120000 | `" + "0" * 64 + "` | 1 | `" + "0" * 64 + "` | x |")
