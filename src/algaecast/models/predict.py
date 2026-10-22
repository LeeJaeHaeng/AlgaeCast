"""submission.csv 생성 (T9-b): 동결 레지스트리(앙상블)로 test 조합(sample_submission) 예측.

- 입력: data/processed/features_S1.parquet 의 split=='test' 행(타깃 없음), sample_submission.csv(행
순서·컬럼 기준)
- 회귀 current 가 ensemble_v2(v2 운영 모델)이면 test 행 피처에 상류 피처(features.upstream.build_upstream,
  원자료를 행의 기준일까지만 사용)를 붙여 예측한다. 제출 형식·검증은 v1 과 같다.
- 출력: submission/submission.csv — 컬럼 station_id, base_date, target_date, pred_cells(정수, ≥0),
UTF-8(BOM, 예시 서식과 동일)
사용: python -m algaecast.models.predict [--sample
data/raw/competition/algae_contest_2026/sample_submission.csv] [--out submission/submission.csv]
[--registry models]
"""

from __future__ import annotations

import argparse
import hashlib
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from algaecast.config import ROOT, SUBMISSION_PATH
from algaecast.db.upload import predict_registry
from algaecast.models import data as D

log = logging.getLogger(__name__)
DEFAULT_SAMPLE = ROOT / "data" / "raw" / "competition" / "algae_contest_2026" / "sample_submission.csv"
DEFAULT_OUT = SUBMISSION_PATH


def make_submission(
    sample_path: Path = DEFAULT_SAMPLE,
    strategy: str = "S1",
    *,
    reg_dir: Path | None = None,
    algae: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """sample_submission 조합 순서대로 레지스트리 current 예측(정수 반올림, ≥0).

    reg_dir: 레지스트리 디렉터리(None = models/, freeze_v2 --dry-run 은 임시 레지스트리).
    algae: v2 상류 피처용 조류 원자료(None = data/raw parquet, 행마다 기준일까지만 사용).
    """
    sample = pd.read_csv(sample_path, encoding="utf-8-sig", dtype={"station_id": str})
    cols = list(sample.columns)
    test = D.load_test_features(strategy)
    test["base_date"] = pd.to_datetime(test["base_date"]).dt.strftime("%Y-%m-%d")
    test["target_date"] = pd.to_datetime(test["target_date"]).dt.strftime("%Y-%m-%d")
    pr = predict_registry(test, reg_dir=reg_dir, algae=algae)
    pred = pd.DataFrame(
        {
            "station_id": test["station_id"].astype(str),
            "base_date": test["base_date"],
            "target_date": test["target_date"],
            "pred_cells": np.clip(np.round(pr["pred_cell_count"].to_numpy()), 0, None).astype("int64"),
        }
    )
    out = sample[["station_id", "base_date", "target_date"]].merge(
        pred, on=["station_id", "base_date", "target_date"], how="left"
    )
    missing = int(out["pred_cells"].isna().sum())
    if missing:
        raise RuntimeError(f"sample_submission 조합 {missing}건의 예측이 없음")
    out["pred_cells"] = out["pred_cells"].astype("int64")
    assert list(out.columns) == cols, f"컬럼 불일치 {list(out.columns)} vs {cols}"
    assert len(out) == len(sample)
    assert (out["pred_cells"] >= 0).all() and out["pred_cells"].notna().all()
    return out


def validate_submission(path: Path, sample_path: Path = DEFAULT_SAMPLE) -> dict:
    raw = path.read_bytes()
    sub = pd.read_csv(path, encoding="utf-8-sig", dtype={"station_id": str})
    sample = pd.read_csv(sample_path, encoding="utf-8-sig", dtype={"station_id": str})
    same_order = (
        sub[["station_id", "base_date", "target_date"]].values
        == sample[["station_id", "base_date", "target_date"]].values
    ).all()
    return {
        "rows": len(sub),
        "columns": list(sub.columns) == list(sample.columns),
        "order_same_as_sample": bool(same_order),
        "nan": int(sub["pred_cells"].isna().sum()),
        "negative": int((sub["pred_cells"] < 0).sum()),
        "bom": raw.startswith(b"\xef\xbb\xbf"),
        "sha256": hashlib.sha256(raw).hexdigest()[:16],
        "min": int(sub["pred_cells"].min()),
        "max": int(sub["pred_cells"].max()),
        "median": float(sub["pred_cells"].median()),
    }


def write_submission(sub: pd.DataFrame, path: Path) -> Path:
    """제출 파일 저장: UTF-8(BOM), LF, 인덱스 없음(예시 서식과 동일)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sub.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--strategy", default="S1")
    ap.add_argument("--registry", type=Path, default=None, help="레지스트리 디렉터리(기본 models/)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    out = make_submission(args.sample, args.strategy, reg_dir=args.registry)
    write_submission(out, args.out)
    print(validate_submission(args.out, args.sample))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
