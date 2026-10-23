# ruff: noqa: E501  (한국어 설명)
"""v2.1 전환 적재(1회): Supabase 에 v2.1(누수 수정판, 제출·운영 모델) 기준 run 과 평가 표를 올린다.

- predictions: 2025 홀드아웃 OOF(점예측·분위·분류기 모두 v2.1, 폴드별 수정 피처) + 2026 test 조합·지점별 최신 as-of
  (레지스트리 current = v2.1). 2026 실측은 backfill_obs 가 채운다(test 타깃 격리 준수).
- shap_contributions·recommendations: 최신 as-of 행(설명 구성원 = 가중치 최대 단일 구성원).
- model_metrics: holdout2025_v21(같은 252행·CI), cv_v21, posthoc2026_v21(test 124 + 리드타임).
- bloom_events: 2020~2025 경계 사건 20건(v2.1 OOF, tbl_leadtime 정의) + 2026 8건(v2.1 사후, posthoc 정의) — 28건 모두 v2.1 기준.
- transition_metrics: 2020~2025(OOF)·2026(사후) 전환 분해.
값 원천: reports/eval/tbl_holdout_2025_v21.json·headline_metrics.json·posthoc_2026_v21_summary.json, data/processed/posthoc_2026_v21.parquet.
이 run 뒤 일일 러너(--force-predict)가 최신 as-of 를 v2.1 로 다시 예측하며 같은 모델의 이전 run 이력을 이어 붙인다.
사용: python scripts/upload_v21_run.py [--dry-run]
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
from algaecast.config import CONFIG_DIR, DATA_DIR, ROOT
from algaecast.db.upload import (
    client,
    events_rows,
    predictions_rows,
    shap_and_reco_rows,
    transition_rows,
    upsert,
)
from algaecast.eval import posthoc as PH
from algaecast.eval.transitions import T1K, T10K, load_oof, official_events
from algaecast.models import registry as R
from algaecast.models import v2 as V2

log = logging.getLogger("upload_v21_run")
EVAL = ROOT / "reports" / "eval"
TAG = "model-frozen-v2.1-217260e"


def metric_rows(run_id: str) -> list[dict]:
    same = json.loads((EVAL / "tbl_holdout_2025_v21.json").read_text(encoding="utf-8"))
    h = json.loads((EVAL / "headline_metrics.json").read_text(encoding="utf-8"))
    s26 = json.loads((EVAL / "posthoc_2026_v21_summary.json").read_text(encoding="utf-8"))
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

    for k, v in same["h2025"]["v21"].items():
        if k == "n":
            add("holdout2025_v21", "n", v)
        else:
            add("holdout2025_v21", k, v["value"], v["ci_low"], v["ci_high"])
    add("holdout2025_v21", "picp80", same["shared_2025"]["picp80"])
    for k, v in same["cv"]["v21"].items():
        add("cv_v21", k, v)
    for k, v in h["posthoc2026"]["v21"].items():
        add("posthoc2026_v21", k, v)
    add("posthoc2026_v21", "leadtime_events", s26["n_events"])
    add("posthoc2026_v21", "leadtime_detected_watch", s26["v2.1"]["watch"]["detected"])
    add("posthoc2026_v21", "leadtime_median_days_watch_E", s26["v2.1"]["watch"]["median_lead_e"])
    add("posthoc2026_v21", "leadtime_detected_point", s26["v2.1"]["point"]["detected"])
    return rows


def events_2026(cfg: dict) -> tuple[list[dict], list[dict]]:
    """2026 경계 사건(v2.1 사후 예측, posthoc 정의)과 2026 전환 분해 행."""
    pred = pd.read_parquet(DATA_DIR / "processed" / "posthoc_2026_v21.parquet")
    pred["base_date"] = pd.to_datetime(pred["base_date"])
    _, det = PH.leadtime_2026(pred, T10K)
    sid_map = {s["station_id"]: s["site_code"] for s in cfg["sites"]}
    w = det[det["방식"] == "감시(q90_cqr≥임계)"].set_index(["지점", "E"])
    a = det[det["방식"] == "경보(p_alert≥운영점)"].set_index(["지점", "E"])
    rows = []
    for e in official_events(T10K, start_year=2026).itertuples():
        key = (e.station_id, e._3)
        ww = w.loc[key] if key in w.index else None
        aa = a.loc[key] if key in a.index else None
        rows.append(
            {
                "site_id": sid_map[e.station_id],
                "event_id": f"{e.station_id}-{e._3}",
                "first_exceed_date": str(e._3),
                "official_alert_date": str(e._2),
                "first_watch_date": None if ww is None else str(ww["첫 경보 base_date"]),
                "first_alert_date": None if aa is None else str(aa["첫 경보 base_date"]),
                "lead_days_watch_e": None if ww is None else int(ww["리드(E)"]),
                "lead_days_alert_e": None if aa is None else int(aa["리드(E)"]),
                "lead_days_watch_d": None if ww is None else int(ww["리드(D)"]),
                "lead_days_alert_d": None if aa is None else int(aa["리드(D)"]),
                "detected_watch": ww is not None,
                "detected_alert": aa is not None,
            }
        )
    seg_map = {
        "유지-미만": "stay_below",
        "유지-초과": "stay_above",
        "진입(onset)": "onset",
        "이탈(offset)": "offset",
    }
    trows = []
    for level in (T10K, T1K):
        for d in PH.transitions_2026(pred, level).to_dict("records"):
            trows.append(
                {
                    "split": "posthoc2026",
                    "method": d["방식"],
                    "segment": "all",
                    "threshold": level,
                    "n": int(d["n"]),
                    "recall": None if pd.isna(d["Recall"]) else d["Recall"],
                    "precision": None if pd.isna(d["Precision"]) else d["Precision"],
                    "f1": d["F1"],
                    "false_alarm_rate": None,
                }
            )
            for ko, seg in seg_map.items():
                pos = seg in ("onset", "stay_above")
                rate = d[f"{ko} 경보율"]
                rate = None if pd.isna(rate) else float(rate)
                trows.append(
                    {
                        "split": "posthoc2026",
                        "method": d["방식"],
                        "segment": seg,
                        "threshold": level,
                        "n": int(d[f"{ko} n"]),
                        "recall": rate if pos else None,
                        "precision": None,
                        "f1": None,
                        "false_alarm_rate": None if pos else rate,
                    }
                )
    return rows, trows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    entry = R.current_entry("regression")
    if R.current_kind("regression") != V2.KIND or entry.get("meta", {}).get("model_name") != "v2.1":
        raise SystemExit("중단: current 회귀가 v2.1 이 아니다.")
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
                "frozen": TAG,
                "regression_kind": V2.KIND,
                "model": "v2.1",
            }
        ),
        "status": "success",
        "notes": "v2.1 전환 적재(데이터 유래 상수 누수 수정판): 2025 홀드아웃 v2.1 OOF + 2026 test 조합 + 최신 as-of (동결 커밋 217260e)",
    }
    sb = None if args.dry_run else client()
    run_id = (
        "00000000-0000-0000-0000-000000000000"
        if args.dry_run
        else sb.table("model_runs").insert(run).execute().data[0]["run_id"]
    )
    oof, _ = load_oof()
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
    ev26, tr26 = events_2026(cfg)
    ev_prior = [r for r in events_rows(cfg) if str(r["first_exceed_date"]) < "2026-01-01"]  # 2020~2025(OOF)
    if len(ev_prior) + len(ev26) != 28:
        raise SystemExit(f"중단: 경계 사건 수 {len(ev_prior)}+{len(ev26)} ≠ 28")
    counts["bloom_events"] = upsert(sb, "bloom_events", ev_prior + ev26, "site_id,event_id", args.dry_run)
    counts["transition_metrics"] = upsert(
        sb, "transition_metrics", transition_rows() + tr26, "split,method,segment,threshold", args.dry_run
    )
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
