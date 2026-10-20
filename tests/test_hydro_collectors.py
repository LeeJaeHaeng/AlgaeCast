"""T1-b: WAMIS·K-water 수문 수집기 파싱/변환/검증 로직 (네트워크 없음)."""

import json
from datetime import date

import pandas as pd
import pytest

from algaecast.collect import kwater_dam as kd
from algaecast.collect import wamis
from algaecast.collect.base import CollectError


def _wamis_rows():
    return [
        {
            "obsymd": "20250801",
            "rwl": "25.67",
            "iqty": "80.884",
            "tdqty": "79.698",
            "edqty": "34.2",
            "spdqty": None,
            "otltdqty": "43.497",
            "itqty": "2",
            "rf": "0",
        },
        {
            "obsymd": "20250802",
            "rwl": "25.71",
            "iqty": "89.911",
            "tdqty": "85.166",
            "edqty": "34.2",
            "spdqty": "0",
            "otltdqty": "48.9",
            "itqty": "2",
            "rf": ".5",
        },
        {
            "obsymd": "20250802",
            "rwl": "25.72",
            "iqty": "89.9",
            "tdqty": "85.1",
            "edqty": "34.2",
            "spdqty": "0",
            "otltdqty": "48.9",
            "itqty": "2",
            "rf": ".5",
        },  # 중복 → 마지막 유지
    ]


def test_wamis_parse_and_tidy_and_cacheable():
    ok = json.dumps({"result": {"code": "success", "msg": "완료"}, "count": 3, "list": _wamis_rows()})
    rows = wamis.WamisBase.parse(ok)
    assert len(rows) == 3
    df = wamis.WamisDamDailyCollector.tidy(rows, "2011801", pd.Timestamp("2026-10-20", tz="Asia/Seoul"))
    assert len(df) == 2 and df["obs_date"].tolist() == [date(2025, 8, 1), date(2025, 8, 2)]
    assert (
        df.loc[0, "rwl"] == 25.67
        and pd.isna(df.loc[0, "spdqty"])
        and df.loc[1, "rf"] == 0.5
        and df.loc[1, "rwl"] == 25.72
    )
    wamis.DAM_SCHEMA.validate(df)
    col = wamis.WamisDamDailyCollector.__new__(wamis.WamisDamDailyCollector)
    assert col.is_cacheable(ok)
    assert not col.is_cacheable(
        json.dumps({"result": {"code": "failure", "msg": "유효하지 않은 인증키입니다."}})
    )
    assert not col.is_cacheable("<html/>")
    with pytest.raises(CollectError):
        wamis.WamisBase.parse(json.dumps({"result": {"code": "failure", "msg": "x"}}))
    with pytest.raises(CollectError):
        wamis.WamisBase.parse("not json")
    assert wamis.WamisDamDailyCollector.tidy([], "x", None).empty


def test_kwater_sluice_parse_and_tidy():
    payload = {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "items": {
                    "item": [
                        {
                            "inflowqy": "40.870",
                            "lowlevel": 75.04,
                            "obsryymtde": "2024-01-01",
                            "prcptqy": "0.000",
                            "rsvwtqy": "1,102.212",
                            "rsvwtrt": 73.97,
                            "totdcwtrqy": 32.199,
                        }
                    ]
                },
                "numOfRows": 3,
                "pageNo": 1,
                "totalCount": 1,
            },
        }
    }
    rows, total = kd.KwaterSluiceCollector.parse(json.dumps(payload))
    assert total == 1 and rows[0]["lowlevel"] == 75.04
    df = kd.KwaterSluiceCollector.tidy(rows, "3008110", pd.Timestamp("2026-10-20", tz="Asia/Seoul"))
    assert (
        df.loc[0, "rsvwtqy"] == 1102.212
        and df.loc[0, "iqty"] == 40.87
        and df.loc[0, "obs_date"] == date(2024, 1, 1)
    )
    kd.KwaterSluiceCollector.schema.validate(df)
    # 단일 item 이 dict 로 오는 경우와 빈 items
    payload["response"]["body"]["items"] = {"item": payload["response"]["body"]["items"]["item"][0]}
    assert len(kd.KwaterSluiceCollector.parse(json.dumps(payload))[0]) == 1
    payload["response"]["body"]["items"] = ""
    payload["response"]["body"]["totalCount"] = 0
    assert kd.KwaterSluiceCollector.parse(json.dumps(payload)) == ([], 0)
    col = kd.KwaterSluiceCollector.__new__(kd.KwaterSluiceCollector)
    assert col.is_cacheable(json.dumps(payload)) and not col.is_cacheable("{}")


def test_damapi_tidy_shifts_to_previous_day():
    rows = [
        {
            "damnm": "대청",
            "suge": "금강",
            "prcptqy": "21.8",
            "inflowqy": 31.7,
            "totdcwtrqy": 31.4,
            "nowlowlevel": 72.02,
            "nowrsvwtqy": 923,
            "rsvwtrt": 61.9,
            "_vdate": "2026-10-19",
            "_fetched_at": "2026-10-20T15:00:00+09:00",
        },
    ]
    df = kd.KwaterDamApiCollector.tidy(rows)
    assert (
        df.loc[0, "obs_date"] == date(2026, 10, 18) and df.loc[0, "rf"] == 21.8 and df.loc[0, "rwl"] == 72.02
    )
    assert str(df["fetched_at"].dtype) == "datetime64[ns, Asia/Seoul]"
    assert kd._year_ago(date(2028, 2, 29)) == date(2027, 2, 28)


def test_load_kwater_csv_alias_mapping(tmp_path):
    (tmp_path / "a.csv").write_text(
        '댐명,일자,강우량(mm),유입량(cms),총방류량(㎥/s),저수위(EL.m),저수량(백만㎥),저수율(%)\n대청,2024.01.01,0.0,40.87,32.199,75.04,"1,102.2",73.97\n',
        encoding="cp949",
    )
    df = kd.load_kwater_csv(tmp_path)
    assert (
        df is not None and df.loc[0, "facility_name"] == "대청" and df.loc[0, "obs_date"] == date(2024, 1, 1)
    )
    assert (
        df.loc[0, "rsvwtqy"] == 1102.2
        and df.loc[0, "rwl"] == 75.04
        and df.loc[0, "source"].startswith("kwater_csv:")
    )
    assert kd.load_kwater_csv(tmp_path / "none") is None
    (tmp_path / "b.csv").write_text("x,y\n1,2\n", encoding="utf-8-sig")
    with pytest.raises(CollectError):
        kd.load_kwater_csv(tmp_path)


def test_to_long_and_match_and_missing_tables():
    cat = pd.DataFrame(
        [
            {
                "facility_type": "dam",
                "facility_code": "3008110",
                "kwater_code": "3008110",
                "facility_name": "대청",
                "basin": "금강",
                "role": "main",
            },
        ]
    )
    ts = pd.Series(pd.Timestamp("2026-10-20", tz="Asia/Seoul")).astype("datetime64[ns, Asia/Seoul]")[0]
    bundle = pd.DataFrame(
        {
            "facility_code": "3008110",
            "obs_date": [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)],
            "rwl": [75.04, 75.04, None, 75.05],
            "iqty": [40.87, 35.72, 36.68, 30.0],
            "tdqty": [32.2, 32.5, 32.6, 32.7],
            "rf": [0.0, 0.0, 1.5, 0.0],
            "source": "bundle_wamis",
            "fetched_at": ts,
        }
    )
    ext = bundle.copy()
    ext.loc[1, "iqty"] = 35.72 * 1.02  # 2% 차이 → 불일치
    ext.loc[3, "rwl"] = 75.08  # 0.03 차이 → 불일치
    ext["source"] = "kwater_sluice_delist"
    long = kd.to_long(bundle, cat.iloc[0], ["rwl", "iqty", "tdqty", "rf"])
    assert list(long.columns) == kd.LONG_COLS and len(long) == 15  # 16 값 중 rwl 결측 1 제외
    assert set(long["unit"]) == {"EL.m", "m3/s", "mm"}
    mt = kd.match_table(bundle, ext, cat, "K-water delist").set_index("변수")
    assert mt.loc["수위", "공통일"] == 3 and mt.loc["수위", "일치율 %"] == pytest.approx(66.67, abs=0.01)
    assert mt.loc["유입량", "일치율 %"] == pytest.approx(75.0) and mt.loc["방류량", "일치율 %"] == 100.0
    miss = kd.missing_table(bundle, cat)
    assert miss.loc[0, "rwl 결측%"] == 25.0 and miss.loc[0, "기대일"] == 4


def test_facility_catalog_from_sites_yaml():
    cat = kd.facility_catalog()
    assert set(cat["facility_type"]) == {"dam", "weir"}
    weirs = cat[cat["facility_type"] == "weir"].set_index("facility_name")
    assert (
        weirs.loc["칠곡보", "facility_code"] == "2011801" and weirs.loc["칠곡보", "kwater_code"] == "2011601"
    )
    dams = cat[cat["facility_type"] == "dam"].set_index("facility_name")
    assert dams.loc["군위", "kwater_code"] == "2008101" and dams.loc["군위", "facility_code"] == "2008110"
    assert len(kd.dam_codes()) >= 50
