"""EXP-005(R2) 상류 지점 피처의 as_of 누수 테스트와 정의 점검(모델 학습 없음).

tests/test_no_leakage.py 와 같은 방식: as_of 이후 행을 난수로 바꾸고 절반을 지워도 결과가 같아야 한다.
고정 lag 은 (as_of − lag, as_of] 구간 측정도 쓰지 않아야 하고, travel lag 의 보 방류량도 as_of 까지만 쓴다.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from algaecast.exp import harness as H
from algaecast.exp import r2_upstream as R
from algaecast.features.base import cut_as_of

AS_OFS = [date(2024, 7, 15), date(2024, 9, 2)]


def _algae(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for s in ("HP", "GJGR", "CS", "MGMR", "DCHN"):
        for d in pd.date_range("2024-03-04", "2024-11-25", freq="7D"):
            rows.append(
                {
                    "station_id": s,
                    "obs_date": d,
                    "cells": float(10 ** rng.uniform(0, 5)),
                    "wtemp": float(rng.uniform(5, 32)),
                }
            )
    a = pd.DataFrame(rows)
    a.loc[a.index[::11], "cells"] = np.nan  # 결측 측정 포함
    a.loc[a.index[::7], "wtemp"] = np.nan
    return a


def _hydro(seed: int = 0) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", "2024-12-31", freq="D")
    out = {}
    for s in R.NAKDONG:
        nom = R.NOMINAL_MCM[s] or 300.0
        out[s] = pd.DataFrame(
            {
                "obs_date": idx,
                "fac_outflow": rng.uniform(30, 600, len(idx)),
                "fac_storage": rng.uniform(0.8, 1.1, len(idx)) * nom,
            }
        )
    return out


def _tamper_algae(a: pd.DataFrame, as_of: date, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = a.copy()
    after = pd.to_datetime(t["obs_date"]) > pd.Timestamp(as_of)
    t.loc[after, "cells"] = rng.uniform(-1e6, 1e6, after.sum())
    t.loc[after, "wtemp"] = rng.uniform(-50, 50, after.sum())
    return t.drop(index=t.index[after][::2]).reset_index(drop=True)


def _tamper_hydro(h: dict[str, pd.DataFrame], as_of: date, seed: int) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    out = {}
    for s, d in h.items():
        t = d.copy()
        after = pd.to_datetime(t["obs_date"]) > pd.Timestamp(as_of)
        t.loc[after, "fac_outflow"] = rng.uniform(0, 1e5, after.sum())
        t.loc[after, "fac_storage"] = rng.uniform(0, 1e4, after.sum())
        out[s] = t.drop(index=t.index[after][::2]).reset_index(drop=True)
    return out


def _same(a: dict[str, float], b: dict[str, float]) -> bool:
    if a.keys() != b.keys():
        return False
    return all(
        (isinstance(x, float) and math.isnan(x) and math.isnan(y)) or x == y
        for x, y in zip(a.values(), b.values(), strict=True)
    )


@pytest.mark.parametrize("lag_mode", R.LAG_MODES)
@pytest.mark.parametrize("station", ["GJGR", "CS", "MGMR"])
@pytest.mark.parametrize("as_of", AS_OFS)
def test_upstream_features_ignore_future(lag_mode: str, station: str, as_of: date) -> None:
    a, h = _algae(), _hydro()
    base = R.make_upstream_features(a, h, as_of, station, 7.0, lag_mode, 2.5)
    assert np.isfinite(base["up1_cell_log"]), "상류 1단계 값이 있어야 함"
    for seed in (1, 2, 3):
        out = R.make_upstream_features(
            _tamper_algae(a, as_of, seed), _tamper_hydro(h, as_of, seed), as_of, station, 7.0, lag_mode, 2.5
        )
        assert _same(base, out), f"{station} {lag_mode} seed={seed}"


@pytest.mark.parametrize("lag_mode", R.LAG_MODES)
def test_truncated_inputs_give_same_result(lag_mode: str) -> None:
    a, h = _algae(), _hydro()
    as_of = AS_OFS[1]
    full = R.make_upstream_features(a, h, as_of, "CS", 7.0, lag_mode, 1.0)
    trunc = R.make_upstream_features(
        cut_as_of(a, as_of), {k: cut_as_of(v, as_of) for k, v in h.items()}, as_of, "CS", 7.0, lag_mode, 1.0
    )
    assert _same(full, trunc)


def test_fixed_lag_excludes_recent_window() -> None:
    """lag=7: (as_of−7, as_of] 측정을 바꿔도 결과 불변, lag=0 은 바뀌어야 한다(사용 여부 확인)."""
    a = _algae()
    as_of = date(2024, 7, 15)  # 월요일 측정일
    t = a.copy()
    recent = (pd.to_datetime(t["obs_date"]) > pd.Timestamp(as_of) - pd.Timedelta(days=7)) & (
        pd.to_datetime(t["obs_date"]) <= pd.Timestamp(as_of)
    )
    assert recent.any()
    t.loc[recent, "cells"] = 123456.0
    t.loc[recent, "wtemp"] = 99.0
    for lag in ("7", "3"):
        assert _same(
            R.make_upstream_features(a, None, as_of, "CS", 7.0, lag),
            R.make_upstream_features(t, None, as_of, "CS", 7.0, lag),
        )
    changed = R.make_upstream_features(t, None, as_of, "CS", 7.0, "0")
    assert changed["up1_cell_log"] == pytest.approx(np.log10(123456.0 + 1))
    assert changed["up1_wtemp"] == 99.0 and changed["up1_days"] == 0.0


def test_point_feature_values() -> None:
    a = _algae()
    as_of = date(2024, 9, 2)
    out = R.upstream_point_features(a[a["station_id"] == "GJGR"], as_of, 3)
    g = a[(a["station_id"] == "GJGR") & (a["obs_date"] <= pd.Timestamp(as_of) - pd.Timedelta(days=3))]
    v = g.dropna(subset=["cells"])
    assert out["cell_log"] == pytest.approx(np.log10(v["cells"].iloc[-1] + 1))
    assert out["days"] == (pd.Timestamp(as_of) - v["obs_date"].iloc[-1]).days
    assert out["wtemp"] == g["wtemp"].dropna().iloc[-1]
    x = (v["obs_date"].iloc[-3:] - pd.Timestamp(as_of)).dt.days.to_numpy(dtype=float)
    y = np.log10(v["cells"].iloc[-3:].to_numpy() + 1)
    assert out["slope3"] == pytest.approx(np.polyfit(x, y, 1)[0])


def test_chain_and_no_upstream_sites() -> None:
    a, h = _algae(), _hydro()
    as_of = AS_OFS[0]
    for s in ("HP", "DCHN"):
        out = R.make_upstream_features(a, h, as_of, s, 7.0, "travel", 1.0)
        assert all(math.isnan(v) for v in out.values()), s
    g = R.make_upstream_features(a, h, as_of, "GJGR", 7.0, "0", 1.0)
    assert np.isfinite(g["up1_cell_log"]) and math.isnan(g["up2_cell_log"])
    # CS 의 1단계 = GJGR, 2단계 = HP
    cs = R.make_upstream_features(a, h, as_of, "CS", 7.0, "0", 1.0)
    for k, up in ((1, "GJGR"), (2, "HP")):
        ref = R.upstream_point_features(a[a["station_id"] == up], as_of, 0)
        assert cs[f"up{k}_cell_log"] == ref["cell_log"]
        assert cs[f"up{k}_diff"] == pytest.approx(ref["cell_log"] - 1.0)


def test_travel_time_formula_constant_flow() -> None:
    idx = pd.date_range("2024-01-01", "2024-03-31", freq="D")
    h = {}
    for s in R.NAKDONG:
        h[s] = pd.DataFrame({"obs_date": idx, "fac_outflow": 100.0, "fac_storage": R.NOMINAL_MCM[s] or 300.0})
    as_of = date(2024, 3, 1)
    a_hp = 88.8e6 / 27e3
    a_gj = 92.3e6 / 25e3
    expect = 41e3 * (a_hp + a_gj) / 2 / 100.0 / 86400
    assert R.travel_days(h, as_of, "HP", "GJGR") == pytest.approx(expect)
    two = R.travel_days(h, as_of, "HP", "CS")
    assert two == pytest.approx(expect + R.segment_travel_days(h, as_of, "GJGR", "CS"))
    lag, t = R.lag_for("travel", h, as_of, "HP", "GJGR", 7.0)
    assert t == pytest.approx(expect) and lag == int(np.clip(np.round(expect - 7.0), 0, R.LAG_CAP))
    # 이상치 저수량(제원의 3배 초과)은 제원 값으로 대체
    h["HP"]["fac_storage"] = 1e5
    assert R.travel_days(h, as_of, "HP", "GJGR") == pytest.approx(expect)


def test_columns_for_bundles() -> None:
    assert R.columns_for(1, "cell") == ["up1_cell_log"]
    assert R.columns_for(2, "all4") == [
        "up1_cell_log", "up1_slope3", "up1_wtemp", "up1_days",
        "up2_cell_log", "up2_slope3", "up2_wtemp", "up2_days",
    ]  # fmt: skip
    assert "up2_diff" in R.columns_for(2, "all4_diff")


@pytest.mark.skipif(not H.ALGAE_PARQUET.exists(), reason="조류 원자료 없음")
def test_build_features_real_rows_index_and_2026_guard() -> None:
    df = H.load_base()
    sub = df.groupby("station_id", observed=True).tail(6)
    out = R.build_features(sub)
    assert list(out.index) == list(sub.index)
    assert list(out.columns) == R.columns_for(int(R.CHOSEN["depth"]), str(R.CHOSEN["bundle"]))
    sid = sub["station_id"].astype(str)
    assert out[sid.isin(["HP", "DCHN"])].isna().all().all()
    assert out.loc[sid.isin(["GJGR", "CS", "MGMR"]), "up1_cell_log"].notna().all()
    assert R.load_algae()["obs_date"].max() <= H.LAST_DATE
