"""EXP-006(R3) 속별 모델: 속별 피처 as_of 누수, 속별 타깃 정렬·합계 일치, 학습 라벨 시점, 2026 가드."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from algaecast.exp import harness as H
from algaecast.exp import r3_genus as R
from algaecast.models.train import VariantSpec

GCOLS = list(R.GENUS.values())


def _algae(start: str = "2024-04-01", n: int = 40, sid: str = "HP", seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    d = pd.date_range(start, periods=n, freq="7D")
    a = pd.DataFrame({"station_id": sid, "obs_date": d})
    for c in GCOLS:
        a[c] = rng.integers(0, 5000, size=n).astype(float)
    a.loc[a.index % 5 == 0, R.GENUS["osc"]] = 0.0
    a.loc[3, R.GENUS["anba"]] = np.nan
    a[R.TOTAL_COL] = a[GCOLS].sum(axis=1)
    return a


def _same(a: dict, b: dict) -> bool:
    return a.keys() == b.keys() and all(
        (np.isnan(a[k]) and np.isnan(b[k])) or a[k] == pytest.approx(b[k]) for k in a
    )


# ---------------------------------------------------------------- as_of 누수
@pytest.mark.parametrize("as_of", [date(2024, 6, 3), date(2024, 6, 5), date(2024, 9, 30)])
def test_genus_ar_features_ignore_rows_after_as_of(as_of: date) -> None:
    a = _algae()
    ref = R.genus_ar_features(a, as_of, "HP")
    after = pd.to_datetime(a["obs_date"]) > pd.Timestamp(as_of)
    assert after.any() and (~after).any()
    rng = np.random.default_rng(1)
    # (1) as_of 이후 값을 난수로 교체
    b = a.copy()
    for c in [*GCOLS, R.TOTAL_COL]:
        b.loc[after, c] = rng.uniform(0, 1e6, size=int(after.sum()))
    assert _same(ref, R.genus_ar_features(b, as_of, "HP"))
    # (2) as_of 이후 행 삭제
    assert _same(ref, R.genus_ar_features(a[~after], as_of, "HP"))
    # (3) as_of 다음날 행 추가(큰 값)
    extra = a.iloc[[0]].copy()
    extra["obs_date"] = pd.Timestamp(as_of) + pd.Timedelta(days=1)
    extra[GCOLS] = 9e6
    assert _same(ref, R.genus_ar_features(pd.concat([a, extra], ignore_index=True), as_of, "HP"))


def test_genus_ar_features_values_and_other_station() -> None:
    a = _algae()
    other = _algae(sid="CS", seed=5)
    as_of = pd.Timestamp(a["obs_date"].iloc[10]).date()
    out = R.genus_ar_features(pd.concat([a, other]), as_of, "HP")
    last = a.iloc[10]
    assert out["micro_log_t0"] == pytest.approx(np.log10(last[R.GENUS["micro"]] + 1))
    win = a[
        (a["obs_date"] <= pd.Timestamp(as_of))
        & (a["obs_date"] >= pd.Timestamp(as_of) - pd.Timedelta(days=27))
    ]
    assert out["apzo_log_max4w"] == pytest.approx(np.log10(win[R.GENUS["apzo"]].max() + 1))
    tot = sum(last[c] for c in GCOLS)
    assert out["micro_share_t0"] == pytest.approx(last[R.GENUS["micro"]] / tot)
    assert set(out) == set(R.GF_COLS)


def test_build_features_same_index_new_columns_only() -> None:
    a = _algae()
    df = pd.DataFrame(
        {
            "station_id": ["HP", "HP", "CS"],
            "base_date": [date(2024, 6, 3), date(2024, 8, 12), date(2024, 8, 12)],
        },
        index=[7, 3, 11],
    )
    out = R.build_features(df, a)
    assert list(out.index) == [7, 3, 11]
    assert list(out.columns) == R.GF_COLS
    assert out.loc[11].isna().all()  # CS 원자료 없음
    with pytest.raises(RuntimeError):
        R.build_features(pd.DataFrame({"station_id": ["HP"], "base_date": [date(2026, 5, 1)]}), a)


# ---------------------------------------------------------------- 속별 타깃·합계 일치
def test_genus_targets_alignment_and_consistency() -> None:
    a = _algae()
    a.loc[5, R.GENUS["micro"]] += 10  # 4속 합 ≠ 총합(=v1 타깃)인 행을 만든다
    d = a["obs_date"]
    df = pd.DataFrame(
        {
            "station_id": ["HP", "HP", "HP", "HP"],
            "base_date": [d[0].date(), d[2].date(), d[4].date(), d[30].date()],
            "target_date": [d[1].date(), d[3].date(), d[5].date(), (d[30] + pd.Timedelta(days=3)).date()],
            "target_cells": [a.loc[1, R.TOTAL_COL], 100.0, a.loc[5, R.TOTAL_COL], 50.0],
        },
        index=[10, 11, 12, 13],
    )
    tg = R.genus_targets(df, a)
    assert list(tg.index) == [10, 11, 12, 13]
    assert tg.loc[10, "y_micro"] == a.loc[1, R.GENUS["micro"]]
    assert bool(tg.loc[10, "consistent"])
    assert np.isnan(tg.loc[11, "y_anba"]) and pd.isna(tg.loc[11, "consistent"])  # 4속 중 결측
    assert not bool(tg.loc[12, "consistent"]) and np.isnan(tg.loc[12, "y_micro"])  # 불일치 → 비움
    assert tg.loc[13, ["y_micro", "y_apzo"]].isna().all()  # 같은 날 측정 없음
    rest = R.part_target(tg, "rest")
    assert rest[0] == pytest.approx(a.loc[1, [R.GENUS[g] for g in ("anba", "apzo", "osc")]].sum())
    assert np.isnan(rest[1])


def test_compare_sources_counts_matches() -> None:
    a = _algae()
    c = a.copy()
    assert (R.compare_sources(a, c)["일치"] == R.compare_sources(a, c)["둘 다 값"]).all()
    c.loc[2, R.GENUS["apzo"]] += 5
    t = R.compare_sources(a, c).set_index("열")
    assert t.loc[R.GENUS["apzo"], "일치"] == t.loc[R.GENUS["apzo"], "둘 다 값"] - 1


# ---------------------------------------------------------------- 학습 라벨 시점(연도 확장)
def _synthetic(seed: int = 0) -> tuple[pd.DataFrame, np.ndarray]:
    rng = np.random.default_rng(seed)
    dates = [pd.Timestamp(f"{y}-0{m}-1{k}") for y in range(2016, 2026) for m in (5, 7, 9) for k in range(10)]
    n = len(dates)
    df = pd.DataFrame(
        {
            "station_id": "HP",
            "base_date": [d.date() for d in dates],
            "x1": rng.normal(size=n),
            "x2": rng.normal(size=n),
        }
    )
    y = np.where(rng.uniform(size=n) < 0.4, 0.0, 10 ** (2 + df["x1"].to_numpy() + rng.normal(0, 0.3, n)))
    df["target_cells"] = y + 1.0  # 합계 타깃(속별 모델에는 쓰지 않음)
    df["target_log"] = np.log10(df["target_cells"] + 1)
    return df, y


SMALL = VariantSpec(
    "log_w",
    alpha=0.05,
    params={"n_estimators": 20, "learning_rate": 0.1, "num_leaves": 7, "min_child_samples": 5},
)


@pytest.mark.parametrize("mode", ["log", "hurdle"])
def test_fit_component_uses_only_prior_year_labels(mode: str) -> None:
    df, y = _synthetic()
    ref = R.fit_component(df, ["x1", "x2"], y, mode, SMALL)
    years = H.years_of(df)
    y2 = y.copy()
    fut = years >= 2023
    y2[fut] = np.random.default_rng(9).uniform(0, 1e6, size=int(fut.sum()))  # 2023 이후 라벨 교란
    y2[years == 2017] = np.nan  # 결측 라벨은 학습에서 빠진다
    out = R.fit_component(df, ["x1", "x2"], y2, mode, SMALL)
    keep = (years >= 2020) & (years <= 2023)
    ref_nan = R.fit_component(df, ["x1", "x2"], np.where(years == 2017, np.nan, y), mode, SMALL)
    for b in R.BIASES:
        np.testing.assert_allclose(out[b][keep], ref_nan[b][keep])  # ≤2023 검증 행은 2023+ 라벨과 무관
        assert np.isnan(ref[b][years < 2020]).all() and np.isfinite(ref[b][years >= 2020]).all()
        assert (ref[b][years >= 2020] >= 0).all()


def test_members_rejects_2026_rows() -> None:
    df = pd.DataFrame({"station_id": ["HP"], "base_date": [date(2026, 6, 1)], "target_cells": [1.0]})
    with pytest.raises(RuntimeError):
        R.members(df, ["x1"])


@pytest.mark.skipif(not H.ALGAE_PARQUET.exists(), reason="조류 원자료 없음")
def test_load_algae_cuts_after_2025() -> None:
    a = R.load_algae()
    assert a["obs_date"].max() <= H.LAST_DATE
    assert set(R.GENUS.values()) <= set(a.columns)
