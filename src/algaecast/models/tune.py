"""Optuna 튜닝 (T4-b): TPE + MedianPruner, 목적 rmse_log 또는 복합 J.

결과 → data/processed/optuna/<study>.json

사용: python -m algaecast.models.tune --variant log_w --objective rmse_log --trials 200 --timeout 3600
     [--feature-set perc75] [--strategy S1] [--bias smearing]
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime

import numpy as np
import optuna
import pandas as pd

from algaecast.config import DATA_DIR
from algaecast.eval.metrics import compute_all
from algaecast.models import data as D
from algaecast.models.cv import year_folds
from algaecast.models.train import (
    SEED,
    Fitted,
    VariantSpec,
    apply_bias,
    feature_sets,
    fit_isotonic,
    fit_predict,
)

log = logging.getLogger(__name__)
OUT_DIR = DATA_DIR / "processed" / "optuna"


def suggest_params(trial: optuna.Trial) -> dict:
    return {
        "n_estimators": trial.suggest_int("n_estimators", 200, 1500, step=100),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
        "num_leaves": trial.suggest_int("num_leaves", 7, 127, log=True),
        "max_depth": trial.suggest_int("max_depth", 3, 12),
        "min_child_samples": trial.suggest_int("min_child_samples", 5, 80, log=True),
        "feature_fraction": trial.suggest_float("feature_fraction", 0.4, 1.0),
        "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
        "bagging_freq": 1,
        "lambda_l1": trial.suggest_float("lambda_l1", 1e-3, 10.0, log=True),
        "lambda_l2": trial.suggest_float("lambda_l2", 1e-3, 10.0, log=True),
        "min_split_gain": trial.suggest_float("min_split_gain", 0.0, 0.5),
    }


def spec_from_trial(trial: optuna.Trial, variant: str) -> VariantSpec:
    p = suggest_params(trial)
    if variant == "log_w":
        return VariantSpec("log_w", alpha=trial.suggest_float("alpha", 0.0, 1.5), params=p)
    if variant == "tweedie":
        obj = trial.suggest_categorical("objective_raw", ["tweedie", "poisson"])
        vp = trial.suggest_float("variance_power", 1.2, 1.9) if obj == "tweedie" else 1.5
        return VariantSpec("tweedie", variance_power=vp, objective_raw=obj, params=p)
    if variant == "hurdle":
        cls = {**p, "n_estimators": trial.suggest_int("cls_n_estimators", 100, 800, step=100)}
        return VariantSpec("hurdle", params=p, cls_params=cls)
    if variant == "ens":
        return VariantSpec(
            "ens",
            alpha=trial.suggest_float("alpha", 0.0, 1.5),
            variance_power=trial.suggest_float("variance_power", 1.2, 1.9),
            w_c1=trial.suggest_float("w_c1", 0.2, 0.8),
            params=p,
        )
    raise ValueError(variant)


def spec_from_params(params: dict, variant: str) -> VariantSpec:
    keys = [
        "n_estimators",
        "learning_rate",
        "num_leaves",
        "max_depth",
        "min_child_samples",
        "feature_fraction",
        "bagging_fraction",
        "lambda_l1",
        "lambda_l2",
        "min_split_gain",
    ]
    p = {k: params[k] for k in keys if k in params}
    p["bagging_freq"] = 1
    sp = VariantSpec(variant, params=p)
    sp.alpha = float(params.get("alpha", 0.0))
    sp.variance_power = float(params.get("variance_power", 1.5))
    sp.objective_raw = str(params.get("objective_raw", "tweedie"))
    sp.w_c1 = float(params.get("w_c1", 0.5))
    if variant == "hurdle":
        sp.cls_params = {**p, "n_estimators": int(params.get("cls_n_estimators", 300))}
    return sp


def cv_score(
    df: pd.DataFrame, cols: list[str], spec: VariantSpec, bias: str, trial: optuna.Trial | None = None
) -> dict[str, float]:
    """F1~F5 (Final 제외) 평균 rmse_log / r2_raw.

    isotonic 은 이전 폴드 OOF 로 적합. trial 이 있으면 폴드마다 report → pruning.
    """
    folds = year_folds(df, include_final=False)
    obs_all = df["target_cells"].to_numpy(dtype=float)
    oof_log = np.full(len(df), np.nan)
    rm, r2 = [], []
    for i, fo in enumerate(folds):
        tr, va = df.iloc[fo.train_idx], df.iloc[fo.valid_idx]
        f: Fitted = fit_predict(tr, va, cols, spec, seed=SEED)
        prev = ~np.isnan(oof_log)
        iso = (
            fit_isotonic(oof_log[prev], obs_all[prev])
            if bias == "isotonic" and prev.any() and f.log_pred is not None
            else None
        )
        pred = np.clip(np.nan_to_num(apply_bias(f, bias, iso), nan=0.0), 0, None)
        m = compute_all(va["target_cells"].to_numpy(dtype=float), pred)
        rm.append(m["rmse_log"])
        r2.append(m["r2_raw"] if np.isfinite(m["r2_raw"]) else -1.0)
        if f.log_pred is not None:
            oof_log[fo.valid_idx] = f.log_pred
        if trial is not None:
            trial.report(float(np.mean(rm)), step=i)
            if trial.should_prune():
                raise optuna.TrialPruned()
    return {"rmse_log": float(np.mean(rm)), "r2_raw": float(np.mean(r2))}


def objective_value(score: dict[str, float], objective: str) -> float:
    if objective == "rmse_log":
        return score["rmse_log"]
    if objective == "composite":
        return 0.5 * score["rmse_log"] / 0.83 + 0.5 * (1 - float(np.clip(score["r2_raw"], -1, 1)))
    raise ValueError(objective)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", default="log_w", choices=["log_w", "tweedie", "hurdle", "ens"])
    ap.add_argument("--objective", default="rmse_log", choices=["rmse_log", "composite"])
    ap.add_argument("--feature-set", default="perc75")
    ap.add_argument("--strategy", default="S1")
    ap.add_argument(
        "--bias", default="smearing", help="튜닝 중 원단위 지표에 쓸 보정 (none/smearing/isotonic)"
    )
    ap.add_argument("--trials", type=int, default=200)
    ap.add_argument("--timeout", type=int, default=3600, help="초")
    ap.add_argument("--name", default=None)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    df = D.load_train_valid(args.strategy)
    cols = feature_sets()[args.feature_set]
    name = args.name or f"{args.variant}_{args.objective}_{args.feature_set}_{args.strategy}"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    storage = f"sqlite:///{(OUT_DIR / (name + '.db')).as_posix()}"
    study = optuna.create_study(
        study_name=name,
        storage=storage,
        load_if_exists=True,
        direction="minimize",
        sampler=optuna.samplers.TPESampler(seed=SEED, multivariate=True),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=15, n_warmup_steps=2),
    )
    t0 = time.time()

    def obj(trial: optuna.Trial) -> float:
        spec = spec_from_trial(trial, args.variant)
        score = cv_score(df, cols, spec, args.bias, trial)
        trial.set_user_attr("rmse_log", score["rmse_log"])
        trial.set_user_attr("r2_raw", score["r2_raw"])
        return objective_value(score, args.objective)

    study.optimize(
        obj, n_trials=args.trials, timeout=args.timeout, gc_after_trial=True, show_progress_bar=False
    )
    done = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    top = sorted(done, key=lambda t: t.value)[:5]
    result = {
        "study": name,
        "variant": args.variant,
        "objective": args.objective,
        "feature_set": args.feature_set,
        "strategy": args.strategy,
        "bias": args.bias,
        "n_trials": len(study.trials),
        "n_complete": len(done),
        "n_pruned": sum(t.state == optuna.trial.TrialState.PRUNED for t in study.trials),
        "elapsed_min": round((time.time() - t0) / 60, 1),
        "finished_at": datetime.now().isoformat(timespec="minutes"),
        "best_value": study.best_value,
        "best_params": study.best_params,
        "best_attrs": study.best_trial.user_attrs,
        "top5": [
            {"number": t.number, "value": t.value, "params": t.params, "attrs": t.user_attrs} for t in top
        ],
    }
    out = OUT_DIR / f"{name}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    attrs = study.best_trial.user_attrs
    print(
        f"{name}: {len(done)} complete / {result['n_pruned']} pruned, best {study.best_value:.4f} "
        f"(rmse_log {attrs.get('rmse_log'):.4f}, r2_raw {attrs.get('r2_raw'):.3f}) → {out.name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
