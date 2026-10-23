"""분위 회귀 q10/q50/q90 (T4-c): C1(log 타깃) 파라미터 고정, objective=quantile 로 alpha 만 변경."""

from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd

from algaecast.models import data as D
from algaecast.models.cv import fold_frames, year_folds
from algaecast.models.train import SEED, VariantSpec, _lgb_params, _prep, to_cells

QUANTILES = (0.1, 0.5, 0.9)


def fit_quantiles(
    tr: pd.DataFrame, cols: list[str], spec: VariantSpec, seed: int = SEED
) -> dict[float, lgb.LGBMRegressor]:
    nums, cats = D.numeric_and_categorical(cols)
    Xt = _prep(tr[cols], cats)
    y = tr["target_log"].to_numpy(dtype=float)
    w = 1.0 + spec.alpha * y
    out = {}
    for q in QUANTILES:
        m = lgb.LGBMRegressor(**_lgb_params(spec.params, seed, objective="quantile", alpha=q))
        m.fit(Xt, y, sample_weight=w, categorical_feature=cats or "auto")
        m._prep_ref = Xt  # type: ignore[attr-defined]
        out[q] = m
    return out


def predict_quantiles(
    models: dict[float, lgb.LGBMRegressor], va: pd.DataFrame, cols: list[str]
) -> dict[str, np.ndarray]:
    nums, cats = D.numeric_and_categorical(cols)
    ref = next(iter(models.values()))._prep_ref  # type: ignore[attr-defined]
    Xv = _prep(va[cols], cats, ref=ref)
    lp = {q: np.asarray(m.predict(Xv), dtype=float) for q, m in models.items()}
    lo, mid, hi = lp[0.1], lp[0.5], lp[0.9]
    lo, hi = np.minimum(lo, hi), np.maximum(lo, hi)  # 교차 정렬
    mid = np.clip(mid, lo, hi)
    return {"q10": to_cells(lo), "q50": to_cells(mid), "q90": to_cells(hi)}


def cv_quantiles(
    df: pd.DataFrame, cols: list[str], spec: VariantSpec, include_final: bool = True
) -> dict[str, np.ndarray]:
    out = {k: np.full(len(df), np.nan) for k in ("q10", "q50", "q90")}
    for fo in year_folds(df, include_final=include_final):
        tr, va = fold_frames(df, fo)
        models = fit_quantiles(tr, cols, spec)
        pr = predict_quantiles(models, va, cols)
        for k in out:
            out[k][fo.valid_idx] = pr[k]
    return out
