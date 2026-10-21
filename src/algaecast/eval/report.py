"""평가 보고서 표·그림 11종 생성 (T5, docs/04 6.2). OOF 캐시 + 레지스트리 + features_S1(valid)
사용. test 미접근.

사용: python -m algaecast.eval.report [--boot 1000]
"""

from __future__ import annotations

import argparse
import logging
import pickle
import warnings

import matplotlib
import matplotlib.ticker
import numpy as np
import pandas as pd
import yaml
from scipy import stats

from algaecast.collect.nier_forecast import level_from_cells
from algaecast.config import CONFIG_DIR, MODELS_DIR, ROOT
from algaecast.eval import decision as DEC
from algaecast.eval.metrics import (
    bootstrap_ci,
    compute_all,
    f1_at,
    mae_log,
    nse_raw,
    r2_log,
    r2_pearson_raw,
    r2_raw,
    rmse_log,
)
from algaecast.eval.stats_tests import dm_test, ljung_box, wilcoxon_abs_err
from algaecast.eval.transitions import OOF_PATH, T10K
from algaecast.models import classifier as C
from algaecast.models import data as D
from algaecast.models.baselines import b4_elasticnet
from algaecast.models.cv import year_folds
from algaecast.models.train import feature_sets, run_cv
from algaecast.models.tune import spec_from_params

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

warnings.filterwarnings("ignore")
log = logging.getLogger(__name__)
EVAL = ROOT / "reports" / "eval"
for f in ("Malgun Gothic", "NanumGothic", "AppleGothic", "DejaVu Sans"):
    if any(ft.name == f for ft in matplotlib.font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = f
        break
plt.rcParams["axes.unicode_minus"] = False
METRICS = [
    "rmse_log",
    "mae_log",
    "r2_log",
    "r2_raw",
    "r2_pearson_raw",
    "nse_raw",
    "f1_10k",
    "f1_1k",
    "kge_log",
]
MODELS = {
    "앙상블(채택)": "ens",
    "회귀 C1": "reg_c1",
    "회귀 C3 hurdle": "reg_c3",
    "회귀 C2 tweedie": "reg_c2",
    "B0 지속성": "b0",
}
GROUPS = ("ar", "water", "hydro", "weather", "time_site")


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


def _write(name: str, title: str, body: str) -> None:
    (EVAL / name).write_text(f"# {title}\n\n{body}\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--boot", type=int, default=1000)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))
    o = pd.read_parquet(OOF_PATH)
    o["base_date"] = pd.to_datetime(o["base_date"])
    o["target_date"] = pd.to_datetime(o["target_date"])
    fin = o[o["year"] == 2025].reset_index(drop=True)
    cvm = o[(o["year"] >= 2020) & (o["year"] <= 2024)].reset_index(drop=True)
    obs = fin["target_cells"].to_numpy(dtype=float)
    # B4 2025 예측 (train ≤2024)
    df = D.load_train_valid("S1")
    folds = year_folds(df, include_final=True)
    ffold = [f for f in folds if f.name == "Final"][0]
    b4 = b4_elasticnet(df.iloc[ffold.train_idx], df.iloc[ffold.valid_idx])
    va = df.iloc[ffold.valid_idx][["station_id", "base_date"]].copy()
    va["base_date"] = pd.to_datetime(va["base_date"])
    va["b4"] = b4
    fin = fin.merge(
        va.assign(station_id=va["station_id"].astype(str)), on=["station_id", "base_date"], how="left"
    )
    preds = {k: fin[v].to_numpy(dtype=float) for k, v in MODELS.items()}
    preds["B4 ElasticNet"] = fin["b4"].to_numpy(dtype=float)
    qhat = cfg.get("cqr", {}).get("qhat_log10", 0.0)
    q10c = np.clip(10 ** (np.log10(fin["q10"].to_numpy() + 1) - qhat) - 1, 0, None)
    q90c = 10 ** (np.log10(fin["q90"].to_numpy() + 1) + qhat) - 1

    # ---- 3) 2025 홀드아웃 + 부트스트랩 CI
    fns = {
        "rmse_log": rmse_log,
        "mae_log": mae_log,
        "r2_log": r2_log,
        "r2_raw": r2_raw,
        "r2_pearson_raw": r2_pearson_raw,
        "nse_raw": nse_raw,
        "f1_10k": lambda a, b: f1_at(a, b, 10_000)["f1"],
        "f1_1k": lambda a, b: f1_at(a, b, 1_000)["f1"],
    }
    rows = []
    for name, p in preds.items():
        m = compute_all(
            obs,
            p,
            q10=q10c if name == "앙상블(채택)" else None,
            q90=q90c if name == "앙상블(채택)" else None,
            p10k=fin["clf_a"].to_numpy() if name == "앙상블(채택)" else None,
        )
        row = {"모델": name, "n": m["n"]}
        for k, fn in fns.items():
            ci = bootstrap_ci(obs, p, fn, n=args.boot, seed=42)
            row[k] = f"{m[k]:.3f} [{ci['lo']:.3f}, {ci['hi']:.3f}]"
        row["kge_log"] = round(m["kge_log"], 3)
        if "picp80" in m:
            row["PICP80(CQR)"] = round(m["picp80"], 3)
            row["MPIW80_log(CQR)"] = round(m["mpiw80_log"], 3)
            row["Brier_10k(분류기 a)"] = round(m["brier_10k"], 3)
        rows.append(row)
    hold = pd.DataFrame(rows)
    sens = (
        (EVAL / "tbl_sensitivity.md").read_text(encoding="utf-8")
        if (EVAL / "tbl_sensitivity.md").exists()
        else ""
    )
    _write(
        "tbl_holdout_2025.md",
        "2025 홀드아웃 — 모든 지표 + 부트스트랩 95% CI (1,000회, (site, base_date) 행 재표본)",
        "- **원단위 r2_raw·r2_pearson_raw·nse_raw 를 첫 줄에 그대로 보고**(docs/04 6.3). 2025 최대 "
        "관측 1건(회남 8/18, 194,194 cells/mL)이 "
        "2025 분산의 43% → 민감도 표(tbl_sensitivity.md) 병기. 모델 비교 검정은 tbl_stat_tests.md.\n\n"
        + _md(hold)
        + "\n\n## 민감도(원문 tbl_sensitivity.md 요약)\n"
        + "\n".join(
            ln
            for ln in sens.splitlines()
            if ln.startswith("|")
            and ("log_w_composite" in ln or ln.startswith("| study") or ln.startswith("|---"))
        ),
    )

    # ---- 2) CV 폴드 평균 ± 표준편차
    rows = []
    for name, col in MODELS.items():
        per = []
        for _y, g in cvm.groupby("year"):
            ok = np.isfinite(g[col])
            m = compute_all(
                g.loc[ok, "target_cells"].to_numpy(dtype=float), g.loc[ok, col].to_numpy(dtype=float)
            )
            per.append({k: m[k] for k in METRICS})
        per = pd.DataFrame(per)
        rows.append({"모델": name, **{k: f"{per[k].mean():.3f} ± {per[k].std():.3f}" for k in METRICS}})
    _write(
        "tbl_models_cv.md", "모델별 CV(F1~F5, valid 2020~2024) 폴드 평균 ± 표준편차", _md(pd.DataFrame(rows))
    )

    # ---- 4) 지점별·월별 (2025)
    rows = []
    for sid, g in fin.groupby("station_id"):
        for name in ("앙상블(채택)", "회귀 C1", "B0 지속성"):
            p = g[MODELS[name]].to_numpy(dtype=float)
            m = compute_all(g["target_cells"].to_numpy(dtype=float), p)
            rows.append(
                {
                    "station_id": sid,
                    "모델": name,
                    "n": m["n"],
                    **{k: m[k] for k in METRICS[:8]},
                    "비고": "표본 부족" if sid == "MGMR" else "",
                }
            )
    _write("tbl_by_site.md", "지점별 분해 (2025)", _md(pd.DataFrame(rows)))
    rows = []
    fin["month"] = fin["target_date"].dt.month
    for mo, g in fin.groupby("month"):
        for name in ("앙상블(채택)", "B0 지속성"):
            p = g[MODELS[name]].to_numpy(dtype=float)
            m = compute_all(g["target_cells"].to_numpy(dtype=float), p)
            rows.append(
                {
                    "월": int(mo),
                    "모델": name,
                    "n": m["n"],
                    **{k: m[k] for k in ("rmse_log", "mae_log", "r2_log", "f1_10k", "f1_1k")},
                }
            )
    _write("tbl_by_month.md", "월별 분해 (2025, target_date 월)", _md(pd.DataFrame(rows)))

    # ---- 7) 통계 검정
    elog = {name: np.log10(obs + 1) - np.log10(p + 1) for name, p in preds.items()}
    rows = []
    for a, b in (
        ("앙상블(채택)", "B0 지속성"),
        ("앙상블(채택)", "B4 ElasticNet"),
        ("회귀 C1", "B0 지속성"),
        ("회귀 C1", "B4 ElasticNet"),
        ("앙상블(채택)", "회귀 C1"),
    ):
        d = dm_test(elog[a], elog[b])
        w = wilcoxon_abs_err(elog[a], elog[b])
        rows.append(
            {
                "비교(모델1 vs 모델2)": f"{a} vs {b}",
                "n": d["n"],
                "DM 통계량(제곱 log 오차, HAC)": d["dm"],
                "DM p": d["p"],
                "평균 손실차": d["mean_d"],
                "Wilcoxon 통계량(|log 오차|)": w["stat"],
                "Wilcoxon p": w["p"],
                "중앙 |오차| 차": w["median_diff"],
            }
        )
    _write(
        "tbl_stat_tests.md",
        "통계 검정 (2025 홀드아웃)",
        "- DM: 음수 = 모델1 이 더 좋음(손실 = 제곱 log10 오차, HAC 분산, HLN 보정). Wilcoxon: "
        "|log10 오차| 부호순위.\n\n" + _md(pd.DataFrame(rows), 4),
    )

    # ---- 6) 피처 그룹 ablation — 회귀(채택 C1 파라미터) + 분류기(a) 진입 Recall
    cols = feature_sets()["perc75"]
    spec_c1 = spec_from_params(cfg["selected"]["params"], "log_w")
    clf_params = cfg["alert"]["over_target"]["params"]
    thr_a = cfg["thresholds"]["clf_a"]
    dfa = C.add_targets(df)
    years = pd.to_datetime(dfa["base_date"]).dt.year.to_numpy()
    cv_mask = (years >= 2020) & (years <= 2024)
    fin_mask = years == 2025
    s0 = (np.clip(10 ** dfa["cell_log_t0"].fillna(0).to_numpy(dtype=float) - 1, 0, None) >= T10K).astype(int)
    onset_cv = cv_mask & (s0 == 0) & (dfa["over_target"].to_numpy() == 1)
    onset_fin = fin_mask & (s0 == 0) & (dfa["over_target"].to_numpy() == 1)
    rows = []

    def one(label: str, use: list[str]) -> None:
        res = run_cv(dfa, use, spec_c1, bias_methods=("smearing",))
        f = res.folds[res.folds["bias"] == "smearing"]
        cvr = f[f["fold"] != "Final"]["rmse_log"].mean()
        finr = f[f["fold"] == "Final"]["rmse_log"].iloc[0]
        p, _ = C.cv_proba(dfa, use, "over_target", clf_params)
        al = p >= thr_a
        ya = dfa["over_target"].to_numpy()
        prauc_cv = C.cls_metrics(ya[cv_mask], p[cv_mask], thr_a)["pr_auc"]
        rows.append(
            {
                "구성": label,
                "피처 수": len(use),
                "CV rmse_log": cvr,
                "2025 rmse_log": finr,
                "분류기 CV PR-AUC": prauc_cv,
                "분류기 2025 F1": C.cls_metrics(ya[fin_mask], p[fin_mask], thr_a)["f1"],
                "진입 Recall CV": float(al[onset_cv].mean()),
                "진입 Recall 2025": float(al[onset_fin].mean()),
                "진입 n(CV/2025)": f"{int(onset_cv.sum())}/{int(onset_fin.sum())}",
            }
        )

    one("전체 30개", cols)
    for g in GROUPS:
        use = [c for c in cols if DEC.group_of(c) != g]
        one(f"− {g} ({DEC.GROUP_KO[g]})", use)
    abl = pd.DataFrame(rows)
    base = abl.iloc[0]
    hyd = abl[abl["구성"].str.startswith("− hydro")].iloc[0]
    _write(
        "tbl_ablation.md",
        "피처 그룹 ablation (채택 C1 파라미터 회귀 + 분류기(a) 임계 고정)",
        "- **수문(보·댐) 그룹 효과(제거 시 변화)**: "
        f"CV rmse_log {base['CV rmse_log']:.3f}→{hyd['CV rmse_log']:.3f}, "
        f"2025 rmse_log {base['2025 rmse_log']:.3f}→{hyd['2025 rmse_log']:.3f}; 진입 Recall CV "
        f"{base['진입 Recall CV']:.2f}→"
        f"{hyd['진입 Recall CV']:.2f}, 2025 {base['진입 Recall 2025']:.2f}→{hyd['진입 Recall 2025']:.2f}; "
        f"분류기 CV PR-AUC {base['분류기 CV PR-AUC']:.3f}→{hyd['분류기 CV PR-AUC']:.3f}. "
        "세포수 회귀 정확도에는 기여하나 진입 Recall 은 제거 시 오히려 오르므로 "
        "'융합의 가치' 는 회귀 정확도·리드타임 측면으로 서술한다.\n\n" + _md(abl),
    )

    # ---- 9) 잔차 진단 (앙상블, 2025)
    r = elog["앙상블(채택)"]
    plog = np.log10(preds["앙상블(채택)"] + 1)
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))
    axes[0].scatter(plog, r, s=10, alpha=0.5)
    axes[0].axhline(0, color="gray")
    axes[0].set_xlabel("예측 log10(cells+1)")
    axes[0].set_ylabel("잔차 (관측−예측, log10)")
    axes[0].set_title("잔차 vs 예측 (2025, 앙상블)")
    stats.probplot(r[np.isfinite(r)], dist="norm", plot=axes[1])
    axes[1].set_title("잔차 Q-Q")
    lb_rows = []
    for sid, g in fin.sort_values("target_date").groupby("station_id"):
        rr = np.log10(g["target_cells"].to_numpy() + 1) - np.log10(g["ens"].to_numpy() + 1)
        lb = ljung_box(rr, lags=4)
        lb_rows.append({"station_id": sid, **lb})
    lb_df = pd.DataFrame(lb_rows)
    axes[2].axis("off")
    axes[2].table(cellText=lb_df.round(3).values, colLabels=["지점", "n", "LB(4)", "p"], loc="center")
    axes[2].set_title("Ljung-Box(lag 4) 잔차 자기상관")
    fig.tight_layout()
    fig.savefig(EVAL / "fig_residuals.png", dpi=140)
    plt.close(fig)
    _write("tbl_residual_ljungbox.md", "잔차 Ljung-Box (2025, 지점별, lag 4)", _md(lb_df, 4))

    # ---- 10) SHAP 전역 + 진입 사례 5건
    import shap

    reg = json_load_registry()
    c1 = reg["members"]["회귀 C1(smearing)"] if reg.get("kind") == "ensemble" else reg
    model, cats = c1["model"], c1["cats"]
    feat = pd.read_parquet(D.PROCESSED / "features_S1.parquet")
    feat["base_date"] = pd.to_datetime(feat["base_date"])
    fv = feat[feat["split"] == "valid"].reset_index(drop=True)
    X = fv[cols].copy()
    for c in cats:
        X[c] = pd.Categorical(X[c].astype(str), categories=c1["categories"][c])
    expl = shap.TreeExplainer(model)
    sv = expl.shap_values(X)
    sv_df = pd.DataFrame(sv, columns=cols)
    fig = plt.figure(figsize=(9, 8))
    shap.summary_plot(sv, X, show=False, max_display=20)
    plt.title("SHAP 전역 (2025 검증, 회귀 C1, log10 기여)")
    plt.tight_layout()
    fig.savefig(EVAL / "fig_shap_global.png", dpi=140, bbox_inches="tight")
    plt.close("all")
    key = fv[["station_id", "base_date"]].assign(station_id=fv["station_id"].astype(str))
    fin_key = fin[["station_id", "base_date", "ens", "clf_a", "target_cells", "b0"]]
    merged = key.merge(fin_key, on=["station_id", "base_date"], how="left")
    onset = (merged["b0"] < T10K) & (merged["target_cells"] >= T10K)
    cases = merged[onset].sort_values("ens", ascending=False).head(5)
    fig, axes = plt.subplots(len(cases), 1, figsize=(10, 3.2 * max(len(cases), 1)))
    axes = np.atleast_1d(axes)
    case_rows = []
    for ax, (i, row) in zip(axes, cases.iterrows(), strict=False):
        contrib = sv_df.iloc[i].sort_values(key=np.abs, ascending=False).head(8)
        ax.barh(
            [f"{DEC.FEATURE_KO.get(f, f)}" for f in contrib.index][::-1],
            contrib.values[::-1],
            color=["tab:red" if v > 0 else "tab:blue" for v in contrib.values[::-1]],
        )
        ax.set_title(
            f"{row['station_id']} base {row['base_date'].date()} — 관측 {row['target_cells']:,.0f}, "
            f"예측 {row['ens']:,.0f}, p(≥10k) {row['clf_a']:.2f}"
        )
        ax.set_xlabel("SHAP 기여 (log10)")
        case_rows.append(
            {
                "station_id": row["station_id"],
                "base_date": row["base_date"].date(),
                "관측": row["target_cells"],
                "앙상블 예측": row["ens"],
                "p_over_10k": row["clf_a"],
                "담당자 문장": DEC.explain_sentence(sv_df.iloc[i]),
            }
        )
    fig.tight_layout()
    fig.savefig(EVAL / "fig_shap_cases.png", dpi=130)
    plt.close(fig)
    # 설비 배치 우선순위 데모: 2025 마지막 base_date 의 p_over(분류기 b OOF)
    last = fin.sort_values("base_date").groupby("station_id").tail(1).set_index("station_id")["clf_b"]
    prio = DEC.deployment_priority(last, as_of="2025 각 지점 마지막 base_date")
    _write(
        "tbl_decision_demo.md",
        "의사결정 변환 데모 — 진입 사례 설명 문장·설비 배치 우선순위",
        "## 진입 사례 5건 (2025)\n"
        + _md(pd.DataFrame(case_rows))
        + "\n\n## 설비 배치 우선순위 (단계 → p_alert 내림차순, 가중치 없음)\n"
        + _md(prio),
    )

    # ---- 11) 지점별 시계열
    for sid, g in fin.sort_values("target_date").groupby("station_id"):
        fig, ax = plt.subplots(figsize=(11, 4))
        idx = g.index
        ax.plot(g["target_date"], g["target_cells"], "k.-", label="관측")
        ax.plot(g["target_date"], g["ens"], "r.-", label="앙상블 예측")
        ax.fill_between(
            g["target_date"], q10c[idx], q90c[idx], color="tab:red", alpha=0.15, label="80% 구간(CQR)"
        )
        ax.axhline(10_000, ls="--", color="orange", label="경계 10,000")
        ax.axhline(1_000, ls=":", color="green", label="관심 1,000")
        ax.set_yscale("symlog", linthresh=100)
        # 세포수는 0 이상이다. 자동 여백이 음수 눈금을 만들지 않게 하한을 0 으로 두고,
        # 눈금은 천 단위 쉼표 정수로 표기한다(수학 기호 글리프 누락 방지).
        ax.set_ylim(bottom=0)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
        ax.set_title(f"{sid} 2025 — 관측 vs 7일 예측")
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(EVAL / f"fig_pred_vs_obs_{sid}.png", dpi=130)
        plt.close(fig)

    # ---- 8) 물모아 벤치마크 (누적분)
    bench = (
        pd.read_csv(EVAL / "live_benchmark.csv") if (EVAL / "live_benchmark.csv").exists() else pd.DataFrame()
    )
    if len(bench) < 10:
        body = (
            f"- 누적 중 (현재 n={len(bench)}): 물모아 AI 녹조 예측은 2026-10-19 발표분부터 "
            "스냅샷을 쌓고 있어 실측 도착 후 표가 채워진다(scripts/update_live_benchmark.py).\n"
            "- 비교 설계는 docs/04 6.4(단계 분류: 정확도, ≥2단계 P/R/F1, 혼동행렬). "
            "우리 모델 단계는 예측 세포수 → level_from_cells."
        )
    else:
        bench["level_ours"] = level_from_cells(bench.get("pred_cells", pd.Series(np.nan, index=bench.index)))
        body = _md(bench.head(50))
    _write("tbl_benchmark_nier.md", "물모아 벤치마크 — 경보 단계 분류 비교 (라이브 누적)", body)
    print(hold.to_string(index=False))
    print(abl.round(3).to_string(index=False))
    return 0


def json_load_registry() -> dict:
    import json

    reg = json.loads((MODELS_DIR / "registry.json").read_text(encoding="utf-8"))
    ver = reg["current"]["regression"]
    entry = next(e for e in reg["versions"] if e["name"] == "regression" and e["version"] == ver)
    with (MODELS_DIR / entry["name"] / entry["version"] / "model.pkl").open("rb") as f:
        return pickle.load(f)


if __name__ == "__main__":
    raise SystemExit(main())
