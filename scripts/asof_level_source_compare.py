# ruff: noqa: E501  (한국어 설명)
"""연속 수위 원천 비교: 본댐 8개소 수위를 WAMIS 대신 K-water delist 댐수위로 대체해도 예측이 거의 같은지 본다.

- 수집: ``asof.collect_recent`` 를 ``ASOF_LEVEL_SOURCE=wamis`` 와 ``delist`` 로 두 번 부른다
  (wamis = 연속 수위 관측소 전부 WAMIS, delist = 본댐 8개소만 delist rwl+오프셋, 나머지는 WAMIS).
- 피처: ``asof.build_daily`` → 지점별 최근 ``--per-site`` 개 조류 측정일(base_date)마다 ``features.run.GROUPS`` 로 피처 행
  (asof.feature_rows 와 같은 열·목표일 = base+7) → ``asof.attach_model_features``(v2 상류 5열).
- 예측: ``algaecast.db.upload.predict_registry``(레지스트리 current, Supabase 접속 없음) — daily_run 과 같은 함수·tier 규칙.
- 출력: reports/eval/tbl_level_source_compare.md(요약 JSON 한 줄 + 표), 원자료 csv(--out-csv).
사용: python scripts/asof_level_source_compare.py [--today YYYY-MM-DD] [--days 400] [--per-site 6]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from algaecast.collect.base import KST
from algaecast.config import CONFIG_DIR, ROOT
from algaecast.db.upload import predict_registry
from algaecast.features.run import GROUPS
from algaecast.models.registry import current_versions
from algaecast.predict import asof

log = logging.getLogger("level_source_compare")
SOURCES = ("wamis", "delist")
OUT_MD = ROOT / "reports" / "eval" / "tbl_level_source_compare.md"
OUT_CSV = ROOT / "reports" / "experiments" / "FIX-v2.1" / "rerun" / "level_source_compare_v21.csv"
FROZEN = "동결 모델 v2.1(217260e)"


def collect(source: str, sites_cfg: dict, start: date, end: date) -> dict[str, pd.DataFrame]:
    """ASOF_LEVEL_SOURCE 를 잠시 바꿔 증분 수집한다(끝나면 원래 값으로 되돌림)."""
    old = os.environ.get("ASOF_LEVEL_SOURCE")
    os.environ["ASOF_LEVEL_SOURCE"] = source
    try:
        return asof.collect_recent(sites_cfg, start, end)
    finally:
        if old is None:
            os.environ.pop("ASOF_LEVEL_SOURCE", None)
        else:
            os.environ["ASOF_LEVEL_SOURCE"] = old


def recent_bases(daily: dict[str, pd.DataFrame], today: date, per_site: int) -> dict[str, list[date]]:
    """지점별 today 이전(포함) 최근 per_site 개 조류 측정일."""
    out = {}
    for sid, d in daily.items():
        obs = d.loc[d["is_obs"].astype(bool) & (d["obs_date"] <= pd.Timestamp(today)), "obs_date"]
        out[sid] = [t.date() for t in sorted(obs.unique())[-per_site:]]
    return out


def feature_rows_multi(
    daily: dict[str, pd.DataFrame], sites_cfg: dict, bases: dict[str, list[date]], horizon: int = 7
) -> pd.DataFrame:
    """asof.feature_rows 와 같은 행 구성을 지점당 여러 base_date 로 만든다."""
    rows = []
    for s in sites_cfg["sites"]:
        sid = s["station_id"]
        for b in bases.get(sid, []):
            feats: dict = {}
            for fn in GROUPS.values():
                feats.update(fn(daily[sid], b, s["site_code"]))
            feats.update(
                {
                    "station_id": sid,
                    "site_code": s["site_code"],
                    "base_date": pd.Timestamp(b),
                    "target_date": pd.Timestamp(b + timedelta(days=horizon)),
                    "horizon_days": float(horizon),
                }
            )
            rows.append(feats)
    return pd.DataFrame(rows)


def level_stations(src: dict[str, pd.DataFrame]) -> list[str]:
    lc = src.get("level_cont")
    return sorted(lc["station_code"].astype(str).unique()) if lc is not None and len(lc) else []


def run_source(
    source: str, sites_cfg: dict, feat_cfg: dict, start: date, today: date, per_site: int
) -> tuple[pd.DataFrame, list[str], dict[str, list[date]]]:
    src = collect(source, sites_cfg, start, today)
    daily = asof.build_daily(sites_cfg, feat_cfg, src, start, today)
    bases = recent_bases(daily, today, per_site)
    feat = feature_rows_multi(daily, sites_cfg, bases)
    feat = asof.attach_model_features(feat, src.get("algae"))
    pr = predict_registry(feat, algae=src.get("algae"))
    out = pd.concat(
        [feat[["station_id", "site_code", "base_date", "target_date", "level_cont_t0"]], pr], axis=1
    )
    return out, level_stations(src), bases


def compare(w: pd.DataFrame, d: pd.DataFrame) -> pd.DataFrame:
    keep = ["level_cont_t0", "pred_cell_count", "q50", "p_alert", "tier"]
    m = w[["station_id", "base_date", *keep]].merge(
        d[["station_id", "base_date", *keep]], on=["station_id", "base_date"], suffixes=("_w", "_d")
    )
    m["dlog_q50"] = np.log10(m["q50_d"] + 1) - np.log10(m["q50_w"] + 1)
    m["dlog_pred"] = np.log10(m["pred_cell_count_d"] + 1) - np.log10(m["pred_cell_count_w"] + 1)
    m["dp_alert"] = m["p_alert_d"] - m["p_alert_w"]
    return m.sort_values(["base_date", "station_id"]).reset_index(drop=True)


def summarize(m: pd.DataFrame) -> dict:
    lc = m[["level_cont_t0_w", "level_cont_t0_d"]].dropna()
    corr = float(np.corrcoef(lc.iloc[:, 0], lc.iloc[:, 1])[0, 1]) if len(lc) >= 2 else None
    return {
        "n": int(len(m)),
        "mean_abs_dlog_q50": float(m["dlog_q50"].abs().mean()),
        "max_abs_dlog_q50": float(m["dlog_q50"].abs().max()),
        "mean_abs_dlog_pred": float(m["dlog_pred"].abs().mean()),
        "max_abs_dlog_pred": float(m["dlog_pred"].abs().max()),
        "mean_abs_dp_alert": float(m["dp_alert"].abs().mean()),
        "tier_agree": float((m["tier_w"] == m["tier_d"]).mean()),
        "lc_t0_corr": corr,
    }


def _f(v: float, fmt: str) -> str:
    return "" if pd.isna(v) else format(v, fmt)


def write_md(m: pd.DataFrame, summ: dict, info: dict) -> None:
    lines = [
        f"# 연속 수위 소스 비교 — WAMIS vs K-water delist 댐수위 대체 (최근 {summ['n']} base_date, {FROZEN} 예측)",
        "",
        f"- 계산 일시: {info['computed_at']} KST · {FROZEN} — 레지스트리 current {json.dumps(info['registry'], ensure_ascii=False)} · "
        f"수집 창 {info['start']} ~ {info['today']} · 지점별 최근 {info['per_site']}개 조류 측정일 · 피처 v2.1(수위 편차 = 관측소별 직전 365일 평균 대비)",
        f"- 요약: {json.dumps(summ)}",
        "- 본댐 8개소(안동·임하·성덕·군위·김천부항·합천·밀양·대청)만 대체, 방수로·조정지·하굿둑·대리는 WAMIS 유지(러너 실패 시 결측).",
        f"- 수신 연속 수위 관측소: WAMIS 실행 {len(info['stations']['wamis'])}/{info['n_stations']}개, "
        f"delist 실행 {len(info['stations']['delist'])}/{info['n_stations']}개"
        + (f" (WAMIS 실행 미수신: {', '.join(info['missing']['wamis'])})" if info["missing"]["wamis"] else "")
        + (
            f" (delist 실행 미수신: {', '.join(info['missing']['delist'])})"
            if info["missing"]["delist"]
            else ""
        ),
        "- 열: lc_t0 = level_cont_t0(m), q50 = 분위 모델 중앙값, 예상값 = pred_cell_count(화면의 '예상값', v2.1 회귀 앙상블), "
        "Δlog = log10(delist+1) − log10(WAMIS+1), p = 분류기 b p_alert, tier = daily_run 규칙(p_alert ≥ 운영점 → alert, q90_cqr ≥ 10,000 → watch).",
        "",
        "| 지점 | base | lc_t0 WAMIS | lc_t0 delist | q50 WAMIS | q50 delist | Δlog q50 | 예상값 WAMIS | 예상값 delist | Δlog 예상값 | p WAMIS | p delist | tier W/D |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in m.itertuples():
        lines.append(
            f"| {r.station_id} | {r.base_date.date()} | {_f(r.level_cont_t0_w, '.3f')} | {_f(r.level_cont_t0_d, '.3f')} | "
            f"{_f(r.q50_w, ',.0f')} | {_f(r.q50_d, ',.0f')} | {_f(r.dlog_q50, '+.3f')} | "
            f"{_f(r.pred_cell_count_w, ',.0f')} | {_f(r.pred_cell_count_d, ',.0f')} | {_f(r.dlog_pred, '+.3f')} | "
            f"{_f(r.p_alert_w, '.2f')} | {_f(r.p_alert_d, '.2f')} | {r.tier_w}/{r.tier_d} |"
        )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--days", type=int, default=400, help="최소 수집 일수(시작 = min(올해 1/1, today−days))")
    ap.add_argument("--per-site", type=int, default=6, help="지점별 최근 base_date 수")
    ap.add_argument("--out-csv", default=str(OUT_CSV))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    sites_cfg, feat_cfg = asof.load_cfgs()
    start = asof.window_start(args.today, args.days)
    res, stations, bases = {}, {}, {}
    for s in SOURCES:
        res[s], stations[s], bases[s] = run_source(s, sites_cfg, feat_cfg, start, args.today, args.per_site)
        log.info("%s: 예측 %d행, 연속 수위 관측소 %d개", s, len(res[s]), len(stations[s]))
    if bases["wamis"] != bases["delist"]:
        log.warning(
            "두 실행의 base_date 가 다르다 — 공통 행만 비교: %s vs %s", bases["wamis"], bases["delist"]
        )
    m = compare(res["wamis"], res["delist"])
    summ = summarize(m)
    stats = json.loads((CONFIG_DIR / "level_cont_stats.json").read_text(encoding="utf-8"))
    all_codes = sorted({c for v in stats["site_stations"].values() for c in v})
    info = {
        "computed_at": datetime.now(tz=KST).strftime("%Y-%m-%d %H:%M"),
        "registry": current_versions(),
        "start": str(start),
        "today": str(args.today),
        "per_site": args.per_site,
        "n_stations": len(all_codes),
        "stations": stations,
        "missing": {s: [c for c in all_codes if c not in stations[s]] for s in SOURCES},
    }
    write_md(m, summ, info)
    m.to_csv(args.out_csv, index=False, encoding="utf-8", lineterminator="\n")
    print(json.dumps(summ))
    print(json.dumps({k: info[k] for k in ("start", "today", "n_stations", "missing")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
