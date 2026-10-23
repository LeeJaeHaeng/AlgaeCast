# ruff: noqa: E402, I001  (scripts 경로를 먼저 넣고 leakage_audit 를 가져온다)
"""음성 대조: 수위 편차를 예전 방식(전 기간 관측소 평균)으로 되돌리면 원자료 재계산 감사가 불일치를 잡는지.

결과(2026-10-23): 칠서 5개 기준일 모두 불일치(일괄 vs 기준일까지 원자료, level_cont_t0 차 0.009~1.453).
사용: python reports/experiments/FIX-v2.1/audit_negative_control.py
"""

from __future__ import annotations

import sys
from datetime import date

import pandas as pd

sys.path.insert(0, "scripts")
import algaecast.align.run as A
from algaecast.features.base import cut_as_of
from algaecast.features.run import GROUPS
import leakage_audit as L


def old_full_period(c: pd.DataFrame, days: pd.DatetimeIndex) -> tuple[pd.Series, pd.Series]:
    """FIX-v2.1 이전 방식: 관측소별 전 기간 평균 대비 편차(기준일 이후 자료 포함)."""
    w = c.pivot_table(index="obs_date", columns="station_code", values="wl_adj")
    w.index = pd.to_datetime(w.index)
    anom = (w - w.mean()).mean(axis=1).reindex(days)
    return anom, w.notna().sum(axis=1).reindex(days).fillna(0)


def features_at(daily: pd.DataFrame, b: date, site_code: str) -> dict:
    out: dict = {}
    for fn in GROUPS.values():
        out.update(fn(cut_as_of(daily, b), b, site_code))
    return out


def main() -> int:
    A.level_anomaly_asof = old_full_period
    sites_cfg, feat_cfg = A.load_cfg()
    full = A.load_sources()
    site = next(s for s in sites_cfg["sites"] if s["station_id"] == "CS")
    end = full["algae"]["obs_date"].max().date()
    batch = A.apply_strategy(A.build_site_daily(site, full, sites_cfg, feat_cfg, end), "S1", feat_cfg)
    batch["obs_date"] = pd.to_datetime(batch["obs_date"])
    n_bad = 0
    for b in [date(2018, 7, 2), date(2020, 8, 3), date(2022, 6, 13), date(2024, 9, 2), date(2025, 7, 7)]:
        src = L.truncate_sources(full, b)
        t = A.apply_strategy(A.build_site_daily(site, src, sites_cfg, feat_cfg, b), "S1", feat_cfg)
        t["obs_date"] = pd.to_datetime(t["obs_date"])
        x = features_at(batch, b, site["site_code"])["level_cont_t0"]
        y = features_at(t, b, site["site_code"])["level_cont_t0"]
        n_bad += abs(x - y) > 1e-9
        print(b, "전기간평균 일괄", round(x, 4), "기준일까지 원자료", round(y, 4), "차", round(x - y, 4))
    print("불일치", n_bad, "/ 5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
