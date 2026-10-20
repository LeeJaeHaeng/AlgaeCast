"""T1-c: ASOS 일자료 수집기·유역 CSV 파서 파싱/변환/선정 로직 (네트워크 없음)."""

import json
from datetime import date

import pandas as pd
import pytest

from algaecast.collect import kma_asos as ka
from algaecast.collect import kma_basin as kb
from algaecast.collect.base import CollectError


def _payload(items, total=None, code="00"):
    return json.dumps(
        {
            "response": {
                "header": {"resultCode": code, "resultMsg": "NORMAL_SERVICE"},
                "body": {
                    "items": {"item": items} if items else "",
                    "totalCount": total if total is not None else len(items),
                },
            }
        }
    )


def _items():
    base = {
        "stnId": "279",
        "stnNm": "구미",
        "avgTa": "12.3",
        "maxTa": "18.0",
        "minTa": "7.1",
        "avgWs": "1.2",
        "maxWs": "4.5",
        "avgRhm": "70",
        "sumSsHr": "8.1",
        "sumGsr": "",
        "avgPs": "1013.2",
        "avgTca": "3.5",
    }
    return [
        {**base, "tm": "2024-01-01", "sumRn": "", "hr1MaxRn": ""},  # 무강수 관측일 → 0
        {**base, "tm": "2024-01-02", "sumRn": "5.5", "hr1MaxRn": "2.0"},
        {
            **base,
            "tm": "2024-01-03",
            "sumRn": "",
            "hr1MaxRn": "",
            "avgTa": "",
            "avgRhm": "",
        },  # 결측일 → NaN 유지
        {**base, "tm": "2024-01-03", "sumRn": "", "hr1MaxRn": "", "avgTa": "", "avgRhm": ""},  # 중복
    ]


def test_asos_parse_tidy_and_cacheable():
    rows, total = ka.KmaAsosCollector.parse(_payload(_items()))
    assert total == 4 and rows[0]["stnNm"] == "구미"
    df = ka.KmaAsosCollector.tidy(rows, pd.Timestamp("2026-10-20", tz="Asia/Seoul"))
    assert len(df) == 3 and df["obs_date"].tolist() == [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
    assert df.loc[0, "sum_rn"] == 0.0 and df.loc[0, "rn_blank"] and df.loc[0, "day_observed"]
    assert df.loc[1, "sum_rn"] == 5.5 and not df.loc[1, "rn_blank"]
    assert pd.isna(df.loc[2, "sum_rn"]) and not df.loc[2, "day_observed"]
    assert pd.isna(df.loc[0, "sum_gsr"]) and df.loc[0, "avg_ps"] == 1013.2
    ka.SCHEMA.validate(df)
    col = ka.KmaAsosCollector.__new__(ka.KmaAsosCollector)
    assert col.is_cacheable(_payload(_items()))
    assert not col.is_cacheable(_payload([], 0, code="99")) and not col.is_cacheable("<html/>")
    with pytest.raises(CollectError):
        ka.KmaAsosCollector.parse(_payload([], 0, code="99"))
    with pytest.raises(CollectError):
        ka.KmaAsosCollector.parse("not json")
    assert ka.KmaAsosCollector.parse(_payload([], 0)) == ([], 0)
    assert ka.KmaAsosCollector.tidy([], None).empty


def _asos_frame():
    days = pd.date_range("2024-01-01", periods=40)
    rows = []
    for stn, slope in ((279, 1.0), (143, 0.5)):
        for i, d in enumerate(days):
            rows.append(
                {
                    "stn_id": stn,
                    "stn_nm": str(stn),
                    "obs_date": d.date(),
                    "avg_ta": slope * i,
                    "sum_gsr": float(i) if stn == 143 else None,
                }
            )
    df = pd.DataFrame(rows)
    for v in ka.FIELDS.values():
        if v not in df:
            df[v] = float("nan")
    return df


def test_compare_missing_and_station_choice():
    api = _asos_frame()
    bundle = api.copy()
    bundle.loc[1, "avg_ta"] = 99.0  # 1건 불일치
    cmp_t = ka.compare_with_bundle(api, bundle).set_index("stn_id")
    assert (
        cmp_t.loc[279, "공통일"] == 40
        and cmp_t.loc[279, "avg_ta"] == 97.5
        and cmp_t.loc[143, "avg_ta"] == 100.0
    )
    assert pd.isna(cmp_t.loc[279, "sum_gsr"])  # 양쪽 모두 결측 → 비교 불가
    miss = ka.missing_table(api).set_index("stn")
    assert (
        miss.loc["279(279)", "sum_gsr"] == 100.0
        and miss.loc["143(143)", "avg_ta"] == 0.0
        and miss.loc["143(143)", "기대일"] == 40
    )
    sites = {
        "sites": [
            {
                "station_id": "HP",
                "site_code": "2011G26",
                "name": "해평",
                "asos_candidates": [
                    {"stn_id": 279, "name": "구미", "distance_km": 7.4},
                    {"stn_id": 143, "name": "대구"},
                    {"stn_id": 999, "name": "없음"},
                ],
            }
        ]
    }
    algae = pd.DataFrame(
        {
            "site_code": "2011G26",
            "obs_date": [d.date() for d in pd.date_range("2024-01-08", periods=20)],
            "iem_wtrtp": [float(i) for i in range(20)],  # 기온과 단조 → ρ=1
        }
    )
    ch = ka.station_choice(api, sites, algae)
    assert ch["stn_id"].tolist() == [279, 143]  # 자료 없는 후보 999 제외
    assert (ch["spearman 당일기온"] == 1.0).all() and (ch["spearman 7일평균기온"] == 1.0).all()
    assert ch.loc[0, "거리 km"] == 7.4 and ch.loc[1, "일사 보유율 %"] == 100.0 and ch.loc[0, "n"] == 20


def test_basin_csv_parser(tmp_path):
    d1 = tmp_path / "수문기상정보"
    d1.mkdir()
    (d1 / "a.csv").write_text(
        '일자,대권역,중권역코드,중권역,표준유역코드,표준유역,면적강수량(mm),토양수분(%),증발산량(mm)\n2024.01.01,낙동강,2011,낙동왜관,201101,x,"1,002.5",23.1,1.2\n2024.01.02,낙동강,2011,낙동왜관,201101,x,,23.0,\n',
        encoding="cp949",
    )
    d2 = tmp_path / "유역단위_면적강수량"
    d2.mkdir()
    (d2 / "b.csv").write_text("날짜,표준유역코드,강수량\n2024-01-01,300801,3.3\n", encoding="utf-8-sig")
    long = kb.load_all({"hydromet": d1, "basin_rain": d2, "none": tmp_path / "없음"})
    assert list(long.columns) == kb.LONG_COLS and len(long) == 5  # 결측 2값 제외
    a = long[long["source"].str.startswith("hydromet")]
    assert a.loc[a["variable"] == "area_rain", "value"].tolist() == [1002.5]
    assert set(a["basin_mid_code"]) == {"2011"} and a["obs_date"].min() == date(2024, 1, 1)
    b = long[long["source"].str.startswith("basin_rain")].iloc[0]
    assert b["basin_mid_code"] == "3008" and b["unit"] == "mm" and b["value"] == 3.3  # 표준유역 앞 4자리
    assert kb.load_all({"x": tmp_path / "없음"}) is None
    (d2 / "bad.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    with pytest.raises(CollectError):
        kb.load_all({"basin_rain": d2})


def test_sites_yaml_asos_candidates_and_basin_codes():
    import yaml

    from algaecast.config import CONFIG_DIR

    cfg = yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))
    for s in cfg["sites"]:
        ids = [c["stn_id"] for c in s["asos_candidates"]]
        assert 2 <= len(ids) <= 3 and s["asos_primary"] in ids and s["asos_secondary"] in ids
        assert all(c["distance_km"] > 0 for c in s["asos_candidates"])
        assert s["basin_mid_code"] == s["site_code"][:4]  # 중권역 코드 = 조사지점코드 앞 4자리
