"""수문 피처 (03 문서 4.3절 + T2 반영) (T3-b).

1차: 시설 자체(``fac_*`` = 낙동강 4지점 보, 회남 대청댐) 유입·방류·수위·저수량 → ``weir_*`` 이름
(회남도 같은 이름으로 생성, 의미는 댐).
보조: 상류 본댐 합산 ``dam_*`` → ``inflow_*``/``outflow_*``/``storage_*``/``upstream_dam_release_sum7``.
연속 수위(DataON+WAMIS) ``level_cont_anom`` → ``level_cont_diff7``.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from algaecast.features.base import cut_as_of, f, feature_cfg, site_by_code, sites_cfg, window_days

SEC_PER_DAY = 86_400.0


def _last(df: pd.DataFrame, col: str) -> float:
    s = df[col].astype(float).dropna()
    return f(s.iloc[-1]) if len(s) else math.nan


def _storage_mcm(site: dict) -> float:
    """시설 저수량 제원(10^6 m³): 보는 sites.yaml weirs.storage_mcm, 댐은 dams.effective_mcm."""
    cfg = sites_cfg()
    if site.get("facility_dam_code"):
        return f(cfg["dams"].get(site["facility_dam_code"], {}).get("effective_mcm"))
    return f(cfg["weirs"].get(site.get("facility_kwater_code"), {}).get("storage_mcm"))


def make_hydro_features(df_daily: pd.DataFrame, as_of: date, site_code: str) -> dict[str, float]:
    df = cut_as_of(df_daily, as_of)
    cfg = feature_cfg()
    site = site_by_code(site_code)
    out: dict[str, float] = {}
    # --- 1차: 시설 자체
    out["weir_inflow_t0"] = _last(df, "fac_inflow")
    out["weir_outflow_t0"] = _last(df, "fac_outflow")
    out["weir_level_t0"] = _last(df, "fac_level")
    out["weir_storage_t0"] = _last(df, "fac_storage")
    out["weir_storage_rate_t0"] = _last(df, "fac_storage_rate")
    for w in (7, 14):
        out[f"weir_outflow_sum{w}"] = f(window_days(df, as_of, w, "fac_outflow").sum(min_count=1))
    out["weir_flow_ma7"] = f(window_days(df, as_of, 7, "fac_inflow").mean())
    out["weir_outflow_ma7"] = f(window_days(df, as_of, 7, "fac_outflow").mean())
    lv = df["fac_level"].astype(float)
    out["weir_level_diff7"] = f(lv.iloc[-1] - lv.iloc[-8]) if len(lv) >= 8 else math.nan
    out["weir_outflow_change7"] = (
        f(
            (out["weir_outflow_t0"] - df["fac_outflow"].astype(float).iloc[-8])
            / (abs(df["fac_outflow"].astype(float).iloc[-8]) + 1.0)
        )
        if len(df) >= 8
        else math.nan
    )
    # 체류시간 대리: 저수량 / 방류 7일 평균 (일). 저수량 자료가 없으면 제원 저수량, 그것도 없으면 1/유량
    storage_m3 = (
        out["weir_storage_t0"] * 1e6 if not math.isnan(out["weir_storage_t0"]) else _storage_mcm(site) * 1e6
    )
    q7 = out["weir_outflow_ma7"]
    if not math.isnan(storage_m3) and not math.isnan(q7) and q7 > 0:
        out["weir_residence_proxy"] = storage_m3 / (q7 * SEC_PER_DAY)
    elif not math.isnan(q7) and q7 > 0:
        out["weir_residence_proxy"] = 1.0 / q7
    else:
        out["weir_residence_proxy"] = math.nan
    q14 = window_days(df, as_of, 14, "fac_outflow").astype(float)
    if not math.isnan(storage_m3) and q14.notna().any():
        qq = q14.where(q14 > 0)
        out["weir_residence_proxy_ma14"] = f((storage_m3 / (qq * SEC_PER_DAY)).mean())
    else:
        out["weir_residence_proxy_ma14"] = math.nan
    thr = cfg["hydro"]["release_event_m3s"]
    w7 = window_days(df, as_of, 7, "fac_outflow").astype(float)
    out["dam_release_event_7d"] = f((w7 > thr).sum()) if w7.notna().any() else math.nan
    out["weir_rain_sum7"] = f(window_days(df, as_of, 7, "fac_rain").sum(min_count=1))
    # --- 보조: 상류 본댐 합산
    out["inflow_t0"] = _last(df, "dam_inflow")
    out["outflow_t0"] = _last(df, "dam_outflow")
    for w in cfg["windows"]["flow_sum"]:
        out[f"inflow_sum{w}"] = f(window_days(df, as_of, w, "dam_inflow").sum(min_count=1))
        out[f"outflow_sum{w}"] = f(window_days(df, as_of, w, "dam_outflow").sum(min_count=1))
    out["upstream_dam_release_sum7"] = out["outflow_sum7"]
    out["storage_t0"] = _last(df, "dam_storage")
    out["storage_rate_t0"] = _last(df, "dam_storage_rate")
    st = out["storage_t0"] * 1e6 if not math.isnan(out["storage_t0"]) else math.nan
    o7 = f(window_days(df, as_of, 7, "dam_outflow").mean())
    out["residence_proxy"] = (
        st / (o7 * SEC_PER_DAY) if not math.isnan(st) and not math.isnan(o7) and o7 > 0 else math.nan
    )
    o14 = window_days(df, as_of, 14, "dam_outflow").astype(float)
    out["residence_proxy_ma14"] = (
        f((st / (o14.where(o14 > 0) * SEC_PER_DAY)).mean())
        if not math.isnan(st) and o14.notna().any()
        else math.nan
    )
    do_ = df["dam_outflow"].astype(float)
    out["outflow_change7"] = (
        f((do_.iloc[-1] - do_.iloc[-8]) / (abs(do_.iloc[-8]) + 1.0)) if len(do_) >= 8 else math.nan
    )
    # --- 연속 수위
    lc = df["level_cont_anom"].astype(float)
    out["level_cont_t0"] = f(lc.dropna().iloc[-1]) if lc.notna().any() else math.nan
    out["level_cont_diff7"] = f(lc.iloc[-1] - lc.iloc[-8]) if len(lc) >= 8 else math.nan
    # --- 결측 플래그 (최근 7일 결측 일수)
    for c, name in (("fac_inflow", "weir_inflow"), ("fac_outflow", "weir_outflow"), ("dam_inflow", "inflow")):
        m = window_days(df, as_of, 7, f"{c}_missing")
        out[f"{name}_missing7"] = f(m.sum()) if len(m) else math.nan
    out["hydro_fac_available"] = float(np.isfinite(out["weir_outflow_t0"]))
    return out
