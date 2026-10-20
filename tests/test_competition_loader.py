"""T0-b: 대회 데이터 로더 검증. 번들이 없는 환경(CI)에서는 건너뛴다."""

from datetime import date

import pandas as pd
import pytest

from algaecast.collect import competition as comp

pytestmark = pytest.mark.skipif(not comp.available(), reason="대회 데이터 번들 없음 (git 미포함)")


@pytest.fixture(scope="module")
def data():
    return comp.load()


def test_all_tables_have_convention_columns(data):
    for name, df in data.items():
        if name == "sample_submission":
            continue
        assert "source" in df.columns and "fetched_at" in df.columns, name
        if name not in ("eval_pairs", "stations"):  # 정적 메타·조합 표는 obs_date 없음
            assert "obs_date" in df.columns, name


def test_stations(data):
    st = data["stations"]
    assert len(st) == 5
    assert set(st["site_code"]) == {"2011G26", "2011G56", "2020G33", "2022G05", "3008G30"}
    assert set(st["station_id"]) == {"HP", "GJGR", "CS", "MGMR", "DCHN"}
    asos = st.set_index("station_id")["asos_stn_id"].to_dict()
    assert asos == {"HP": 279, "GJGR": 143, "CS": 263, "MGMR": 159, "DCHN": 133}
    assert st.set_index("station_id")["asos_alt_stn_id"]["CS"] == 155


def test_algae_target_and_keys(data):
    al = data["algae"]
    assert len(al) == 2939
    assert not al.duplicated(["site_code", "obs_date"]).any()
    assert al[comp.TARGET].dtype == "float64"
    assert al[comp.TARGET].notna().sum() > 2700
    assert al["obs_date"].min() == date(2012, 4, 2)
    assert al["obs_date"].max() == date(2026, 9, 10)
    # 강정·고령 2026-08-18 = 483,021 cells/mL (문제 설명서·주간보고서 수치)
    sel = (al["station_id"] == "GJGR") & (al["obs_date"] == date(2026, 8, 18))
    assert al.loc[sel, comp.TARGET].item() == 483021


def test_date_columns_are_pure_dates(data):
    """datetime 은 date 의 하위형이라 isinstance 로는 못 잡는다 — 정확히 date 여야 한다 (02 문서 9절)."""
    for name, df in data.items():
        for col in ("obs_date", "base_date", "target_date"):
            if col in df.columns:
                assert df[col].map(type).eq(date).all(), f"{name}.{col}"


def test_non_numeric_tokens_are_flagged(data):
    al = data["algae"]
    assert al["iem_chla_pending"].sum() == 3  # '분석중' (2026-09-10 CS·DCHN·MGMR)
    assert al.loc[al["iem_chla_pending"], "iem_chla"].isna().all()
    with pytest.raises(ValueError):
        comp._num(pd.Series(["1.0", "???"], name="x"))


def test_dam_operation_api(data):
    api = data["dam_operation_api"]
    assert len(api) == 1128
    assert api["dam_name"].nunique() == 12 and "보현산" in set(api["dam_name"])
    assert not api.duplicated(["dam_name", "obs_date"]).any()
    assert api["obs_date"].min() == date(2026, 6, 10) and api["obs_date"].max() == date(2026, 9, 11)
    assert api["rsvwtrt"].between(0, 100).all()


def test_algae_numeric_and_loq(data):
    al = data["algae"]
    assert al["iem_mib2_below_loq"].any()
    assert al.loc[al["iem_mib2_below_loq"], "iem_mib2"].isna().all()


def test_dam_daily(data):
    dam = data["dam_daily"]
    assert len(dam) == 79964
    assert dam["dam_code"].nunique() == 15
    assert not dam.duplicated(["dam_code", "obs_date"]).any()
    assert dam["iqty"].dtype == "float64"
    sel = (dam["dam_code"] == "2001110") & (dam["obs_date"] == date(2012, 1, 3))
    assert dam.loc[sel, "iqty"].item() == pytest.approx(0.76)  # 원본 '.76'


def test_asos(data):
    asos = data["asos"]
    assert len(asos) == 32208
    assert set(asos["stn_id"]) == {133, 143, 155, 159, 263, 279}
    assert not asos.duplicated(["stn_id", "obs_date"]).any()
    filled = asos["rn_blank"] & asos["day_observed"]
    assert asos.loc[filled, "sum_rn"].eq(0).all()
    assert asos.loc[asos["rn_blank"] & ~asos["day_observed"], "sum_rn"].isna().all()  # 관측소 결측일 보호
    assert (asos["rn_blank"] & ~asos["day_observed"]).sum() == 20  # 기온·습도 모두 없는 날(의령군 18, 구미 2)
    raw_nan = comp.load_asos(rain_blank_as_zero=False)
    assert raw_nan.loc[raw_nan["rn_blank"], "sum_rn"].isna().all()


def test_eval_pairs_and_submission(data):
    ev, sub = data["eval_pairs"], data["sample_submission"]
    assert len(ev) == 2754
    assert ev["split"].value_counts().to_dict() == {"train": 2310, "valid": 256, "test": 124, "excluded": 64}
    assert ev["lag_days"].between(4, 10).all()
    delta = (pd.to_datetime(ev["target_date"]) - pd.to_datetime(ev["base_date"])).dt.days
    assert (delta == ev["lag_days"]).all()
    assert len(sub) == 124
    assert list(sub.columns) == ["station_id", "base_date", "target_date", "pred_cells"]
    test_rows = ev.loc[ev["split"] == "test", ["station_id", "base_date", "target_date"]]
    assert set(map(tuple, sub[["station_id", "base_date", "target_date"]].values)) == set(
        map(tuple, test_rows.values)
    )
    # 기준일·정답일 모두 실측이 존재하는 날짜여야 한다 (README 매칭 규칙)
    obs = set(map(tuple, data["algae"][["station_id", "obs_date"]].values))
    assert all((s, d) in obs for s, d in zip(ev["station_id"], ev["base_date"], strict=True))
    assert all((s, d) in obs for s, d in zip(ev["station_id"], ev["target_date"], strict=True))
