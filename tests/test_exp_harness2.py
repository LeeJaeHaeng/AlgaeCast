"""2차 하네스: 구간 마스크·시드 짝 차이·대조군 난수(모델 학습 없음)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from algaecast.exp import harness2 as H2


def _frame() -> pd.DataFrame:
    base = pd.to_datetime(
        ["2024-07-01", "2025-03-01", "2025-08-28", "2025-09-10", "2025-10-20", "2025-12-29"]
    )
    return pd.DataFrame(
        {
            "station_id": ["HP"] * 6,
            "base_date": base.date,
            "target_date": (base + pd.Timedelta(days=7)).date,
            "target_cells": np.arange(6, dtype=float),
        }
    )


def test_scope_masks_by_target_month() -> None:
    m = H2.scope_masks(_frame())
    assert m["cv"].tolist() == [True, False, False, False, False, False]
    assert m["y25"].tolist() == [False, True, True, True, True, False]  # 목표일 2026-01 행 제외
    # 2025-08-28 기준일의 목표일은 9월 4일 → 9~10월 구간
    assert m["y25a"].tolist() == [False, True, False, False, False, False]
    assert m["y25b"].tolist() == [False, False, True, True, True, False]
    assert not (m["y25a"] & m["y25b"]).any()


def test_paired_delta_matches_seeds() -> None:
    rows = [{"seed": 1, "x": 0.5}, {"seed": 2, "x": 0.7}]
    base = [{"seed": 2, "x": 0.4}, {"seed": 1, "x": 0.3}]
    assert abs(H2.paired_delta(rows, base, "x") - 0.25) < 1e-12


def test_noise_like_keeps_missing_pattern() -> None:
    f = pd.DataFrame({"a": [1.0, np.nan, 3.0], "b": [np.nan, 2.0, 2.0]})
    n1, n2 = H2.noise_like(f, 11), H2.noise_like(f, 22)
    assert (n1.isna().to_numpy() == f.isna().to_numpy()).all()
    assert not np.allclose(n1.fillna(0).to_numpy(), n2.fillna(0).to_numpy())
