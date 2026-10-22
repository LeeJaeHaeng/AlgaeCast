"""EXP-008(R5) 전국 경보지점 통합 학습 — as_of 누수·2026 차단·폴드 경계·수집기 파서 테스트(모델 학습 없음).

- 다른 지점 피처는 v1 함수(align S1 달력 + features/*)에 지점 dict 만 보태 만든다. as_of 이후 원자료를 지우거나
  난수로 바꿔도 base_date = as_of 표본의 피처가 같아야 한다(tests/test_no_leakage.py 와 같은 방식, 달력 단계 포함).
- 통합 학습 폴드는 모든 지점에서 기준일 연도 < valid 연도 행만 학습하고, 평가는 우리 지점 행만이어야 한다.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from algaecast.collect.kma_stn_info import asos_representative, parse_station_html
from algaecast.collect.nier_algae_all import tidy_all
from algaecast.exp import harness as H
from algaecast.exp import r5_national as R
from algaecast.features import base as fb
from algaecast.features.run import GROUPS

CODE = "9999T01"  # 가상의 다른 지점
AS_OFS = [date(2024, 7, 15), date(2024, 9, 2)]
TARGET_COLS = {"target_cells", "target_log", "target_date", "horizon_days"}


def _meta_row(code: str = CODE) -> pd.Series:
    return pd.Series(
        {
            "site_code": code,
            "swmn_nm": "가상보",
            "swmn_detail_nm": "가상",
            "basin": "낙동강",
            "facility_type": "보",
            "asos_stn": 279,
            "river_lkmh_se": "하천",
        }
    )


def _site() -> dict:
    s = R.pseudo_site(_meta_row())
    s["facility_kwater_code"] = "2011602"
    s["upstream_dams"] = ["2001110"]
    return s


def _src(seed: int = 0) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    days = pd.date_range("2023-01-01", "2024-12-31", freq="D")
    obs = pd.date_range("2023-03-06", "2024-11-25", freq="7D")
    algae = pd.DataFrame(
        {
            "station_id": CODE,
            "obs_date": obs,
            "iem_wtrtp": rng.uniform(5, 32, len(obs)),
            "iem_ph": rng.uniform(6.5, 9.5, len(obs)),
            "iem_doc": rng.uniform(4, 14, len(obs)),
            "iem_tur": rng.uniform(1, 30, len(obs)),
            "iem_trp": rng.uniform(0.5, 3, len(obs)),
            "iem_chla": rng.uniform(1, 80, len(obs)),
            "iem_bgalage_cell_co": 10 ** rng.uniform(0, 5, len(obs)),
            "iem_geosm": rng.uniform(0, 50, len(obs)),
            "iem_mib2": rng.uniform(0, 10, len(obs)),
            "dominant_genus": rng.choice(["Microcystis", "Anabaena"], len(obs)),
            "alert_level_2consec": rng.integers(0, 3, len(obs)),
        }
    )
    algae.loc[algae.index[::9], "iem_bgalage_cell_co"] = np.nan
    asos = pd.DataFrame(
        {
            "stn_id": 279,
            "obs_date": days,
            "avg_ta": rng.uniform(-5, 30, len(days)),
            "max_ta": rng.uniform(0, 35, len(days)),
            "min_ta": rng.uniform(-10, 25, len(days)),
            "sum_rn": rng.exponential(3, len(days)),
            "avg_ws": rng.uniform(0, 5, len(days)),
            "max_ws": rng.uniform(1, 10, len(days)),
            "avg_rhm": rng.uniform(30, 95, len(days)),
            "sum_ss_hr": rng.uniform(0, 12, len(days)),
            "sum_gsr": rng.uniform(0, 30, len(days)),
        }
    )
    asos.loc[asos.index[::13], "avg_ta"] = np.nan
    hyd = []
    for fac, kw in (("2011802", "2011602"), ("2001110", "2001110")):
        for var in ("iqty", "tdqty", "rwl", "rsvwtqy", "rsvwtrt", "rf"):
            v = rng.uniform(1, 500, len(days))
            v[::17] = np.nan
            hyd.append(
                pd.DataFrame(
                    {"facility_code": fac, "kwater_code": kw, "variable": var, "obs_date": days, "value": v}
                )
            )
    return {"algae": algae, "asos": asos, "hydro": pd.concat(hyd, ignore_index=True)}


def _cut(src: dict[str, pd.DataFrame], as_of: date, seed: int | None) -> dict[str, pd.DataFrame]:
    """as_of 이후 원자료: seed=None 이면 삭제, 아니면 값을 난수로 바꾸고 절반 삭제."""
    out = {}
    for k, d in src.items():
        d = d.copy()
        after = pd.to_datetime(d["obs_date"]) > pd.Timestamp(as_of)
        if seed is None:
            out[k] = d[~after].reset_index(drop=True)
            continue
        rng = np.random.default_rng(seed)
        for c in d.columns:
            if c not in (
                "obs_date",
                "station_id",
                "stn_id",
                "facility_code",
                "kwater_code",
                "variable",
            ) and pd.api.types.is_float_dtype(d[c]):
                d.loc[after, c] = rng.uniform(-1e4, 1e4, int(after.sum()))
        out[k] = d.drop(index=d.index[after][::2]).reset_index(drop=True)
    return out


def _features_at(src: dict[str, pd.DataFrame], as_of: date) -> dict:
    site = _site()
    daily = R.site_daily(site, src)
    out: dict = {}
    with R.pseudo_sites({CODE: site}):
        for fn in GROUPS.values():
            out.update(fn(daily, as_of, CODE))
    return out


def _same(a: dict, b: dict) -> None:
    assert a.keys() == b.keys()
    for k, v in a.items():
        if isinstance(v, float) and math.isnan(v):
            assert isinstance(b[k], float) and math.isnan(b[k]), k
        else:
            assert b[k] == pytest.approx(v) if isinstance(v, float) else b[k] == v, k


@pytest.mark.parametrize("as_of", AS_OFS)
def test_other_site_features_ignore_future_raw_rows(as_of: date) -> None:
    """달력(align S1) + 피처(features/*) 전체 경로가 as_of 이후 원자료와 무관해야 한다."""
    src = _src()
    full = _features_at(src, as_of)
    assert (
        np.isfinite(full["cell_log_t0"])
        and np.isfinite(full["weir_outflow_t0"])
        and np.isfinite(full["inflow_t0"])
    )
    _same(full, _features_at(_cut(src, as_of, None), as_of))
    for seed in (1, 2):
        _same(full, _features_at(_cut(src, as_of, seed), as_of))


def test_site_samples_targets_after_base_and_features_match() -> None:
    """build_samples 경로: 타깃은 base 이후 측정, 피처는 같은 as_of 의 피처 함수 결과와 같다."""
    src = _src()
    site = _site()
    daily = R.site_daily(site, src)
    s = R.site_samples(daily, site, {CODE: site})
    assert len(s) > 50 and (pd.to_datetime(s["target_date"]) > pd.to_datetime(s["base_date"])).all()
    row = s[pd.to_datetime(s["base_date"]) >= pd.Timestamp("2024-07-10")].iloc[0]
    as_of = pd.Timestamp(row["base_date"]).date()
    feats = _features_at(_cut(src, as_of, None), as_of)
    for k, v in feats.items():
        if k in TARGET_COLS:
            continue
        if isinstance(v, float) and math.isnan(v):
            assert pd.isna(row[k]), k
        else:
            assert row[k] == pytest.approx(v) if isinstance(v, float) else row[k] == v, k


def test_pseudo_sites_patch_is_scoped_and_keeps_v1_sites() -> None:
    site = _site()
    with R.pseudo_sites({CODE: site}):
        from algaecast.features import water as fw

        assert fw.site_by_code(CODE)["station_id"] == CODE
        assert fw.feature_cfg()["site_caution_wtemp"][CODE] == R.DEFAULT_WTEMP_THRESH
        assert (
            fw.feature_cfg()["site_caution_wtemp"]["GJGR"] == fb.feature_cfg()["site_caution_wtemp"]["GJGR"]
        )
        assert fw.site_by_code("2011G56")["station_id"] == "GJGR"
    from algaecast.features import water as fw2

    with pytest.raises(KeyError):
        fw2.site_by_code(CODE)
    assert CODE not in fb.feature_cfg()["site_caution_wtemp"]


def test_pseudo_site_hydro_mapping() -> None:
    s = R.pseudo_site(_meta_row("2011A26"))
    assert s["facility_kwater_code"] == "2011601" and s["upstream_dams"] == R.own_site("HP")["upstream_dams"]
    assert s["dataon_stations"] == R.own_site("HP")["dataon_stations"]
    lake = R.pseudo_site(_meta_row("1003G40"))
    assert (
        "facility_kwater_code" not in lake and "facility_dam_code" not in lake and lake["upstream_dams"] == []
    )


def test_fold_plan_trains_only_past_years_and_evaluates_own_rows() -> None:
    rng = np.random.default_rng(0)
    years = rng.integers(2012, 2026, 3000)
    own = rng.random(3000) < 0.2
    plan = R.fold_plan(years, own)
    assert [p[1] for p in plan] == [*H.CV_YEARS, H.FINAL_YEAR]
    for _, vy, tr, va in plan:
        assert (years[tr] < vy).all() and tr.sum() == (years < vy).sum()
        assert own[va].all() and (years[va] == vy).all() and va.sum() == (own & (years == vy)).sum()
        assert not (tr & va).any()


def test_combine_blocks_2026_and_aligns_own_rows_first() -> None:
    own = pd.DataFrame(
        {
            "station_id": pd.Categorical(["HP", "CS"]),
            "site_code": ["2011G26", "2020G33"],
            "base_date": [date(2024, 7, 1), date(2025, 7, 1)],
            "target_cells": [1.0, 2.0],
            "target_log": [0.3, 0.5],
            "x": [1.0, 2.0],
        }
    )
    other = pd.DataFrame(
        {
            "station_id": ["9999T01"],
            "site_code": ["9999T01"],
            "base_date": [date(2025, 12, 1)],
            "target_cells": [3.0],
            "target_log": [0.6],
        }
    )
    comb, mask = R.combine(own, other, ["x"])
    assert mask.tolist() == [True, True, False] and comb["station_id"].tolist() == ["HP", "CS", "9999T01"]
    assert np.isnan(comb["x"].iloc[2])
    bad = other.assign(base_date=[date(2026, 1, 5)])
    with pytest.raises(RuntimeError):
        R.combine(own, bad, ["x"])


def test_load_algae_all_cuts_2026() -> None:
    if not R.ALGAE_ALL.exists():
        pytest.skip("전 지점 원자료 없음")
    a = R.load_algae_all()
    assert pd.to_datetime(a["obs_date"]).max() <= H.LAST_DATE


def test_site_coordinates_rules() -> None:
    wq = pd.DataFrame(
        {
            "ptno": ["1007A20", "1003A74", "1003B10", "1003A11", "2014A01"],
            "ptnm": ["강천", "충주댐", "충주댐4", "달천", "논공"],
            "lat": [37.0, 36.9, 37.1, 36.5, 35.7],
            "lon": [127.6, 128.0, 128.2, 127.9, 128.4],
        }
    )
    sites = pd.DataFrame(
        {
            "site_code": ["1007A20", "1003G40", "1003G99", "2014A25"],
            "swmn_nm": ["강천보", "충주호", "기타", "달성보"],
            "swmn_detail_nm": ["강천", "댐앞", "무명", "논공"],
            "detail_adres": ["a", "b", "c", "d"],
        }
    )
    c = R.site_coordinates(sites, wq).set_index("site_code")
    assert c.loc["1007A20", "coord_method"] == "수질측정망 동일 코드" and c.loc["1007A20", "lat"] == 37.0
    assert c.loc["1003G40", "lat"] == pytest.approx(37.0) and "수계명" in c.loc["1003G40", "coord_method"]
    assert c.loc["1003G99", "lat"] == pytest.approx((36.9 + 37.1 + 36.5) / 3)
    assert c.loc["2014A25", "coord_method"] == "중권역 측정소명=상세지점명"
    assert c.loc["2011G26", "coord_method"].startswith("sites.yaml")


def test_haversine_known_distance() -> None:
    # 해평(sites.yaml 근사 좌표) ↔ 구미 ASOS: sites.yaml asos_candidates 7.4 km
    d = R.haversine_km(36.1695, 128.3873, np.array([36.1306]), np.array([128.3206]))
    assert d[0] == pytest.approx(7.4, abs=0.2)


def test_tidy_all_station_ids_tokens_and_negative_cells() -> None:
    items = [
        {
            "swmnCode": "2011G26",
            "chckDe": "2024.07.01",
            "iemBgalageCellCo": "1,200",
            "iemBgalageMicrosts": "1200",
            "iemGeosm": "정량한계미만",
        },
        {
            "swmnCode": "1003G40",
            "chckDe": "2024.07.01",
            "iemBgalageCellCo": "-5",
            "iemChla": "분석중",
            "iemWtrtp": "측정불가",
        },
        {
            "swmnCode": "1003G40",
            "chckDe": "2024.07.08",
            "iemBgalageCellCo": "15000",
            "iemBgalageAnba": "15000",
        },
    ]
    df, report = tidy_all(items, pd.Timestamp("2026-10-21", tz="Asia/Seoul"))
    assert df.set_index("site_code")["station_id"].to_dict() == {"2011G26": "HP", "1003G40": "1003G40"}
    assert df.loc[df["site_code"] == "2011G26", "iem_bgalage_cell_co"].iloc[0] == 1200.0
    lake = df[df["site_code"] == "1003G40"].sort_values("obs_date")
    assert np.isnan(lake["iem_bgalage_cell_co"].iloc[0]) and lake["iem_chla_pending"].iloc[0]
    assert lake["dominant_genus"].iloc[1] == "Anabaena" and lake["alert_level_single"].iloc[1] == 2
    assert report == [{"column": "iem_wtrtp", "value": "측정불가", "count": 1}]


def test_parse_station_html_and_representative() -> None:
    html = (
        "<table><caption>조회 자료 결과 - x</caption><tbody>"
        "<tr><td>279</td><td>구미</td><!-- <td></td> --><td>36.1306</td><td>128.3206</td><td>49.2</td><td></td></tr>"
        "<tr><td>143</td><td>대구</td><td>35.8852</td><td>128.619</td><td>64</td><td></td></tr>"
        "<tr><td>143</td><td>대구</td><td>35.8780</td><td>128.653</td><td>54</td><td></td></tr>"
        "<tr><td>3</td><td>선봉</td><td>42.3</td><td>130.4</td><td>3</td><td></td></tr>"
        "</tbody></table>"
    )
    df = parse_station_html(html)
    assert df["stn_id"].tolist() == [279, 143, 143, 3] and df["lat"].iloc[0] == 36.1306
    rep = asos_representative(df).set_index("stn_id")
    assert list(rep.index) == [143, 279] and rep.loc[143, "n_hist"] == 2
    assert rep.loc[143, "lat"] == pytest.approx((35.8852 + 35.8780) / 2)


def _hist_algae(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    d = pd.date_range("2018-03-05", "2021-11-29", freq="7D")
    return pd.DataFrame(
        {"station_id": "X1", "obs_date": d, "iem_bgalage_cell_co": 10 ** rng.uniform(0, 5.5, len(d))}
    )


@pytest.mark.parametrize("year", [2019, 2020, 2021])
def test_site_history_uses_only_years_before(year: int) -> None:
    """지점 이력 피처: 그 해 1월 1일 이후 측정을 지우거나 난수로 바꿔도 값이 같다(base_date ≥ 1월 1일)."""
    a = _hist_algae()
    base = R.site_history_features(a, "X1", year)
    after = pd.to_datetime(a["obs_date"]) >= pd.Timestamp(year, 1, 1)
    assert base == R.site_history_features(a[~after], "X1", year)
    t = a.copy()
    t.loc[after, "iem_bgalage_cell_co"] = np.random.default_rng(1).uniform(0, 1e7, int(after.sum()))
    assert base == R.site_history_features(t, "X1", year)
    past = a.loc[~after, "iem_bgalage_cell_co"]
    assert base["site_hist_n"] == len(past)
    assert base["site_hist_frac10k"] == pytest.approx(float((past >= 1e4).mean()))


def test_site_history_first_year_is_missing_and_table_joins_by_base_year() -> None:
    a = _hist_algae()
    first = R.site_history_features(a, "X1", 2018)
    assert math.isnan(first["site_hist_mean_log"]) and first["site_hist_n"] == 0.0
    tb = R.site_history_table(a)
    comb = pd.DataFrame(
        {"station_id": ["X1", "X1"], "base_date": pd.to_datetime(["2020-01-02", "2021-08-01"])}
    )
    out = R.add_site_history(comb, tb)
    assert out["site_hist_n"].tolist() == [
        R.site_history_features(a, "X1", 2020)["site_hist_n"],
        R.site_history_features(a, "X1", 2021)["site_hist_n"],
    ]


def test_variant_cols_adds_embedding_flag_history_prior() -> None:
    cols = H.base_columns()
    assert R.variant_cols(cols, R.VARIANTS["own_only"]) == cols
    c = R.variant_cols(cols, R.VARIANTS["all_embed"])
    assert c[-2:] == ["hydro_fac_available", "station_id"]
    h = R.variant_cols(cols, R.VARIANTS["all_hist"])
    assert h[-3:] == R.SITE_HIST_COLS and "station_id" not in h
    assert R.variant_cols(cols, R.VARIANTS["prior_own"])[-1] == R.PRIOR_COL
