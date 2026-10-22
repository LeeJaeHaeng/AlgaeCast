# ruff: noqa: E501  (한국어 표·보고서 문자열)
"""EXP-005(2차) P4 보고 단계 — 측정 잡음 상한 표와 변형 학습·선택(r2nd_p4_kalman 의 실행 부분).

- ceiling_report(df, algae): 지점별 σ_ε² 추정(모형 5종 + 모형 없는 반변동 절편), 구간별 log·원단위 R² 상한,
  칼만 모형 내부 기대 R² 와 실제 값, 표준화 혁신 점검 → reports/experiments/EXP-005/P4/ceiling.{md,json}
- models_report(df, budget): 피처 묶음(+난수 대조군)·구성원 변형을 탐색 시드 5개로 학습 → CV 규칙으로 선택
  → tables.md·metrics.json, 선택 변형의 행 단위 OOF → data/processed/exp/EXP-005b/P4/chosen_oof.parquet

선택 규칙(2020~2024 CV OOF, 탐색 시드 평균, C 대비 시드 짝 차이)
- 적격: Δrmse_log(CV) ≤ +0.01, 리드타임 ≥ 18(분위 v1 동결이라 항상 18), 피처가 들어간 변형은 고유 효과(Δ − Δ대조군) > 0.
- 1단계: 피처 묶음 4개(kf3·kf5·kfd3·kfd5)와 구성원 6개(kf·kfd × 중앙값·로그정규 평균, 수준 의존 잡음 kflv·kfdlv 중앙값)
  중 각각 적격 최대 Δr2_raw. (kflv·kfdlv 는 1차 표를 본 뒤 잡음 진단(≤2024 자료)에 근거해 추가했다 — README 에 밝힘.)
- 2단계: 두 최선을 합친 변형(+ 그 대조군)을 돌린다. 최종 = 적격 변형 전체 중 Δr2_raw 최대(지속성 b0 는 참고, 선택 대상 아님).
- 2025(전체·1~8월·9~10월)는 확인용으로 표에만 싣는다.
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import asdict

import numpy as np
import pandas as pd

from algaecast.eval.metrics import compute_all
from algaecast.exp import confirm as CF
from algaecast.exp import harness as H
from algaecast.exp import harness2 as H2
from algaecast.exp import r2nd_p4_kalman as K

log = logging.getLogger(__name__)

RMSE_SLACK = 0.01
SCOPE_NAMES = dict(H2.SCOPES)
FEATURE_VARIANTS: tuple[str, ...] = ("P4_kf3", "P4_kf5", "P4_kfd3", "P4_kfd5")
MEMBER_VARIANTS: tuple[str, ...] = (
    "P4_kf_member",
    "P4_kf_member_mean",
    "P4_kfd_member",
    "P4_kfd_member_mean",
    "P4_kflv_member",
    "P4_kfdlv_member",
)
REFERENCE_VARIANTS: tuple[str, ...] = ("P4_b0_member",)


def _fmt(x: float, nd: int = 3, sign: bool = False) -> str:
    if x is None or not np.isfinite(x):
        return "–"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def _q(d: dict) -> str:
    return f"{d['mean']:.3f} / {d['median']:.3f} [{d['p05']:.3f}, {d['p95']:.3f}]"


def _lv(f: K.Fit) -> str:
    return f"{K.r_level(f.params, 3.0):.3f} / {K.r_level(f.params, 4.0):.3f} ({f.params.rho1:+.2f})"


def _md_table(rows: list[dict], cols: list[str]) -> str:
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "\n".join("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows) + "\n"


# ================================================================ 1. 잡음 상한
def _fits(algae: pd.DataFrame, model: str, year: int = 2025) -> dict[str, K.Fit]:
    return {sid: K.params_for_year(algae, sid, year, model) for sid in sorted(algae["station_id"].unique())}


def ceiling_report(df: pd.DataFrame, algae: pd.DataFrame) -> dict:
    """σ_ε² 추정과 구간별 상한. 매개변수는 ≤2024 측정(2025 폴드와 같은 학습 구간), 사전분포도 ≤2024 측정."""
    t0 = time.time()
    H.guard_no_2026(df)
    fits = {m: _fits(algae, m) for m in K.MODELS}
    sites = sorted(fits[K.MAIN_MODEL])
    ser = {
        s: [K.make_series(algae[(algae["station_id"] == s) & (algae["obs_date"] <= "2024-12-31")])]
        for s in sites
    }

    # --- 1-1. 지점별 σ_ε² (모형별) + 신뢰구간 + 반변동 절편
    nug = K.variogram_nugget(algae)
    sig_rows, sig_json = [], {}
    for s in sites:
        ci_l = K.hessian_ci_r(fits["lltemp"][s], ser[s], "lltemp")
        ci_d = K.hessian_ci_r(fits["damped"][s], ser[s], "damped")
        fl, fd = fits["lltemp"][s], fits["damped"][s]
        nobs = fl.n_obs
        aic = {m: 2 * fits[m][s].nll + 2 * len(fits[m][s].theta) for m in K.MODELS}
        rec = {
            "지점": s,
            "n(≤2024)": nobs,
            "σ²_ε lltemp [95%]": f"{fl.params.r:.3f} [{ci_l[0]:.3f}, {ci_l[1]:.3f}]",
            "q/일 lltemp": f"{fl.params.q:.4f}",
            "b1(/℃·일)": f"{fl.params.b1:+.5f}",
            "σ²_ε ll": f"{fits['ll'][s].params.r:.3f}",
            "σ²_ε lltemp_r2 5~10월/11~4월": f"{fits['lltemp_r2'][s].params.r:.3f} / {fits['lltemp_r2'][s].params.r_cold:.3f}",
            "σ²_ε damped [95%]": f"{fd.params.r:.3f} [{ci_d[0]:.3f}, {ci_d[1]:.3f}]",
            "φ/일 damped": f"{fd.params.phi:.4f}",
            "a1(/℃) damped": f"{fd.params.a1:+.3f}",
            "σ²_ε damped_r2 5~10월/11~4월": f"{fits['damped_r2'][s].params.r:.3f} / {fits['damped_r2'][s].params.r_cold:.3f}",
            "σ²_ε lltemp_lv @10³/@10⁴ (ρ1)": _lv(fits["lltemp_lv"][s]),
            "σ²_ε damped_lv @10³/@10⁴ (ρ1)": _lv(fits["damped_lv"][s]),
            "반변동 절편(6~10월)": _fmt(nug[s]["nugget"]),
            "γ(3~4일, 경보기 짝 n)": f"{nug[s]['gamma']['3-4']:.3f} (n={nug[s]['n_pairs']['3-4']})",
            "ΔAIC damped−lltemp": f"{aic['damped'] - aic['lltemp']:+.1f}",
        }
        sig_rows.append(rec)
        sig_json[s] = {
            "n_obs": nobs,
            "lltemp": {**asdict(fl.params), "r_ci95": list(ci_l), "nll": fl.nll},
            "damped": {**asdict(fd.params), "r_ci95": list(ci_d), "nll": fd.nll},
            **{
                m: {**asdict(fits[m][s].params), "nll": fits[m][s].nll}
                for m in ("ll", "lltemp_r2", "damped_r2", "lltemp_lv", "damped_lv")
            },
            "aic": aic,
            "variogram": nug[s],
        }

    # --- 1-2. 연도별 안정성(매개변수 연도 = 그 해 기준일 행에 쓰는 값)
    stab = []
    for m in ("lltemp", "damped"):
        for s in sites:
            r = {"모형": m, "지점": s}
            for y in range(2018, 2026):
                f = K.params_for_year(algae, s, y, m)
                r[str(y)] = (
                    "–" if f is None else (f"{f.params.r:.3f}" + ("*" if f.source == "pooled" else ""))
                )
            stab.append(r)

    # --- 1-3. 구간별 상한
    masks = H2.scope_masks(df)
    prior = K._site_month_prior(algae)
    sources: dict[str, np.ndarray] = {
        m: K.sigma2_rows(df, fits[m])
        for m in ("lltemp", "damped", "lltemp_r2", "damped_r2", "lltemp_lv", "damped_lv")
    }
    sid = df["station_id"].astype(str).to_numpy()
    sources["nugget"] = np.array([max(nug[s]["nugget"], 1e-4) for s in sid])
    # 고수준 잡음 상한 시나리오: 목표값 ≥ 10³ 인 행은 min(lltemp σ², 경보기 3~4일 짝 반변동 γ) — γ ≥ σ² 이므로 보수적
    g34 = np.array([nug[s]["gamma"]["3-4"] for s in sid])
    hi = np.log10(df["target_cells"].to_numpy(dtype=float) + 1) >= 3
    sources["gamma34_hi"] = np.where(hi, np.minimum(sources["lltemp"], g34), sources["lltemp"])
    ceil: dict = {}
    for src, s2 in sources.items():
        ceil[src] = {}
        for key, m in masks.items():
            c = K.ceiling_sim(df, m, s2, prior, n_sim=4000 if src in ("lltemp", "damped") else 1000)
            c["obs_as_truth_raw"] = K.obs_as_truth_raw(
                df, m, s2, n_sim=4000 if src in ("lltemp", "damped") else 1000
            )
            ceil[src][key] = c

    # --- 1-4. 칼만 모형 내부 기대 vs 실제, C(탐색 시드 평균) 참고
    obs = df["target_cells"].to_numpy(dtype=float)
    ell = np.log10(obs + 1)
    c_rows = H2.baseline_c(df)
    c_mean = H2.mean_rows(c_rows, "C")
    ladder = []
    for key, m in masks.items():
        sst = float(np.sum((ell[m] - ell[m].mean()) ** 2))
        row = {"구간": SCOPE_NAMES[key], "n": int(m.sum())}
        for mod in ("lltemp", "damped"):
            kk = K.load_kf(df, mod)
            exp_sse = float(np.sum(kk["kf_obsvarh"].to_numpy(dtype=float)[m]))
            pr = K.kf_member(df, "median", mod)
            real = compute_all(obs[m], pr[m])
            row[f"{mod}_log_expected"] = 1 - exp_sse / sst
            row[f"{mod}_log_real"] = real["r2_log"]
            row[f"{mod}_raw_real"] = real["r2_raw"]
            row[f"{mod}_rmse_log"] = real["rmse_log"]
        row["C_r2_log"] = c_mean[f"{key}_r2_log"]
        row["C_r2_raw"] = c_mean[f"{key}_r2_raw"]
        row["C_rmse_log"] = c_mean[f"{key}_rmse_log"]
        ladder.append(row)

    # --- 1-5. 표준화 혁신 점검(≤2024 매개변수로 2025 까지 필터)
    innov = {m: K.innovation_check(algae, fits[m]) for m in ("lltemp", "damped")}

    # --- 표 작성
    lines = ["# P4 측정 잡음 상한 — 자동 생성 표(손으로 고치지 않음)\n"]
    lines.append("매개변수·사전분포: obs_date ≤ 2024-12-31 측정(2025 폴드 학습 구간). 2026 은 읽지 않았다.\n")
    lines.append("## 1. 지점별 측정 잡음 분산 σ_ε²(log10(세포수+1) 단위)\n")
    lines.append(_md_table(sig_rows, list(sig_rows[0])))
    lines.append("\n## 2. σ_ε² 연도별 안정성(매개변수 연도 Y = ≤ Y−1 측정, * = 공통 매개변수)\n")
    lines.append(_md_table(stab, list(stab[0])))
    lines.append("\n## 3. 구간별 상한(진짜 상태를 아는 완벽한 모형의 기대 R²)\n")
    for src in sources:
        rows = []
        for key in masks:
            c = ceil[src][key]
            rows.append(
                {
                    "구간": SCOPE_NAMES[key],
                    "n": c["n"],
                    "Var(log y)": _fmt(c["var_log"]),
                    "평균 σ²_ε": _fmt(c["mean_sigma2"]),
                    "log R² 상한(해석식)": _fmt(c["log_analytic"]),
                    "log R² 모의 B": f"{c['B_log']['mean']:.3f} [{c['B_log']['p05']:.3f}, {c['B_log']['p95']:.3f}]",
                    "원단위 A(합성, 주) 평균 / 중앙값 [5%, 95%]": _q(c["A_raw_condmean"]),
                    "원단위 B(조건부) 평균 / 중앙값 [5%, 95%]": _q(c["B_raw_condmean"]),
                    "원단위 B(중앙값 예측)": f"{c['B_raw_median']['mean']:.3f}",
                    "원단위 관측=진짜(낙관) 평균 / 중앙값": f"{c['obs_as_truth_raw']['mean']:.3f} / {c['obs_as_truth_raw']['median']:.3f}",
                    "최대 1행 SST 비중": _fmt(c["top1_share_sst_raw"]),
                }
            )
        lines.append(f"\n### σ²_ε 출처: {src}\n\n" + _md_table(rows, list(rows[0])))
    lines.append(
        "\n## 4. 칼만 모형 내부 기대 R²(σ²_ε + 7일 상태 분산) vs 실제, 기준 모델 C(탐색 시드 평균)\n"
    )
    lr = [
        {
            "구간": r["구간"],
            "n": r["n"],
            "lltemp 기대 log R²": _fmt(r["lltemp_log_expected"]),
            "lltemp 실제 log R²": _fmt(r["lltemp_log_real"]),
            "lltemp 실제 원단위 R²": _fmt(r["lltemp_raw_real"]),
            "damped 기대 log R²": _fmt(r["damped_log_expected"]),
            "damped 실제 log R²": _fmt(r["damped_log_real"]),
            "damped 실제 원단위 R²": _fmt(r["damped_raw_real"]),
            "C log R²": _fmt(r["C_r2_log"]),
            "C 원단위 R²": _fmt(r["C_r2_raw"]),
        }
        for r in ladder
    ]
    lines.append(_md_table(lr, list(lr[0])))
    lines.append("\n## 5. 표준화 혁신² 평균(모형이 맞으면 1, ≤2024 매개변수)\n")
    for m, t in innov.items():
        piv = t.pivot(index="지점", columns="구간", values="z2_mean").round(3).reset_index()
        nn = t.pivot(index="지점", columns="구간", values="n").reset_index()
        rows = []
        for (_, a), (_, b) in zip(piv.iterrows(), nn.iterrows(), strict=True):
            rows.append(
                {"지점": a["지점"], **{c: f"{a[c]:.3f} (n={int(b[c])})" for c in piv.columns if c != "지점"}}
            )
        lines.append(f"\n### {m}\n\n" + _md_table(rows, list(rows[0])))
    txt = "\n".join(lines)
    K.OUT_REPORT.mkdir(parents=True, exist_ok=True)
    (K.OUT_REPORT / "ceiling.md").write_text(txt, encoding="utf-8")
    out = {
        "sigma2": sig_json,
        "ceiling": ceil,
        "ladder": ladder,
        "innovation": {m: t.to_dict("records") for m, t in innov.items()},
    }
    H2.write_json(K.OUT_REPORT / "ceiling.json", out)
    log.info("상한 표 %.0fs", time.time() - t0)
    return out


# ================================================================ 2. 변형 학습·선택
def _const_rows(df: pd.DataFrame, pred: np.ndarray, label: str) -> tuple[list[dict], dict]:
    """시드와 무관한 예측(칼만 단독) → 시드마다 같은 행(짝 차이 계산용)."""
    r = H2.metric_row2(df, pred, None, label)
    rows = [{**r, "seed": s} for s in H2.EXPLORE_SEEDS]
    return rows, H2.mean_rows(rows, label)


def _record(name: str, res: dict, base_rows: list[dict]) -> dict:
    rows, mean = res[name]
    ctrl = K.control_of(name) if name.startswith("P4_") else None
    ctrl_rows = res[ctrl][0] if ctrl and ctrl in res else None
    d = {
        k: H2.paired_delta(rows, base_rows, k)
        for k in ("cv_r2_raw", "cv_rmse_log", "y25_r2_raw", "y25_rmse_log", "y25b_rmse_log", "cvfold_r2_raw")
    }
    rec = {
        "name": name,
        "label": mean["구성"],
        "cv_r2_raw": mean["cv_r2_raw"],
        "cv_r2_raw_min": mean["cv_r2_raw_min"],
        "cv_r2_raw_max": mean["cv_r2_raw_max"],
        **{f"d_{k}": v for k, v in d.items()},
        "lead": mean["lead_q90"],
        "ctrl": ctrl,
        "d_ctrl": H2.paired_delta(rows, ctrl_rows, "cv_r2_raw") if ctrl_rows else math.nan,
        "explore": H2.explore_check(mean, rows, base_rows, ctrl_rows),
    }
    # 고유 효과 = Δ(피처) − Δ(대조군) = 같은 시드 짝 (후보 − 대조군) 평균
    rec["unique"] = rec["d_ctrl"]
    rec["ok_rmse"] = bool(rec["d_cv_rmse_log"] <= RMSE_SLACK + 1e-12)
    rec["ok_lead"] = bool(rec["lead"] >= 18.0 - 1e-9)
    rec["ok_ctrl"] = bool(rec["unique"] > 0) if ctrl else True
    rec["eligible"] = bool(rec["ok_rmse"] and rec["ok_lead"] and rec["ok_ctrl"])
    return rec


def _best(recs: list[dict]) -> dict | None:
    el = [r for r in recs if r["eligible"]]
    return max(el, key=lambda r: r["d_cv_r2_raw"]) if el else None


def year_r2(df: pd.DataFrame, pred: np.ndarray) -> dict[int, float]:
    obs = df["target_cells"].to_numpy(dtype=float)
    yrs = H.years_of(df)
    return {int(y): float(compute_all(obs[yrs == y], pred[yrs == y])["r2_raw"]) for y in H.CV_YEARS}


def models_report(df: pd.DataFrame, budget: H.Budget) -> dict:
    t0 = time.time()
    H.guard_no_2026(df)
    base_rows = H2.baseline_c(df)
    c_mean = H2.mean_rows(base_rows, "C(기준 모델)")
    res: dict[str, tuple[list[dict], dict]] = {}
    # 1단계: 피처 묶음 + 대조군, 구성원, 참고
    stage1: list[str] = []
    for f in FEATURE_VARIANTS:
        stage1 += [f, K.control_of(f)]
    stage1 += list(MEMBER_VARIANTS) + list(REFERENCE_VARIANTS)
    res.update(K.run_variants(df, stage1, budget))
    recs = {n: _record(n, res, base_rows) for n in res}
    best_f = _best([recs[n] for n in FEATURE_VARIANTS])
    best_m = _best([recs[n] for n in MEMBER_VARIANTS])
    stage2: list[str] = []
    if best_f and best_m:
        combo = f"{best_f['name']}+{best_m['name'][3:]}"
        stage2 = [combo, K.control_of(combo)]
        res.update(K.run_variants(df, stage2, budget))
        for n in stage2:
            recs[n] = _record(n, res, base_rows)
    # 칼만 단독(시드 무관, 참고)
    solo = {}
    for mod in ("lltemp", "damped"):
        nm = f"칼만 단독({K.MODEL_LABEL[mod]}, 중앙값)"
        solo[nm] = _const_rows(df, K.kf_member(df, "median", mod), nm)
    # 최종 선택(CV 규칙)
    cands = [
        recs[n]
        for n in [*FEATURE_VARIANTS, *MEMBER_VARIANTS, *[s for s in stage2 if not K.parse_variant(s)[1]]]
    ]
    chosen = _best(cands)
    chosen_name = chosen["name"] if chosen else None
    if chosen_name and chosen_name != K.CHOSEN["variant"]:
        log.warning(
            "CV 선택 %s 가 CHOSEN 상수(%s)와 다르다 — 상수를 고칠 것", chosen_name, K.CHOSEN["variant"]
        )

    # 표준 표
    order = ["C"]
    for f in FEATURE_VARIANTS:
        order += [f, K.control_of(f)]
    order += list(MEMBER_VARIANTS) + list(REFERENCE_VARIANTS) + stage2
    entries = [(c_mean, base_rows)] + [(res[n][1], res[n][0]) for n in order[1:]]
    entries += [(m, r) for r, m in solo.values()]
    std_tab = H2.table2(entries, base_rows)

    # 요약 표
    srows = []
    for n in order[1:]:
        r = recs[n]
        ex = r["explore"]
        srows.append(
            {
                "변형": f"`{n}`",
                "구성": r["label"],
                "CV r2_raw 평균 [최소, 최대]": f"{r['cv_r2_raw']:.3f} [{r['cv_r2_raw_min']:.3f}, {r['cv_r2_raw_max']:.3f}]",
                "ΔC r2_raw": _fmt(r["d_cv_r2_raw"], sign=True),
                "고유 효과(−대조군)": _fmt(r["unique"], sign=True) if r["ctrl"] else "–",
                "ΔC rmse_log": _fmt(r["d_cv_rmse_log"], 4, True),
                "ΔC 폴드평균 r2_raw": _fmt(r["d_cvfold_r2_raw"], sign=True),
                "ΔC 2025 r2_raw": _fmt(r["d_y25_r2_raw"], sign=True),
                "ΔC 2025 rmse_log": _fmt(r["d_y25_rmse_log"], 4, True),
                "ΔC 2025 9~10월 rmse_log": _fmt(r["d_y25b_rmse_log"], 4, True),
                "리드": f"{r['lead']:.1f}",
                "CV 적격": "예" if r["eligible"] else "아니오",
                "탐색 판정(explore_check)": "충족" if ex["meets_explore"] else "미충족",
            }
        )
    sum_tab = _md_table(srows, list(srows[0]))

    # NNLS 가중치(구성원 변형, 시드 평균)
    wrows = []
    for n in [*MEMBER_VARIANTS, *REFERENCE_VARIANTS, *stage2]:
        mem = K.MEMBER_NAME[K.parse_variant(n)[2]]
        r = {"변형": f"`{n}`", "구성원": mem}
        for y in (*H.CV_YEARS, 2025):
            ws = [
                float(H2.run_cached(df, n, s, K.variant_builder(n))[f"w{y}_{mem}"][0])
                for s in H2.EXPLORE_SEEDS
            ]
            r[str(y)] = f"{np.mean(ws):.3f}"
        wrows.append(r)
    w_tab = _md_table(wrows, list(wrows[0]))

    # 연도별 CV r2_raw(C vs 선택), 블록 부트스트랩(탐색 시드, 참고)
    boot = None
    yr_tab = ""
    if chosen_name:
        c_preds = [H2.run_cached(df, "C", s, H2.c_pred)["pred"] for s in H2.EXPLORE_SEEDS]
        x_preds = [
            H2.run_cached(df, chosen_name, s, K.variant_builder(chosen_name))["pred"]
            for s in H2.EXPLORE_SEEDS
        ]
        lo, hi, med = CF.bootstrap_ci(df, x_preds, c_preds)
        boot = {"ci95": [lo, hi], "median": med}
        yc = [year_r2(df, p) for p in c_preds]
        yx = [year_r2(df, p) for p in x_preds]
        yrows = [
            {
                "연도": y,
                "C": _fmt(float(np.mean([d[y] for d in yc]))),
                chosen_name: _fmt(float(np.mean([d[y] for d in yx]))),
                "Δ": _fmt(float(np.mean([a[y] - b[y] for a, b in zip(yx, yc, strict=True)])), sign=True),
            }
            for y in H.CV_YEARS
        ]
        yr_tab = _md_table(yrows, list(yrows[0]))
        oof = {f"pred_s{s}": p for s, p in zip(H2.EXPLORE_SEEDS, x_preds, strict=True)}
        oof.update({f"C_s{s}": p for s, p in zip(H2.EXPLORE_SEEDS, c_preds, strict=True)})
        H.save_oof(df, oof, K.OUT_DATA / "chosen_oof.parquet")

    txt = (
        "# P4 변형 표 — 자동 생성(손으로 고치지 않음)\n\n"
        f"탐색 시드 {list(H2.EXPLORE_SEEDS)} 평균, 분위 v1 동결(q90). ΔC = 같은 시드 C 대비 짝 차이 평균. 2025 는 목표일 2025 행만(252행).\n\n"
        "## 1. 표준 표(harness2.table2)\n\n"
        + std_tab
        + "\n## 2. 요약·선택(CV 규칙)\n\n"
        + sum_tab
        + f"\n1단계 최선 피처 묶음: {best_f['name'] if best_f else '없음(적격 없음)'}, 최선 구성원: {best_m['name'] if best_m else '없음(적격 없음)'}.\n"
        + f"최종 선택: **{chosen_name or '없음'}**"
        + (f" (블록 부트스트랩 95% [{boot['ci95'][0]:+.3f}, {boot['ci95'][1]:+.3f}])" if boot else "")
        + "\n"
        + "\n## 3. 연도 확장 NNLS 가중치(추가 구성원, 시드 평균)\n\n"
        + w_tab
        + ("\n## 4. 연도별 CV r2_raw(시드 평균)\n\n" + yr_tab if yr_tab else "")
    )
    (K.OUT_REPORT / "tables.md").write_text(txt, encoding="utf-8")
    metrics = {
        "C": {"mean": c_mean, "seed_rows": base_rows},
        "variants": {n: {"mean": res[n][1], "seed_rows": res[n][0], "record": recs[n]} for n in res},
        "solo_kalman": {k: {"mean": m, "row": r[0]} for k, (r, m) in solo.items()},
        "stage1_best_feature": best_f["name"] if best_f else None,
        "stage1_best_member": best_m["name"] if best_m else None,
        "chosen": chosen_name,
        "chosen_record": chosen,
        "bootstrap_explore": boot,
        "minutes": round((time.time() - t0) / 60, 1),
        "elapsed_h_total": budget.elapsed_h,
    }
    metrics["ceiling_summary"] = ceiling_summary()
    H2.write_json(K.OUT_REPORT / "metrics.json", metrics)
    print(txt)
    return metrics


def ceiling_summary() -> dict | None:
    """ceiling.json → 요약(σ²_ε 출처별·구간별 log 상한, 원단위 상한 A·관측=진짜, 모형 AIC 합)."""
    p = K.OUT_REPORT / "ceiling.json"
    if not p.exists():
        return None
    c = json.loads(p.read_text(encoding="utf-8"))
    out: dict = {"aic_total_minus_lltemp": {}, "by_source": {}}
    aic = pd.DataFrame({s: v["aic"] for s, v in c["sigma2"].items()}).T
    tot = aic.sum()
    out["aic_total_minus_lltemp"] = {m: float(tot[m] - tot["lltemp"]) for m in tot.index}
    for src, by in c["ceiling"].items():
        out["by_source"][src] = {
            key: {
                "log_ceiling": v["log_analytic"],
                "raw_ceiling_A_mean": v["A_raw_condmean"]["mean"],
                "raw_ceiling_A_median": v["A_raw_condmean"]["median"],
                "raw_ceiling_A_p05": v["A_raw_condmean"]["p05"],
                "raw_ceiling_A_p95": v["A_raw_condmean"]["p95"],
                "raw_obs_as_truth_mean": v["obs_as_truth_raw"]["mean"],
                "mean_sigma2": v["mean_sigma2"],
            }
            for key, v in by.items()
        }
    return out
