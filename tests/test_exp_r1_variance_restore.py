"""R1(EXP-004) 분산 반영 원단위 복원 — 변환식·제약 선택·연도 확장 누수·2026 가드 테스트(모델 학습 없음)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from algaecast.exp import r1_variance_restore as R

YEARS = range(2019, 2026)
SITES = ("CS", "DCHN", "GJGR", "HP", "MGMR")


def _synthetic(seed: int = 0, per_site_year: int = 12) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    """harness.load_base() 형식 축소판 + run_members 형식 예측(로그정규 잡음)."""
    rng = np.random.default_rng(seed)
    rows = [
        (s, pd.Timestamp(f"{y}-06-01") + pd.Timedelta(days=int(d)))
        for y in YEARS
        for s in SITES
        for d in rng.integers(0, 120, per_site_year)
    ]
    df = pd.DataFrame(rows, columns=["station_id", "base_date"])
    df["base_date"] = df["base_date"].dt.date
    n = len(df)
    z = rng.normal(2.5, 1.0, n)
    df["target_cells"] = np.clip(10 ** (z + rng.normal(0, 0.7, n)) - 1, 0, None)
    c1_log = z + rng.normal(0, 0.3, n)
    width = 0.5 + 0.3 * rng.random(n)
    preds = {
        "c1_log": c1_log,
        "c1": (10**c1_log - 1) * 1.4,
        "c1_none": 10**c1_log - 1,
        "c3": 10 ** (z + rng.normal(0, 0.3, n)) - 1,
        "c2": 10 ** (z + rng.normal(0, 0.4, n)) - 1,
        "q10": 10 ** (z - width) - 1,
        "q50": 10**z - 1,
        "q90": 10 ** (z + width) - 1,
    }
    return df, {k: v if k == "c1_log" else np.clip(v, 0, None) for k, v in preds.items()}


# ---------------------------------------------------------------- 변환식
def test_sigma_from_quantiles() -> None:
    s = R.sigma_from_quantiles(np.array([9.0]), np.array([999.0]))
    assert s[0] == pytest.approx(2.0 / (2 * R.Z90))
    assert R.sigma_from_quantiles(np.array([100.0]), np.array([10.0]))[0] == 0.0  # 교차는 0


def test_lognormal_mean_matches_monte_carlo() -> None:
    rng = np.random.default_rng(42)
    mu, sig, k = 2.0, 0.4, 1.3
    draws = 10 ** rng.normal(mu, k * sig, 2_000_000) - 1
    got = R.lognormal_mean(np.array([mu]), np.array([sig]), k)[0]
    assert got == pytest.approx(draws.mean(), rel=0.01)


def test_identity_parameters() -> None:
    p = np.array([0.5, 2.0, 3.5, 5.0])
    np.testing.assert_allclose(R.lognormal_mean(p, np.full(4, 0.5), 0.0), R.from_log(p))
    np.testing.assert_allclose(R.stretch(p, 2.7, 1.0), p)
    np.testing.assert_allclose(R.hinge(p, 3.0, 1.0), p)
    np.testing.assert_allclose(R.hinge(p, 3.0, 1.3)[:2], p[:2])  # m 아래는 그대로
    assert R.hinge(p, 3.0, 1.3)[3] == pytest.approx(5.0 + 0.3 * 2.0)


def test_simplex_grid() -> None:
    w = R.simplex_grid(3, 0.1)
    assert len(w) == 66
    assert (w >= 0).all()
    np.testing.assert_allclose(w.sum(axis=1), 1.0)


def test_select_params_respects_log_constraint() -> None:
    obs = np.array([10.0, 100.0, 1000.0, 100000.0])
    ref = obs * 0.9
    theta = np.array([[0.0], [1.0]])
    cands = np.vstack([ref, np.array([1e3, 1e3, 1e4, 1e5])])  # 두 번째: 원단위 MSE 작지만 log 오차 큼
    assert R.select_params(theta, cands, obs, ref, None)[0] == 1.0
    assert R.select_params(theta, cands, obs, ref, 0.005)[0] == 0.0
    assert R.select_params(theta[1:], cands[1:], obs, ref, 0.005) is None


# ---------------------------------------------------------------- 연도 확장 적합 누수
LEAK_KEYS = (
    "s_smear",
    "b_lognorm",
    "c_lognorm_q50_c",
    "d_stretch_m",
    "e_stretch_site_c",
    "f_c1_lognorm",
    "f_c1_lognorm_raw",
    "g_hinge_c",
    "h_gated",
    "r_combine",
    "r_combine_c",
    "r_nnls_free",
    "rh_gated_c",
)


@pytest.mark.parametrize("key", LEAK_KEYS)
@pytest.mark.parametrize("cut", [2021, 2023, 2024])
def test_no_future_information(key: str, cut: int) -> None:
    """연도 cut 이상 관측과 cut 초과 연도의 예측을 바꿔도 cut 이하 연도의 후처리 결과가 같아야 한다."""
    df, preds = _synthetic()
    years = pd.to_datetime(df["base_date"]).dt.year.to_numpy()
    out0, _ = R.run_variant(df, preds, key)

    rng = np.random.default_rng(7)
    df2 = df.copy()
    fut_obs = years >= cut
    df2.loc[fut_obs, "target_cells"] = 10 ** rng.uniform(0, 6, fut_obs.sum())
    preds2 = {k: v.copy() for k, v in preds.items()}
    fut = years > cut
    for k in preds2:
        if k == "c1_log":
            preds2[k][fut] = rng.uniform(0, 6, fut.sum())
        else:
            preds2[k][fut] = 10 ** rng.uniform(0, 6, fut.sum())
    out1, _ = R.run_variant(df2, preds2, key)

    keep = (years >= 2020) & (years <= cut)
    np.testing.assert_allclose(out1[keep], out0[keep], rtol=0, atol=1e-9)
    assert np.isnan(out0[years < 2020]).all()  # 2019 이하는 예측 없음
    # 같은 값이 되지 않는지(테스트가 무의미하지 않은지) — 바뀐 연도는 대개 달라진다
    if key not in ("c_lognorm_q50_c",):
        assert not np.allclose(out1[years > cut], out0[years > cut]) or cut == 2025


def test_2020_equals_v1_ensemble() -> None:
    """적합 자료가 없는 2020 은 입력 앙상블(v1 방식) 그대로."""
    df, preds = _synthetic(seed=3)
    years = pd.to_datetime(df["base_date"]).dt.year.to_numpy()
    ens = R._ens(df, preds)
    for key in ("b_lognorm", "r_combine", "rh_gated_c", "e_stretch_site_c"):
        out, _ = R.run_variant(df, preds, key)
        np.testing.assert_allclose(out[years == 2020], ens[years == 2020])


def test_postprocess_uses_chosen_variant() -> None:
    df, preds = _synthetic(seed=5)
    assert R.CHOSEN in R.VARIANTS
    np.testing.assert_allclose(R.postprocess(df, preds), R.run_variant(df, preds, R.CHOSEN)[0])


def test_rejects_2026_rows() -> None:
    df, preds = _synthetic(seed=1)
    df.loc[df.index[-1], "base_date"] = pd.Timestamp("2026-06-01").date()
    with pytest.raises(RuntimeError):
        R.run_variant(df, preds, R.CHOSEN)
