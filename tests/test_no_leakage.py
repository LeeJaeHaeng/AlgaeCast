"""누수 방지 테스트 (CLAUDE.md 절대 규칙).

각 피처 함수에 대해 as_of 이후 행의 값을 난수로 바꿔도(행 추가·삭제 포함) 출력이 동일해야 한다.
예보 피처는 issued_at 기준(as_of 06:00 이후 발표분은 무시)을 검사한다.
"""

from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from algaecast.collect.base import KST
from algaecast.features import forecast as fc
from algaecast.features.ar import make_ar_features
from algaecast.features.base import cut_as_of
from algaecast.features.constants import FINAL_THRESHOLD_YEAR, site_thresholds
from algaecast.features.forecast import make_forecast_features
from algaecast.features.hydro import make_hydro_features
from algaecast.features.run import GROUPS, match_target
from algaecast.features.time_site import make_time_site_features
from algaecast.features.water import make_water_features
from algaecast.features.weather import make_weather_features

SITE = "2011G56"
NUM_COLS = [
    "wtemp", "ph", "do", "turb", "transp", "chla", "cells", "geosmin", "mib", "alert_level",
    "fac_inflow", "fac_outflow", "fac_level", "fac_storage", "fac_storage_rate", "fac_rain",
    "dam_inflow", "dam_outflow", "dam_storage", "dam_storage_rate", "level_cont_anom",
    "ta_mean", "ta_max", "ta_min", "rn", "ws_mean", "ws_max", "hm", "ss", "si",
    "fc_ta_mean_d1_7", "fc_ta_max_d1_7", "fc_rn_sum_d1_7", "fc_pop_mean_d1_7", "fc_rain_days", "fc_n_leads",
]  # fmt: skip


def _daily(days: int = 120, seed: int = 42, start: str = "2026-08-01") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=days, freq="D")
    df = pd.DataFrame({"obs_date": idx})
    for c in NUM_COLS:
        df[c] = rng.uniform(1, 100, size=days)
    df["alert_level"] = rng.integers(0, 3, size=days).astype(float)
    df["is_obs"] = np.arange(days) % 7 == 3
    df["genus"] = np.where(df["is_obs"], "Microcystis", None)
    for c in [
        "wtemp",
        "ph",
        "do",
        "turb",
        "transp",
        "chla",
        "cells",
        "geosmin",
        "mib",
        "genus",
        "alert_level",
    ]:
        df[f"{c}_obs"] = df[c].where(df["is_obs"])
    for c in NUM_COLS:
        df[f"{c}_missing"] = 0
    df["cells_missing"] = 0
    df["fc_available"] = 1
    df["level_cont_n"] = 3
    df["dam_n"] = 2
    df["days_since_obs"] = 0
    df["station_id"] = "GJGR"
    df["site_code"] = SITE
    return df


def _tamper(df: pd.DataFrame, as_of: date, seed: int) -> pd.DataFrame:
    """as_of 이후 행: 값을 난수로 교체하고 절반은 삭제, 측정 여부도 뒤집는다."""
    rng = np.random.default_rng(seed)
    t = df.copy()
    after = pd.to_datetime(t["obs_date"]) > pd.Timestamp(as_of)
    for c in NUM_COLS + [
        f"{c}_obs"
        for c in ["wtemp", "ph", "do", "turb", "transp", "chla", "cells", "geosmin", "mib", "alert_level"]
    ]:
        t.loc[after, c] = rng.uniform(-1e4, 1e4, size=after.sum())
    t.loc[after, "is_obs"] = rng.random(after.sum()) > 0.5
    t.loc[after, "genus_obs"] = "Oscillatoria"
    t.loc[after, "fc_available"] = 0
    drop = t.index[after][::2]
    return t.drop(index=drop).reset_index(drop=True)


@pytest.mark.parametrize("name", list(GROUPS))
@pytest.mark.parametrize("as_of", [date(2026, 9, 20), date(2026, 10, 22)])
def test_feature_functions_ignore_future(name: str, as_of: date) -> None:
    fn = GROUPS[name]
    df = _daily()
    base = fn(df, as_of, SITE)
    assert base, f"{name}: 빈 피처"
    for seed in (1, 2, 3):
        out = fn(_tamper(df, as_of, seed), as_of, SITE)
        assert out.keys() == base.keys()
        for k, v in base.items():
            if isinstance(v, float) and np.isnan(v):
                assert isinstance(out[k], float) and np.isnan(out[k]), f"{name}.{k}"
            else:
                assert out[k] == v, f"{name}.{k}: {v} != {out[k]}"


def test_feature_functions_use_only_rows_up_to_as_of() -> None:
    """전체 프레임 vs as_of 까지 잘라낸 프레임의 결과가 완전히 같아야 한다 (감사 스크립트와 같은 검사)."""
    df = _daily()
    as_of = date(2026, 10, 22)
    trunc = cut_as_of(df, as_of)
    for name, fn in GROUPS.items():
        a, b = fn(df, as_of, SITE), fn(trunc, as_of, SITE)
        assert a.keys() == b.keys() and all(
            (isinstance(x, float) and np.isnan(x) and np.isnan(y)) or x == y
            for x, y in zip(a.values(), b.values(), strict=True)
        ), name


def test_ar_values_are_from_last_measurement_only() -> None:
    df = _daily()
    as_of = date(2026, 10, 22)
    obs = df[df["is_obs"] & (pd.to_datetime(df["obs_date"]) <= pd.Timestamp(as_of))]
    out = make_ar_features(df, as_of, SITE)
    assert out["cell_log_t0"] == pytest.approx(np.log10(obs["cells_obs"].iloc[-1] + 1))
    assert out["days_since_obs"] == (pd.Timestamp(as_of) - pd.to_datetime(obs["obs_date"].iloc[-1])).days
    assert out["dominant_genus"] == "Microcystis"


def test_water_hydro_weather_windows() -> None:
    df = _daily()
    for c in ("wtemp", "fac_outflow", "rn", "ta_mean"):
        df[c] = 1.0
    df["fac_storage"] = np.nan  # 저수량 자료 없음 → 제원 storage_mcm 사용
    as_of = date(2026, 10, 22)
    w = make_water_features(df, as_of, SITE)
    assert w["wtemp_ma7"] == 1.0 and w["wtemp_degree_days20"] == 0.0 and w["wtemp_days_over25"] == 0.0
    th = site_thresholds(FINAL_THRESHOLD_YEAR)["GJGR"]  # 측정 ≤2025 임계(FIX-v2.1 R3)
    assert w["wtemp_over_site_thresh_days"] == 0.0 and w["wtemp_minus_site_thresh"] == pytest.approx(1.0 - th)
    h = make_hydro_features(df, as_of, SITE)
    assert (
        h["weir_outflow_sum7"] == 7.0
        and h["weir_outflow_sum14"] == 14.0
        and h["weir_level_diff7"] == pytest.approx(df["fac_level"].iloc[82] - df["fac_level"].iloc[75])
    )
    assert h["weir_residence_proxy"] == pytest.approx(
        92.3e6 / 86400
    )  # 강정고령보 저수량 92.3 백만 m3 / 1 m3/s
    x = make_weather_features(df, as_of, SITE)
    assert (
        x["rn_sum7"] == 7.0
        and x["rn_sum30"] == 30.0
        and x["ta_degree_days20"] == 0.0
        and np.isnan(x["dry_days"])
    )  # 5 mm 이상 강우 없음
    df["rn"] = 10.0
    assert make_weather_features(df, as_of, SITE)["dry_days"] == 0.0
    t = make_time_site_features(df, as_of, SITE)
    assert t["station_id"] == "GJGR" and t["total_storage_mcm"] == 92.3 and abs(t["doy_sin"]) <= 1


def test_forecast_respects_issued_at_and_availability() -> None:
    df = _daily()
    out = make_forecast_features(df, date(2026, 10, 22), SITE)
    assert out["fc_available"] == 1.0 and out["fc_ta_mean_d1_7"] == pytest.approx(
        df.loc[pd.to_datetime(df["obs_date"]) == "2026-10-22", "fc_ta_mean_d1_7"].iloc[0]
    )
    before = make_forecast_features(df, date(2026, 10, 20), SITE)  # available_from 이전 → 결측 + 0
    assert before["fc_available"] == 0.0 and np.isnan(before["fc_ta_mean_d1_7"])
    # long 테이블: 06:00 이후 발표분(issued 07:00)은 제외, 전날 발표분은 사용
    rows = []
    for issued, val in (
        (datetime(2026, 10, 21, 6, tzinfo=KST), 10.0),
        (datetime(2026, 10, 22, 7, tzinfo=KST), 99.0),
    ):
        for lead in range(1, 8):
            rows.append(
                {
                    "issued_at": issued,
                    "site_code": SITE,
                    "target_date": date(2026, 10, 22) + pd.Timedelta(days=lead),
                    "variable": "ta_mean",
                    "value": val,
                    "source": "x",
                }
            )
            rows.append(
                {
                    "issued_at": issued,
                    "site_code": SITE,
                    "target_date": date(2026, 10, 22) + pd.Timedelta(days=lead),
                    "variable": "pop_max",
                    "value": 70.0,
                    "source": "x",
                }
            )
    long = pd.DataFrame(rows)
    out = fc.forecast_features_from_long(long, date(2026, 10, 22), SITE)
    assert out["fc_ta_mean_d1_7"] == 10.0 and out["fc_rain_days"] == 7.0 and out["fc_available"] == 1.0
    assert fc.forecast_features_from_long(long, date(2026, 10, 20), SITE)["fc_available"] == 0.0


def test_match_target_rule() -> None:
    obs = pd.DatetimeIndex(
        pd.to_datetime(["2025-06-02", "2025-06-09", "2025-06-12", "2025-06-16", "2025-06-30"])
    )
    assert match_target(pd.Timestamp("2025-06-02"), obs, 7, 3) == pd.Timestamp("2025-06-09")
    assert match_target(pd.Timestamp("2025-06-05"), obs, 7, 3) == pd.Timestamp("2025-06-12")  # 6/12 (차 0)
    assert match_target(pd.Timestamp("2025-06-07"), obs, 7, 3) == pd.Timestamp(
        "2025-06-12"
    )  # 6/12(2) vs 6/16(2) 동률 → 이른 날
    assert match_target(pd.Timestamp("2025-06-20"), obs, 7, 3) == pd.Timestamp(
        "2025-06-30"
    )  # 6/27+3 경계 포함
    assert match_target(pd.Timestamp("2025-06-19"), obs, 7, 3) is None  # 6/26 ±3 에 없음
