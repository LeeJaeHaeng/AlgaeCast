"""EXP-009(R6) 수질자동측정망 7일 추세 피처 — 파서·통합 규칙·as_of 누수 테스트.

누수 테스트는 tests/test_no_leakage.py 와 같은 방식: as_of 이후 행의 값을 난수로 바꾸고 일부를 지우고 새 행을 더해도
피처가 같아야 한다.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from algaecast.collect.base import KST, CollectError, FetchResult
from algaecast.collect.nier_autowq import (
    NierAutoWQCollector,
    items_to_frame,
    parse_items,
)
from algaecast.exp import r6_autowq as R

VARS = R.DAILY_VARS


def _daily(days: int = 150, seed: int = 42, start: str = "2024-06-01", station: str = "GJGR") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    d = pd.DataFrame({"obs_date": pd.date_range(start, periods=days, freq="D")})
    for v in ("wtemp", "ph", "do", "ec", "toc", "chla", "turb", "tn", "tp"):
        d[v] = rng.uniform(1, 30, size=days)
    # 결측도 섞는다
    d.loc[rng.random(days) < 0.15, "chla"] = np.nan
    d = R.add_derived(d)
    d["station_id"] = station
    return d


def _tamper(d: pd.DataFrame, as_of: date, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = d.copy()
    after = pd.to_datetime(t["obs_date"]) > pd.Timestamp(as_of)
    for v in VARS:
        t.loc[after, v] = rng.uniform(-1e4, 1e4, size=int(after.sum()))
    t = t.drop(t.index[after.to_numpy() & (rng.random(len(t)) < 0.5)])
    extra = t.tail(3).copy()
    extra["obs_date"] = pd.Timestamp(as_of) + pd.Timedelta(days=1)
    return pd.concat([t, extra], ignore_index=True)


def _eq(a: dict, b: dict) -> None:
    assert a.keys() == b.keys()
    for k in a:
        assert (np.isnan(a[k]) and np.isnan(b[k])) or a[k] == pytest.approx(b[k], abs=1e-12), k


@pytest.mark.parametrize("lag", [0, 1])
@pytest.mark.parametrize("as_of", [date(2024, 7, 15), date(2024, 8, 3), date(2024, 9, 30)])
def test_autowq_features_no_leakage(lag: int, as_of: date) -> None:
    d = _daily()
    base = R.autowq_features(d, as_of, lag=lag, variables=VARS)
    for seed in range(3):
        _eq(base, R.autowq_features(_tamper(d, as_of, seed), as_of, lag=lag, variables=VARS))


def test_lag1_excludes_base_date_value() -> None:
    d = _daily()
    as_of = date(2024, 8, 10)
    t = d.copy()
    t.loc[pd.to_datetime(t["obs_date"]) == pd.Timestamp(as_of), "chla"] = 9999.0
    _eq(
        R.autowq_features(d, as_of, lag=1, variables=("chla",)),
        R.autowq_features(t, as_of, lag=1, variables=("chla",)),
    )
    assert R.autowq_features(t, as_of, lag=0, variables=("chla",))["aw_chla_mean7"] != pytest.approx(
        R.autowq_features(d, as_of, lag=0, variables=("chla",))["aw_chla_mean7"]
    )


def test_window_stats_known_series() -> None:
    days = pd.date_range("2024-07-01", periods=20, freq="D")
    d = pd.DataFrame({"obs_date": days, "chla": 2.0 * np.arange(20, dtype=float)})
    d.loc[d["obs_date"] == pd.Timestamp("2024-07-12"), "chla"] = np.nan  # 창 안 1일 결측
    as_of = date(2024, 7, 14)  # 창 7/8~7/14 (lag 0)
    f = R.autowq_features(d, as_of, lag=0, variables=("chla",))
    vals = 2.0 * np.array([7, 8, 9, 10, 12, 13])
    assert f["aw_chla_mean7"] == pytest.approx(vals.mean())
    assert f["aw_chla_slope7"] == pytest.approx(2.0)
    assert f["aw_chla_miss7"] == pytest.approx(1 / 7)
    g = R.autowq_features(d, date(2024, 8, 30), lag=0, variables=("chla",))  # 자료 없는 창
    assert np.isnan(g["aw_chla_mean7"]) and np.isnan(g["aw_chla_slope7"]) and g["aw_chla_miss7"] == 1.0


def test_build_variant_features_row_no_leakage() -> None:
    daily = pd.concat([_daily(station="GJGR"), _daily(seed=7, station="HP")], ignore_index=True)
    df = pd.DataFrame(
        {
            "station_id": ["GJGR", "HP", "GJGR", "HP"],
            "base_date": [date(2024, 7, 20), date(2024, 7, 25), date(2024, 8, 30), date(2024, 9, 15)],
        }
    )
    full = R.build_variant_features(df, 0, "primary", VARS, daily=daily)
    assert list(full.index) == list(df.index)
    for i, r in df.iterrows():
        t = pd.concat(
            [_tamper(daily[daily["station_id"] == s], r["base_date"], 3) for s in ("GJGR", "HP")],
            ignore_index=True,
        )
        one = R.build_variant_features(df.loc[[i]], 0, "primary", VARS, daily=t)
        pd.testing.assert_series_equal(full.loc[i], one.loc[i], check_names=False)


def test_build_features_chosen_no_leakage(monkeypatch: pytest.MonkeyPatch) -> None:
    """공개 함수 build_features(선택 설정)도 기준일 이후 원자료를 바꿔도 같은 값을 낸다."""
    daily = pd.concat([_daily(seed=i, station=s) for i, s in enumerate(R.SITES)], ignore_index=True)
    df = pd.DataFrame(
        {
            "station_id": list(R.SITES),
            "base_date": [
                date(2024, 7, 20),
                date(2024, 8, 1),
                date(2024, 8, 15),
                date(2024, 9, 2),
                date(2024, 10, 5),
            ],
        }
    )
    monkeypatch.setattr(R, "load_daily", lambda source="primary", raw=None: daily)
    base = R.build_features(df)
    assert list(base.columns) == list(R.BUNDLES[str(R.CHOSEN["bundle"])])
    assert base.notna().any().all()
    for i, r in df.iterrows():
        t = pd.concat(
            [_tamper(daily[daily["station_id"] == s], r["base_date"], 5) for s in R.SITES], ignore_index=True
        )
        monkeypatch.setattr(R, "load_daily", lambda source="primary", raw=None, t=t: t)
        one = R.build_features(df.loc[[i]])
        pd.testing.assert_series_equal(base.loc[i], one.loc[i], check_names=False)


def test_build_variant_features_rejects_2026() -> None:
    df = pd.DataFrame({"station_id": ["HP"], "base_date": [date(2026, 7, 1)]})
    with pytest.raises(RuntimeError):
        R.build_variant_features(df, 0, "primary", VARS, daily=_daily(station="HP"))


def _raw(site: str, start: str, days: int, val: float) -> pd.DataFrame:
    d = pd.DataFrame({"site_id": site, "obs_date": pd.date_range(start, periods=days, freq="D")})
    for v in R.UNIFIED:
        d[v] = val
    return d


def test_load_daily_cuts_2026_and_fills_from_secondary() -> None:
    raws = []
    for sid in R.SITES:
        p = _raw(R.PRIMARY[sid], "2025-12-20", 30, 1.0)  # 2026-01-18 까지
        p.loc[p.index[:5], "tn"] = np.nan
        raws.append(p)
        raws.append(_raw(R.SECONDARY[sid], "2025-12-15", 40, 2.0))
    raw = pd.concat(raws, ignore_index=True)
    prim = R.load_daily("primary", raw)
    fill = R.load_daily("fill", raw)
    assert prim["obs_date"].max() <= pd.Timestamp("2025-12-31")
    assert fill["obs_date"].max() <= pd.Timestamp("2025-12-31")
    hp_p, hp_f = prim[prim["station_id"] == "HP"], fill[fill["station_id"] == "HP"]
    assert hp_p["tn"].isna().sum() == 5
    assert hp_f["tn"].isna().sum() == 0  # 주 결측 5일 + 차순위만 있는 5일(12/15~19)을 차순위 값으로
    assert (hp_f.set_index("obs_date").loc["2025-12-20", "wtemp"]) == 1.0  # 주 값 우선


def test_bundles_map_to_known_variables() -> None:
    for name, cols in R.BUNDLES.items():
        vs = R.variables_of(cols)
        assert set(vs) <= set(R.DAILY_VARS), name
        assert set(cols) <= set(R.columns_for(vs)), name
    assert R.variables_of(["aw_do_pct_mean7", "aw_do_slope7"]) == ["do_pct", "do"]
    assert R.CHOSEN["bundle"] in R.BUNDLES and R.CHOSEN["source"] in R.SOURCES


def test_do_saturation_reference() -> None:
    assert R.do_saturation(np.array([20.0]))[0] == pytest.approx(9.09, abs=0.02)
    assert R.do_saturation(np.array([0.0]))[0] == pytest.approx(14.62, abs=0.02)  # APHA 표 14.621


# ---------------------------------------------------------------- 수집기
def _resp(items: list[dict], total: int, code: str = "00") -> str:
    return json.dumps(
        {
            "getRealTimeWaterQualityList": {
                "header": {"code": code, "message": "x"},
                "item": items,
                "totalCount": total,
            }
        }
    )


def _item(day: str, **m: float) -> dict:
    return {"SITE_ID": "S02012", "SITE_NAME": "해평", "MSR_DATE": day, **m}


def test_parse_items_and_errors() -> None:
    items, total = parse_items(_resp([_item("2025-08-01", M69=30.0)], 1))
    assert total == 1 and items[0]["M69"] == 30.0
    with pytest.raises(CollectError):
        parse_items(_resp([], 0, code="99"))
    with pytest.raises(CollectError):
        parse_items("<html>not json</html>")


def test_items_to_frame_unify_priority_loq_range() -> None:
    f = items_to_frame(
        [
            _item("2025-08-01", M69=30.0, M02=10.0, M70=8.0, M29=-999.0, M72=0.0, M06=3.0, M81=9.0),
            _item("2025-08-02", M38=29.0, M39=0.5, M80=4.0, M79=7.0, M27=2.0, M28=0.02),
        ]
    )
    assert f.loc[0, "wtemp"] == 30.0  # 센서 묶음 3 우선
    assert f.loc[1, "wtemp"] == 29.0  # 묶음 2
    assert f.loc[0, "chla"] == 0.0 and bool(f.loc[0, "chla_loq"])  # 정량한계 미만 → 0
    assert np.isnan(f.loc[0, "do"])  # 범위 밖(0 mg/L)
    assert np.isnan(f.loc[1, "ph"])  # 범위 밖(pH 0.5)
    assert f.loc[0, "toc"] == 3.0  # M06 우선
    assert f.loc[1, "turb"] == 4.0  # 탁도2(M80) > 탁도1(M79)
    assert f.loc[1, "tn"] == 2.0 and f.loc[1, "tp"] == 0.02
    assert f["obs_date"].map(type).eq(date).all()


def test_fetch_year_paginates_and_formats_dates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NIER_WQDB_KEY", "dummy-key-for-test")
    col = NierAutoWQCollector(cache_dir=tmp_path / "cache", out_dir=tmp_path / "out", use_cache=False)
    seen: list[dict] = []
    pages = {
        1: _resp([_item(f"2024-01-{d:02d}", M69=5.0) for d in range(1, 4)], 5),
        2: _resp([_item(f"2024-01-{d:02d}", M69=5.0) for d in range(4, 6)], 5),
    }

    def fake_get(url: str, params: dict, *, ttl: object = None) -> FetchResult:
        seen.append(dict(params))
        return FetchResult(pages[params["pageNo"]], False, datetime.now(KST), url)

    monkeypatch.setattr(col, "get", fake_get)
    items = col.fetch_year("S02012", 2024)
    assert len(items) == 5 and [p["pageNo"] for p in seen] == [1, 2]
    assert seen[0]["startDate"] == "20231231000000" and seen[0]["endDate"] == "20241231000000"
    assert seen[0]["siteId"] == "S02012" and seen[0]["resultType"] == "JSON"


def test_is_cacheable() -> None:
    col = NierAutoWQCollector(use_cache=False)
    assert col.is_cacheable(_resp([], 0))
    assert not col.is_cacheable(_resp([], 0, code="99"))
    assert col.is_cacheable(json.dumps({"list": []}))
    assert col.is_cacheable(json.dumps({"features": []}))
    assert not col.is_cacheable("<OpenAPI_ServiceResponse/>")
