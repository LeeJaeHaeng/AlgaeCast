"""예보 피처 — issued_at <= as_of 발표분만 허용 (03 문서 4.5절) (T3-b).

align 단계가 발표일 행에 ``fc_*`` 요약(당일 05/06시 발표분, +1~+7일)을 두므로 ``obs_date == as_of`` 행이 곧
"as_of 06:00 까지 발표된 예보" 이다. 그 행이 없거나(2026-10-21 이전) 비어 있으면 결측 + ``fc_available=0``.
원 long 테이블에서 직접 만들 때는 ``forecast_features_from_long`` 이 ``issued_at <= as_of 06:00`` 을 강제한다.
"""

from __future__ import annotations

import math
from datetime import date, datetime

import pandas as pd

from algaecast.collect.base import KST
from algaecast.features.base import cut_as_of, f, feature_cfg

FC_COLS = ("fc_ta_mean_d1_7", "fc_ta_max_d1_7", "fc_rn_sum_d1_7", "fc_pop_mean_d1_7", "fc_rain_days")


def make_forecast_features(df_daily: pd.DataFrame, as_of: date, site_code: str) -> dict[str, float]:
    df = cut_as_of(df_daily, as_of)
    cfg = feature_cfg()
    out: dict[str, float] = {c: math.nan for c in FC_COLS}
    out["fc_available"] = 0.0
    if pd.Timestamp(as_of) < pd.Timestamp(cfg["forecast"]["available_from"]):
        return out
    row = df[pd.to_datetime(df["obs_date"]).dt.normalize() == pd.Timestamp(as_of)]
    if row.empty or not bool(row["fc_available"].iloc[-1]):
        return out
    for c in FC_COLS:
        out[c] = f(row[c].iloc[-1])
    out["fc_available"] = 1.0
    return out


def forecast_features_from_long(fc_long: pd.DataFrame, as_of: date, site_code: str) -> dict[str, float]:
    """원 long(issued_at, site_code, target_date, variable, value) 에서 직접 계산.

    issued_at ≤ as_of 06:00 KST 발표분만 사용한다.
    """
    cfg = feature_cfg()
    cutoff = datetime.combine(as_of, datetime.min.time()).replace(
        hour=cfg["forecast"]["cutoff_hour_kst"], tzinfo=KST
    )
    g = fc_long[(fc_long["site_code"] == site_code) & (pd.to_datetime(fc_long["issued_at"]) <= cutoff)].copy()
    out: dict[str, float] = {c: math.nan for c in FC_COLS}
    out["fc_available"] = 0.0
    if g.empty:
        return out
    latest = g["issued_at"].max()
    g = g[g["issued_at"] == latest]
    g["lead"] = (pd.to_datetime(g["target_date"]) - pd.Timestamp(as_of)).dt.days
    g = g[g["lead"].between(1, 7)]
    if g.empty:
        return out
    p = g.pivot_table(index="lead", columns="variable", values="value", aggfunc="mean")
    out["fc_ta_mean_d1_7"] = f(p["ta_mean"].mean()) if "ta_mean" in p else math.nan
    out["fc_ta_max_d1_7"] = f(p["ta_max"].mean()) if "ta_max" in p else math.nan
    out["fc_rn_sum_d1_7"] = f(p["rn_sum"].sum()) if "rn_sum" in p else math.nan
    out["fc_pop_mean_d1_7"] = f(p["pop_max"].mean()) if "pop_max" in p else math.nan
    out["fc_rain_days"] = (
        f((p["pop_max"] >= cfg["forecast"]["pop_rain_day"]).sum()) if "pop_max" in p else math.nan
    )
    out["fc_available"] = 1.0
    return out
