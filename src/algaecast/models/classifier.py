"""경계(10,000 cells/mL) 초과 분류기 (T4-c).

타깃 두 종류
- (a) ``over_target``: target_date 측정값 ≥ 10,000 (대회 매칭 그대로)
- (b) ``over_window``: base_date 이후 +4~+10일 창의 **어느 측정이든** ≥ 10,000
  (운영 정의; 측정 원값은 interim 달력의 is_obs 행)
LightGBM binary + scale_pos_weight, Optuna 목적 = CV 평균 PR-AUC(average precision).
임계값은 CV OOF 에서 F1 최대 지점으로
고정하고 2025 Final 은 그 임계로만 평가한다(2025 로 임계를 정하지 않음).
"""

from __future__ import annotations

import logging

import lightgbm as lgb
import numpy as np
import optuna
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, f1_score, precision_score, recall_score

from algaecast.config import DATA_DIR
from algaecast.models import data as D
from algaecast.models.cv import Fold, year_folds
from algaecast.models.train import SEED, _lgb_params, _prep

log = logging.getLogger(__name__)
THRESH_10K = 10_000.0
WINDOW = (4, 10)
INTERIM = DATA_DIR / "interim"


# ---------------------------------------------------------------- 타깃
def add_targets(df: pd.DataFrame) -> pd.DataFrame:
    """over_target(a)·over_window(b) 컬럼 추가.

    (b) 는 지점별 interim 달력의 측정 원값으로 계산 — test 행 없음(로더 보장).
    """
    d = df.copy()
    d["over_target"] = (d["target_cells"] >= THRESH_10K).astype(int)
    win = np.zeros(len(d), dtype=int)
    for sid, g in d.groupby("station_id", observed=True):
        daily = pd.read_parquet(
            INTERIM / f"daily_{sid}_S1.parquet", columns=["obs_date", "is_obs", "cells_obs"]
        )
        obs = daily[daily["is_obs"].astype(bool)].copy()
        obs["obs_date"] = pd.to_datetime(obs["obs_date"])
        od = obs["obs_date"].to_numpy()
        oc = obs["cells_obs"].to_numpy(dtype=float)
        for i, b in zip(g.index, pd.to_datetime(g["base_date"]).to_numpy(), strict=True):
            lo, hi = b + np.timedelta64(WINDOW[0], "D"), b + np.timedelta64(WINDOW[1], "D")
            m = (od >= lo) & (od <= hi)
            win[d.index.get_loc(i)] = (
                int(np.nanmax(oc[m]) >= THRESH_10K) if m.any() and np.isfinite(oc[m]).any() else 0
            )
    d["over_window"] = win
    return d


# ---------------------------------------------------------------- 모델
def fit_clf(
    tr: pd.DataFrame, cols: list[str], target: str, params: dict, seed: int = SEED
) -> lgb.LGBMClassifier:
    nums, cats = D.numeric_and_categorical(cols)
    Xt = _prep(tr[cols], cats)
    y = tr[target].to_numpy(dtype=int)
    pos = max(int(y.sum()), 1)
    spw = params.get("spw_mult", 1.0) * (len(y) - pos) / pos
    p = {k: v for k, v in params.items() if k != "spw_mult"}
    m = lgb.LGBMClassifier(**_lgb_params(p, seed, objective="binary", scale_pos_weight=spw))
    m.fit(Xt, y, categorical_feature=cats or "auto")
    m._prep_ref = Xt  # type: ignore[attr-defined]
    return m


def predict_proba(m: lgb.LGBMClassifier, va: pd.DataFrame, cols: list[str]) -> np.ndarray:
    nums, cats = D.numeric_and_categorical(cols)
    Xv = _prep(va[cols], cats, ref=m._prep_ref)  # type: ignore[attr-defined]
    return np.asarray(m.predict_proba(Xv)[:, 1], dtype=float)


def cv_proba(
    df: pd.DataFrame, cols: list[str], target: str, params: dict, seed: int = SEED, include_final: bool = True
) -> tuple[np.ndarray, list[Fold]]:
    folds = year_folds(df, include_final=include_final)
    oof = np.full(len(df), np.nan)
    for fo in folds:
        m = fit_clf(df.iloc[fo.train_idx], cols, target, params, seed)
        oof[fo.valid_idx] = predict_proba(m, df.iloc[fo.valid_idx], cols)
    return oof, folds


def best_threshold(y: np.ndarray, p: np.ndarray) -> float:
    """OOF 에서 F1 최대 임계 (0.05~0.95 격자)."""
    grid = np.linspace(0.05, 0.95, 91)
    f1s = [f1_score(y, (p >= t).astype(int), zero_division=0) for t in grid]
    return float(grid[int(np.argmax(f1s))])


def cls_metrics(y: np.ndarray, p: np.ndarray, thr: float) -> dict[str, float]:
    ok = np.isfinite(p)
    y, p = y[ok], p[ok]
    pred = (p >= thr).astype(int)
    return {
        "n": int(len(y)),
        "n_pos": int(y.sum()),
        "pr_auc": float(average_precision_score(y, p)) if y.sum() and (1 - y).sum() else float("nan"),
        "brier": float(brier_score_loss(y, np.clip(p, 0, 1))),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "thr": thr,
    }


# ---------------------------------------------------------------- 튜닝
def suggest_clf_params(trial: optuna.Trial) -> dict:
    return {
        "n_estimators": trial.suggest_int("n_estimators", 100, 1000, step=50),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
        "num_leaves": trial.suggest_int("num_leaves", 7, 63, log=True),
        "max_depth": trial.suggest_int("max_depth", 3, 10),
        "min_child_samples": trial.suggest_int("min_child_samples", 5, 80, log=True),
        "feature_fraction": trial.suggest_float("feature_fraction", 0.4, 1.0),
        "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
        "bagging_freq": 1,
        "lambda_l1": trial.suggest_float("lambda_l1", 1e-3, 10.0, log=True),
        "lambda_l2": trial.suggest_float("lambda_l2", 1e-3, 10.0, log=True),
        "spw_mult": trial.suggest_float("spw_mult", 0.3, 2.0),
    }


def tune_clf(
    df: pd.DataFrame, cols: list[str], target: str, n_trials: int = 150, timeout: int = 1500
) -> dict:
    """CV(F1~F5) 평균 PR-AUC 최대화."""
    y_all = df[target].to_numpy(dtype=int)
    folds = year_folds(df, include_final=False)

    def obj(trial: optuna.Trial) -> float:
        params = suggest_clf_params(trial)
        aps = []
        for i, fo in enumerate(folds):
            m = fit_clf(df.iloc[fo.train_idx], cols, target, params)
            p = predict_proba(m, df.iloc[fo.valid_idx], cols)
            yv = y_all[fo.valid_idx]
            aps.append(average_precision_score(yv, p) if yv.sum() else 0.0)
            trial.report(float(np.mean(aps)), step=i)
            if trial.should_prune():
                raise optuna.TrialPruned()
        return -float(np.mean(aps))

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        direction="minimize",
        sampler=optuna.samplers.TPESampler(seed=SEED, multivariate=True),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=15, n_warmup_steps=2),
    )
    study.optimize(obj, n_trials=n_trials, timeout=timeout, gc_after_trial=True)
    best = {**study.best_params, "bagging_freq": 1}
    return {
        "params": best,
        "cv_pr_auc": -study.best_value,
        "n_complete": sum(t.state.name == "COMPLETE" for t in study.trials),
        "n_trials": len(study.trials),
    }
