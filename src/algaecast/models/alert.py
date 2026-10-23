"""T4-c 러너: 경보 분류기(타깃 a/b)·회귀 결합·분위 회귀·NNLS 앙상블·단계 정확도·레지스트리 등록.

출력: reports/eval/tbl_alert_classification.md, tbl_quantile.md, tbl_ensemble.md,
      reports/experiments/EXP-002.md,
      config/model.yaml(alert 섹션), models/registry.json(current: regression / classifier / quantile)
사용: python -m algaecast.models.alert [--trials 150] [--skip-tune]
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date

import numpy as np
import pandas as pd
import yaml
from sklearn.linear_model import LogisticRegression

from algaecast.collect.nier_algae import two_consecutive_levels
from algaecast.collect.nier_forecast import level_from_cells
from algaecast.config import CONFIG_DIR, ROOT
from algaecast.eval.metrics import compute_all, f1_at
from algaecast.models import classifier as C
from algaecast.models import data as D
from algaecast.models import registry as R
from algaecast.models.ensemble import combine, nnls_weights
from algaecast.models.quantile import cv_quantiles, fit_quantiles
from algaecast.models.train import SEED, feature_sets, fit_predict, run_cv
from algaecast.models.tune import OUT_DIR as OPTUNA_DIR
from algaecast.models.tune import spec_from_params

log = logging.getLogger(__name__)
EVAL = ROOT / "reports" / "eval"
EXP = ROOT / "reports" / "experiments"
T10K, T1K = 10_000.0, 1_000.0
OOF_PATH = ROOT / "data" / "processed" / "oof_predictions.parquet"


def _md(t: pd.DataFrame, nd: int = 3) -> str:
    d = t.copy()
    for c in d.columns:
        if d[c].dtype.kind == "f":
            d[c] = d[c].round(nd)
    return (
        "| "
        + " | ".join(map(str, d.columns))
        + " |\n|"
        + "---|" * len(d.columns)
        + "\n"
        + "\n".join(
            "| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |"
            for r in d.itertuples(index=False)
        )
    )


def _study(name: str) -> dict:
    return json.loads((OPTUNA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def level_accuracy(df: pd.DataFrame, pred: np.ndarray, mask: np.ndarray) -> dict[str, float]:
    """2025 target_date 순서로 관측/예측 세포수 → 단일 단계·2회 연속 산출 단계 정확도 (지점별 시계열)."""
    d = df.loc[mask, ["station_id", "target_date", "target_cells"]].copy()
    d["pred"] = pred[mask]
    exact, within1, exact2, n = 0, 0, 0, 0
    for _, g in d.groupby("station_id", observed=True):
        g = g.sort_values("target_date")
        lo = level_from_cells(g["target_cells"]).astype(float)
        lp = level_from_cells(pd.Series(g["pred"].to_numpy(), index=g.index)).astype(float)
        exact += int((lo == lp).sum())
        within1 += int(((lo - lp).abs() <= 1).sum())
        lo2 = two_consecutive_levels(level_from_cells(g["target_cells"])).astype(float)
        lp2 = two_consecutive_levels(level_from_cells(pd.Series(g["pred"].to_numpy(), index=g.index))).astype(
            float
        )
        exact2 += int((lo2 == lp2).sum())
        n += len(g)
    return {
        "n": n,
        "단일단계 정확도": exact / n,
        "±1단계": within1 / n,
        "2회연속 산출단계 정확도": exact2 / n,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trials", type=int, default=150)
    ap.add_argument("--skip-tune", action="store_true", help="config/model.yaml alert.params 재사용")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))
    cols = feature_sets()["perc75"]
    df = C.add_targets(D.load_train_valid("S1"))
    years = pd.to_datetime(df["base_date"]).dt.year.to_numpy()
    cv_mask, fin_mask = (years >= 2020) & (years <= 2024), years == 2025  # OOF 가 있는 폴드 연도만
    obs = df["target_cells"].to_numpy(dtype=float)
    y_a = df["over_target"].to_numpy(dtype=int)
    y_b = df["over_window"].to_numpy(dtype=int)
    EVAL.mkdir(parents=True, exist_ok=True)
    EXP.mkdir(parents=True, exist_ok=True)

    # ---- 회귀 OOF (C1 채택·C3·C2)
    sel = cfg["selected"]
    spec_c1 = spec_from_params(sel["params"], "log_w")
    res_c1 = run_cv(df, cols, spec_c1)
    reg_c1 = res_c1.oof["smearing"]
    spec_c3 = spec_from_params(_study("hurdle_rmse_log_perc75_S1")["best_params"], "hurdle")
    reg_c3 = run_cv(df, cols, spec_c3, bias_methods=("none",)).oof["none"]
    spec_c2 = spec_from_params(_study("tweedie_rmse_log_perc75_S1")["best_params"], "tweedie")
    reg_c2 = run_cv(df, cols, spec_c2, bias_methods=("none",)).oof["none"]
    log.info("회귀 OOF 완료")

    # ---- 분류기 (a)(b)
    clf_rows, tuned = [], {}
    probs: dict[str, np.ndarray] = {}
    for tname, y in (("over_target", y_a), ("over_window", y_b)):
        if args.skip_tune and cfg.get("alert", {}).get(tname):
            params = cfg["alert"][tname]["params"]
            tuned[tname] = {"params": params, "cv_pr_auc": float("nan"), "n_complete": 0, "n_trials": 0}
        else:
            tuned[tname] = C.tune_clf(df, cols, tname, n_trials=args.trials)
            params = tuned[tname]["params"]
        p, _ = C.cv_proba(df, cols, tname, params)
        probs[tname] = p
        thr = C.best_threshold(y[cv_mask], p[cv_mask])
        tuned[tname]["thr"] = thr
        for scope, m in (("CV OOF(≤2024)", cv_mask), ("Final 2025", fin_mask)):
            clf_rows.append(
                {"타깃": tname, "방식": "(i) 분류기 단독", "구간": scope, **C.cls_metrics(y[m], p[m], thr)}
            )
        log.info("%s: thr %.2f, CV PR-AUC %.3f", tname, thr, tuned[tname]["cv_pr_auc"])

    # ---- 결합 (평가 타깃 = (a) target_date ≥10k 와 (b) 창, 둘 다)
    pred_sets = {"회귀 C1(smearing)": reg_c1, "회귀 C3 hurdle": reg_c3, "회귀 C2 tweedie": reg_c2}
    b0 = np.clip(10 ** df["cell_log_t0"].fillna(0).to_numpy(dtype=float) - 1, 0, None)
    quant = cv_quantiles(df, cols, spec_c1)
    stack_p: dict[str, np.ndarray] = {}
    stack_thr: dict[str, float] = {}
    for tname, y in (("over_target", y_a), ("over_window", y_b)):
        p_clf = probs[tname]
        thr = tuned[tname]["thr"]
        # (ii) 회귀 ≥10k
        for rname, rp in pred_sets.items():
            ind = (rp >= T10K).astype(float)
            for scope, m in (("CV OOF(≤2024)", cv_mask), ("Final 2025", fin_mask)):
                clf_rows.append(
                    {
                        "타깃": tname,
                        "방식": f"(ii) {rname} ≥10k",
                        "구간": scope,
                        **C.cls_metrics(y[m], ind[m], 0.5),
                    }
                )
        # (iii) 스태킹(확장): 연도 Y 의 OOF 는 Y 이전 폴드 OOF 로 적합한 로지스틱으로 산출
        #       (2020 은 이전 OOF 없음 → 제외), 2025 는 ≤2024 OOF 전체로 적합. 임계는 스태킹 OOF 에서 F1 최대.
        Z = np.column_stack([_logit(p_clf), np.log10(reg_c1 + 1)])
        okz = np.isfinite(Z).all(axis=1)
        p_st = np.full(len(df), np.nan)
        for yv in (2021, 2022, 2023, 2024, 2025):
            fit_m = okz & (years >= 2020) & (years < yv)
            app_m = okz & (years == yv)
            if y[fit_m].sum() < 5 or not app_m.any():
                continue
            lr = LogisticRegression(C=1.0, class_weight="balanced", max_iter=1000)
            lr.fit(Z[fit_m], y[fit_m])
            p_st[app_m] = lr.predict_proba(Z[app_m])[:, 1]
        st_cv = cv_mask & np.isfinite(p_st)
        thr_st = C.best_threshold(y[st_cv], p_st[st_cv])
        for scope, m in (("CV OOF(≤2024)", st_cv), ("Final 2025", fin_mask)):
            clf_rows.append(
                {
                    "타깃": tname,
                    "방식": "(iii) 분류기+회귀 스태킹(로지스틱)",
                    "구간": scope,
                    **C.cls_metrics(y[m], p_st[m], thr_st),
                }
            )
        # (iv) q90 ≥ 10k
        ind = (quant["q90"] >= T10K).astype(float)
        for scope, m in (("CV OOF(≤2024)", cv_mask), ("Final 2025", fin_mask)):
            clf_rows.append(
                {
                    "타깃": tname,
                    "방식": "(iv) 분위 q90 ≥10k",
                    "구간": scope,
                    **C.cls_metrics(y[m], ind[m], 0.5),
                }
            )
        # B0 지속성
        ind = (b0 >= T10K).astype(float)
        for scope, m in (("CV OOF(≤2024)", cv_mask), ("Final 2025", fin_mask)):
            clf_rows.append(
                {
                    "타깃": tname,
                    "방식": "B0 지속성 (최근 측정 ≥10k)",
                    "구간": scope,
                    **C.cls_metrics(y[m], ind[m], 0.5),
                }
            )
        stack_p[tname], stack_thr[tname] = p_st, thr_st
        if tname == "over_target":
            p_st_a, thr_st_a = p_st, thr_st
    clf_tbl = pd.DataFrame(clf_rows)

    # ---- 지점별 F1 (2025, 타깃 a): 분류기·스태킹·B0·C1
    site_rows = []
    for sid in sorted(df["station_id"].astype(str).unique()):
        m = fin_mask & (df["station_id"].astype(str).to_numpy() == sid)
        npos = int(y_a[m].sum())
        row = {"station_id": sid, "n": int(m.sum()), "n_pos(≥10k)": npos}
        for name, pv, thr in (
            ("분류기(a)", probs["over_target"], tuned["over_target"]["thr"]),
            ("분류기(b)", probs["over_window"], tuned["over_window"]["thr"]),
            ("스태킹", p_st_a, thr_st_a),
            ("회귀 C1", (reg_c1 >= T10K).astype(float), 0.5),
            ("B0", (b0 >= T10K).astype(float), 0.5),
        ):
            row[f"F1 {name}"] = C.cls_metrics(y_a[m], pv[m], thr)["f1"] if npos > 0 else np.nan
        row["비고"] = "" if npos > 0 else "2025 양성 0 → 제외"
        site_rows.append(row)
    site_tbl = pd.DataFrame(site_rows)

    # ---- 관심(≥1k) F1 · 단계 정확도 (2025)
    lvl_rows = []
    for name, pv in (("회귀 C1(smearing)", reg_c1), ("회귀 C3 hurdle", reg_c3), ("B0 지속성", b0)):
        f1k = f1_at(obs[fin_mask], pv[fin_mask], T1K)
        f10k = f1_at(obs[fin_mask], pv[fin_mask], T10K)
        lvl_rows.append(
            {"모델": name, "F1@1k": f1k["f1"], "F1@10k": f10k["f1"], **level_accuracy(df, pv, fin_mask)}
        )
    lvl_tbl = pd.DataFrame(lvl_rows)

    # ---- 분위 회귀 평가
    q_rows = []
    for scope, m in (("CV OOF(≤2024)", cv_mask), ("Final 2025", fin_mask)):
        mm = compute_all(obs[m], quant["q50"][m], q10=quant["q10"][m], q90=quant["q90"][m])
        q_rows.append(
            {
                "구간": scope,
                "n": mm["n"],
                "q50 rmse_log": mm["rmse_log"],
                "picp80": mm["picp80"],
                "mpiw80_log": mm["mpiw80_log"],
                "mpiw80_raw": mm["mpiw80_raw"],
                "q90≥10k F1(a)": C.cls_metrics(y_a[m], (quant["q90"][m] >= T10K).astype(float), 0.5)["f1"],
            }
        )
    q_tbl = pd.DataFrame(q_rows)

    # ---- NNLS 앙상블(확장): 연도 Y 는 Y 이전 OOF 로 가중 적합(2020 은 균등 가중),
    #      2025·제출은 ≤2024 OOF 전체 가중
    ens = np.full(len(df), np.nan)
    for yv in (2020, 2021, 2022, 2023, 2024, 2025):
        fit_m = cv_mask & (years < yv)
        app_m = years == yv
        if fit_m.sum() < 50:
            wy = {k: 1.0 / len(pred_sets) for k in pred_sets}
        else:
            wy = nnls_weights({k: v[fit_m] for k, v in pred_sets.items()}, obs[fit_m])
        ens[app_m] = combine({k: v[app_m] for k, v in pred_sets.items()}, wy)
    w = nnls_weights({k: v[cv_mask] for k, v in pred_sets.items()}, obs[cv_mask])
    ens_rows = []
    for name, pv in (
        *pred_sets.items(),
        (f"NNLS 앙상블 {json.dumps({k: round(v, 2) for k, v in w.items()}, ensure_ascii=False)}", ens),
    ):
        for scope, m in (("CV OOF(≤2024)", cv_mask), ("Final 2025", fin_mask)):
            mm = compute_all(obs[m], pv[m])
            ens_rows.append(
                {
                    "모델": name,
                    "구간": scope,
                    **{
                        k: mm[k]
                        for k in ("rmse_log", "r2_log", "r2_raw", "r2_pearson_raw", "nse_raw", "f1_10k")
                    },
                }
            )
    ens_tbl = pd.DataFrame(ens_rows)
    cv_c1 = ens_tbl[(ens_tbl["모델"] == "회귀 C1(smearing)") & (ens_tbl["구간"].str.startswith("CV"))].iloc[0]
    cv_en = ens_tbl[ens_tbl["모델"].str.startswith("NNLS") & ens_tbl["구간"].str.startswith("CV")].iloc[0]
    adopt_ens = bool(cv_en["rmse_log"] < cv_c1["rmse_log"] - 0.002)

    # ---- 채택 규칙: 2025 가 아닌 CV OOF F1 기준 (타깃 a)
    cand = clf_tbl[(clf_tbl["타깃"] == "over_target") & clf_tbl["구간"].str.startswith("CV")].sort_values(
        "f1", ascending=False
    )
    rule = str(cand.iloc[0]["방식"])
    fin_rule = clf_tbl[
        (clf_tbl["타깃"] == "over_target") & (clf_tbl["방식"] == rule) & (clf_tbl["구간"] == "Final 2025")
    ].iloc[0]
    b0_fin = clf_tbl[
        (clf_tbl["타깃"] == "over_target")
        & clf_tbl["방식"].str.startswith("B0")
        & (clf_tbl["구간"] == "Final 2025")
    ].iloc[0]

    # ---- 레지스트리: ≤2025 전체로 재학습 (제출·대시보드용)
    full = df
    reg_fit = fit_predict(full, full.iloc[:5], cols, spec_c1)  # smear 계수 확보용
    nums, cats = D.numeric_and_categorical(cols)
    import lightgbm as lgb

    from algaecast.models.train import _lgb_params, _prep

    Xt = _prep(full[cols], cats)
    ylog = full["target_log"].to_numpy(dtype=float)
    reg_model = lgb.LGBMRegressor(**_lgb_params(spec_c1.params, SEED, objective="regression"))
    reg_model.fit(Xt, ylog, sample_weight=1.0 + spec_c1.alpha * ylog, categorical_feature=cats or "auto")
    reg_obj = {
        "model": reg_model,
        "smear": reg_fit.smear,
        "cols": cols,
        "cats": cats,
        "categories": {c: list(Xt[c].cat.categories) for c in cats},
        "variant": "log_w",
        "alpha": spec_c1.alpha,
        "bias": "smearing",
    }
    fin_c1 = compute_all(obs[fin_mask], reg_c1[fin_mask])
    metric_keys = ("rmse_log", "r2_log", "r2_raw", "r2_pearson_raw", "nse_raw", "f1_10k")
    if adopt_ens:
        # 앙상블 채택 시 C3·C2 도 ≤2025 전체로 재학습해 멤버로 등록 (predict 는 log 공간 가중 평균)
        yraw = full["target_cells"].to_numpy(dtype=float)
        over = (yraw > 1000.0).astype(int)
        cls_m = lgb.LGBMClassifier(**_lgb_params(spec_c3.cls_params, SEED, objective="binary"))
        cls_m.fit(Xt, over, categorical_feature=cats or "auto")
        hi_m = lgb.LGBMRegressor(**_lgb_params(spec_c3.params, SEED, objective="regression"))
        hi_m.fit(Xt[over == 1], ylog[over == 1], categorical_feature=cats or "auto")
        lo_m = lgb.LGBMRegressor(**_lgb_params(spec_c3.params, SEED, objective="regression"))
        lo_m.fit(Xt[over == 0], ylog[over == 0], categorical_feature=cats or "auto")
        extra = {"objective": spec_c2.objective_raw}
        if spec_c2.objective_raw == "tweedie":
            extra["tweedie_variance_power"] = spec_c2.variance_power
        tw_m = lgb.LGBMRegressor(**_lgb_params(spec_c2.params, SEED, **extra))
        tw_m.fit(Xt, yraw, categorical_feature=cats or "auto")
        reg_obj = {
            "kind": "ensemble",
            "weights": w,
            "members": {
                "회귀 C1(smearing)": {**reg_obj, "kind": "log_w"},
                "회귀 C3 hurdle": {"kind": "hurdle", "clf": cls_m, "hi": hi_m, "lo": lo_m},
                "회귀 C2 tweedie": {"kind": "tweedie", "model": tw_m},
            },
            "cols": cols,
            "cats": cats,
            "categories": {c: list(Xt[c].cat.categories) for c in cats},
        }
        fin_reg = compute_all(obs[fin_mask], ens[fin_mask])
    else:
        reg_obj = {**reg_obj, "kind": "log_w"}
        fin_reg = fin_c1
    R.register(
        "regression",
        reg_obj,
        features=cols,
        metrics_holdout={k: fin_reg[k] for k in metric_keys},
        meta={
            "train_through": 2025,
            "study": sel["study"],
            "purpose": "submission cells",
            "kind": reg_obj["kind"],
            "ensemble_weights": w if adopt_ens else None,
        },
    )
    clf_model = C.fit_clf(full, cols, "over_window", tuned["over_window"]["params"])
    clf_obj = {
        "model": clf_model,
        "cols": cols,
        "cats": cats,
        "categories": {c: list(clf_model._prep_ref[c].cat.categories) for c in cats},
        "threshold": tuned["over_window"]["thr"],
        "target": "over_window",
    }
    fin_b = clf_tbl[
        (clf_tbl["타깃"] == "over_window")
        & (clf_tbl["방식"] == "(i) 분류기 단독")
        & (clf_tbl["구간"] == "Final 2025")
    ].iloc[0]
    R.register(
        "classifier",
        clf_obj,
        features=cols,
        metrics_holdout={
            "pr_auc": fin_b["pr_auc"],
            "brier": fin_b["brier"],
            "f1": fin_b["f1"],
            "thr": fin_b["thr"],
        },
        meta={
            "train_through": 2025,
            "target": "over_window(+4~+10일 창 ≥10k)",
            "purpose": "dashboard probability",
        },
    )
    q_models = fit_quantiles(full, cols, spec_c1)
    q_obj = {"models": q_models, "cols": cols, "cats": cats}
    fq = q_tbl[q_tbl["구간"] == "Final 2025"].iloc[0]
    R.register(
        "quantile",
        q_obj,
        features=cols,
        metrics_holdout={"picp80": fq["picp80"], "mpiw80_log": fq["mpiw80_log"]},
        meta={"train_through": 2025, "quantiles": [0.1, 0.5, 0.9]},
    )

    # ---- OOF 예측 캐시 (T5 평가 모듈이 재학습 없이 사용; test 행 없음)
    oof = pd.DataFrame(
        {
            "station_id": df["station_id"].astype(str).to_numpy(),
            "base_date": df["base_date"].to_numpy(),
            "target_date": df["target_date"].to_numpy(),
            "year": years,
            "target_cells": obs,
            "cell_log_t0": df["cell_log_t0"].to_numpy(dtype=float),
            "over_target": y_a,
            "over_window": y_b,
            "b0": b0,
            "reg_c1": reg_c1,
            "reg_c3": reg_c3,
            "reg_c2": reg_c2,
            "ens": ens,
            "clf_a": probs["over_target"],
            "clf_b": probs["over_window"],
            "stack_a": stack_p["over_target"],
            "stack_b": stack_p["over_window"],
            "q10": quant["q10"],
            "q50": quant["q50"],
            "q90": quant["q90"],
        }
    )
    oof.to_parquet(OOF_PATH, index=False)
    thresholds = {
        "clf_a": float(tuned["over_target"]["thr"]),
        "clf_b": float(tuned["over_window"]["thr"]),
        "stack_a": float(stack_thr["over_target"]),
        "stack_b": float(stack_thr["over_window"]),
    }
    # ---- 저장
    cfg["alert"] = {
        t: {"params": tuned[t]["params"], "thr": tuned[t]["thr"], "cv_pr_auc": tuned[t]["cv_pr_auc"]}
        for t in tuned
    }
    cfg["alert_rule"] = {
        "adopted": rule,
        "basis": "CV OOF(≤2024) F1 최대, 타깃 (a)",
        "final_2025_f1": float(fin_rule["f1"]),
        "b0_final_2025_f1": float(b0_fin["f1"]),
    }
    cfg["ensemble"] = {
        "weights": w,
        "adopted": adopt_ens,
        "cv_rmse_log_c1": float(cv_c1["rmse_log"]),
        "cv_rmse_log_ens": float(cv_en["rmse_log"]),
    }
    cfg["registry_current"] = R.current_versions()
    cfg["thresholds"] = thresholds
    (CONFIG_DIR / "model.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8"
    )
    note = (
        "- 임계값은 CV OOF(≤2024) F1 최대 지점으로 고정하고 2025 는 그 임계로만 평가. "
        "(iii) 스태킹의 CV 행은 in-sample 적합이라 참고용.\n"
    ) + (
        "- 분류기 하이퍼파라미터: config/model.yaml 의 이전 튜닝값 고정(--skip-tune, Optuna 재실행 없음), "
        "현재 피처로 재적합만 했다.\n"
        if args.skip_tune
        else f"- 분류기 튜닝: Optuna {args.trials} trial, 목적 CV PR-AUC — "
        f"(a) {tuned['over_target']['cv_pr_auc']:.3f} / (b) {tuned['over_window']['cv_pr_auc']:.3f}\n"
    )
    (EVAL / "tbl_alert_classification.md").write_text(
        "# 경보(≥10,000) 분류 — 방식별 F1·Brier·PR-AUC (T4-c)\n\n"
        + note
        + f"- **채택 규칙(타깃 a, CV F1 기준)**: {rule} → 2025 F1 {fin_rule['f1']:.3f} "
        + f"(B0 지속성 {b0_fin['f1']:.3f})\n\n"
        + _md(clf_tbl)
        + "\n\n## 지점별 F1 (2025, 타깃 a)\n"
        + _md(site_tbl)
        + "\n\n## 관심(≥1k)·경계 F1 과 단계 정확도 (2025)\n"
        + _md(lvl_tbl)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (EVAL / "tbl_quantile.md").write_text(
        "# 분위 회귀 q10/q50/q90 (C1 파라미터, objective=quantile)\n\n" + _md(q_tbl) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (EVAL / "tbl_ensemble.md").write_text(
        "# NNLS 앙상블 (C1 smearing · C3 hurdle · C2 tweedie, F1~F5 OOF log 공간 적합, 합=1)\n\n"
        + f"- 가중치 {w}\n- 채택: {'예' if adopt_ens else '아니오'} "
        + f"(CV rmse_log 단일 C1 {cv_c1['rmse_log']:.4f} vs 앙상블 {cv_en['rmse_log']:.4f}; "
        + "0.002 이상 개선 시 채택)\n\n"
        + _md(ens_tbl)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (EXP / "EXP-002.md").write_text(
        f"# EXP-002 T4-c 경보 분류·분위·앙상블 ({date.today()})\n\n"
        "## 설정\n- features_S1, perc75 30개, 폴드 docs/04 §2, 시드 42. "
        "분류 타깃 (a) target_date ≥10k / (b) +4~+10일 창 ≥10k.\n"
        + (
            "- 분류기 하이퍼파라미터 이전 튜닝값 고정(--skip-tune). "
            if args.skip_tune
            else f"- 분류기 Optuna {args.trials} trial(PR-AUC). "
        )
        + "임계 CV OOF F1 최대. "
        "회귀 OOF: C1 채택 파라미터, C3/C2 각 스터디 best.\n\n"
        "## 결과\n- reports/eval/tbl_alert_classification.md, tbl_quantile.md, tbl_ensemble.md\n\n"
        f"## 채택\n- 경보 규칙: {rule} (2025 F1 {fin_rule['f1']:.3f} vs B0 {b0_fin['f1']:.3f})\n"
        f"- 앙상블: {'채택' if adopt_ens else '미채택 — 단일 C1 유지'} (가중 {w})\n"
        f"- registry current: {R.current_versions()}\n",
        encoding="utf-8",
        newline="\n",
    )
    print(clf_tbl[clf_tbl["구간"] == "Final 2025"].round(3).to_string(index=False))
    print("\n채택 규칙:", rule, "| 앙상블 채택:", adopt_ens, w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
