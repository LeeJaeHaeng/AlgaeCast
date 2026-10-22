"""EXP-005 2차 P1(변화량 타깃·성장 기작 피처)의 as_of 누수 테스트와 정의 점검.

- 성장 기작 피처: as_of 이후 달력 행을 난수로 바꾸고 절반을 지워도 결과가 같아야 한다(tests/test_no_leakage.py 방식).
- 약화 열: 같은 행의 v1 피처끼리의 차이라 다른 행·미래 값에 의존하지 않는다.
- Δ 구성원 OOF: 검증 연도 이후(또는 그 연도) 타깃을 바꿔도 그 연도 이전 OOF·연도 확장 smear 계수가 같아야 한다.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from algaecast.exp import r2nd_p1_change as P

AS_OFS = [date(2024, 7, 15), date(2024, 9, 2), date(2024, 3, 1)]


# ---------------------------------------------------------------- 수온 성장률
def test_mu_temp_shape() -> None:
    for g, topt in P.T_OPT.items():
        assert P.mu_temp(topt, g) == pytest.approx(P.MU_OPT)
        # 최적 아래: Q10 형태(10℃ 낮으면 1/Q10)
        assert P.mu_temp(topt - 10, g) == pytest.approx(P.MU_OPT / P.Q10)
        lo = P.mu_temp(np.linspace(0, topt, 30), g)
        assert np.all(np.diff(lo) > 0)
        # 최적 위: 감소, T_MAX 에서 0
        hi = P.mu_temp(np.linspace(topt, P.T_MAX + 3, 30), g)
        assert np.all(np.diff(hi) <= 1e-12)
        assert P.mu_temp(P.T_MAX, g) == pytest.approx(0.0)
    assert np.isnan(P.mu_temp(np.nan, "Microcystis"))
    # 모르는 속은 generic
    assert P.mu_temp(20.0, "other") == pytest.approx(P.mu_temp(20.0, "generic"))


# ---------------------------------------------------------------- 성장 기작 피처 누수
def _daily(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", "2024-12-31", freq="D")
    n = len(idx)
    d = pd.DataFrame(
        {
            "obs_date": idx,
            "wtemp": 15 + 12 * np.sin(np.linspace(0, np.pi, n)) + rng.normal(0, 0.5, n),
            "si": rng.uniform(2, 30, n),
            "ss": rng.uniform(0, 13, n),
            "fac_outflow": rng.uniform(10, 900, n),
            "fac_storage": rng.uniform(60, 95, n),
            "is_obs": (np.arange(n) % 7 == 0),
            "genus_obs": np.where(np.arange(n) % 14 == 0, "Microcystis", "Anabaena"),
        }
    )
    d.loc[d.index[::9], "wtemp"] = np.nan
    d.loc[d.index[::13], "fac_storage"] = 0.0  # 0 은 결측으로 본다
    d.loc[~d["is_obs"], "genus_obs"] = None
    return d


def _tamper(d: pd.DataFrame, as_of: date, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = d.copy()
    after = t["obs_date"] > pd.Timestamp(as_of)
    for c in ("wtemp", "si", "ss", "fac_outflow", "fac_storage"):
        t.loc[after, c] = rng.uniform(-1e4, 1e4, after.sum())
    t.loc[after, "genus_obs"] = "Oscillatoria"
    t.loc[after, "is_obs"] = True
    return t.drop(index=t.index[after][::2]).reset_index(drop=True)


def _same(a: dict[str, float], b: dict[str, float]) -> bool:
    if a.keys() != b.keys():
        return False
    for k in a:
        x, y = a[k], b[k]
        if (isinstance(x, float) and math.isnan(x)) and (isinstance(y, float) and math.isnan(y)):
            continue
        if x != pytest.approx(y, rel=1e-12, abs=1e-12):
            return False
    return True


@pytest.mark.parametrize("as_of", AS_OFS)
@pytest.mark.parametrize("seed", [1, 2])
def test_mech_features_no_leakage(as_of: date, seed: int) -> None:
    d = _daily()
    a = P.make_mech_features(d, as_of, "HP", 7.0)
    b = P.make_mech_features(_tamper(d, as_of, seed), as_of, "HP", 7.0)
    assert set(a) == set(P.MECH_COLS)
    assert _same(a, b)
    assert all(np.isfinite(v) for v in a.values())


def test_mech_features_definitions() -> None:
    d = _daily()
    as_of = date(2024, 7, 15)
    out = P.make_mech_features(d, as_of, "HP", 7.0)
    w = d[
        (d["obs_date"] > pd.Timestamp(as_of) - pd.Timedelta(days=7)) & (d["obs_date"] <= pd.Timestamp(as_of))
    ]
    assert len(w) == 7
    assert out["si_mean7"] == pytest.approx(w["si"].mean())
    assert out["ss_mean7"] == pytest.approx(w["ss"].mean())
    st = d[d["obs_date"] <= pd.Timestamp(as_of)]["fac_storage"]
    v_last = st[st > 0].iloc[-1]
    assert out["dil_rate7"] == pytest.approx(w["fac_outflow"].mean() * 86400 / (v_last * 1e6))
    # 마지막 측정의 우점 속은 Microcystis 또는 Anabaena — mu_dom7 은 둘 중 하나와 같다
    assert out["mu_dom7"] in (pytest.approx(out["mu_micro7"]), pytest.approx(out["mu_dolicho7"]))
    tau = 1 / out["dil_rate7"]
    assert out["growth_pot_h"] == pytest.approx(out["mu_dom7"] * min(tau, 7.0) / math.log(10))


def test_mech_features_before_data_is_nan() -> None:
    out = P.make_mech_features(_daily(), date(2023, 12, 1), "HP", 7.0)
    assert all(math.isnan(v) for v in out.values())


# ---------------------------------------------------------------- 약화 열·피처 묶음
def _sample_frame(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for y in range(2016, 2026):
        for d in pd.date_range(f"{y}-04-01", f"{y}-10-31", freq="7D"):
            for s in ("HP", "DCHN"):
                rows.append(
                    {"station_id": s, "base_date": d.date(), "target_date": (d + pd.Timedelta(days=7)).date()}
                )
    df = pd.DataFrame(rows)
    n = len(df)
    t0 = rng.uniform(0, 5, n)
    x1 = rng.normal(size=n)
    df["cell_log_t0"] = t0
    df["cell_max_4w"] = t0 + rng.uniform(0, 1, n)
    df["cell_log_lag1w"] = t0 + rng.normal(0, 0.5, n)
    df["cell_log_lag3w"] = t0 + rng.normal(0, 0.8, n)
    df["x1"] = x1
    df["x2"] = rng.normal(size=n)
    df.loc[df.index[::5], "x2"] = np.nan
    df["dominant_genus"] = rng.choice(["Microcystis", "Anabaena", "none"], n)
    df["target_log"] = np.clip(t0 + 0.4 * x1 + rng.normal(0, 0.3, n), 0, None)
    df["target_cells"] = 10 ** df["target_log"] - 1
    return df


def test_weak_frame_rowwise() -> None:
    df = _sample_frame()
    w = P.weak_frame(df)
    assert list(w.columns) == list(P.WEAK_REL)
    assert np.allclose(w["cell_max4w_rel"], df["cell_max_4w"] - df["cell_log_t0"])
    assert np.allclose(w["cell_chg_1w"], df["cell_log_t0"] - df["cell_log_lag1w"])
    # 다른 행을 바꿔도 행 0 은 같다
    t = df.copy()
    t.loc[1:, ["cell_max_4w", "cell_log_lag1w", "cell_log_lag3w", "cell_log_t0"]] = 99.0
    assert np.allclose(P.weak_frame(t).iloc[0], w.iloc[0])


def _fake_feats(df: pd.DataFrame) -> P.Feats:
    rng = np.random.default_rng(3)
    f = P.Feats.__new__(P.Feats)
    f.f2 = pd.DataFrame(
        {"up1_cell_log": rng.normal(size=len(df)), "up1_diff": rng.normal(size=len(df))}, index=df.index
    )
    m = pd.DataFrame(rng.normal(size=(len(df), len(P.MECH_COLS))), index=df.index, columns=list(P.MECH_COLS))
    m.iloc[::4, 0] = np.nan
    f.mech = m
    f.weak = P.weak_frame(df)
    return f


def test_feature_sets_and_controls() -> None:
    df = _sample_frame()
    feats = _fake_feats(df)
    _, c_mech = P.fs_frame(df, feats, "mech", 11)
    dk, c_k = P.fs_frame(df, feats, "mechK", 11)
    _, c_k2 = P.fs_frame(df, feats, "mechK", 22)
    assert len(c_mech) == len(c_k)
    ctrl = [c for c in c_k if c.startswith("ctrl_rnd_")]
    assert len(ctrl) == len(P.MECH_COLS)
    # 대조군은 같은 결측 위치
    assert (dk[ctrl].isna().to_numpy() == feats.mech.isna().to_numpy()).all()
    assert c_k == c_k2
    _, c_w = P.fs_frame(df, feats, "weak", 11)
    assert not set(P.WEAK_DROP) & set(c_w)
    assert set(P.WEAK_REL) <= set(c_w) and "cell_log_t0" in c_w
    _, c_w0 = P.fs_frame(df, feats, "weak0", 11)
    assert "cell_log_t0" not in c_w0


# ---------------------------------------------------------------- Δ 구성원 OOF 의 폴드 격리
COLS = ["cell_log_t0", "x1", "x2", "dominant_genus"]


@pytest.mark.parametrize("model", ["gbm", "gam", "lin"])
def test_member_oof_fold_isolation(model: str) -> None:
    df = _sample_frame()
    years = pd.to_datetime(df["base_date"]).dt.year.to_numpy()
    a = P.member_oof(df, COLS, model, 11)
    # 2025 타깃을 바꿔도 모든 OOF(2020~2025)와 smear 가 같다
    t = df.copy()
    t.loc[years == 2025, "target_log"] = 6.5
    t["target_cells"] = 10 ** t["target_log"] - 1
    b = P.member_oof(t, COLS, model, 11)
    for k in ("lp", "smear", "smear_fac"):
        assert np.allclose(a[k], b[k], equal_nan=True), k
    # 2023 타깃을 바꾸면 2020~2023 OOF 와 그 연도 smear 는 그대로
    t = df.copy()
    t.loc[years == 2023, "target_log"] = 0.0
    t["target_cells"] = 10 ** t["target_log"] - 1
    c = P.member_oof(t, COLS, model, 11)
    m = years <= 2023
    for k in ("lp", "smear", "smear_fac"):
        assert np.allclose(a[k][m], c[k][m], equal_nan=True), k
    # 2020 이전 행은 예측하지 않는다
    assert np.isnan(a["lp"][years < 2020]).all()
    assert np.isfinite(a["lp"][years >= 2020]).all()


def test_member_delta_restores_t0() -> None:
    """Δ = 상수 0.5 인 자료에서 Δ 구성원은 t0 + 0.5 를 복원한다(GAM, 로그 0~7 범위 안)."""
    df = _sample_frame()
    df["target_log"] = df["cell_log_t0"] + 0.5
    df["target_cells"] = 10 ** df["target_log"] - 1
    o = P.member_oof(df, COLS, "gam", 11)
    years = pd.to_datetime(df["base_date"]).dt.year.to_numpy()
    m = years >= 2020
    assert np.allclose(o["lp"][m], df["cell_log_t0"].to_numpy()[m] + 0.5, atol=1e-3)
    # 수준 타깃은 t0 를 더하지 않는다
    lv = P.member_oof(df, COLS, "gam", 11, target="level")
    assert np.allclose(lv["lp"][m], df["target_log"].to_numpy()[m], atol=0.05)
