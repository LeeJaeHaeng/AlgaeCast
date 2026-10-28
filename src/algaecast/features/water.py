"""수온·수질 피처 (03 문서 4.2절 + T2 반영: 지점별 관심 도달 수온 임계) (T3-b).

지점별 임계는 config/derived_constants.json 의 연도별 값(FIX-v2.1 R3). 피처 파일에는
제출 모델 T24용(측정 ≤2024, FINAL_THRESHOLD_YEAR) 임계로 계산하고,
CV 폴드는 features.constants.apply_site_thresholds 가 그 폴드 학습기간 임계로 다시 계산한다.

일 단위 ``wtemp`` 는 정렬 전략(S1 LOCF / S2 보간 / S3 모델)으로 채워진 값, ``*_obs`` 는 측정일 원값.
총인·총질소는 조류경보제 자료에 없어 생략(수질측정망 결합 시 추가).
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from algaecast.features.base import cut_as_of, f, feature_cfg, site_by_code, window_days
from algaecast.features.constants import FINAL_THRESHOLD_YEAR, WTEMP_LAST, site_thresholds


def make_water_features(df_daily: pd.DataFrame, as_of: date, site_code: str) -> dict[str, float]:
    df = cut_as_of(df_daily, as_of)
    cfg = feature_cfg()
    site = site_by_code(site_code)
    out: dict[str, float] = {}
    obs = df[df["is_obs"].astype(bool)]
    for col in ("wtemp", "ph", "do", "turb", "transp"):
        s = obs[f"{col}_obs"].astype(float).dropna()
        out[f"{col}_t0"] = f(s.iloc[-1]) if len(s) else math.nan
    wt = df["wtemp"].astype(float)
    for w in cfg["windows"]["water_ma"]:
        out[f"wtemp_ma{w}"] = f(window_days(df, as_of, w, "wtemp").mean())
    last = wt.iloc[-1] if len(wt) else math.nan
    prev7 = wt.iloc[-8] if len(wt) >= 8 else math.nan
    out["wtemp_diff7"] = f(last - prev7)
    w30 = window_days(df, as_of, 30, "wtemp").astype(float)
    base = cfg["degree_day_base_c"]
    out["wtemp_days_over25"] = f((w30 > cfg["wtemp_hot_c"]).sum()) if w30.notna().any() else math.nan
    out["wtemp_degree_days20"] = f(np.clip(w30 - base, 0, None).sum()) if w30.notna().any() else math.nan
    th = site_thresholds(FINAL_THRESHOLD_YEAR).get(site["station_id"])
    th = math.nan if th is None else float(th)
    out["wtemp_over_site_thresh_days"] = (
        f((w30 > th).sum()) if w30.notna().any() and not math.isnan(th) else math.nan
    )
    out["wtemp_minus_site_thresh"] = f(last - th)
    out[WTEMP_LAST] = f(last)
    out["wtemp_missing_days30"] = f(w30.isna().sum())
    return out
