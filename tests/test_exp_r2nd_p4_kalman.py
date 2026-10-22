"""EXP-005(2차) P4 칼만 필터: as_of 누수 테스트, 일 단위 격자 동치, 매개변수 추정 구간(모델 학습 없음).

tests/test_no_leakage.py 와 같은 방식: as_of 이후 행을 난수로 바꾸고 절반을 지워도 결과가 같아야 한다.
매개변수는 (as_of 연도 − 1)-12-31 까지의 측정으로만 추정해야 하고, 필터는 as_of 까지의 측정만 쓴다(평활화 없음).
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from algaecast.exp import harness as H
from algaecast.exp import harness2 as H2
from algaecast.exp import r2nd_p4_kalman as K
from algaecast.features.base import cut_as_of

AS_OFS = [date(2024, 7, 15), date(2024, 9, 2), date(2024, 12, 30)]
SITES = ("HP", "GJGR", "CS", "MGMR", "DCHN")


def _algae(seed: int = 0, start: str = "2021-01-04", short_site: str | None = None) -> pd.DataFrame:
    """주 1회 측정 합성 자료(계절 수온·로그 세포수, 일부 결측). short_site 는 2023-06 부터만 측정."""
    rng = np.random.default_rng(seed)
    rows = []
    for s in SITES:
        x = 1.0
        for d in pd.date_range(start, "2024-12-30", freq="7D"):
            if s == short_site and d < pd.Timestamp("2023-06-05"):
                continue
            t = 15 + 10 * math.sin(2 * math.pi * (d.dayofyear - 110) / 365.25)
            x = 0.85 * x + 0.15 * (1.5 + 0.12 * (t - 15)) + rng.normal(0, 0.4)
            y = x + rng.normal(0, 0.3)
            rows.append({"station_id": s, "obs_date": d, "cells": float(max(10**y - 1, 0)), "wtemp": t})
    a = pd.DataFrame(rows)
    a.loc[a.index[::13], "cells"] = np.nan
    a.loc[a.index[::9], "wtemp"] = np.nan
    return a


def _tamper(a: pd.DataFrame, as_of: date, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = a.copy()
    after = pd.to_datetime(t["obs_date"]) > pd.Timestamp(as_of)
    t.loc[after, "cells"] = rng.uniform(0, 1e7, after.sum())
    t.loc[after, "wtemp"] = rng.uniform(-50, 80, after.sum())
    extra = pd.DataFrame(
        {
            "station_id": ["CS", "HP"],
            "obs_date": [
                pd.Timestamp(as_of) + pd.Timedelta(days=1),
                pd.Timestamp(as_of) + pd.Timedelta(days=3),
            ],
            "cells": [1e8, 0.0],
            "wtemp": [35.0, 1.0],
        }
    )
    t = t.drop(index=t.index[after][::2])
    return pd.concat([t, extra], ignore_index=True)


def _same(a: dict[str, float], b: dict[str, float]) -> bool:
    if a.keys() != b.keys():
        return False
    return all(
        (math.isnan(x) and math.isnan(y)) or x == y for x, y in zip(a.values(), b.values(), strict=True)
    )


@pytest.mark.parametrize("model", ["lltemp", "damped"])
@pytest.mark.parametrize("station", ["CS", "DCHN"])
@pytest.mark.parametrize("as_of", AS_OFS)
def test_kf_features_ignore_future(model: str, station: str, as_of: date) -> None:
    a = _algae()
    base = K.make_kf_features(a, as_of, station, 7.0, model)
    assert np.isfinite(base["kf_level"]) and np.isfinite(base["kf_predh"])
    for seed in (1, 2, 3):
        out = K.make_kf_features(_tamper(a, as_of, seed), as_of, station, 7.0, model)
        assert _same(base, out), f"{model} {station} {as_of} seed={seed}"


@pytest.mark.parametrize("model", ["lltemp", "damped"])
def test_truncated_input_gives_same_result(model: str) -> None:
    a = _algae()
    as_of = AS_OFS[1]
    assert _same(
        K.make_kf_features(a, as_of, "GJGR", 6.0, model),
        K.make_kf_features(cut_as_of(a, as_of), as_of, "GJGR", 6.0, model),
    )


def test_pooled_fallback_ignores_future() -> None:
    """측정이 적은 지점(2023-06~)은 공통 매개변수 — 그 경우도 as_of 이후 자료와 무관해야 한다."""
    a = _algae(short_site="MGMR")
    as_of = date(2024, 3, 4)
    fit = K.params_for_year(cut_as_of(a, as_of), "MGMR", 2024)
    assert fit is not None and fit.source == "pooled"
    base = K.make_kf_features(a, as_of, "MGMR", 7.0)
    for seed in (4, 5):
        assert _same(base, K.make_kf_features(_tamper(a, as_of, seed), as_of, "MGMR", 7.0))


def test_params_use_only_previous_years() -> None:
    """매개변수 = ≤ (연도−1)-12-31 측정. 같은 해 as_of 이전 측정을 바꾸면 상태만 바뀌고 매개변수는 그대로."""
    a = _algae()
    as_of = date(2024, 8, 5)
    f0 = K.params_for_year(cut_as_of(a, as_of), "CS", 2024)
    t = a.copy()
    same_year = (t["station_id"] == "CS") & (t["obs_date"] >= "2024-01-01") & (t["obs_date"] <= "2024-07-31")
    t.loc[same_year, "cells"] = t.loc[same_year, "cells"] * 50
    f1 = K.params_for_year(cut_as_of(t, as_of), "CS", 2024)
    assert f0 is not None and f1 is not None and f0.params == f1.params
    assert K.make_kf_features(a, as_of, "CS")["kf_level"] != K.make_kf_features(t, as_of, "CS")["kf_level"]
    prev = (t["station_id"] == "CS") & (t["obs_date"].dt.year == 2023)
    t.loc[prev, "cells"] = t.loc[prev, "cells"] * 50
    f2 = K.params_for_year(cut_as_of(t, as_of), "CS", 2024)
    assert f2 is not None and f2.params != f0.params


def _daily_reference(s: K.Series, p: K.Params) -> tuple[dict[int, tuple[float, float]], float]:
    """일 단위 격자에서 하루씩 전이하는 순진한 필터(측정 없는 날은 갱신 생략). 측정일의 (m, P)·로그우도."""
    obs = {
        int(d): (float(y), float(t), int(mo)) for d, y, t, mo in zip(s.days, s.y, s.T, s.month, strict=True)
    }
    first = int(s.days[np.isfinite(s.y)][0])
    m = P = 0.0
    T = math.nan
    ll = 0.0
    out = {}
    started = False
    for d in range(int(s.days[0]), int(s.days[-1]) + 1):
        if started:
            a, c, Q = K.transition(p, 1.0, T)
            m, P = float(a * m + c), float(a * a * P + Q)
        if d in obs:
            y, t, mo = obs[d]
            T = t
            r = float(K.r_of(p, np.array([mo]))[0])
            lv = p.model.endswith("_lv")
            if math.isfinite(y):
                if not started:
                    m, P, started = y, (K.r_level(p, y) if lv else r), True
                else:
                    S = P + (K.r_level(p, m) if lv else r)
                    v = y - m
                    ll -= 0.5 * (math.log(2 * math.pi * S) + v * v / S)
                    k = P / S
                    m, P = m + k * v, (1 - k) * P
            if started and d >= first:
                out[d] = (m, P)
    return out, ll


@pytest.mark.parametrize(
    "p",
    [
        K.Params("lltemp", q=0.03, r=0.2, b0=-0.001, b1=0.002),
        K.Params("damped", q=0.05, r=0.1, phi=0.95, a0=1.8, a1=0.13),
        K.Params("damped_r2", q=0.05, r=0.1, r_cold=0.3, phi=0.95, a0=1.8, a1=0.13),
        K.Params("lltemp_lv", q=0.03, r=0.2, b0=-0.001, b1=0.002, rho1=-0.3),
        K.Params("damped_lv", q=0.05, r=0.1, phi=0.95, a0=1.8, a1=0.13, rho1=-0.4),
    ],
)
def test_event_filter_equals_daily_grid(p: K.Params) -> None:
    a = _algae(seed=3)
    s = K.make_series(a[a["station_id"] == "HP"])
    fo = K.kf_filter(s, p)
    ref, ll = _daily_reference(s, p)
    for i, d in enumerate(s.days):
        if int(d) in ref:
            assert fo.m[i] == pytest.approx(ref[int(d)][0], abs=1e-9)
            assert fo.P[i] == pytest.approx(ref[int(d)][1], abs=1e-9)
    assert fo.ll == pytest.approx(ll, abs=1e-7)


@pytest.mark.parametrize("model", ["lltemp", "damped"])
def test_forecast_equals_seven_daily_transitions(model: str) -> None:
    p = K.Params(model, q=0.04, r=0.2, b0=0.002, b1=0.001, phi=0.93, a0=2.0, a1=0.1)
    m, P = 2.3, 0.15
    for _ in range(7):
        m, P = K.forecast(p, m, P, 22.0, 1.0)
    m7, P7 = K.forecast(p, 2.3, 0.15, 22.0, 7.0)
    assert m7 == pytest.approx(m) and P7 == pytest.approx(P)


def test_variant_names_and_controls() -> None:
    assert K.parse_variant("P4_kfd3") == ("kfd3", False, "")
    assert K.parse_variant("P4_kfd3_ctrl+kfd_member") == ("kfd3", True, "kfd_member")
    assert K.parse_variant("P4_kf_member_mean") == ("", False, "kf_member_mean")
    assert K.control_of("P4_kf5") == "P4_kf5_ctrl"
    assert K.control_of("P4_kfd3+kfd_member") == "P4_kfd3_ctrl+kfd_member"
    assert K.control_of("P4_kfd_member") is None
    with pytest.raises(KeyError):
        K.parse_variant("P4_xyz")


@pytest.mark.skipif(not H.ALGAE_PARQUET.exists(), reason="조류 원자료 없음")
def test_real_rows_index_noise_control_and_2026_guard() -> None:
    df = H.load_base()
    sub = df[H.years_of(df) >= 2024].groupby("station_id", observed=True).tail(3)
    kf = K.all_kf(sub, "lltemp")
    assert list(kf.index) == list(sub.index)
    assert kf[["kf_level", "kf_pred7", "kf_sd", "kf_predh"]].notna().all().all()
    feat = kf[list(K.BUNDLES["kf3"][1])]
    ctrl = H2.noise_like(feat, 11)
    assert ctrl.shape == feat.shape and (ctrl.isna().to_numpy() == feat.isna().to_numpy()).all()
    bad = sub.copy()
    bad.loc[bad.index[0], "base_date"] = pd.Timestamp("2026-01-05").date()
    with pytest.raises(RuntimeError):
        K.all_kf(bad, "lltemp")
    a = K.load_algae()
    assert pd.to_datetime(a["obs_date"]).max() <= H.LAST_DATE
