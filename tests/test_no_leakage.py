"""누수 방지 테스트 (CLAUDE.md 절대 규칙).

T3-b 에서 피처 함수마다 테스트를 추가한다. 여기서는 공통 가드 `cut_as_of` 를 검증한다.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from algaecast.features.base import cut_as_of


def _daily(start: str = "2025-06-01", days: int = 30, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "site_code": "2011G56",
            "obs_date": pd.date_range(start, periods=days, freq="D").date,
            "value": rng.normal(size=days),
        }
    )


def test_cut_as_of_drops_rows_after_base_date() -> None:
    df = _daily()
    as_of = date(2025, 6, 15)
    out = cut_as_of(df, as_of)
    assert out["obs_date"].max() <= as_of
    assert len(out) == 15  # 6/1 ~ 6/15 포함


def test_cut_as_of_output_is_invariant_to_future_values() -> None:
    """as_of 이후 값을 무작위로 바꿔도 결과가 동일해야 한다 (피처 함수 공통 계약)."""
    as_of = date(2025, 6, 15)
    df = _daily()
    base = cut_as_of(df, as_of)

    tampered = df.copy()
    future = pd.to_datetime(tampered["obs_date"]) > pd.Timestamp(as_of)
    tampered.loc[future, "value"] = 1e9
    tampered = pd.concat([tampered, _daily("2025-07-01", 10, seed=7)], ignore_index=True)

    pd.testing.assert_frame_equal(
        cut_as_of(tampered, as_of).reset_index(drop=True), base.reset_index(drop=True)
    )


def test_cut_as_of_requires_date_column() -> None:
    with pytest.raises(KeyError):
        cut_as_of(pd.DataFrame({"x": [1]}), date(2025, 1, 1))
