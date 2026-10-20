"""자기회귀 피처 (03 문서 4.1절) (T3-b). 측정일 원값(``*_obs``) 만 사용한다."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from algaecast.features.base import cut_as_of, f, feature_cfg, slope

GENUS_CATS = ("Microcystis", "Dolichospermum", "Anabaena", "Oscillatoria", "Aphanizomenon", "none", "other")


def _genus_cat(g: object) -> str:
    s = str(g) if g is not None and not (isinstance(g, float) and math.isnan(g)) else "none"
    for c in GENUS_CATS:
        if c.lower() in s.lower():
            return "Anabaena" if c == "Dolichospermum" else c
    return "none" if s in ("", "nan", "None", "없음") else "other"


def make_ar_features(df_daily: pd.DataFrame, as_of: date, site_code: str) -> dict[str, float | str]:
    """cell_log_t0, lag1w~3w, slope_3, max/mean_4w, days_since_obs, dominant_genus, alert_level_t0,
    consecutive_over_1k, chla_t0/lag1w. as_of 이후 행은 진입 직후 drop."""
    df = cut_as_of(df_daily, as_of)
    cfg = feature_cfg()
    obs = df[df["is_obs"].astype(bool)]
    cells = obs["cells_obs"].astype(float)
    logc = np.log10(cells + 1)
    dates = pd.to_datetime(obs["obs_date"])
    out: dict[str, float | str] = {}
    valid = logc.dropna()
    out["cell_log_t0"] = f(valid.iloc[-1]) if len(valid) else math.nan
    for k, name in ((1, "cell_log_lag1w"), (2, "cell_log_lag2w"), (3, "cell_log_lag3w")):
        out[name] = f(valid.iloc[-1 - k]) if len(valid) > k else math.nan
    last3 = logc.dropna().iloc[-3:]
    if len(last3) == 3:
        x = (dates.loc[last3.index] - pd.Timestamp(as_of)).dt.days.to_numpy(dtype=float)
        out["cell_slope_3"] = slope(last3.to_numpy(dtype=float), x)
    else:
        out["cell_slope_3"] = math.nan
    win = cfg["windows"]["ar_days"]
    recent = logc[dates >= pd.Timestamp(as_of) - pd.Timedelta(days=win - 1)].dropna()
    out["cell_max_4w"] = f(recent.max()) if len(recent) else math.nan
    out["cell_mean_4w"] = f(recent.mean()) if len(recent) else math.nan
    out["cell_n_obs_4w"] = float(len(recent))
    out["days_since_obs"] = float((pd.Timestamp(as_of) - dates.iloc[-1]).days) if len(dates) else math.nan
    out["dominant_genus"] = (
        _genus_cat(obs["genus_obs"].dropna().iloc[-1]) if obs["genus_obs"].notna().any() else "none"
    )
    lv = obs["alert_level_obs"].dropna()
    out["alert_level_t0"] = f(lv.iloc[-1]) if len(lv) else 0.0
    n = 0
    for v in cells.dropna().iloc[::-1]:
        if v >= 1000:
            n += 1
        else:
            break
    out["consecutive_over_1k"] = float(n)
    chla = obs["chla_obs"].astype(float).dropna()
    out["chla_t0"] = f(chla.iloc[-1]) if len(chla) else math.nan
    out["chla_lag1w"] = f(chla.iloc[-2]) if len(chla) > 1 else math.nan
    out["cells_missing_t0"] = float(obs["cells_obs"].isna().iloc[-1]) if len(obs) else math.nan
    return out
