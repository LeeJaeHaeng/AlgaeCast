"""EXP-007(R4 영양염) — 누수(as_of) 테스트와 수집기 파서 테스트.

as_of(또는 공개 지연 반영 시 as_of − d) 이후 측정을 난수로 바꾸고, 절반 삭제하고, 새 행을 추가해도
피처가 같아야 한다(tests/test_no_leakage.py 와 같은 방식).
"""

import json
import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from algaecast.collect import nier_wq_measuring as W
from algaecast.exp import r4_nutrients as R

SITE = "HP"
PT = R.SITE_STATION[SITE]


def _wq(seed: int = 42, start: str = "2023-01-02", weeks: int = 80) -> pd.DataFrame:
    """대표 측정소(주 1회) + 다른 지점 측정소 행이 섞인 합성 원자료."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, periods=weeks, freq="7D")
    frames = []
    for pt in (PT, R.SITE_STATION["CS"]):
        d = pd.DataFrame({"pt_no": pt, "obs_date": dates})
        for it in R.ITEMS:
            d[it] = rng.uniform(0.001, 5.0, size=len(d))
        d.loc[d.sample(frac=0.1, random_state=seed).index, "po4p"] = np.nan  # 일부 결측
        frames.append(d)
    return pd.concat(frames, ignore_index=True)


def _tamper(wq: pd.DataFrame, cut: pd.Timestamp, seed: int) -> pd.DataFrame:
    """cut 이후 행: 값을 난수로 교체, 절반 삭제, 새 행 추가(대표 측정소)."""
    rng = np.random.default_rng(seed)
    t = wq.copy()
    after = pd.to_datetime(t["obs_date"]) > cut
    for it in R.ITEMS:
        t.loc[after, it] = rng.uniform(-1e4, 1e4, size=int(after.sum()))
    drop = t[after].sample(frac=0.5, random_state=seed).index
    t = t.drop(index=drop)
    extra = pd.DataFrame(
        {"pt_no": PT, "obs_date": pd.date_range(cut + pd.Timedelta(days=1), periods=10, freq="2D")}
    )
    for it in R.ITEMS:
        extra[it] = rng.uniform(-1e4, 1e4, size=len(extra))
    return pd.concat([t, extra], ignore_index=True).sample(frac=1.0, random_state=seed)


def _same(a: dict, b: dict) -> bool:
    assert a.keys() == b.keys()
    for k in a:
        x, y = a[k], b[k]
        if (isinstance(x, float) and math.isnan(x)) or (isinstance(y, float) and math.isnan(y)):
            if not (isinstance(x, float) and isinstance(y, float) and math.isnan(x) and math.isnan(y)):
                return False
        elif not np.isclose(x, y, rtol=0, atol=1e-12):
            return False
    return True


@pytest.mark.parametrize("delay", [0, 30, 60])
@pytest.mark.parametrize("as_of", [date(2023, 8, 7), date(2023, 8, 9), date(2024, 3, 1)])
def test_no_leakage_after_as_of(as_of: date, delay: int) -> None:
    wq = _wq()
    base = R.nutrient_features(wq, as_of, SITE, delay_days=delay)
    cut = pd.Timestamp(as_of) - pd.Timedelta(days=delay)
    for seed in range(3):
        got = R.nutrient_features(_tamper(wq, cut, seed), as_of, SITE, delay_days=delay)
        assert _same(base, got), f"as_of={as_of} delay={delay} seed={seed}"


def test_after_as_of_tamper_is_ignored_even_without_delay_cut() -> None:
    """지연 0 에서 as_of 이후만 바꾸면 결과 동일, as_of 당일 측정은 포함(≤ as_of)."""
    wq = _wq()
    as_of = pd.Timestamp(wq["obs_date"].iloc[30]).date()  # 측정일과 같은 날
    f = R.nutrient_features(wq, as_of, SITE)
    assert f["wq_days_since"] == 0.0
    assert f["wq_tn_last"] == pytest.approx(float(wq["tn"].iloc[30]))


def test_sensitive_to_past_values() -> None:
    """as_of 이전 값을 바꾸면 피처가 바뀐다(테스트가 무력하지 않음을 확인)."""
    wq = _wq()
    as_of = date(2023, 8, 9)
    base = R.nutrient_features(wq, as_of, SITE)
    t = wq.copy()
    before = (pd.to_datetime(t["obs_date"]) <= pd.Timestamp(as_of)) & (t["pt_no"] == PT)
    t.loc[before, "tp"] = t.loc[before, "tp"] * 3 + 1
    got = R.nutrient_features(t, as_of, SITE)
    assert got["wq_tp_last"] != base["wq_tp_last"]
    assert got["wq_np_last"] != base["wq_np_last"]


def test_delay_shifts_reference() -> None:
    wq = _wq()
    as_of = date(2023, 8, 9)
    f0 = R.nutrient_features(wq, as_of, SITE, delay_days=0)
    f30 = R.nutrient_features(wq, as_of, SITE, delay_days=30)
    assert f30["wq_days_since"] >= 30
    assert f0["wq_days_since"] < f30["wq_days_since"]


def test_window_and_ratios() -> None:
    d = pd.DataFrame(
        {
            "pt_no": PT,
            "obs_date": pd.to_datetime(["2024-06-01", "2024-06-20", "2024-07-01", "2024-07-08"]),
        }
    )
    for it in R.ITEMS:
        d[it] = 1.0
    d["tn"] = [9.0, 2.0, 4.0, 3.0]
    d["tp"] = [1.0, 0.1, 0.2, 0.0]  # 마지막 TP 0(정량한계미만 대치) → 분모 하한 0.001
    d["no3n"], d["nh3n"], d["po4p"] = 1.0, 0.5, 0.0
    f = R.nutrient_features(d, date(2024, 7, 10), SITE)
    # 4주 창: (07-10 − 28일, 07-10] = 06-13 초과 → 06-20, 07-01, 07-08
    assert f["wq_tn_4w"] == pytest.approx(3.0)
    assert f["wq_tp_4w"] == pytest.approx(0.1)
    assert f["wq_np_last"] == pytest.approx(3.0 / R.P_FLOOR)
    assert f["wq_np_4w"] == pytest.approx(30.0)
    assert f["wq_dinp_last"] == pytest.approx(1.5 / R.P_FLOOR)
    assert f["wq_days_since"] == 2.0


def test_other_site_rows_ignored_and_empty() -> None:
    wq = _wq()
    only_other = wq[wq["pt_no"] != PT]
    f = R.nutrient_features(only_other, date(2023, 8, 9), SITE)
    assert all(math.isnan(v) for v in f.values())


def test_build_features_index_and_columns() -> None:
    wq = _wq()
    df = pd.DataFrame(
        {"station_id": ["HP", "CS", "HP", "MGMR"], "base_date": [date(2023, 5, 1), date(2023, 6, 5)] * 2},
        index=[10, 11, 12, 13],
    )
    out = R.build_features(df, wq=wq)
    assert list(out.index) == [10, 11, 12, 13]
    assert list(out.columns) == list(R.CHOSEN.cols)
    assert out.loc[13].isna().all()  # MGMR 측정소 행 없음 → NaN
    assert out.loc[10].notna().all()


def test_build_features_rejects_2026() -> None:
    df = pd.DataFrame({"station_id": ["HP"], "base_date": [date(2026, 7, 1)]})
    with pytest.raises(RuntimeError):
        R.build_features(df, wq=_wq())


# ---------------------------------------------------------------- 수집기 파서
ITEM_OK = {
    "PT_NO": "2022A10",
    "PT_NM": "물금",
    "ADDR": "경상남도 양산시 물금읍",
    "ORG_NM": "낙동강물환경연구소",
    "WMYR": "2025",
    "WMOD": "07",
    "WMWK": "4회차",
    "LON_DGR": 128,
    "LON_MIN": 58,
    "LON_SEC": 20,
    "LAT_DGR": 35,
    "LAT_MIN": 18,
    "LAT_SEC": 55,
    "WMCYMD": "2025.07.28",
    "WMDEP": None,
    "ITEM_TN": "         3.567",
    "ITEM_TP": "         0.153",
    "ITEM_POP": "정량한계미만",
    "ITEM_DOC": "         7.5",
}


def _resp(items: list[dict], code: str = "00") -> str:
    return json.dumps(
        {
            "getWaterMeasuringList": {
                "header": {"code": code, "message": "NORMAL SERVICE"},
                "item": items,
                "numOfRows": 10,
                "pageNo": 1,
                "totalCount": len(items),
            }
        },
        ensure_ascii=False,
    )


def test_parse_and_tidy() -> None:
    items, total = W.parse_json(_resp([ITEM_OK, {**ITEM_OK, "WMCYMD": None}]))
    assert total == 2
    df = W.tidy(items, pd.Timestamp("2026-10-21 18:00", tz="Asia/Seoul"))
    assert len(df) == 1  # 측정일 없는 행 제외
    r = df.iloc[0]
    assert r["obs_date"] == date(2025, 7, 28)
    assert r["tn"] == pytest.approx(3.567)
    assert math.isnan(r["po4p"]) and bool(r["po4p_below_loq"])
    assert r["do"] == pytest.approx(7.5)
    assert r["lat"] == pytest.approx(35 + 18 / 60 + 55 / 3600)
    assert r["lon"] == pytest.approx(128 + 58 / 60 + 20 / 3600)


def test_parse_error_code() -> None:
    with pytest.raises(W.CollectError):
        W.parse_json(_resp([], code="03"))
    with pytest.raises(W.CollectError):
        W.parse_json("<html>점검</html>")


def test_surface_layer_picks_shallowest() -> None:
    d = pd.DataFrame(
        {
            "pt_no": ["3008B30"] * 3 + ["2022A10"],
            "obs_date": [date(2024, 7, 1)] * 3 + [date(2024, 7, 1)],
            "depth_m": [15.0, 1.0, 30.0, np.nan],
            "tp": [0.5, 0.02, 0.9, 0.1],
        }
    )
    s = W.surface_layer(d)
    assert len(s) == 2
    assert s.loc[s["pt_no"] == "3008B30", "tp"].item() == pytest.approx(0.02)


def test_load_wq_loq_zero(tmp_path) -> None:
    raw = pd.DataFrame(
        {
            "pt_no": [PT, PT],
            "obs_date": [date(2024, 7, 1), date(2024, 7, 8)],
            "depth_m": [np.nan, np.nan],
            **{it: [1.0, 1.0] for it in R.ITEMS},
        }
    )
    for it in R.ITEMS:
        raw[f"{it}_below_loq"] = False
    raw.loc[1, "po4p"] = np.nan
    raw.loc[1, "po4p_below_loq"] = True
    p = tmp_path / "wq.parquet"
    raw.to_parquet(p, index=False)
    wq = R.load_wq(p)
    assert wq.loc[1, "po4p"] == 0.0
