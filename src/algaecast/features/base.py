"""피처 함수 공통 유틸 — 누수 방지 규칙(CLAUDE.md)의 구현체.

모든 피처 함수는 진입 직후 `cut_as_of(df, as_of)`를 호출해 기준일 이후 행을 제거한다.
"""

from __future__ import annotations

import math
from datetime import date
from functools import lru_cache

import numpy as np
import pandas as pd
import yaml

from algaecast.config import CONFIG_DIR


def cut_as_of(df: pd.DataFrame, as_of: date, date_col: str = "obs_date") -> pd.DataFrame:
    """`as_of`(포함) 이전 행만 반환한다. 이후 행은 어떤 경우에도 사용하지 않는다.

    Args:
        df: `date_col` 컬럼을 가진 일별/측정일별 데이터프레임.
        as_of: 예측 기준일(base_date).
        date_col: 관측일 컬럼명(기본 ``obs_date``).

    Returns:
        복사본 데이터프레임(`date_col <= as_of`).
    """
    if date_col not in df.columns:
        msg = f"'{date_col}' 컬럼이 없습니다: {list(df.columns)[:10]}"
        raise KeyError(msg)
    observed = pd.to_datetime(df[date_col]).dt.normalize()
    return df.loc[observed <= pd.Timestamp(as_of)].copy()


@lru_cache(maxsize=1)
def feature_cfg() -> dict:
    return yaml.safe_load((CONFIG_DIR / "features.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def sites_cfg() -> dict:
    return yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))


def site_by_code(site_code: str) -> dict:
    for s in sites_cfg()["sites"]:
        if s["site_code"] == site_code or s["station_id"] == site_code:
            return s
    raise KeyError(site_code)


def f(x: object) -> float:
    """NaN-safe float 변환 (None/NA → nan)."""
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return math.nan
    return v


def tail(s: pd.Series, n: int) -> pd.Series:
    """마지막 n 행 (as_of 이전으로 이미 잘린 시리즈 가정)."""
    return s.iloc[-n:] if n > 0 else s.iloc[0:0]


def window_days(df: pd.DataFrame, as_of: date, days: int, col: str) -> pd.Series:
    """as_of 를 포함해 최근 ``days`` 일 구간의 값 (일 단위 달력 가정)."""
    d = pd.to_datetime(df["obs_date"])
    lo = pd.Timestamp(as_of) - pd.Timedelta(days=days - 1)
    return df.loc[(d >= lo) & (d <= pd.Timestamp(as_of)), col]


def slope(y: np.ndarray, x: np.ndarray) -> float:
    ok = ~np.isnan(y) & ~np.isnan(x)
    if ok.sum() < 2 or np.ptp(x[ok]) == 0:
        return math.nan
    return float(np.polyfit(x[ok], y[ok], 1)[0])
