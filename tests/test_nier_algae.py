"""조류경보제 수집기: XML 파싱·형변환·파생(4속 합, 우점종, 단일/2회 연속 단계)·대회 대조 (네트워크 없음)."""

from datetime import date

import pandas as pd
import pytest

from algaecast.collect import nier_algae as na

ITEM = (
    "<item><rowno>{i}</rowno><swmnCode>{code}</swmnCode><riverLkmhSe>하천</riverLkmhSe>"
    "<swmnNm>낙동강</swmnNm><swmnDetailNm>해평</swmnDetailNm><detailAdres>x</detailAdres>"
    "<chckDe>{d}</chckDe><iemWtrtp>{wt}</iemWtrtp><iemPh>8.1</iemPh><iemDoc>9.0</iemDoc><iemTrp/>"
    "<iemTur>5.3</iemTur><iemChla>{chla}</iemChla><iemBgalageCellCo>{tot}</iemBgalageCellCo>"
    "<iemBgalageMicrosts>{a}</iemBgalageMicrosts><iemBgalageAnba>{b}</iemBgalageAnba>"
    "<iemBgalageOsrtria>{c}</iemBgalageOsrtria><iemBgalageApzo>{e}</iemBgalageApzo>"
    "<iemGeosm>{geo}</iemGeosm><iemMib2>정량한계미만</iemMib2><iemMicrostlr/></item>"
)


def _xml(rows):
    items = "".join(ITEM.format(i=i, **r) for i, r in enumerate(rows, 1))
    return (
        "<response><header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE</resultMsg></header>"
        f"<body><items>{items}</items><numOfRows>10000</numOfRows><pageNo>1</pageNo>"
        f"<totalCount>{len(rows)}</totalCount></body></response>"
    )


def _row(d, tot, a, b="0", c="0", e="0", chla="80", geo=""):
    return dict(code="2011G26", d=d, wt="25.0", chla=chla, tot=tot, a=a, b=b, c=c, e=e, geo=geo)


ROWS = [
    _row("2026.06.01", "1120", "325", "275", "0", "520", chla="69.0", geo="3"),
    _row("2026.06.08", "12000", "12000", chla="분석중"),
    _row("2026.06.15", "15000", "14000", "1000"),
    _row("2026.06.22", "900", "900"),
    _row("2026.06.29", "800", "0"),  # 4속 전부 0 인데 총합 800 → 불일치
    _row("2026.07.06", "", "", "", "", ""),  # 전부 결측
    _row("2026.07.13", "500", "500"),
    dict(
        code="9999X99", d="2026.06.01", wt="1", chla="1", tot="1", a="1", b="0", c="0", e="0", geo=""
    ),  # 대상 외
]


def test_parse_and_tidy_types_tokens_and_derivations():
    items, total = na.parse_items(_xml(ROWS))
    assert total == 8 and len(items) == 8
    df = na.tidy(items, pd.Timestamp("2026-10-20 15:00", tz="Asia/Seoul"))
    assert len(df) == 7 and set(df["site_code"]) == {"2011G26"} and (df["station_id"] == "HP").all()
    assert df["obs_date"].map(type).eq(date).all() and df["obs_date"].iloc[0] == date(2026, 6, 1)
    assert df["iem_bgalage_cell_co"].dtype == "float64"
    assert df["iem_mib2"].isna().all() and df["iem_mib2_below_loq"].all()
    assert df.loc[1, "iem_chla_pending"] and pd.isna(df.loc[1, "iem_chla"])
    # 4속 합 대조: 325+275+0+520=1120 일치 … 5행은 0 vs 800 불일치, 6행은 전부 결측 → NA
    assert df["cells_sum4"].tolist()[:2] == [1120.0, 12000.0]
    assert df["cells_consistent"].tolist()[:5] == [True, True, True, True, False]
    assert pd.isna(df.loc[5, "cells_consistent"])
    assert df["dominant_genus"].tolist()[:3] == ["Aphanizomenon", "Microcystis", "Microcystis"]
    assert df.loc[4, "dominant_genus"] is None  # 4속 전부 0 → 결측
    na.SCHEMA.validate(df)


def test_alert_levels_single_and_two_consecutive():
    s = na.single_level(pd.Series([0, 999, 1000, 9999, 10000, 999999, 1000000, None]))
    assert s.tolist()[:7] == [0, 0, 1, 1, 2, 2, 3] and pd.isna(s.iloc[7])
    # 1,120 → 12,000: 2회 연속 ≥1,000 이므로 관심(min=1) → 15,000: 2회 연속 ≥10,000 → 경계
    # → 900: 1회 미만이라 유지 → 800: 900·800 모두 <1,000 → 바로 해제 → 결측: 유지 → 500: 해제 유지
    single = na.single_level(pd.Series([1120, 12000, 15000, 900, 800, None, 500]))
    assert na.two_consecutive_levels(single).tolist() == [0, 1, 2, 2, 0, 0, 0]

    def f(x):
        return na.two_consecutive_levels(na.single_level(pd.Series(x, dtype="float64"))).tolist()

    assert f([20000, 30000]) == [0, 2]  # 두 번 연속 ≥10,000 이면 해제에서 바로 경계
    assert f([20000, 20000, 500, 500]) == [0, 2, 2, 0]  # 경계 → 해제 직행 (매뉴얼 표6)
    assert f([12000, 15000, 5000, 3000]) == [0, 2, 2, 1]  # 경계 → 관심
    assert f([2e6, 2e6, 500, 500]) == [0, 3, 3, 0]  # 대발생 → 해제 직행
    assert f([500, 20000, 800, 500]) == [0, 0, 0, 0]  # 단일 급증은 상태 불변
    assert f([71100, 71100, 557, 659, 3201, 1940]) == [
        0,
        2,
        2,
        0,
        0,
        1,
    ]  # 해평 '26: 9/4 해제 → 9/14 관심 재발령
    assert f([float("nan"), 20000, 20000, float("nan"), 500, 500]) == [0, 0, 2, 2, 2, 0]


def test_compare_with_competition():
    d = [date(2026, 6, 1), date(2026, 6, 8), date(2026, 6, 15), date(2026, 6, 1)]
    api = pd.DataFrame(
        {
            "site_code": ["2011G26"] * 3 + ["3008G30"],
            "obs_date": d,
            "iem_bgalage_cell_co": [1120.0, 12000.0, None, 5.0],
        }
    )
    comp = pd.DataFrame(
        {
            "site_code": ["2011G26"] * 3 + ["3008G30"],
            "obs_date": [d[0], d[1], date(2026, 6, 22), d[3]],
            "iem_bgalage_cell_co": [1120.0, 12001.0, 3.0, 5.0],
        }
    )
    t = na.compare_with_competition(api, comp).set_index("site_code")
    hp = t.loc["2011G26"]
    assert hp["공통 측정일"] == 2 and hp["세포수 일치"] == 1 and hp["일치율 %"] == 50.0
    assert hp["대회에만"] == 1 and hp["API에만"] == 1
    assert t.loc["3008G30", "일치율 %"] == 100.0


def test_unknown_token_raises():
    with pytest.raises(na.CollectError):
        na._num(pd.Series(["1", "???"], name="iem_ph"))


def test_parse_items_rejects_non_api_bodies():
    with pytest.raises(na.CollectError):
        na.parse_items("<html><body>점검중</body></html>")  # XML 이지만 resultCode 없음
    with pytest.raises(na.CollectError):
        na.parse_items("not xml at all")
    with pytest.raises(na.CollectError):
        na.parse_items("<response><header><resultCode>99</resultCode></header></response>")
    col = na.NierAlgaeCollector.__new__(na.NierAlgaeCollector)
    assert col.is_cacheable(_xml(ROWS[:1]))
    assert not col.is_cacheable("<html/>") and not col.is_cacheable("x")


def test_flag_columns_always_present_and_item_without_tags_ok():
    items, _ = na.parse_items(_xml([_row("2026.06.01", "10", "10")]))
    items[0].pop("iemGeosm")  # 일부 item 에 태그가 없어도 처리
    df = na.tidy(items, pd.Timestamp("2026-10-20", tz="Asia/Seoul"))
    for c in na.LOQ_COLS:
        assert f"{c}_below_loq" in df.columns
    for c in na.PENDING_COLS:
        assert f"{c}_pending" in df.columns
    assert not df["iem_chla_pending"].any() and pd.isna(df.loc[0, "iem_geosm"])
    na.SCHEMA.validate(df)


def test_cache_ttl_year_rollover():
    from datetime import datetime, timedelta

    kst = na.KST
    ttl = na.NierAlgaeCollector.cache_ttl
    assert ttl(2026, datetime(2026, 10, 20, tzinfo=kst)) == timedelta(hours=12)  # 진행 중인 해
    assert ttl(2025, datetime(2026, 1, 5, tzinfo=kst)) == timedelta(hours=12)  # 1월: 마감 전 → 재조회
    assert ttl(2025, datetime(2026, 10, 20, tzinfo=kst)) > timedelta(days=250)  # 마감 후: 2월 1일 이후 캐시만
