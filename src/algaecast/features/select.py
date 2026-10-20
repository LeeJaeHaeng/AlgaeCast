"""T3-c 피처 선별: VIF 반복 제거 → Boruta(LightGBM, shadow 100회) → 보 피처 ablation → 최종 ≤ 115.

train(≤2024, 전략 S1)만 사용. 결과는 config/features.yaml ``selected``/``excluded`` 와
reports/features/tbl_feature_select.md 에 기록한다.

사용: python -m algaecast.features.select [--strategy S1] [--boruta-iter 100]
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml
from scipy import stats

from algaecast.config import CONFIG_DIR, ROOT
from algaecast.models import data as D
from algaecast.models.cv import cv_evaluate, summarize

log = logging.getLogger(__name__)
PROTECTED = ["cell_log_t0", "wtemp_ma14", "wtemp_minus_site_thresh", "weir_outflow_ma7", "horizon_days"]
BORUTA_PERC = (
    75  # shadow 중요도 백분위 임계(BorutaPy perc). 100(=max) 은 과도하게 엄격(14개 생존) → 75, 보고서에 근거
)
WEIR_GROUP_PREFIX = ("weir_", "dam_release_event_7d", "hydro_fac_available")
MAX_FEATURES = 115  # 2,310 / 20
VIF_LIMIT = 10.0
SEED = 42


def vif_table(X: pd.DataFrame) -> pd.Series:
    """표준화 후 각 열을 나머지로 회귀한 R² 로 VIF = 1/(1−R²)."""
    Z = (X - X.mean()) / X.std(ddof=0).replace(0, 1)
    Z = Z.fillna(0).to_numpy()
    n, p = Z.shape
    out = {}
    for j in range(p):
        y = Z[:, j]
        A = np.delete(Z, j, axis=1)
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        resid = y - A @ coef
        ss_res, ss_tot = float(resid @ resid), float(((y - y.mean()) ** 2).sum()) or 1.0
        r2 = max(0.0, 1 - ss_res / ss_tot)
        out[X.columns[j]] = np.inf if r2 >= 1 - 1e-12 else 1 / (1 - r2)
    return pd.Series(out)


def vif_prune(
    X: pd.DataFrame, protected: list[str], limit: float = VIF_LIMIT
) -> tuple[list[str], list[tuple[str, float]]]:
    cols = list(X.columns)
    removed: list[tuple[str, float]] = []
    while True:
        v = vif_table(X[cols])
        cand = v.drop(labels=[c for c in protected if c in v.index])
        if cand.empty or cand.max() <= limit:
            break
        worst = str(cand.idxmax())
        removed.append((worst, float(cand.max())))
        cols.remove(worst)
    return cols, removed


def _lgb(seed: int) -> lgb.LGBMRegressor:
    return lgb.LGBMRegressor(
        n_estimators=300,
        learning_rate=0.05,
        num_leaves=31,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        min_child_samples=20,
        random_state=seed,
        verbose=-1,
    )


def boruta(
    X: pd.DataFrame,
    y: np.ndarray,
    cats: list[str],
    n_iter: int = 100,
    alpha: float = 0.05,
    perc: int = BORUTA_PERC,
) -> pd.DataFrame:
    """Boruta: 매 반복 shadow(셔플 복제) 를 붙여 LightGBM gain 중요도 비교.

    임계 = shadow 중요도의 perc 백분위(100 이면 원래 Boruta 의 max). 이항검정(양측, Bonferroni) 판정.
    """
    rng = np.random.default_rng(SEED)
    cols = list(X.columns)
    hits = pd.Series(0, index=cols, dtype=int)
    imp_sum = pd.Series(0.0, index=cols)
    Xc = X.copy()
    for c in cats:
        Xc[c] = Xc[c].astype("category")
    for it in range(n_iter):
        sh = X.drop(columns=cats).apply(
            lambda s: s.sample(frac=1, random_state=int(rng.integers(1 << 31))).to_numpy()
        )
        sh.columns = [f"shadow_{c}" for c in sh.columns]
        Xi = pd.concat([Xc.reset_index(drop=True), sh.reset_index(drop=True)], axis=1)
        m = _lgb(SEED + it)
        m.fit(Xi, y, categorical_feature=cats or "auto")
        imp = pd.Series(m.booster_.feature_importance(importance_type="gain"), index=Xi.columns)
        shadow_max = np.percentile(imp[[c for c in Xi.columns if c.startswith("shadow_")]], perc)
        real = imp[cols]
        hits += (real > shadow_max).astype(int)
        imp_sum += real
    p_acc = stats.binom.sf(hits - 1, n_iter, 0.5)  # P(X ≥ hits)
    p_rej = stats.binom.cdf(hits, n_iter, 0.5)  # P(X ≤ hits)
    bonf = alpha / len(cols)
    decision = np.where(p_acc < bonf, "confirmed", np.where(p_rej < bonf, "rejected", "tentative"))
    return (
        pd.DataFrame(
            {
                "피처": cols,
                "hits": hits.to_numpy(),
                "mean_gain": (imp_sum / n_iter).round(1).to_numpy(),
                "판정": decision,
            }
        )
        .sort_values(["판정", "hits"], ascending=[True, False])
        .reset_index(drop=True)
    )


def lgb_fit_predict(cols: list[str], cats: list[str]) -> Callable[[pd.DataFrame, pd.DataFrame], np.ndarray]:
    def fn(tr: pd.DataFrame, va: pd.DataFrame) -> np.ndarray:
        Xt, Xv = tr[cols].copy(), va[cols].copy()
        for c in cats:
            Xt[c] = Xt[c].astype("category")
            Xv[c] = pd.Categorical(Xv[c], categories=Xt[c].cat.categories)
        m = _lgb(SEED)
        m.fit(Xt, tr["target_log"].to_numpy(dtype=float), categorical_feature=cats or "auto")
        return np.clip(10 ** np.clip(m.predict(Xv), 0, 7) - 1, 0, None)

    return fn


def _md(t: pd.DataFrame) -> str:
    return (
        "| "
        + " | ".join(map(str, t.columns))
        + " |\n|"
        + "---|" * len(t.columns)
        + "\n"
        + "\n".join(
            "| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |"
            for r in t.itertuples(index=False)
        )
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strategy", default="S1")
    ap.add_argument("--boruta-iter", type=int, default=100)
    ap.add_argument("--boruta-perc", type=int, default=BORUTA_PERC)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    df = D.load_train_valid(args.strategy)
    train = df[df["split"] == "train"].reset_index(drop=True)
    all_cols = D.feature_columns(train, selected_only=False)
    nums, cats = D.numeric_and_categorical(all_cols)
    excluded: dict[str, str] = {}
    # 0) 예보 피처: 전부 결측 → 이번 선별 제외, 후속 재검토 플래그
    fc = [c for c in nums if c.startswith("fc_")]
    for c in fc:
        excluded[c] = "예보 피처 — 2026-10-21 이후만 가용, 전 샘플 결측 → 선별 제외, 후속 재검토(T8 이후)"
    nums = [c for c in nums if c not in fc]
    # 상수·거의 전부 결측
    for c in list(nums):
        s = pd.to_numeric(train[c], errors="coerce")
        if s.notna().mean() < 0.3:
            excluded[c] = f"결측 {100 * (1 - s.notna().mean()):.0f}% (train)"
            nums.remove(c)
        elif s.nunique(dropna=True) <= 1:
            excluded[c] = "상수"
            nums.remove(c)
    # 1) VIF
    X = train[nums].apply(pd.to_numeric, errors="coerce")
    X = X.fillna(X.median())
    kept, removed = vif_prune(X, PROTECTED)
    for c, v in removed:
        excluded[c] = f"VIF {v:.1f} > 10 (반복 제거)"
    log.info("VIF: %d → %d (제거 %d)", len(nums), len(kept), len(removed))
    # 2) Boruta
    y = train["target_log"].to_numpy(dtype=float)
    bres = boruta(train[kept + cats], y, cats, n_iter=args.boruta_iter, perc=args.boruta_perc)
    confirmed = bres.loc[bres["판정"] == "confirmed", "피처"].tolist()
    tentative = bres.loc[bres["판정"] == "tentative", "피처"].tolist()
    rejected = bres.loc[bres["판정"] == "rejected", "피처"].tolist()
    for c in rejected:
        if c in PROTECTED or c in cats:
            continue
        excluded[c] = (
            f"Boruta rejected (hits {int(bres.set_index('피처').loc[c, 'hits'])}/{args.boruta_iter})"
        )
    keep = [c for c in kept + cats if c in confirmed or c in tentative or c in PROTECTED or c in cats]
    # 3) 보 피처 ablation (5폴드 CV log-RMSE)
    weir = [c for c in keep if c.startswith(WEIR_GROUP_PREFIX)]
    no_weir = [c for c in keep if c not in weir]
    res_with = summarize(
        cv_evaluate(df, lgb_fit_predict(keep, [c for c in cats if c in keep]), include_final=True)["folds"]
    )
    res_without = summarize(
        cv_evaluate(df, lgb_fit_predict(no_weir, [c for c in cats if c in no_weir]), include_final=True)[
            "folds"
        ]
    )
    delta = res_with["cv_rmse_log"] - res_without["cv_rmse_log"]
    keep_weir = delta <= 0.005  # 보 피처가 해치지 않으면(≤0.005 악화) 유지 — 상호작용 기여 가능
    abl = pd.DataFrame(
        [
            {
                "구성": f"보 피처 포함 ({len(weir)}개)",
                "피처 수": len(keep),
                "CV rmse_log": round(res_with["cv_rmse_log"], 4),
                "CV r2_log": round(res_with["cv_r2_log"], 4),
                "CV f1_10k": round(res_with["cv_f1_10k"], 4),
                "Final rmse_log": round(res_with["final_rmse_log"], 4),
            },
            {
                "구성": "보 피처 제외",
                "피처 수": len(no_weir),
                "CV rmse_log": round(res_without["cv_rmse_log"], 4),
                "CV r2_log": round(res_without["cv_r2_log"], 4),
                "CV f1_10k": round(res_without["cv_f1_10k"], 4),
                "Final rmse_log": round(res_without["final_rmse_log"], 4),
            },
        ]
    )
    if not keep_weir:
        for c in weir:
            if c not in PROTECTED:
                excluded[c] = f"보 피처 ablation: 제외 시 CV rmse_log {-delta:.4f} 개선"
        keep = [c for c in keep if c in PROTECTED or not c.startswith(WEIR_GROUP_PREFIX)]
    # 4) ≤115: Boruta 평균 gain 순으로 절단 (보호·범주는 항상 유지)
    gain = bres.set_index("피처")["mean_gain"]
    ordered = sorted(keep, key=lambda c: (c in PROTECTED or c in cats, gain.get(c, 0.0)), reverse=True)
    if len(ordered) > MAX_FEATURES:
        for c in ordered[MAX_FEATURES:]:
            excluded[c] = "상한 115 초과 (Boruta gain 하위)"
        ordered = ordered[:MAX_FEATURES]
    final = sorted(ordered, key=lambda c: -gain.get(c, 0.0))
    # 저장
    cfg_path = CONFIG_DIR / "features.yaml"
    cfg_text = cfg_path.read_text(encoding="utf-8")
    head = cfg_text.split("\n# ---- T3-c 선별 결과", 1)[0].rstrip("\n") + "\n"  # 주석 있는 원문 보존
    meta = {
        "strategy": args.strategy,
        "train_rows": int(len(train)),
        "boruta_iter": args.boruta_iter,
        "boruta_perc": args.boruta_perc,
        "max_features": MAX_FEATURES,
        "weir_group_kept": bool(keep_weir),
        "weir_ablation_delta_rmse_log": round(float(delta), 4),
        "forecast_features_pending_review": fc,
    }
    tail = yaml.safe_dump(
        {"selected": final, "excluded": excluded, "selection_meta": meta},
        allow_unicode=True,
        sort_keys=False,
        width=200,
    )
    cfg_path.write_text(
        head + "\n# ---- T3-c 선별 결과 (features/select.py 가 생성, 수동 편집 금지) ----\n" + tail,
        encoding="utf-8",
        newline="\n",
    )
    rep = ROOT / "reports" / "features" / "tbl_feature_select.md"
    ex_df = pd.DataFrame([{"피처": k, "제거 사유": v} for k, v in excluded.items()])
    rep.write_text(
        f"# 피처 선별 (T3-c, 전략 {args.strategy}, train {len(train):,}행)\n\n"
        f"- 후보 {len(all_cols)} → 예보 제외 {len(all_cols) - len(fc)} → VIF 후 {len(kept) + len(cats)} "
        f"→ Boruta(perc {args.boruta_perc}) confirmed {len(confirmed)} / tentative {len(tentative)} / "
        f"rejected {len(rejected)} → 최종 **{len(final)}** (상한 {MAX_FEATURES})\n"
        f"- 보호 피처: {PROTECTED}; 범주형 {cats} 은 항상 유지\n"
        f"- 보 피처 그룹 ablation: Δ CV rmse_log(포함 − 제외) = {delta:+.4f} "
        f"→ {'유지' if keep_weir else '제외'}\n\n"
        "## 보 피처 ablation\n"
        + _md(abl)
        + "\n\n## Boruta 결과\n"
        + _md(bres)
        + "\n\n## 제거 목록·사유\n"
        + _md(ex_df)
        + "\n\n## 최종 피처\n"
        + ", ".join(final)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(abl.to_string(index=False))
    print(f"최종 {len(final)}개 → config/features.yaml selected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
