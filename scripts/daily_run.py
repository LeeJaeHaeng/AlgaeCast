"""일일 자동화 러너 (T8).

동결 모델 검증 → 증분 수집 → as-of 피처 → 예측 → Supabase → backfill → 라이브 벤치마크 → revalidate.

- 제출 전(2026-11-06)까지 재학습 금지: models/FROZEN.md(v1)·FROZEN_v2.md(있으면)의 sha256 과 불일치하면
  즉시 중단(종료코드 2).
- 실패 시 model_runs 에 status='failed' 행을 남긴다(대시보드 배너). 대회 번들·모델 pickle 은 저장소에 없고
  모델은 GitHub Release(환경변수 FROZEN_TAG, 기본 model-frozen-13ac483) 에서 워크플로가 내려받는다.
- 회귀 current 가 ensemble_v2(v2 운영 모델)이면 as-of 피처 행에 상류 피처 5열을 붙여 예측한다
  (추가 수집 없음 — 이번에 모은 5지점 조류 자료를 행의 기준일까지 잘라 계산). v1 이면 동작이 이전과 같다.
사용: python scripts/daily_run.py [--days 120] [--today YYYY-MM-DD] [--dry-run] [--skip-collect]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import traceback
from datetime import date, datetime
from typing import Any

import pandas as pd
import requests
import yaml

from algaecast.collect.base import KST
from algaecast.config import CONFIG_DIR, ROOT, get_env
from algaecast.predict.asof import (
    attach_model_features,
    build_daily,
    collect_recent,
    feature_rows,
    latest_base_dates,
    load_cfgs,
    window_start,
)

log = logging.getLogger("daily")
LOG_DIR = ROOT / "logs"
# 동결 모델 Release 태그(워크플로 env FROZEN_TAG). v2 동결 후 워크플로에서 교체한다.
FROZEN_TAG = os.environ.get("FROZEN_TAG", "model-frozen-13ac483")


def verify_frozen() -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_frozen.py")], capture_output=True, text=True
    )
    log.info(r.stdout.strip())
    if r.returncode != 0:
        raise SystemExit(2)


def _sb() -> Any:
    from algaecast.db.upload import client

    return client()


def record_failed(exc: BaseException, dry: bool) -> None:
    if dry:
        return
    try:
        _sb().table("model_runs").insert(
            {
                "run_at": datetime.now(tz=KST).isoformat(),
                "model_name": "algaecast7-ensemble",
                "model_version": FROZEN_TAG.removeprefix("model-"),
                "git_commit": os.environ.get("GITHUB_SHA", "")[:7] or None,
                "status": "failed",
                "notes": f"daily_run 실패: {type(exc).__name__}: {str(exc)[:300]}",
            }
        ).execute()
    except Exception as e2:  # noqa: BLE001
        log.error("failed 기록 실패: %s", e2)


def upload_predictions(
    feat: pd.DataFrame, cfg_sites: dict, dry: bool, algae: pd.DataFrame | None = None
) -> tuple[str, int]:
    """as-of 피처 행 예측 → Supabase.

    algae = 이번에 수집한 조류 자료(v2 상류 피처가 feat 에 없을 때만 사용).
    """
    from algaecast.db.upload import _clean, level_of, predict_registry, shap_and_reco_rows, upsert
    from algaecast.models.registry import current_kind, current_versions

    pr = predict_registry(feat, algae=algae)
    mcfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))
    run = {
        "run_at": datetime.now(tz=KST).isoformat(),
        "model_name": "algaecast7-ensemble",
        "model_version": current_versions().get("regression", "frozen"),
        "git_commit": (os.environ.get("GITHUB_SHA") or _git_short())[:7],
        "hyperparams": json.dumps(
            {
                "registry": current_versions(),
                "operating_point": mcfg.get("operating_point"),
                "cqr": mcfg.get("cqr"),
                "frozen": FROZEN_TAG,
                "regression_kind": current_kind("regression"),
            }
        ),
        "status": "success",
        "notes": "daily as-of: "
        + ", ".join(f"{r.station_id}@{r.base_date.date()}" for r in feat.itertuples()),
    }
    if dry:
        print(
            pd.concat([feat[["station_id", "base_date", "target_date"]], pr], axis=1)
            .round(3)
            .to_string(index=False)
        )
        return "dry-run", len(feat)
    sb = _sb()
    run_id = sb.table("model_runs").insert(run).execute().data[0]["run_id"]
    rows = pd.DataFrame(
        {
            "run_id": run_id,
            "site_id": feat["site_code"].astype(str),
            "base_date": feat["base_date"],
            "target_date": feat["target_date"],
            "horizon_days": feat["horizon_days"].astype(int),
        }
    )
    for c in pr.columns:
        rows[c] = pr[c].to_numpy()
    rows["pred_alert_level"] = level_of(rows["pred_cell_count"].to_numpy()).astype(int)
    rows["p_over_10k"] = None
    rows["obs_cell_count"] = None
    n = upsert(sb, "predictions", _clean(rows), "run_id,site_id,base_date,target_date", False)
    shap_rows, reco_rows = shap_and_reco_rows(run_id, cfg_sites, feat, algae=algae)
    upsert(sb, "shap_contributions", shap_rows, None, False)
    upsert(sb, "recommendations", reco_rows, None, False)
    return run_id, n


def _git_short() -> str:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
            ).stdout.strip()
            or "local"
        )
    except OSError:
        return "local"


def update_live_benchmark(dry: bool) -> int:
    """live_benchmark.csv 에 우리 모델 pred_level·p_alert 를 (site, target_date) 로 결합(최신 run 기준)."""
    path = ROOT / "reports" / "eval" / "live_benchmark.csv"
    if not path.exists() or dry:
        return 0
    bench = pd.read_csv(path)
    if bench.empty:
        return 0
    sb = _sb()
    preds = pd.DataFrame(
        sb.table("predictions")
        .select("site_id,base_date,target_date,pred_cell_count,p_alert,tier,run_id")
        .order("base_date", desc=True)
        .limit(2000)
        .execute()
        .data
    )
    if preds.empty:
        return 0
    from algaecast.collect.nier_forecast import level_from_cells

    preds["pred_level"] = level_from_cells(preds["pred_cell_count"]).astype("Int64")
    latest = preds.sort_values("base_date").drop_duplicates(["site_id", "target_date"], keep="last")
    m = bench.merge(
        latest[["site_id", "target_date", "pred_level", "p_alert", "tier"]].rename(
            columns={"site_id": "site_code"}
        ),
        on=["site_code", "target_date"],
        how="left",
        suffixes=("", "_new"),
    )
    for c in ("pred_level", "p_alert", "tier"):
        if f"{c}_new" in m:
            m[c] = m[f"{c}_new"].combine_first(m[c]) if c in bench else m[f"{c}_new"]
            m = m.drop(columns=[f"{c}_new"])
    m.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
    return int(m["pred_level"].notna().sum())


def revalidate(dry: bool) -> str:
    secret = get_env("REVALIDATE_SECRET")
    url = get_env("DASHBOARD_URL", "https://algaecast-7.vercel.app")
    if dry or not secret:
        return "skipped"
    r = requests.post(f"{url}/api/revalidate", headers={"x-revalidate-secret": secret}, timeout=30)
    return f"{r.status_code} {r.text[:80]}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--days", type=int, default=400, help="최소 수집 일수(실제 시작 = min(올해 1/1, today−days))"
    )
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(LOG_DIR / "daily_run.log", encoding="utf-8")],
    )
    summary: dict[str, object] = {"today": str(args.today), "steps": {}}
    try:
        verify_frozen()
        summary["steps"]["verify_frozen"] = "ok"
        sites_cfg, feat_cfg = load_cfgs()
        start = window_start(args.today, args.days)
        src = collect_recent(sites_cfg, start, args.today)
        summary["steps"]["collect"] = {k: int(len(v)) for k, v in src.items()}
        daily = build_daily(sites_cfg, feat_cfg, src, start, args.today)
        bases = latest_base_dates(daily, args.today)
        summary["bases"] = {k: str(v) for k, v in bases.items()}
        # 새 측정 여부: 최신 base_date 가 이미 predictions 에 있으면 건너뜀
        if not args.dry_run and bases:
            sb = _sb()
            have = pd.DataFrame(
                sb.table("predictions")
                .select("site_id,base_date")
                .order("base_date", desc=True)
                .limit(500)
                .execute()
                .data
            )
            sid2code = {s["station_id"]: s["site_code"] for s in sites_cfg["sites"]}
            if not have.empty:
                done = {(r.site_id, str(r.base_date)) for r in have.itertuples()}
                bases = {k: v for k, v in bases.items() if (sid2code[k], str(v)) not in done}
        summary["new_bases"] = {k: str(v) for k, v in bases.items()}
        if bases:
            feat = feature_rows(daily, sites_cfg, bases)
            # v2(ensemble_v2) 이면 상류 피처 5열을 같은 조류 자료로 붙인다(v1 이면 그대로)
            feat = attach_model_features(feat, src.get("algae"))
            run_id, n = upload_predictions(feat, sites_cfg, args.dry_run, algae=src.get("algae"))
            summary["steps"]["predict"] = {"run_id": run_id, "n": n}
        else:
            summary["steps"]["predict"] = "skipped (새 측정 없음)"
        if not args.dry_run:
            from algaecast.db.backfill_obs import main as backfill

            # 최신 관측도 먼저 적재(backfill 전제)
            from algaecast.db.upload import _clean, upsert

            algae = src["algae"]
            if not algae.empty:
                inc = pd.DataFrame(
                    {
                        "site_id": algae["site_code"],
                        "obs_date": algae["obs_date"],
                        "cell_count": algae["iem_bgalage_cell_co"],
                        "water_temp": algae["iem_wtrtp"],
                        "ph": algae["iem_ph"],
                        "do_mgl": algae["iem_doc"],
                        "turbidity": algae["iem_tur"],
                        "transparency": algae["iem_trp"],
                        "chla": algae["iem_chla"],
                        "dominant_genus": algae["dominant_genus"],
                        "alert_level": pd.to_numeric(algae["alert_level_2consec"], errors="coerce").clip(
                            0, 3
                        ),
                        "source": "NIER 조류경보제 API (daily)",
                        "fetched_at": algae["fetched_at"].astype(str),
                    }
                ).drop_duplicates(["site_id", "obs_date"], keep="last")
                summary["steps"]["observations"] = upsert(
                    _sb(), "observations", _clean(inc), "site_id,obs_date", False
                )
            backfill([])
            summary["steps"]["backfill"] = "ok"
        summary["steps"]["live_benchmark"] = update_live_benchmark(args.dry_run)
        summary["steps"]["revalidate"] = revalidate(args.dry_run)
        summary["status"] = "success"
    except BaseException as exc:  # noqa: BLE001
        summary["status"] = "failed"
        summary["error"] = f"{type(exc).__name__}: {exc}"
        log.error("daily_run 실패\n%s", traceback.format_exc())
        record_failed(exc, args.dry_run)
        (LOG_DIR / "daily_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
        return 1
    (LOG_DIR / "daily_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
