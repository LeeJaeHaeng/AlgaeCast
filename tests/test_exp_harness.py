"""고도화 실험 하네스의 가드·사건 규칙 테스트(모델 학습 없음)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from algaecast.exp import harness as H


def _frame(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "station_id": ["HP"] * len(dates),
            "base_date": pd.to_datetime(dates).date,
            "target_cells": np.arange(len(dates), dtype=float),
        }
    )


def test_guard_rejects_2026_rows() -> None:
    H.guard_no_2026(_frame(["2025-12-31", "2020-05-01"]))
    with pytest.raises(RuntimeError):
        H.guard_no_2026(_frame(["2025-12-31", "2026-01-01"]))


def test_guard_rejects_test_split() -> None:
    df = _frame(["2024-06-01"]).assign(split="test")
    with pytest.raises(RuntimeError):
        H.guard_no_2026(df)


@pytest.mark.skipif(not H.ALGAE_PARQUET.exists(), reason="조류 원자료 없음")
def test_events_end_by_2025() -> None:
    ev = H.official_events_until()
    assert len(ev) > 0
    assert ev["D"].max() <= H.LAST_DATE and ev["E"].max() <= H.LAST_DATE


def test_expanding_fit_apply_uses_only_prior_years() -> None:
    dates = [f"{y}-07-01" for y in range(2019, 2026) for _ in range(60)]
    df = _frame(dates)
    years = H.years_of(df)
    seen: dict[int, int] = {}

    def fit(mask: np.ndarray) -> int:
        return int(years[mask].max())

    def apply(state: object, mask: np.ndarray) -> np.ndarray:
        y = int(years[mask][0])
        seen[y] = -1 if state is None else int(state)
        return np.zeros(mask.sum())

    H.expanding_fit_apply(df, fit, apply)
    assert seen[2020] == -1  # 2020 은 이전 CV 연도 없음
    assert all(seen[y] < y for y in range(2021, 2026))
    assert seen[2025] == 2024


def test_adoption_rule() -> None:
    base = {"cv_r2_raw": 0.17, "cv_rmse_log": 0.805, "lead_q90": 18}
    assert H.adoption(base, {"cv_r2_raw": 0.28, "cv_rmse_log": 0.81, "lead_q90": 18})["pass"]
    assert not H.adoption(base, {"cv_r2_raw": 0.28, "cv_rmse_log": 0.82, "lead_q90": 18})["pass"]
    assert not H.adoption(base, {"cv_r2_raw": 0.28, "cv_rmse_log": 0.80, "lead_q90": 17})["pass"]
