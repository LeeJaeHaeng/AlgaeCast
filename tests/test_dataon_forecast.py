"""T1-d/e/g: DataON 수위 파서·기상 예보 수집기·run 요약 (네트워크 없음)."""

from datetime import date, datetime

import pandas as pd
import pytest

from algaecast.collect import dataon_level as dl
from algaecast.collect import kma_forecast as kf
from algaecast.collect import run as runmod
from algaecast.collect.base import KST, CollectError


def test_norm_name_and_dates():
    assert dl.norm_name("*경주시(감포댐)") == "경주시(감포댐)"
    assert dl.norm_name("1. 태백시(무사교) 수위관측소") == "태백시(무사교)"
    assert dl.norm_name("부산시(낙동강하구언(내)) 수위 관측소") == "부산시(낙동강하구언(내))"
    assert dl._parse_date(20100101) == date(2010, 1, 1)
    assert dl._parse_date("2024년01월31일") == date(2024, 1, 31)
    assert dl._parse_date("확장불확도 : 0.04 m") is None and dl._parse_date("20231332") is None


def _write_matrix(path):
    info = pd.DataFrame(
        [
            ["기본정보", None, None],
            ["일련번호", "댐명", "관측소명"],
            ["001", "대청댐", "청주시(대청댐)"],
            ["002", "감포댐", "경주시(감포댐)"],
        ]
    )
    sheet = pd.DataFrame(index=range(12), columns=range(5))
    sheet.iloc[0, 0] = "1. 청주시(대청댐) 수위관측소"
    sheet.iloc[1, 0] = "(Cheongju Stage Station, 3008690)"
    sheet.iloc[5, 0] = "Month    일    월\nDate"
    sheet.iloc[5, 1], sheet.iloc[5, 3] = "1월", "2월"
    sheet.iloc[7, 0], sheet.iloc[7, 1], sheet.iloc[7, 3] = 1, 70.1, 70.3
    sheet.iloc[8, 0], sheet.iloc[8, 1] = 2, 70.2
    sheet.iloc[9, 0] = "최저"
    sheet2 = sheet.copy()
    sheet2.iloc[0, 0] = "2. 경주시(감포댐) 수위관측소"
    sheet2.iloc[1, 0] = "(Gampo, 1301601)"
    with pd.ExcelWriter(path) as xw:
        info.to_excel(xw, sheet_name="관측소 정보", header=False, index=False)
        sheet.to_excel(xw, sheet_name="1", header=False, index=False)
        sheet2.to_excel(xw, sheet_name="2", header=False, index=False)


def _write_wide(path, dates, names):
    rows = [["확장불확도 : 0.04 m"] + [None] * len(names), ["일자"] + names]
    for i, d in enumerate(dates):
        rows.append([d] + [70.0 + i + k for k in range(len(names))])
    if len(dates) > 1:
        rows[-1][1] = None  # 결측 1개
    pd.DataFrame(rows).to_excel(path, header=False, index=False)


def test_dataon_parsers_and_load_all(tmp_path):
    _write_matrix(tmp_path / "댐유역 하천 일평균수위(2020).xlsx")
    _write_wide(
        tmp_path / "댐유역 하천 일평균수위(2021).xlsx",
        [20210101, 20210102],
        ["*청주시(대청댐)", "경주시(감포댐)"],
    )
    _write_wide(
        tmp_path / "댐유역 하천 일평균수위(2024).xlsx",
        ["2024년01월01일"],
        ["청주시(대청댐)", "포항시(없는곳)"],
    )
    long = dl.load_all(tmp_path)
    assert list(long.columns) == dl.LONG_COLS
    m = long[long["station_code"] == "3008690"].set_index("obs_date")["wl"]
    assert m[date(2020, 1, 1)] == 70.1 and m[date(2020, 2, 1)] == 70.3 and m[date(2020, 1, 2)] == 70.2
    assert m[date(2021, 1, 1)] == 70.0 and date(2021, 1, 2) not in m.index  # 결측 제외
    assert m[date(2024, 1, 1)] == 70.0
    assert set(long["station_code"]) == {"3008690", "1301601"}  # 코드 없는 '포항시(없는곳)' 제외
    assert long.loc[long["station_code"] == "3008690", "dam_name"].iloc[0] == "대청댐"
    cov = dl.coverage_table(
        long, {"sites": [{"station_id": "DCHN", "dataon_stations": ["3008690", "9999999"]}]}
    )
    assert cov.loc[0, "행"] == 5 and cov.loc[1, "name"] == "(파일에 없음)"
    assert dl.load_all(tmp_path / "none") is None
    (tmp_path / "only").mkdir()
    _write_wide(tmp_path / "only" / "댐유역 하천 일평균수위(2022).xlsx", [20220101], ["a(b)"])
    with pytest.raises(CollectError):
        dl.load_all(tmp_path / "only")


def test_latlon_to_grid_known_points():
    assert kf.latlon_to_grid(37.5665, 126.978) == (60, 127)  # 서울시청 (기상청 예시)
    assert kf.latlon_to_grid(36.1195, 128.3446) == (84, 96)  # 구미시청
    assert kf.latlon_to_grid(35.1796, 129.0756) == (98, 76)  # 부산시청


def test_parse_pcp():
    assert kf.parse_pcp("강수없음") == 0.0 and kf.parse_pcp("1mm 미만") == 0.5
    assert (
        kf.parse_pcp("1.0mm") == 1.0
        and kf.parse_pcp("30.0~50.0mm") == 40.0
        and kf.parse_pcp("50.0mm 이상") == 50.0
    )
    assert kf.parse_pcp("") is None and kf.parse_pcp("-") is None


def _site():
    return {"site_code": "2011G26", "station_id": "HP", "lat": 36.1695, "lon": 128.3873}


def test_vilage_tidy_daily_aggregation():
    items = []
    for h, tmp, pop, pcp in ((600, 10, 20, "강수없음"), (900, 14, 60, "1.0mm"), (1200, 18, 30, "5.0mm")):
        items += [
            {"category": "TMP", "fcstDate": "20261021", "fcstTime": f"{h:04d}", "fcstValue": str(tmp)},
            {"category": "POP", "fcstDate": "20261021", "fcstTime": f"{h:04d}", "fcstValue": str(pop)},
            {"category": "PCP", "fcstDate": "20261021", "fcstTime": f"{h:04d}", "fcstValue": pcp},
        ]
    items += [
        {"category": "TMX", "fcstDate": "20261021", "fcstTime": "1500", "fcstValue": "19.0"},
        {"category": "TMN", "fcstDate": "20261021", "fcstTime": "0600", "fcstValue": "9.0"},
        {"category": "TMP", "fcstDate": "20261022", "fcstTime": "0000", "fcstValue": "7"},
    ]
    issued = datetime(2026, 10, 20, 5, 0, tzinfo=KST)
    df = kf.VilageFcstCollector.tidy(items, _site(), issued)
    d1 = df[df["target_date"] == date(2026, 10, 21)].set_index("variable")["value"]
    assert d1["ta_mean"] == 14 and d1["pop_max"] == 60 and d1["rn_sum"] == 6.0
    assert d1["ta_max"] == 19.0 and d1["ta_min"] == 9.0 and d1["n_hours"] == 3
    d2 = df[df["target_date"] == date(2026, 10, 22)].set_index("variable")["value"]
    assert d2["ta_mean"] == 7 and "ta_max" not in d2.index
    assert (df["issued_at"] == issued).all() and (df["source"] == "kma_vilage_fcst").all()
    assert list(df.columns) == kf.LONG_COLS
    assert kf.VilageFcstCollector.tidy([], _site(), issued).empty


def test_mid_tidy_and_as_of():
    issued = datetime(2026, 10, 20, 6, 0, tzinfo=KST)
    ta = {"taMin3": "8", "taMax3": "19", "taMin10": "5", "taMax10": "15"}
    land = {"rnSt3Am": "20", "rnSt3Pm": "70", "rnSt8": "40"}
    df = kf.MidFcstCollector.tidy(ta, land, _site(), issued)
    d3 = df[df["target_date"] == date(2026, 10, 23)].set_index("variable")["value"]
    assert d3["ta_min"] == 8 and d3["ta_max"] == 19 and d3["pop_max"] == 70
    assert df[df["target_date"] == date(2026, 10, 28)].set_index("variable")["value"]["pop_max"] == 40
    assert len(df[df["target_date"] == date(2026, 10, 30)]) == 2
    # as_of: 10-20 06:00 발표분은 base_date 10-20 에 사용 가능, 10-19 에는 불가
    assert len(kf.forecasts_as_of(df, date(2026, 10, 20))) == len(df)
    assert kf.forecasts_as_of(df, date(2026, 10, 19)).empty
    assert kf.MidFcstCollector.tidy({}, {}, _site(), issued).empty


def test_run_format_table_and_date_arg():
    rows = [
        {"step": "nier_algae", "status": "OK", "sec": 1.2, "summary": "수집 10행"},
        {"step": "kma_basin", "status": "FAIL", "sec": 0.1, "summary": "오류"},
    ]
    t = runmod.format_table(rows)
    assert "nier_algae" in t and "FAIL" in t
    assert runmod._date_arg("today") == date.today() and runmod._date_arg("2025-01-02") == date(2025, 1, 2)
    assert [s.name for s in runmod.STEPS][0] == "nier_algae" and runmod.STEPS[-1].name.startswith(
        "nier_forecast"
    )


def test_offset_and_continuous_series():
    days = [date(2024, 12, 29), date(2024, 12, 30), date(2024, 12, 31)]
    dataon = pd.DataFrame(
        {
            "station_code": "3008680",
            "station_name": "대전시(대청조정지댐)",
            "dam_name": "대청댐",
            "obs_date": days,
            "wl": [10.0, 10.1, 10.2],
            "source": "dataon_v5:x.xlsx",
        }
    )
    wamis = pd.DataFrame(
        {
            "station_code": "3008680",
            "obs_date": days + [date(2025, 1, 1)],
            "wl": [10.26, 10.36, 10.46, 10.5],
            "source": "wamis_wl_dtdata",
        }
    )
    off = dl.offset_table(dataon, wamis)
    assert off.loc[0, "오프셋 m(중앙값)"] == pytest.approx(-0.26) and off.loc[0, "기준면 차이"] == "Y"
    assert off.loc[0, "일치율 %"] == 0.0 and off.loc[0, "보정 후 일치율 %"] == 100.0
    cont = dl.continuous_series(dataon, wamis, off, date(2025, 1, 1))
    assert len(cont) == 4 and cont.iloc[-1]["source"] == "wamis_wl_dtdata"
    assert cont.iloc[-1]["wl_adj"] == pytest.approx(10.24) and cont.iloc[0]["wl_adj"] == 10.0
    assert dl.site_station_codes({"sites": [{"dataon_stations": [{"code": "1"}, "2", {"code": "1"}]}]}) == [
        "1",
        "2",
    ]
