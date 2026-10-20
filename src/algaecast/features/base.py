"""피처 함수 공통 유틸 — 누수 방지 규칙(CLAUDE.md)의 구현체.

모든 피처 함수는 진입 직후 `cut_as_of(df, as_of)`를 호출해 기준일 이후 행을 제거한다.
"""

from __future__ import annotations

from datetime import date

import pandas as pd


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
