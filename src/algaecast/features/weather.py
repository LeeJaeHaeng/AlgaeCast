"""기상 관측 피처 (03 문서 4.4절) (T3-b). 관측소는 align 단계에서 asos_by_var 로 이미 선택됨.

유역 면적강수(MT-02/03)·토양수분·증발산은 CSV 미수령
→ 수령 시 ``rn_basin_sum7/14``, ``soil_moisture_t0``, ``et_sum7`` 추가.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from algaecast.features.base import cut_as_of, f, feature_cfg, window_days


def make_weather_features(df_daily: pd.DataFrame, as_of: date, site_code: str) -> dict[str, float]:
    df = cut_as_of(df_daily, as_of)
    cfg = feature_cfg()
    out: dict[str, float] = {}
    out["ta_mean_t0"] = f(df["ta_mean"].astype(float).iloc[-1]) if len(df) else math.nan
    for w in (7, 14):
        out[f"ta_mean_ma{w}"] = f(window_days(df, as_of, w, "ta_mean").mean())
    out["ta_max_ma7"] = f(window_days(df, as_of, 7, "ta_max").mean())
    out["ta_min_ma7"] = f(window_days(df, as_of, 7, "ta_min").mean())
    t30 = window_days(df, as_of, 30, "ta_mean").astype(float)
    out["ta_degree_days20"] = (
        f(np.clip(t30 - cfg["degree_day_base_c"], 0, None).sum()) if t30.notna().any() else math.nan
    )
    for w in cfg["windows"]["rain_sum"]:
        out[f"rn_sum{w}"] = f(window_days(df, as_of, w, "rn").sum(min_count=1))
    rn = df["rn"].astype(float)
    wet = rn[rn >= cfg["dry_day_rain_mm"]]
    if len(wet):
        last_wet = pd.to_datetime(df.loc[wet.index[-1], "obs_date"])
        out["dry_days"] = float((pd.Timestamp(as_of) - last_wet).days)
    else:
        out["dry_days"] = math.nan
    out["ss_sum7"] = f(window_days(df, as_of, 7, "ss").sum(min_count=1))
    out["si_sum7"] = f(window_days(df, as_of, 7, "si").sum(min_count=1))
    out["ws_mean7"] = f(window_days(df, as_of, 7, "ws_mean").mean())
    out["ws_max7"] = f(window_days(df, as_of, 7, "ws_max").max())
    out["hm_mean7"] = f(window_days(df, as_of, 7, "hm").mean())
    out["rn_missing7"] = f(window_days(df, as_of, 7, "rn_missing").sum())
    out["si_missing7"] = f(window_days(df, as_of, 7, "si_missing").sum())
    return out
