"""EXP-005(2차) P6 상류 댐 호소 × 방류 피처의 as_of 누수 테스트와 정의 점검(모델 학습 없음).

tests/test_no_leakage.py 와 같은 방식: as_of 이후 행을 난수로 바꾸고 절반을 지워도 결과가 같아야 한다.
travel lag 은 (as_of − lag, as_of] 구간의 호소 측정·댐 방류도 쓰지 않아야 한다.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from algaecast.exp import harness as H
from algaecast.exp import r2nd_p6_damres as P

AS_OFS = [date(2024, 7, 15), date(2024, 9, 2)]
STATIONS = ["HP", "GJGR", "CS", "MGMR", "DCHN"]


def _algae(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for s in P.link_sites():
        for d in pd.date_range("2024-03-04", "2024-11-25", freq="7D"):
            rows.append({"site_code": s, "obs_date": d, "cells": float(10 ** rng.uniform(0, 5))})
    a = pd.DataFrame(rows)
    a.loc[a.index[::9], "cells"] = np.nan  # 결측 측정 포함
    return a


def _release(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", "2024-12-31", freq="D")
    parts = [
        pd.DataFrame({"dam_code": c, "obs_date": idx, "q_river": rng.uniform(0.5, 300, len(idx))})
        for c in P.link_dams()
    ]
    r = pd.concat(parts, ignore_index=True)
    r.loc[r.index[::13], "q_river"] = np.nan
    return r


def _down(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", "2024-12-31", freq="D")
    return pd.DataFrame({"obs_date": idx, "q_down": rng.uniform(20, 900, len(idx))})


def _tamper(d: pd.DataFrame, cut: pd.Timestamp, col: str, seed: int) -> pd.DataFrame:
    """obs_date > cut 인 행의 col 을 난수로 바꾸고 그 절반을 지운다."""
    rng = np.random.default_rng(seed)
    t = d.copy()
    after = pd.to_datetime(t["obs_date"]) > cut
    t.loc[after, col] = rng.uniform(-1e6, 1e6, int(after.sum()))
    return t.drop(index=t.index[after][::2]).reset_index(drop=True)


def _same(a: dict[str, float], b: dict[str, float]) -> bool:
    if a.keys() != b.keys():
        return False
    return all(
        (math.isnan(a[k]) and math.isnan(b[k])) or (not math.isnan(a[k]) and abs(a[k] - b[k]) < 1e-12)
        for k in a
    )


@pytest.mark.parametrize("lag_mode", P.LAG_MODES)
@pytest.mark.parametrize("as_of", AS_OFS)
@pytest.mark.parametrize("station", STATIONS)
def test_future_rows_do_not_change_features(lag_mode: str, as_of: date, station: str) -> None:
    a, r, d = _algae(), _release(), _down()
    base = P.make_dam_features(a, r, d, as_of, station, lag_mode, 7.0)
    cut = pd.Timestamp(as_of)
    a2, r2, d2 = _tamper(a, cut, "cells", 1), _tamper(r, cut, "q_river", 2), _tamper(d, cut, "q_down", 3)
    assert _same(base, P.make_dam_features(a2, r2, d2, as_of, station, lag_mode, 7.0))
    # as_of 이후 행을 모두 지워도 같다
    a3 = a[pd.to_datetime(a["obs_date"]) <= cut]
    r3 = r[pd.to_datetime(r["obs_date"]) <= cut]
    d3 = d[pd.to_datetime(d["obs_date"]) <= cut]
    assert _same(base, P.make_dam_features(a3, r3, d3, as_of, station, lag_mode, 7.0))


@pytest.mark.parametrize("as_of", AS_OFS)
def test_travel_lag_ignores_window_before_as_of(as_of: date) -> None:
    """travel lag 이 있는 연결(영천→칠서·물금매리, 남강→물금매리)은 (as_of − lag, as_of] 의 값도 쓰지 않는다."""
    a, r = _algae(), _release()
    base = P.make_dam_features(a, r, None, as_of, "MGMR", "travel", 7.0)
    lags = [P.lag_days(lk, "travel", 7.0) for lk in P.LINKS["MGMR"]]
    assert min(lags) == 0 and max(lags) > 0
    # lag 이 양수인 연결만 남긴 경우: (as_of − min_lag_pos, as_of] 를 바꿔도 같아야 한다
    lag_pos = min(x for x in lags if x > 0)
    cut = pd.Timestamp(as_of) - pd.Timedelta(days=lag_pos)
    pos_sites = [s for lk in P.LINKS["MGMR"] if P.lag_days(lk, "travel", 7.0) > 0 for s in lk.sites]
    pos_dams = [lk.dam_code for lk in P.LINKS["MGMR"] if P.lag_days(lk, "travel", 7.0) > 0]
    a2 = a.copy()
    m = a2["site_code"].isin(pos_sites) & (pd.to_datetime(a2["obs_date"]) > cut)
    a2.loc[m, "cells"] = 1e9
    r2 = r.copy()
    m2 = r2["dam_code"].isin(pos_dams) & (pd.to_datetime(r2["obs_date"]) > cut)
    r2.loc[m2, "q_river"] = 1e6
    got = P.make_dam_features(a2, r2, None, as_of, "MGMR", "travel", 7.0)
    assert _same(base, got)
    # 대조: lag 0 에서는 같은 변경이 결과를 바꾼다(테스트가 실제로 민감한지 확인)
    assert not _same(
        P.make_dam_features(a, r, None, as_of, "MGMR", "0", 7.0),
        P.make_dam_features(a2, r2, None, as_of, "MGMR", "0", 7.0),
    )


def test_no_link_sites_are_nan() -> None:
    a, r, d = _algae(), _release(), _down()
    for s in ("HP", "GJGR"):
        out = P.make_dam_features(a, r, d, AS_OFS[0], s, "0", 7.0)
        assert set(out) == set(P.COLS) and all(math.isnan(v) for v in out.values())


def test_definitions_match_hand_calculation() -> None:
    """운문호 단일 연결(certain 만 남긴 물금·매리에서 영천·남강 자료를 지운 경우)로 정의를 손 계산과 대조."""
    as_of = date(2024, 7, 15)
    a = pd.DataFrame(
        {
            "site_code": ["2021G10", "2021G20", "2021G20"],
            "obs_date": pd.to_datetime(["2024-07-08", "2024-07-08", "2024-07-22"]),
            "cells": [100.0, 999.0, 5e6],
        }
    )
    idx = pd.date_range("2024-07-01", "2024-07-31", freq="D")
    r = pd.DataFrame({"dam_code": "2021210", "obs_date": idx, "q_river": np.arange(len(idx), dtype=float)})
    d = pd.DataFrame({"obs_date": idx, "q_down": 50.0})
    out = P.make_dam_features(a, r, d, as_of, "MGMR", "0", 7.0)
    q = float(np.mean(np.arange(8, 15)))  # 7/09~7/15 평균
    assert out["dam_days"] == 7.0
    assert abs(out["dam_cell_log"] - math.log10(999.0 + 1)) < 1e-12
    assert abs(out["dam_q_log"] - math.log10(q + 1)) < 1e-12
    assert abs(out["dam_load_log"] - math.log10(999.0 * q + 1)) < 1e-12
    assert abs(out["dam_contrib_log"] - math.log10(999.0 * q / 50.0 + 1)) < 1e-12


def test_stale_measurement_is_missing() -> None:
    as_of = date(2024, 7, 15)
    a = pd.DataFrame({"site_code": ["2021G10"], "obs_date": pd.to_datetime(["2024-05-01"]), "cells": [10.0]})
    idx = pd.date_range("2024-07-01", "2024-07-31", freq="D")
    r = pd.DataFrame({"dam_code": "2021210", "obs_date": idx, "q_river": 3.0})
    out = P.make_dam_features(a, r, None, as_of, "MGMR", "0", 7.0)
    assert all(math.isnan(v) for v in out.values())


def test_certain_link_set_drops_uncertain_link() -> None:
    a, r, d = _algae(), _release(), _down()
    allv = P.make_dam_features(a, r, d, AS_OFS[0], "CS", "0", 7.0, "all")
    cert = P.make_dam_features(a, r, d, AS_OFS[0], "CS", "0", 7.0, "certain")
    assert not _same(allv, cert)
    only = [lk for lk in P.LINKS["CS"] if lk.certain]
    assert len(only) == 1 and only[0].dam_code == "2012210"


def test_build_variant_features_matches_row_function() -> None:
    a, r = _algae(), _release()
    down = {s: _down(i) for i, s in enumerate(("CS", "MGMR", "DCHN"))}
    df = pd.DataFrame(
        {
            "station_id": ["HP", "CS", "MGMR", "DCHN", "CS"],
            "base_date": pd.to_datetime(
                ["2024-07-15", "2024-07-15", "2024-08-05", "2024-09-02", "2024-10-07"]
            ),
            "horizon_days": [7.0, 7.0, 4.0, 7.0, 10.0],
        },
        index=[10, 11, 12, 13, 14],
    )
    got = P.build_variant_features(df, "travel", "all", algae=a, release=r, down=down)
    assert list(got.index) == list(df.index) and list(got.columns) == list(P.COLS)
    for i, row in df.iterrows():
        exp = P.make_dam_features(
            a,
            r,
            down.get(row["station_id"]),
            row["base_date"].date(),
            row["station_id"],
            "travel",
            row["horizon_days"],
        )
        assert _same(exp, {c: float(got.loc[i, c]) for c in P.COLS})


def test_links_refer_to_known_sites_and_dams() -> None:
    sites = pd.read_csv(P.RAW_DIR / "nier_algae_all" / "sites_all.csv", dtype={"site_code": str})
    known = set(sites["site_code"])
    for ls in P.LINKS.values():
        for lk in ls:
            assert set(lk.sites) <= known
            assert lk.travel_days > 0 and lk.km > 0
    assert P.LINKS["HP"] == () and P.LINKS["GJGR"] == ()
    assert {lk.dam_code for lk in P.LINKS["DCHN"]} == {"3001110"}
    assert set(P.VARIANTS) and P.CHOSEN["variant"] in P.VARIANTS


def test_loaders_drop_rows_after_2025() -> None:
    a = P.load_reservoir_algae()
    r = P.load_dam_release()
    assert a["obs_date"].max() <= H.LAST_DATE and r["obs_date"].max() <= H.LAST_DATE
    assert set(a["site_code"]) == set(P.link_sites())
    assert set(r["dam_code"]) == set(P.link_dams())
    assert (r["q_river"].dropna() >= 0).all()
    for d in P.load_down_flow().values():
        assert d["obs_date"].max() <= H.LAST_DATE
