"""T4-b 실험 러너: 튜닝 결과(JSON) 로 변형·보정·피처세트·결측전략·민감도 비교표와 EXP 기록을 만든다.

입력: data/processed/optuna/*.json (models/tune.py), 피처 파일(S1/S2/S3)
출력: reports/eval/tbl_model_variants.md, tbl_bias_correction.md, tbl_feature_sets.md,
      tbl_missing_strategy.md,
      tbl_sensitivity.md, tbl_seed_revalidation.md, reports/experiments/EXP-001~.md, config/model.yaml(채택안)
사용: python -m algaecast.models.experiments [--seeds 42,7,2026]
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date

import numpy as np
import pandas as pd
import yaml

from algaecast.config import CONFIG_DIR, ROOT
from algaecast.eval.metrics import compute_all
from algaecast.models import data as D
from algaecast.models.baselines import b0_persistence
from algaecast.models.cv import fold_frames, year_folds
from algaecast.models.train import (
    BIAS_METHODS,
    CVResult,
    feature_sets,
    run_cv,
    summarize_cv,
)
from algaecast.models.tune import OUT_DIR as OPTUNA_DIR
from algaecast.models.tune import spec_from_params

log = logging.getLogger(__name__)
EVAL = ROOT / "reports" / "eval"
EXP = ROOT / "reports" / "experiments"
RAW_METRICS = ["rmse_log", "mae_log", "r2_log", "r2_raw", "r2_pearson_raw", "nse_raw", "f1_10k"]
VARIANT_KO = {
    "log_w": "C1 log+가중",
    "tweedie": "C2 tweedie/poisson",
    "hurdle": "C3 hurdle",
    "ens": "C4 C1·C2 앙상블",
}


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


def load_studies() -> dict[str, dict]:
    out = {}
    for p in sorted(OPTUNA_DIR.glob("*.json")):
        j = json.loads(p.read_text(encoding="utf-8"))
        out[j["study"]] = j
    return out


def row_from(res: CVResult, bias: str, label: dict) -> dict:
    s = summarize_cv(res, bias)
    r = {**label, "bias": bias}
    r.update({f"cv_{k}": s[f"cv_{k}"] for k in RAW_METRICS})
    r.update({f"final_{k}": s.get(f"final_{k}", np.nan) for k in RAW_METRICS})
    return r


def sensitivity_2025(res: CVResult, df: pd.DataFrame, bias: str) -> dict:
    """2025 Final 에서 최대 관측 1건 제외 / 지점별 최대 1건씩 제외 시 원단위 지표."""
    y = pd.to_datetime(df["base_date"]).dt.year.to_numpy()
    idx = np.where(y == 2025)[0]
    obs = df["target_cells"].to_numpy(dtype=float)[idx]
    pred = res.oof[bias][idx]
    full = compute_all(obs, pred)
    drop1 = np.argsort(obs)[::-1][:1]
    m1 = compute_all(np.delete(obs, drop1), np.delete(pred, drop1))
    sites = df["station_id"].astype(str).to_numpy()[idx]
    keep = np.ones(len(idx), bool)
    for s in np.unique(sites):
        k = np.where(sites == s)[0]
        keep[k[np.argmax(obs[k])]] = False
    m5 = compute_all(obs[keep], pred[keep])
    return {
        "max_obs": float(obs.max()),
        "max_obs_site": str(sites[int(np.argmax(obs))]),
        "pred_at_max": float(pred[int(np.argmax(obs))]),
        **{f"full_{k}": full[k] for k in ("r2_raw", "r2_pearson_raw", "nse_raw", "rmse_log")},
        **{f"drop1_{k}": m1[k] for k in ("r2_raw", "r2_pearson_raw", "nse_raw", "rmse_log")},
        **{f"drop_site_max_{k}": m5[k] for k in ("r2_raw", "r2_pearson_raw", "nse_raw", "rmse_log")},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", default="42,7,2026")
    ap.add_argument("--skip-seed-reval", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    seeds = tuple(int(s) for s in args.seeds.split(","))
    studies = load_studies()
    if not studies:
        raise SystemExit("optuna 결과 없음 — models.tune 먼저")
    fs = feature_sets()
    df1 = D.load_train_valid("S1")
    EVAL.mkdir(parents=True, exist_ok=True)
    EXP.mkdir(parents=True, exist_ok=True)

    # ---- 1) 변형 × 보정 (각 study 의 best, 피처 perc75/S1, 시드 1개)
    rows, sens_rows, site_rows = [], [], []
    results: dict[str, CVResult] = {}
    for name, st in studies.items():
        if st["feature_set"] != "perc75" or st["strategy"] != "S1":
            continue
        spec = spec_from_params(st["best_params"], st["variant"])
        res = run_cv(df1, fs["perc75"], spec)
        results[name] = res
        for b in BIAS_METHODS:
            rows.append(
                row_from(res, b, {"study": name, "변형": VARIANT_KO[st["variant"]], "목적": st["objective"]})
            )
            sens_rows.append(
                {
                    "study": name,
                    "변형": VARIANT_KO[st["variant"]],
                    "목적": st["objective"],
                    "bias": b,
                    **sensitivity_2025(res, df1, b),
                }
            )
        bs = res.by_site[res.by_site["fold"] == "Final"]
        for b in BIAS_METHODS:
            for r in bs[bs["bias"] == b].itertuples():
                site_rows.append(
                    {
                        "study": name,
                        "bias": b,
                        "station_id": r.station_id,
                        "n": r.n,
                        **{k: getattr(r, k) for k in RAW_METRICS},
                    }
                )
        log.info("%s 완료", name)
    variants = pd.DataFrame(rows)
    sens = pd.DataFrame(sens_rows)
    by_site = pd.DataFrame(site_rows)
    # 베이스라인 B0 (2025) 비교 행
    folds = year_folds(df1, include_final=True)
    fin = [f for f in folds if f.name == "Final"][0]
    tr1, va = fold_frames(df1, fin)
    b0 = compute_all(va["target_cells"].to_numpy(dtype=float), b0_persistence(tr1, va))

    # 채택: 2025 Final 이 아닌 **CV** 기준 — 복합 점수 J 최소 (bias 포함)
    variants["J_cv"] = 0.5 * variants["cv_rmse_log"] / 0.83 + 0.5 * (1 - variants["cv_r2_raw"].clip(-1, 1))
    best = variants.sort_values("J_cv").iloc[0]
    best_study = studies[best["study"]]

    # ---- 2) 시드 재검증: 각 study 상위 5 × 시드 3
    seed_rows = []
    if not args.skip_seed_reval:
        for name, st in studies.items():
            if st["feature_set"] != "perc75" or st["strategy"] != "S1":
                continue
            for t in st["top5"]:
                spec = spec_from_params(t["params"], st["variant"])
                res = run_cv(df1, fs["perc75"], spec, seeds=seeds, include_final=True)
                s = summarize_cv(res, "smearing")
                seed_rows.append(
                    {
                        "study": name,
                        "trial": t["number"],
                        "tune_value": round(t["value"], 4),
                        "cv_rmse_log(3시드)": s["cv_rmse_log"],
                        "cv_r2_raw(3시드)": s["cv_r2_raw"],
                        "final_rmse_log": s["final_rmse_log"],
                        "final_r2_raw": s["final_r2_raw"],
                        "final_nse_raw": s["final_nse_raw"],
                        "final_f1_10k": s["final_f1_10k"],
                    }
                )
    seed_df = pd.DataFrame(seed_rows)

    # ---- 3) 피처 세트 E (채택 변형·파라미터)
    best_spec = spec_from_params(best_study["best_params"], best_study["variant"])
    fs_rows = []
    for fname, cols in fs.items():
        res = run_cv(df1, cols, best_spec)
        fs_rows.append(
            {
                "피처 세트": fname,
                "피처 수": len(cols),
                **{k: v for k, v in row_from(res, best["bias"], {}).items() if k != "bias"},
            }
        )
    fs_df = pd.DataFrame(fs_rows)

    # ---- 4) 결측 전략 F
    st_rows = []
    for s in ("S1", "S2", "S3"):
        try:
            d = D.load_train_valid(s)
        except FileNotFoundError:
            continue
        res = run_cv(d, fs["perc75"], best_spec)
        st_rows.append(
            {
                "전략": s,
                "n": len(d),
                **{k: v for k, v in row_from(res, best["bias"], {}).items() if k != "bias"},
            }
        )
    st_df = pd.DataFrame(st_rows)

    # ---- 저장
    hdr_note = (
        f"- 폴드 F1~F5(train ≤2019~2023 → valid 2020~2024) 평균 = cv_*, Final(train ≤2024 → 2025) = final_*. "
        "test(2026) 미접근. 지표 정의: docs/04 6.1 (r2_raw=sklearn 결정계수 = NSE(대회 공식 R² 아님), "
        "r2_pearson_raw=상관² = 대회 공식 R²(공식 Q&A 2026-10-30 ②)).\n"
        f"- B0 지속성 2025: rmse_log {b0['rmse_log']:.3f}, r2_raw {b0['r2_raw']:.3f}, "
        f"r2_pearson_raw {b0['r2_pearson_raw']:.3f}, "
        f"nse_raw {b0['nse_raw']:.3f}, F1@10k {b0['f1_10k']:.3f}\n"
    )
    (EVAL / "tbl_model_variants.md").write_text(
        "# T4-b 변형 × 역변환 보정 비교 (perc75, S1)\n\n"
        + hdr_note
        + f"- **채택(CV 복합점수 J 최소)**: {best['study']} / bias={best['bias']} (J={best['J_cv']:.4f})\n\n"
        + _md(variants.sort_values("J_cv"))
        + "\n\n## 지점별 — Final(2025)\n"
        + _md(by_site)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    bias_tbl = variants.pivot_table(
        index=["study"],
        columns="bias",
        values=["final_r2_raw", "final_nse_raw", "final_rmse_log", "cv_r2_raw"],
    )
    bias_tbl.columns = [f"{a}:{b}" for a, b in bias_tbl.columns]
    (EVAL / "tbl_bias_correction.md").write_text(
        "# 역변환 편향 보정 비교 (none / Duan smearing / isotonic(이전 폴드 OOF))\n\n"
        + hdr_note
        + "\n"
        + _md(bias_tbl.reset_index())
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (EVAL / "tbl_feature_sets.md").write_text(
        "# 피처 세트 비교 (채택 변형·파라미터, S1)\n\n" + hdr_note + "\n" + _md(fs_df) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (EVAL / "tbl_missing_strategy.md").write_text(
        "# 결측 전략 S1/S2/S3 비교 (채택 변형·파라미터, perc75)\n\n" + hdr_note + "\n" + _md(st_df) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (EVAL / "tbl_sensitivity.md").write_text(
        "# 2025 원단위 지표 민감도 — 최대 관측 1건 제외 / 지점별 최대 1건씩 제외\n\n"
        + hdr_note
        + "\n"
        + _md(sens)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if len(seed_df):
        (EVAL / "tbl_seed_revalidation.md").write_text(
            f"# 상위 5 trial × 시드 {seeds} 재검증 (smearing)\n\n" + _md(seed_df) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    # config/model.yaml
    model_cfg = {
        "selected": {
            "study": best["study"],
            "variant": best_study["variant"],
            "objective": best_study["objective"],
            "bias": best["bias"],
            "feature_set": "perc75",
            "strategy": "S1",
            "params": best_study["best_params"],
            "cv": {k: round(float(best[f"cv_{k}"]), 4) for k in RAW_METRICS},
            "final_2025": {k: round(float(best[f"final_{k}"]), 4) for k in RAW_METRICS},
            "decided_on": str(date.today()),
        },
        "studies": {
            k: {"best_value": v["best_value"], "n_complete": v["n_complete"], "best_params": v["best_params"]}
            for k, v in studies.items()
        },
    }
    (CONFIG_DIR / "model.yaml").write_text(
        yaml.safe_dump(model_cfg, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8"
    )
    # EXP 기록
    exp_lines = [
        "# EXP-001 T4-b LightGBM 변형·보정·튜닝 (" + str(date.today()) + ")",
        "",
        "## 설정",
        "- 데이터: features_S1 (train 2,310 / valid 256), 피처 perc75 30개, 폴드 docs/04 §2, 시드 42",
        "- 튜닝: Optuna TPE(multivariate)+MedianPruner, 목적 rmse_log / "
        "복합 J=0.5·rmse_log/0.83+0.5·(1−clip(r2_raw)), 보정 smearing 기준",
        *[
            f"  - {k}: {v['n_complete']} complete / {v['n_pruned']} pruned, {v['elapsed_min']} min, "
            f"best {v['best_value']:.4f} (rmse_log {v['best_attrs'].get('rmse_log', float('nan')):.4f}, "
            f"r2_raw {v['best_attrs'].get('r2_raw', float('nan')):.3f})"
            for k, v in studies.items()
        ],
        "",
        "## 결과 표",
        "- reports/eval/tbl_model_variants.md, tbl_bias_correction.md, tbl_feature_sets.md, "
        "tbl_missing_strategy.md, tbl_sensitivity.md, tbl_seed_revalidation.md",
        "",
        "## 채택",
        f"- {best['study']} / bias {best['bias']} — CV rmse_log {best['cv_rmse_log']:.3f}, "
        f"CV r2_raw {best['cv_r2_raw']:.3f}; "
        f"Final 2025 rmse_log {best['final_rmse_log']:.3f}, r2_raw {best['final_r2_raw']:.3f}, "
        f"r2_pearson_raw {best['final_r2_pearson_raw']:.3f}, nse_raw {best['final_nse_raw']:.3f}, "
        f"F1@10k {best['final_f1_10k']:.3f} (B0 {b0['f1_10k']:.3f})",
        "- 채택 기준은 2025 Final 이 아닌 CV 복합점수(홀드아웃 과적합 방지). config/model.yaml 에 고정.",
    ]
    (EXP / "EXP-001.md").write_text("\n".join(exp_lines) + "\n", encoding="utf-8", newline="\n")
    print(
        variants.sort_values("J_cv")[
            [
                "study",
                "bias",
                "cv_rmse_log",
                "cv_r2_raw",
                "final_rmse_log",
                "final_r2_raw",
                "final_r2_pearson_raw",
                "final_nse_raw",
                "final_f1_10k",
                "J_cv",
            ]
        ]
        .round(3)
        .to_string(index=False)
    )
    print("\n채택:", best["study"], best["bias"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
