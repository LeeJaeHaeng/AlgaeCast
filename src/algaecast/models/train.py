"""LightGBM 학습 코어 (T4-b): 변형 C1~C4, 역변환 편향 보정 3종, CV/Final 평가.

변형
- C1 ``log_w``: log10(y+1) 타깃, 샘플 가중치 w = 1 + α·log10(y+1)
- C2 ``tweedie``: 원단위 타깃, objective=tweedie(variance_power) 또는 poisson
- C3 ``hurdle``: 출현(>1,000) 분류기 × 양수(>1,000) 조건부 log 회귀 → E[y] = p·E[y|>1k] + (1−p)·E[y|≤1k]
- C4 ``ens``: C1·C2 예측(원단위) 평균(가중 w_c1)
역변환 보정(log 모델): ``none`` 10^ŷ−1 / ``smearing`` Duan(학습 잔차 10^e 평균) /
``isotonic`` CV OOF(과거 폴드)로 적합.
데이터는 models.data 로더만 사용(test 타깃 접근 불가).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml
from sklearn.isotonic import IsotonicRegression

from algaecast.config import CONFIG_DIR
from algaecast.eval.metrics import compute_all
from algaecast.models import data as D
from algaecast.models.cv import REPORT_METRICS, Fold, year_folds

log = logging.getLogger(__name__)
SEED = int(yaml.safe_load((CONFIG_DIR / "seed.yaml").read_text(encoding="utf-8"))["seed"])
LOG_CAP = 7.0
HURDLE_THRESHOLD = 1000.0
BIAS_METHODS = ("none", "smearing", "isotonic")
DEFAULT_PARAMS = {
    "n_estimators": 600,
    "learning_rate": 0.03,
    "num_leaves": 31,
    "min_child_samples": 20,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l1": 0.0,
    "lambda_l2": 1.0,
    "max_depth": -1,
}


@dataclass
class VariantSpec:
    kind: str = "log_w"  # log_w | tweedie | hurdle | ens
    alpha: float = 0.0  # C1 가중치
    variance_power: float = 1.5  # C2 (1 < p < 2); poisson 이면 objective='poisson'
    objective_raw: str = "tweedie"  # tweedie | poisson
    w_c1: float = 0.5  # C4 가중
    params: dict = field(default_factory=lambda: dict(DEFAULT_PARAMS))
    cls_params: dict = field(default_factory=lambda: dict(DEFAULT_PARAMS))


# ---------------------------------------------------------------- 피처 세트
def feature_sets() -> dict[str, list[str]]:
    cfg = yaml.safe_load((CONFIG_DIR / "features.yaml").read_text(encoding="utf-8"))
    sel = list(cfg["selected"])
    ex = cfg.get("excluded", {})
    vif58 = sorted(set(sel) | {k for k, v in ex.items() if str(v).startswith("Boruta rejected")})
    perc100 = [
        "cell_log_t0", "cell_max_4w", "cell_log_lag1w", "wtemp_minus_site_thresh", "ta_degree_days20",
        "wtemp_ma14",
        "rn_sum30", "consecutive_over_1k", "season_day", "inflow_t0", "weir_outflow_ma7", "horizon_days",
        "dominant_genus", "facility_type", "basin",
    ]  # fmt: skip  # T3-c 1차 실행(perc 100) 생존 피처 + 보호 horizon_days
    return {"perc75": sel, "perc100": [c for c in perc100 if c in vif58 or c in sel], "vif58": vif58}


def _prep(X: pd.DataFrame, cats: list[str], ref: pd.DataFrame | None = None) -> pd.DataFrame:
    X = X.copy()
    for c in cats:
        if ref is None:
            X[c] = X[c].astype(str).astype("category")
        else:
            X[c] = pd.Categorical(X[c].astype(str), categories=ref[c].cat.categories)
    return X


def _lgb_params(p: dict, seed: int, **extra: object) -> dict:
    out = {**p, "random_state": seed, "verbose": -1, "n_jobs": 4}
    out.update(extra)
    return out


def to_cells(log_pred: np.ndarray) -> np.ndarray:
    return np.clip(10 ** np.clip(log_pred, 0, LOG_CAP) - 1, 0, None)


# ---------------------------------------------------------------- 모델 적합
class Fitted:
    """한 폴드의 적합 결과: log 예측(있으면)과 원단위 예측, smearing 계수."""

    def __init__(
        self, raw: np.ndarray, log_pred: np.ndarray | None, smear: float, p_over: np.ndarray | None = None
    ) -> None:
        self.raw = raw
        self.log_pred = log_pred
        self.smear = smear
        self.p_over = p_over


def fit_predict(
    tr: pd.DataFrame, va: pd.DataFrame, cols: list[str], spec: VariantSpec, seed: int = SEED
) -> Fitted:
    nums, cats = D.numeric_and_categorical(cols)
    Xt = _prep(tr[cols], cats)
    Xv = _prep(va[cols], cats, ref=Xt)
    ylog = tr["target_log"].to_numpy(dtype=float)
    yraw = tr["target_cells"].to_numpy(dtype=float)
    if spec.kind == "log_w":
        w = 1.0 + spec.alpha * ylog
        m = lgb.LGBMRegressor(**_lgb_params(spec.params, seed, objective="regression"))
        m.fit(Xt, ylog, sample_weight=w, categorical_feature=cats or "auto")
        lp = np.asarray(m.predict(Xv), dtype=float)
        resid = ylog - m.predict(Xt)
        smear = float(np.mean(10**resid))
        return Fitted(to_cells(lp), lp, smear)
    if spec.kind == "tweedie":
        extra = {"objective": spec.objective_raw}
        if spec.objective_raw == "tweedie":
            extra["tweedie_variance_power"] = spec.variance_power
        m = lgb.LGBMRegressor(**_lgb_params(spec.params, seed, **extra))
        m.fit(Xt, yraw, categorical_feature=cats or "auto")
        return Fitted(np.clip(np.asarray(m.predict(Xv), dtype=float), 0, None), None, 1.0)
    if spec.kind == "hurdle":
        over = (yraw > HURDLE_THRESHOLD).astype(int)
        clf = lgb.LGBMClassifier(**_lgb_params(spec.cls_params, seed, objective="binary"))
        clf.fit(Xt, over, categorical_feature=cats or "auto")
        p = np.asarray(clf.predict_proba(Xv)[:, 1], dtype=float)
        hi_mask = over == 1
        reg_hi = lgb.LGBMRegressor(**_lgb_params(spec.params, seed, objective="regression"))
        reg_hi.fit(Xt[hi_mask], ylog[hi_mask], categorical_feature=cats or "auto")
        reg_lo = lgb.LGBMRegressor(**_lgb_params(spec.params, seed, objective="regression"))
        reg_lo.fit(Xt[~hi_mask], ylog[~hi_mask], categorical_feature=cats or "auto")
        e_hi = to_cells(np.asarray(reg_hi.predict(Xv), dtype=float))
        e_lo = to_cells(np.asarray(reg_lo.predict(Xv), dtype=float))
        raw = p * e_hi + (1 - p) * e_lo
        return Fitted(raw, np.log10(raw + 1), 1.0, p_over=p)
    if spec.kind == "ens":
        a = fit_predict(tr, va, cols, VariantSpec("log_w", alpha=spec.alpha, params=spec.params), seed)
        b = fit_predict(
            tr,
            va,
            cols,
            VariantSpec(
                "tweedie",
                variance_power=spec.variance_power,
                objective_raw=spec.objective_raw,
                params=spec.params,
            ),
            seed,
        )
        raw = spec.w_c1 * a.raw * a.smear + (1 - spec.w_c1) * b.raw  # C1 은 smearing 보정값 사용
        return Fitted(raw, np.log10(raw + 1), 1.0)
    raise ValueError(spec.kind)


# ---------------------------------------------------------------- 보정·평가
def apply_bias(f: Fitted, method: str, iso: IsotonicRegression | None) -> np.ndarray:
    if f.log_pred is None or method == "none":
        return f.raw
    if method == "smearing":
        return f.raw * f.smear if f.smear else f.raw
    if method == "isotonic":
        if iso is None:
            return f.raw
        return np.clip(iso.predict(f.log_pred), 0, None)
    raise ValueError(method)


def fit_isotonic(log_pred: np.ndarray, obs: np.ndarray) -> IsotonicRegression | None:
    ok = np.isfinite(log_pred) & np.isfinite(obs)
    if ok.sum() < 50:
        return None
    iso = IsotonicRegression(y_min=0.0, out_of_bounds="clip", increasing=True)
    iso.fit(log_pred[ok], obs[ok])
    return iso


@dataclass
class CVResult:
    folds: pd.DataFrame  # fold × bias 지표
    by_site: pd.DataFrame
    oof: dict[str, np.ndarray]  # bias → 원단위 OOF (train/valid 행 인덱스 기준, NaN = 미예측)
    oof_log: np.ndarray
    final_iso: IsotonicRegression | None


def run_cv(
    df: pd.DataFrame,
    cols: list[str],
    spec: VariantSpec,
    *,
    seeds: tuple[int, ...] = (SEED,),
    include_final: bool = True,
    bias_methods: tuple[str, ...] = BIAS_METHODS,
) -> CVResult:
    """폴드별 적합(시드 평균) → 보정 3종 × 지표.

    isotonic 은 해당 폴드 이전 폴드들의 OOF 로 적합(F1 은 없음→미보정).
    """
    folds: list[Fold] = year_folds(df, include_final=include_final)
    n = len(df)
    oof_raw = np.full(n, np.nan)
    oof_log = np.full(n, np.nan)
    oof_smear = np.full(n, np.nan)
    obs_all = df["target_cells"].to_numpy(dtype=float)
    rows, site_rows = [], []
    oof_by_bias = {b: np.full(n, np.nan) for b in bias_methods}
    final_iso = None
    for fo in folds:
        tr, va = df.iloc[fo.train_idx], df.iloc[fo.valid_idx]
        fits = [fit_predict(tr, va, cols, spec, seed=s) for s in seeds]
        raw = np.mean([f.raw for f in fits], axis=0)
        lp = np.mean([f.log_pred for f in fits], axis=0) if fits[0].log_pred is not None else None
        smear = float(np.mean([f.smear for f in fits]))
        f = Fitted(raw, lp, smear)
        # isotonic: 이전 폴드 OOF(log 예측 → 관측 원단위)
        prev = ~np.isnan(oof_log)
        iso = fit_isotonic(oof_log[prev], obs_all[prev]) if prev.any() and lp is not None else None
        if fo.name == "Final":
            final_iso = iso
        obs = va["target_cells"].to_numpy(dtype=float)
        for b in bias_methods:
            pred = np.clip(np.nan_to_num(apply_bias(f, b, iso), nan=0.0), 0, None)
            oof_by_bias[b][fo.valid_idx] = pred
            m = compute_all(obs, pred)
            rows.append(
                {
                    "fold": fo.name,
                    "valid_year": fo.valid_year,
                    "bias": b,
                    "n": m["n"],
                    **{k: m[k] for k in REPORT_METRICS},
                }
            )
            for sid, g in va.groupby("station_id", observed=True):
                if len(g) < 5:
                    continue
                idx = va.index.get_indexer(g.index)
                ms = compute_all(g["target_cells"].to_numpy(dtype=float), pred[idx])
                site_rows.append(
                    {
                        "fold": fo.name,
                        "bias": b,
                        "station_id": str(sid),
                        "n": ms["n"],
                        **{k: ms[k] for k in REPORT_METRICS},
                    }
                )
        oof_raw[fo.valid_idx] = raw
        if lp is not None:
            oof_log[fo.valid_idx] = lp
            oof_smear[fo.valid_idx] = raw * smear
    return CVResult(pd.DataFrame(rows), pd.DataFrame(site_rows), oof_by_bias, oof_log, final_iso)


def summarize_cv(res: CVResult, bias: str = "none") -> dict[str, float]:
    f = res.folds[res.folds["bias"] == bias]
    cv = f[f["fold"] != "Final"]
    out = {f"cv_{k}": float(cv[k].mean()) for k in REPORT_METRICS}
    fin = f[f["fold"] == "Final"]
    if len(fin):
        out.update({f"final_{k}": float(fin[k].iloc[0]) for k in REPORT_METRICS})
    return out


def composite_objective(cv_rmse_log: float, cv_r2_raw: float, ref_rmse: float = 0.83) -> float:
    """J = 0.5·rmse_log/0.83 + 0.5·(1 − clip(r2_raw, −1, 1))."""
    return 0.5 * cv_rmse_log / ref_rmse + 0.5 * (1 - float(np.clip(cv_r2_raw, -1, 1)))
