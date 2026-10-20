"""시간·지점 피처 (03 문서 4.6절) (T3-b). horizon_days 는 features/run 이 (base, target) 쌍에서 붙인다."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from algaecast.features.base import cut_as_of, f, site_by_code, sites_cfg


def make_time_site_features(df_daily: pd.DataFrame, as_of: date, site_code: str) -> dict[str, float | str]:
    cut_as_of(df_daily, as_of)  # 규약 준수(시간·지점 피처는 달력만 사용)
    site = site_by_code(site_code)
    cfg = sites_cfg()
    ts = pd.Timestamp(as_of)
    doy = ts.dayofyear
    out: dict[str, float | str] = {
        "month_sin": math.sin(2 * math.pi * ts.month / 12),
        "month_cos": math.cos(2 * math.pi * ts.month / 12),
        "doy_sin": math.sin(2 * math.pi * doy / 365.25),
        "doy_cos": math.cos(2 * math.pi * doy / 365.25),
        "season_day": float((ts - pd.Timestamp(year=ts.year, month=5, day=1)).days),
        "year": float(ts.year),
        "site_code": site["site_code"],
        "station_id": site["station_id"],
        "basin": site["basin"],
        "facility_type": site["facility_type"],
        "intake_capacity_tpd": f(site.get("intake_capacity_tpd")),
        "intake_weight": f(site.get("intake_weight")),
    }
    if site.get("facility_dam_code"):
        spec = cfg["dams"].get(site["facility_dam_code"], {})
        out["catchment_area_km2"] = f(spec.get("catchment_km2"))
        out["total_storage_mcm"] = f(spec.get("total_mcm"))
    else:
        spec = cfg["weirs"].get(site.get("facility_kwater_code"), {})
        out["catchment_area_km2"] = f(spec.get("catchment_km2"))
        out["total_storage_mcm"] = f(spec.get("storage_mcm"))
    out["n_upstream_main_dams"] = float(
        np.sum([cfg["dams"].get(d, {}).get("role") == "main" for d in site.get("upstream_dams", [])])
    )
    return out
