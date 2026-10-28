# ruff: noqa: E501  (한국어 설명)
"""T24 전환 적재(1회): Supabase 에 T24(2026-10-28 제출·운영 모델) 기준 run 과 평가 표를 올린다.

T24 = 운영사무국 답변(2026-10-28 '학습은 24년까지')에 따라 사전등록(PREREG_contingency 2절·7절·8절) 규칙대로 바꾼
제출·운영 모델이다. v2.1 구성 그대로 대회 번들 split=train(2,310행, 기준일 ≤2024-12-30)으로 적합했다(동결 커밋 a961caf).
- predictions: 2025 홀드아웃 OOF(oof_predictions.parquet year==2025 = v2.1 Final 폴드 = T24 와 최대 차 0, FROZEN_T24)
  + 2026 test 조합·지점별 최신 as-of(레지스트리 current = T24, 수온 임계 ≤2024). 2026 실측은 backfill_obs 가 채운다.
  · 확인 1: test 124행 반올림 예측 = submission/submission.csv(T24, 057afeee…).
  · 확인 2: 2026 행 예측 열 = data/processed/posthoc_2026_T24.parquet(T24 동결 뒤 1회 사후 예측, 타깃 열은 읽지 않음).
- shap_contributions·recommendations: 최신 as-of 행(설명 구성원 = 가중치 최대 단일 구성원, v2.1 과 같은 c2).
- model_metrics: holdout2025_t24(같은 252행·CI = v2.1 Final 폴드 값), cv_t24, posthoc2026_t24(test 124 + 리드타임).
- bloom_events: 2020~2025 경계 사건 20건(OOF, tbl_leadtime 정의) + 2026 8건(T24 사후, posthoc 정의) — 28건.
  bloom_events·transition_metrics 는 run 에 묶이지 않아 v2.1 의 2026 행이 T24 값으로 덮어써진다(보고서 파일에는 v2.1 값 보존).
값 원천: reports/eval/tbl_holdout_2025_v21.json(h2025.v21 = T24)·headline_metrics.json(posthoc2026.t24),
reports/experiments/contingency_T24/posthoc_2026_T24_summary.json, data/processed/posthoc_2026_T24.parquet.
이 run 바로 뒤 일일 러너(--force-predict)가 최신 as-of 를 T24 로 다시 예측하며 같은 모델의 이 run 이력을 이어 붙인다.
사용: python scripts/upload_t24_run.py [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
from datetime import datetime

import numpy as np
import pandas as pd
import yaml

from algaecast.collect.base import KST
from algaecast.config import CONFIG_DIR, DATA_DIR, ROOT, SUBMISSION_PATH
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
from algaecast.features.constants import FINAL_THRESHOLD_YEAR, apply_site_thresholds
from algaecast.models import data as D
from algaecast.models import registry as R
from algaecast.models import v2 as V2

log = logging.getLogger("upload_t24_run")
EVAL = ROOT / "reports" / "eval"
T24_DIR = ROOT / "reports" / "experiments" / "contingency_T24"
TAG = "model-frozen-T24-a961caf"
T24_VERSION = "20261026_131722"
SUB_SHA = "057afeee93c7a4213bf9176d8696fd9255617641f5c0b0aa35427a8fc1cf3f73"
POSTHOC_PQ = DATA_DIR / "processed" / "posthoc_2026_T24.parquet"
POSTHOC_SHA = "42d48a55455af4598d47d847d61eaad418f8c35a9765c5fbe27bc67fb585124b"


def guard() -> None:
    """current 3개 = T24, 운영 임계 연도 = 2024, 피처 파일 임계 = 2024, 제출본·사후 예측 해시."""
    entry = R.current_entry("regression")
    if R.current_kind("regression") != V2.KIND or entry.get("meta", {}).get("model_name") != "T24-fold":
        raise SystemExit("중단: current 회귀가 T24 가 아니다.")
    if set(R.current_versions().values()) != {T24_VERSION}:
        raise SystemExit(f"중단: current 버전 {R.current_versions()} ≠ T24 {T24_VERSION}")
    if FINAL_THRESHOLD_YEAR != 2024 or entry["meta"]["train"].get("threshold_year") != 2024:
        raise SystemExit("중단: 수온 임계 연도가 2024 가 아니다(코드 상수 또는 T24 meta).")
    feat = pd.read_parquet(D._features_path("S1"))
    cols = ["wtemp_minus_site_thresh", "wtemp_over_site_thresh_days"]
    re24 = apply_site_thresholds(feat, 2024)
    for c in cols:
        if not np.array_equal(feat[c].to_numpy(float), re24[c].to_numpy(float), equal_nan=True):
            raise SystemExit(f"중단: features_S1 의 {c} 가 ≤2024 임계가 아니다(피처를 다시 만든다).")
    if hashlib.sha256(SUBMISSION_PATH.read_bytes()).hexdigest() != SUB_SHA:
        raise SystemExit("중단: submission/submission.csv 가 T24 제출본(057afeee…)이 아니다.")
    if hashlib.sha256(POSTHOC_PQ.read_bytes()).hexdigest() != POSTHOC_SHA:
        raise SystemExit("중단: posthoc_2026_T24.parquet 가 동결 뒤 1회 산출물과 다르다.")


def check_predictions(pred_rows: list[dict], cfg: dict) -> dict:
    """2026 행이 제출본(test 124)·T24 사후 예측(2026 기준일)과 같은지 — 타깃 열은 읽지 않는다."""
    p = pd.DataFrame(pred_rows)
    p["base_date"] = pd.to_datetime(p["base_date"])
    p = p[p["base_date"].dt.year == 2026]
    code2sid = {s["site_code"]: s["station_id"] for s in cfg["sites"]}
    p["station_id"] = p["site_id"].map(code2sid)
    sub = pd.read_csv(SUBMISSION_PATH, encoding="utf-8-sig", dtype={"station_id": str})
    sub["base_date"] = pd.to_datetime(sub["base_date"])
    m = sub.merge(p, on=["station_id", "base_date"], how="left", validate="1:1")
    if m["pred_cell_count"].isna().any():
        raise SystemExit("중단: test 조합 중 적재 행이 없는 것이 있다.")
    diff_sub = int((np.clip(np.round(m["pred_cell_count"].astype(float)), 0, None) != m["pred_cells"]).sum())
    if diff_sub:
        raise SystemExit(f"중단: test 124행 중 {diff_sub}행이 제출본 반올림 값과 다르다.")
    ph = pd.read_parquet(
        POSTHOC_PQ,
        columns=["station_id", "base_date", "pred_cell_count", "q10_cqr", "q90_cqr", "p_alert", "tier"],
    )
    ph["station_id"] = ph["station_id"].astype(str)
    ph["base_date"] = pd.to_datetime(ph["base_date"])
    mm = p.merge(ph, on=["station_id", "base_date"], how="inner", suffixes=("", "_ph"), validate="1:1")
    if len(mm) != len(p):
        raise SystemExit(f"중단: 2026 적재 행 {len(p)} 중 사후 예측에 없는 행이 있다({len(mm)}).")
    maxd = {
        c: float(np.nanmax(np.abs(mm[c].astype(float) - mm[f"{c}_ph"].astype(float))))
        for c in ("pred_cell_count", "q10_cqr", "q90_cqr", "p_alert")
    }
    tier_diff = int((mm["tier"] != mm["tier_ph"]).sum())
    if max(maxd.values()) > 1e-6 or tier_diff:
        raise SystemExit(f"중단: 2026 적재 예측이 T24 사후 예측과 다르다 {maxd} tier 차이 {tier_diff}")
    return {"rows_2026": len(p), "test_vs_submission_diff": 0, "vs_posthoc_max_abs": maxd, "tier_diff": 0}


def metric_rows(run_id: str) -> list[dict]:
    same = json.loads((EVAL / "tbl_holdout_2025_v21.json").read_text(encoding="utf-8"))
    h = json.loads((EVAL / "headline_metrics.json").read_text(encoding="utf-8"))
    s26 = json.loads((T24_DIR / "posthoc_2026_T24_summary.json").read_text(encoding="utf-8"))
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

    # 2025 같은 252행·CV: T24 = v2.1 Final 폴드(FROZEN_T24 '2025 확인' Δ 0)
    for k, v in same["h2025"]["v21"].items():
        if k == "n":
            add("holdout2025_t24", "n", v)
        else:
            add("holdout2025_t24", k, v["value"], v["ci_low"], v["ci_high"])
    add("holdout2025_t24", "picp80", same["shared_2025"]["picp80"])
    for k, v in same["cv"]["v21"].items():
        add("cv_t24", k, v)
    for k, v in h["posthoc2026"]["t24"].items():
        add("posthoc2026_t24", k, v)
    add("posthoc2026_t24", "leadtime_events", s26["n_events"])
    add("posthoc2026_t24", "leadtime_detected_watch", s26["T24"]["watch"]["detected"])
    add("posthoc2026_t24", "leadtime_median_days_watch_E", s26["T24"]["watch"]["median_lead_e"])
    add("posthoc2026_t24", "leadtime_detected_point", s26["T24"]["point"]["detected"])
    return rows


def events_2026(cfg: dict) -> tuple[list[dict], list[dict]]:
    """2026 경계 사건(T24 사후 예측, posthoc 정의)과 2026 전환 분해 행 — upload_v21_run 과 같은 방식·같은 행 키."""
    pred = pd.read_parquet(POSTHOC_PQ)
    pred["base_date"] = pd.to_datetime(pred["base_date"])
    pred["station_id"] = pred["station_id"].astype(str)
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
    guard()
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
                "model": "T24",
                "threshold_year": FINAL_THRESHOLD_YEAR,
            }
        ),
        "status": "success",
        "notes": "T24 전환 적재(운영사무국 답변 2026-10-28 '학습은 24년까지'): 2025 홀드아웃(T24 = v2.1 Final 폴드 OOF, 차이 0) + 2026 test 조합 + 최신 as-of (동결 커밋 a961caf)",
    }
    run_id = "00000000-0000-0000-0000-000000000000"
    oof, _ = load_oof()
    pred_rows, latest = predictions_rows(run_id, cfg, oof, mcfg)
    checks = check_predictions(pred_rows, cfg)
    log.info("2026 행 대조: %s", checks)
    ev26, tr26 = events_2026(cfg)
    ev_prior = [r for r in events_rows(cfg) if str(r["first_exceed_date"]) < "2026-01-01"]  # 2020~2025(OOF)
    if len(ev_prior) + len(ev26) != 28:
        raise SystemExit(f"중단: 경계 사건 수 {len(ev_prior)}+{len(ev26)} ≠ 28")
    sb = None if args.dry_run else client()
    if not args.dry_run:
        run_id = sb.table("model_runs").insert(run).execute().data[0]["run_id"]
        for r in pred_rows:
            r["run_id"] = run_id
    counts = {
        "predictions": upsert(
            sb, "predictions", pred_rows, "run_id,site_id,base_date,target_date", args.dry_run
        )
    }
    shap_rows, reco_rows = shap_and_reco_rows(run_id, cfg, latest)
    counts["shap_contributions"] = upsert(sb, "shap_contributions", shap_rows, None, args.dry_run)
    counts["recommendations"] = upsert(sb, "recommendations", reco_rows, None, args.dry_run)
    counts["model_metrics"] = upsert(sb, "model_metrics", metric_rows(run_id), None, args.dry_run)
    counts["bloom_events"] = upsert(sb, "bloom_events", ev_prior + ev26, "site_id,event_id", args.dry_run)
    counts["transition_metrics"] = upsert(
        sb, "transition_metrics", transition_rows() + tr26, "split,method,segment,threshold", args.dry_run
    )
    print(
        json.dumps(
            {
                "run_id": run_id,
                "model_version": run["model_version"],
                "rows": counts,
                "checks": checks,
                "events_2026": [
                    {k: r[k] for k in ("event_id", "lead_days_watch_e", "lead_days_alert_e")} for r in ev26
                ],
            },
            ensure_ascii=False,
            indent=1,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
