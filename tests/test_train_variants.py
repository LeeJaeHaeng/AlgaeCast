"""T4-b: 변형 적합·보정·목적함수의 기본 계약 (합성 데이터, 네트워크·실데이터 없음)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from algaecast.eval import metrics as M
from algaecast.models import train as T
from algaecast.models.tune import objective_value, spec_from_params


def _df(n_years: int = 7, per_year: int = 40, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for yr in range(2019, 2019 + n_years):
        for k in range(per_year):
            x1, x2 = rng.uniform(0, 4), rng.uniform(5, 30)
            ylog = 0.8 * x1 + 0.05 * x2 + rng.normal(0, 0.3)
            rows.append(
                {
                    "station_id": "HP" if k % 2 else "CS",
                    "site_code": "x",
                    "base_date": date(yr, 4 + k % 8, 1 + k % 27),
                    "target_date": date(yr, 4 + k % 8, 1 + k % 27),
                    "horizon_days": 7.0,
                    "cell_log_t0": x1,
                    "wtemp_ma14": x2,
                    "dominant_genus": "Microcystis" if k % 3 else "none",
                    "target_log": ylog,
                    "target_cells": 10**ylog - 1,
                    "split": "train" if yr <= 2024 else "valid",
                }
            )
    return pd.DataFrame(rows)


COLS = ["cell_log_t0", "wtemp_ma14", "horizon_days", "dominant_genus"]


@pytest.mark.parametrize("kind", ["log_w", "tweedie", "hurdle", "ens"])
def test_variants_fit_and_predict_nonnegative(kind: str) -> None:
    df = _df()
    tr, va = df[df["split"] == "train"], df[df["split"] == "valid"]
    spec = T.VariantSpec(kind, alpha=0.5, params={**T.DEFAULT_PARAMS, "n_estimators": 50})
    f = T.fit_predict(tr, va, COLS, spec)
    assert len(f.raw) == len(va) and (f.raw >= 0).all() and np.isfinite(f.raw).all()
    if kind == "log_w":
        assert f.log_pred is not None and f.smear >= 1.0 - 1e-9
        assert np.allclose(T.apply_bias(f, "smearing", None), f.raw * f.smear)
        assert np.allclose(T.apply_bias(f, "isotonic", None), f.raw)  # iso 없으면 미보정
    if kind == "hurdle":
        assert f.p_over is not None and ((f.p_over >= 0) & (f.p_over <= 1)).all()


def test_run_cv_shapes_and_isotonic_only_from_past_folds() -> None:
    df = _df()
    spec = T.VariantSpec("log_w", alpha=0.3, params={**T.DEFAULT_PARAMS, "n_estimators": 50})
    res = T.run_cv(df, COLS, spec)
    assert set(res.folds["bias"]) == set(T.BIAS_METHODS)
    assert set(res.folds["fold"]) == {"F1", "F2", "F3", "F4", "F5", "Final"}
    f1 = res.folds[(res.folds["fold"] == "F1")]
    # F1 은 이전 OOF 가 없어 isotonic == none
    assert f1[f1["bias"] == "isotonic"]["rmse_log"].iloc[0] == pytest.approx(
        f1[f1["bias"] == "none"]["rmse_log"].iloc[0]
    )
    s = T.summarize_cv(res, "smearing")
    assert {"cv_rmse_log", "cv_r2_raw", "cv_r2_pearson_raw", "final_nse_raw"} <= set(s)
    assert res.final_iso is not None


def test_composite_objective_and_metric_definitions() -> None:
    assert T.composite_objective(0.83, 1.0) == pytest.approx(0.5)
    assert T.composite_objective(0.83, -5.0) == pytest.approx(0.5 + 1.0)  # r2 클리핑 −1
    assert objective_value({"rmse_log": 0.83, "r2_raw": 0.0}, "composite") == pytest.approx(1.0)
    obs = np.array([1.0, 2.0, 3.0, 4.0])
    pred = 2 * obs + 10  # 완전 상관이지만 편향·척도 오차
    assert M.r2_pearson_raw(obs, pred) == pytest.approx(1.0)
    assert M.r2_raw(obs, pred) < 0 and M.nse_raw(obs, pred) == pytest.approx(M.r2_raw(obs, pred))
    assert "r2_pearson_raw" in M.compute_all(obs, pred)


def test_spec_from_params_roundtrip_and_feature_sets() -> None:
    sp = spec_from_params(
        {
            "n_estimators": 300,
            "learning_rate": 0.05,
            "alpha": 0.7,
            "variance_power": 1.4,
            "objective_raw": "poisson",
            "w_c1": 0.6,
        },
        "ens",
    )
    assert (
        sp.kind == "ens"
        and sp.alpha == 0.7
        and sp.objective_raw == "poisson"
        and sp.params["bagging_freq"] == 1
    )
    fs = T.feature_sets()
    assert set(fs) == {"perc75", "perc100", "vif58"} and len(fs["perc100"]) <= len(fs["perc75"]) <= len(
        fs["vif58"]
    )
    assert "cell_log_t0" in fs["perc100"] and "horizon_days" in fs["perc75"]
