"""운영 v2 상류 피처(features.upstream)의 as_of 누수 테스트와 실험 코드(R2) 동등성.

누수: as_of 이후 원자료를 난수로 바꾸고 절반을 지워도 결과가 같아야 한다(tests/test_no_leakage.py 방식).
표본 프레임 build_upstream 은 행마다 그 행의 기준일까지만 쓴다(행별로 확인).
동등성: harness.load_base() 행에서 exp.r2_upstream.build_features 와 값·NaN 위치가 완전히 같아야 한다
(데이터 없으면 skip). 2026 test 행은 confirm_2026 방식(R2.build_variant_features, lag 0)과 같아야 한다.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from algaecast.features import upstream as U

AS_OFS = [date(2024, 7, 15), date(2024, 9, 2), date(2024, 3, 20)]


def _algae(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for s in ("HP", "GJGR", "CS", "MGMR", "DCHN"):
        for d in pd.date_range("2024-03-04", "2024-11-25", freq="7D"):
            rows.append(
                {
                    "station_id": s,
                    "obs_date": d.date(),
                    "iem_bgalage_cell_co": float(10 ** rng.uniform(0, 5)),
                    "iem_wtrtp": float(rng.uniform(5, 32)),
                }
            )
    a = pd.DataFrame(rows)
    a.loc[a.index[::11], "iem_bgalage_cell_co"] = np.nan  # 결측 측정 포함
    a.loc[a.index[::7], "iem_wtrtp"] = np.nan
    return a


def _tamper(a: pd.DataFrame, as_of: date, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = a.copy()
    after = pd.to_datetime(t["obs_date"]) > pd.Timestamp(as_of)
    t.loc[after, "iem_bgalage_cell_co"] = rng.uniform(-1e6, 1e6, after.sum())
    t.loc[after, "iem_wtrtp"] = rng.uniform(-50, 50, after.sum())
    return t.drop(index=t.index[after][::2]).reset_index(drop=True)


def _same(a: dict[str, float], b: dict[str, float]) -> bool:
    return a.keys() == b.keys() and all((math.isnan(a[k]) and math.isnan(b[k])) or a[k] == b[k] for k in a)


@pytest.mark.parametrize("as_of", AS_OFS)
@pytest.mark.parametrize("sid", ["GJGR", "CS", "MGMR", "HP", "DCHN"])
def test_make_upstream_no_leakage(as_of: date, sid: str) -> None:
    raw = _algae()
    base = U.make_upstream_features(U.prepare_algae(raw), as_of, sid, 2.5)
    for seed in (1, 2, 3):
        tampered = U.make_upstream_features(U.prepare_algae(_tamper(raw, as_of, seed)), as_of, sid, 2.5)
        assert _same(base, tampered), (sid, as_of, seed)
    assert list(base) == U.UPSTREAM_COLS


def test_build_upstream_rowwise_no_leakage() -> None:
    raw = _algae()
    df = pd.DataFrame(
        {
            "station_id": ["GJGR", "CS", "MGMR", "HP", "DCHN", "CS"],
            "base_date": ["2024-05-06", "2024-07-15", "2024-09-02", "2024-07-15", "2024-07-15", "2024-03-20"],
            "cell_log_t0": [1.0, 2.0, np.nan, 3.0, 1.5, 0.5],
        }
    )
    full = U.build_upstream(df, raw)
    assert list(full.columns) == U.UPSTREAM_COLS and full.index.equals(df.index)
    for i in range(len(df)):
        bd = pd.Timestamp(df["base_date"].iloc[i]).date()
        for seed in (4, 5):
            t = U.build_upstream(df.iloc[[i]], _tamper(raw, bd, seed))
            assert np.array_equal(t.to_numpy(), full.iloc[[i]].to_numpy(), equal_nan=True), (i, seed)


def test_definitions() -> None:
    raw = _algae()
    a = U.prepare_algae(raw)
    as_of = date(2024, 7, 15)  # 월요일 — 측정일(7일 간격 월요일)과 같은 날: lag 0 이면 당일 측정 사용
    f = U.make_upstream_features(a, as_of, "CS", 1.25)
    gj = a[(a["station_id"] == "GJGR") & (a["obs_date"] <= pd.Timestamp(as_of)) & a["cells"].notna()]
    assert f["up1_cell_log"] == pytest.approx(np.log10(gj["cells"].iloc[-1] + 1))
    assert f["up1_days"] == float((pd.Timestamp(as_of) - gj["obs_date"].iloc[-1]).days)
    assert f["up1_diff"] == pytest.approx(f["up1_cell_log"] - 1.25)
    assert math.isnan(U.make_upstream_features(a, as_of, "CS", math.nan)["up1_diff"])
    for sid in ("HP", "DCHN"):  # 상류 없음 → 모두 NaN
        assert all(math.isnan(v) for v in U.make_upstream_features(a, as_of, sid, 1.0).values())
    # 원자료 열 형식(cells·wtemp)도 받는다
    assert _same(f, U.make_upstream_features(U.prepare_algae(a), as_of, "CS", 1.25))


# ---------------------------------------------------------------- 실험 코드(R2)와 동등성(데이터 필요)
def _need_data() -> None:
    from algaecast.models import data as D

    if not (D.PROCESSED / "features_S1.parquet").exists() or not U.ALGAE_PARQUET.exists():
        pytest.skip("features_S1·조류 원자료 없음")


def test_equals_r2_build_features_sample() -> None:
    _need_data()
    from algaecast.exp import harness as H
    from algaecast.exp import r2_upstream as R2

    df = H.load_base()
    idx = np.random.default_rng(42).choice(len(df), 400, replace=False)
    sub = df.iloc[np.sort(idx)]
    a = R2.build_features(sub)[U.UPSTREAM_COLS]
    b = U.build_upstream(sub)
    assert list(R2.build_features(sub.iloc[:3]).columns) == U.UPSTREAM_COLS
    assert np.array_equal(a.to_numpy(dtype=float), b.to_numpy(dtype=float), equal_nan=True)


def test_equals_confirm_2026_test_rows() -> None:
    _need_data()
    from algaecast.exp import r2_upstream as R2
    from algaecast.models import data as D

    te = D.load_test_features("S1").reset_index(drop=True)
    assert "target_cells" not in te.columns and "target_log" not in te.columns
    algae_all = R2.load_algae(last=pd.Timestamp("2026-12-31"))
    a = R2.build_variant_features(te, str(R2.CHOSEN["lag_mode"]), algae=algae_all)[U.UPSTREAM_COLS]
    b = U.build_upstream(te)
    assert len(b) == 124
    assert np.array_equal(a.to_numpy(dtype=float), b.to_numpy(dtype=float), equal_nan=True)
