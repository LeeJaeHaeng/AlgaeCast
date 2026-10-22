# ruff: noqa: E501  (한국어 설명)
"""v2 전환 적재(1회): Supabase 에 v2(제출·운영 모델) 기준 run 을 만든다.

T6 초기 적재(db/upload.py)와 같은 구성을 v2 로 다시 올린다.
- predictions: 2025 홀드아웃 OOF(점예측 = v2 동결 가중치 OOF, 분위·분류기는 v1 동결본 OOF 공통)
  + 2026 test 조합·지점별 최신 as-of(레지스트리 current = v2 로 예측). 2026 실측은 backfill_obs 가 채운다(test 타깃 격리 준수).
- shap_contributions·recommendations: 최신 as-of 행, 설명 구성원 = v2 가중치 최대 단일 구성원(c2, log10 환산).
- model_metrics: v2 지표(split holdout2025_v2 = 같은 252행·CI, cv_v2 = 2020~2024 통합·폴드 평균, posthoc2026_v2 = test 124 + 리드타임).
  값은 reports/eval/headline_metrics.json·tbl_holdout_2025_v2.json(전체 정밀도)에서 읽는다.
이 run 이 생긴 뒤 일일 러너(--force-predict)가 최신 as-of 를 v2 로 다시 예측하면서 같은 모델의 이전 run 이력을 이어 붙인다.
사용: python scripts/upload_v2_run.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from datetime import datetime

import pandas as pd
import yaml

from algaecast.collect.base import KST
from algaecast.config import CONFIG_DIR, ROOT
from algaecast.db.upload import client, predictions_rows, shap_and_reco_rows, upsert
from algaecast.eval import holdout_v2 as HV
from algaecast.eval.transitions import load_oof
from algaecast.models import registry as R
from algaecast.models import v2 as V2

log = logging.getLogger("upload_v2_run")
EVAL = ROOT / "reports" / "eval"


def v2_oof_frame() -> pd.DataFrame:
    """v1 OOF 프레임(분위·분류기·타깃) 에서 ens 만 v2 동결 가중치 OOF 로 바꾼다(2020~2025 행)."""
    oof, _ = load_oof()
    frame = V2.load_training_frame()
    ens2, _ = HV.v2_oof(frame)
    key = frame[["station_id", "base_date"]].copy()
    key["station_id"] = key["station_id"].astype(str)
    key["base_date"] = pd.to_datetime(key["base_date"])
    key["ens_v2"] = ens2
    o = oof.copy()
    o["station_id"] = o["station_id"].astype(str)
    o["base_date"] = pd.to_datetime(o["base_date"])
    o = o.merge(key, on=["station_id", "base_date"], how="left")
    fin = o["year"] == 2025
    if o.loc[fin, "ens_v2"].isna().any():
        raise SystemExit("중단: 2025 v2 OOF 가 비는 행이 있다.")
    o.loc[fin, "ens"] = o.loc[fin, "ens_v2"]
    return o.drop(columns="ens_v2")


def metric_rows(run_id: str) -> list[dict]:
    h = json.loads((EVAL / "headline_metrics.json").read_text(encoding="utf-8"))
    same = json.loads((EVAL / "tbl_holdout_2025_v2.json").read_text(encoding="utf-8"))
    rows: list[dict] = []

    def add(split: str, metric: str, value: float, lo: float | None = None, hi: float | None = None) -> None:
        rows.append(
            {
                "run_id": run_id,
                "split": split,
                "site_id": None,
                "metric": metric,
                "value": float(value),
                "ci_low": lo,
                "ci_high": hi,
            }
        )

    for k, v in same["h2025"]["v2"].items():
        if k == "n":
            add("holdout2025_v2", "n", v)
        else:
            add("holdout2025_v2", k, v["value"], v["ci_low"], v["ci_high"])
    add("holdout2025_v2", "picp80", same["shared_2025"]["picp80"])
    for k, v in same["cv"]["v2"].items():
        add("cv_v2", k, v)
    for k, v in h["posthoc2026"]["v2"].items():
        add("posthoc2026_v2", k, v)
    # 리드타임(감시·경보는 v1 과 공통, 점예측 포착은 v2 값) — tbl_holdout_2026_posthoc_v2.md 리드타임 요약 표의 v2 행
    lines = (EVAL / "tbl_holdout_2026_posthoc_v2.md").read_text(encoding="utf-8").splitlines()
    head = next(ln for ln in lines if ln.startswith("| 모델 | 방식"))
    cols = [c.strip() for c in head.strip("|").split("|")]
    lt = {}
    for ln in lines[lines.index(head) + 2 :]:
        if not ln.startswith("|"):
            break
        cells = dict(zip(cols, (c.strip() for c in ln.strip("|").split("|")), strict=True))
        if cells["모델"] == "v2":
            lt[cells["방식"]] = cells
    watch = next(v for k, v in lt.items() if k.startswith("감시"))
    point = next(v for k, v in lt.items() if k.startswith("점예측"))
    add("posthoc2026_v2", "leadtime_events", float(watch["사건 수"]))
    add("posthoc2026_v2", "leadtime_detected_watch", float(watch["선행 탐지 수"]))
    add("posthoc2026_v2", "leadtime_median_days_watch_E", float(watch["중앙 리드(E, 일)"]))
    add("posthoc2026_v2", "leadtime_detected_point", float(point["선행 탐지 수"]))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if R.current_kind("regression") != V2.KIND:
        raise SystemExit("중단: current 회귀가 v2 가 아니다.")
    cfg = yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))
    mcfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    versions = R.current_versions()
    run = {
        "run_at": datetime.now(tz=KST).isoformat(),
        "model_name": "algaecast7-ensemble",
        "model_version": versions.get("regression"),
        "git_commit": commit,
        "features_hash": None,
        "hyperparams": json.dumps(
            {
                "registry": versions,
                "operating_point": mcfg.get("operating_point"),
                "cqr": mcfg.get("cqr"),
                "frozen": "model-frozen-v2-9dca86c",
                "regression_kind": V2.KIND,
            }
        ),
        "status": "success",
        "notes": "v2 전환 적재: 2025 홀드아웃 v2 OOF + 2026 test 조합 + 최신 as-of (v2, 동결 커밋 9dca86c)",
    }
    sb = None if args.dry_run else client()
    run_id = (
        "00000000-0000-0000-0000-000000000000"
        if args.dry_run
        else sb.table("model_runs").insert(run).execute().data[0]["run_id"]
    )
    oof = v2_oof_frame()
    pred_rows, latest = predictions_rows(run_id, cfg, oof, mcfg)
    counts = {
        "predictions": upsert(
            sb, "predictions", pred_rows, "run_id,site_id,base_date,target_date", args.dry_run
        )
    }
    shap_rows, reco_rows = shap_and_reco_rows(run_id, cfg, latest)
    counts["shap_contributions"] = upsert(sb, "shap_contributions", shap_rows, None, args.dry_run)
    counts["recommendations"] = upsert(sb, "recommendations", reco_rows, None, args.dry_run)
    counts["model_metrics"] = upsert(sb, "model_metrics", metric_rows(run_id), None, args.dry_run)
    print(
        json.dumps(
            {"run_id": run_id, "model_version": run["model_version"], "rows": counts},
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
