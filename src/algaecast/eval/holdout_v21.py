# ruff: noqa: E501  (한국어 표)
"""2025 홀드아웃·CV — v2.1(누수 수정판) vs v2(이전 동결, 누수 상수 포함), v1-fix vs v1. 같은 252행·같은 부트스트랩.

- v2.1: scripts/freeze_v21.py --oof 의 연도 확장 OOF(data/processed/v21_oof.parquet, 폴드별 수온 임계).
- v1-fix: alert --skip-tune 이 수정 피처로 다시 만든 v1 구성 앙상블 OOF(oof_predictions.parquet 의 ens_v1fix).
- v2·v1: 수정 전 값(reports/experiments/FIX-v2.1/baseline_v2/tbl_holdout_2025_v2.json, 2026-10-22 계산). 다시 계산하지 않는다.
- 분위·CQR·분류기는 v2.1 재적합본(OOF q10/q90 + model.yaml cqr, clf_a).
- 출력: reports/eval/tbl_holdout_2025_v21.md·.json (전체 정밀도). 2026 은 읽지 않는다.
사용: python -m algaecast.eval.holdout_v21
"""

from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd
import yaml

from algaecast.config import CONFIG_DIR, DATA_DIR, ROOT
from algaecast.eval.holdout_v2 import CV_KEYS, FNS, _md
from algaecast.eval.metrics import bootstrap_ci, compute_all
from algaecast.models import v2 as V2

log = logging.getLogger(__name__)
EVAL = ROOT / "reports" / "eval"
OUT = EVAL / "tbl_holdout_2025_v21.md"
OUT_JSON = EVAL / "tbl_holdout_2025_v21.json"
BASE = ROOT / "reports" / "experiments" / "FIX-v2.1" / "baseline_v2" / "tbl_holdout_2025_v2.json"
OOF = DATA_DIR / "processed" / "oof_predictions.parquet"
OOF_V21 = DATA_DIR / "processed" / "v21_oof.parquet"
FIT = ROOT / "reports" / "experiments" / "FIX-v2.1" / "v21_fit.json"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    frame = V2.load_training_frame()
    key = frame[["station_id", "base_date", "target_date"]].copy()
    for d in (key,):
        d["station_id"] = d["station_id"].astype(str)
        d["base_date"] = pd.to_datetime(d["base_date"])
        d["target_date"] = pd.to_datetime(d["target_date"])
    v = pd.read_parquet(OOF_V21)
    o = pd.read_parquet(OOF)
    for d in (v, o):
        d["station_id"] = d["station_id"].astype(str)
        d["base_date"] = pd.to_datetime(d["base_date"])
        d["target_date"] = pd.to_datetime(d["target_date"])
    k3 = ["station_id", "base_date", "target_date"]
    d = key.assign(year=V2.years_of(frame), obs=frame["target_cells"].to_numpy(dtype=float))
    d = d.merge(v[[*k3, "ens"]].rename(columns={"ens": "v21"}), on=k3, how="left")
    d = d.merge(o[[*k3, "ens_v1fix", "b0", "q10", "q90", "clf_a"]], on=k3, how="left")
    if len(d) != len(frame) or d.loc[d["year"] >= 2020, ["v21", "ens_v1fix"]].isna().any().any():
        raise SystemExit("중단: OOF 와 학습 프레임 행이 맞지 않는다.")
    cfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))
    qhat = cfg.get("cqr", {}).get("qhat_log10", 0.0)
    fin = d[d["year"] == 2025].reset_index(drop=True)
    obs = fin["obs"].to_numpy(dtype=float)
    q10c = np.clip(10 ** (np.log10(fin["q10"].to_numpy() + 1) - qhat) - 1, 0, None)
    q90c = 10 ** (np.log10(fin["q90"].to_numpy() + 1) + qhat) - 1
    names = {
        "v21": "v2.1 앙상블(누수 수정, 운영·제출)",
        "v1fix": "v1-fix 앙상블(v1 구성 + 수정 피처)",
        "b0": "B0 지속성",
    }
    preds = {
        "v21": fin["v21"].to_numpy(float),
        "v1fix": fin["ens_v1fix"].to_numpy(float),
        "b0": fin["b0"].to_numpy(float),
    }
    full: dict = {"h2025": {}, "cv": {}}
    rows = []
    for k, p in preds.items():
        m = compute_all(obs, p)
        row = {"모델": names[k], "n": m["n"]}
        fk = full["h2025"].setdefault(k, {"n": int(m["n"])})
        for mk, fn in FNS.items():
            ci = bootstrap_ci(obs, p, fn, n=1000, seed=42)
            row[mk] = f"{m[mk]:.3f} [{ci['lo']:.3f}, {ci['hi']:.3f}]"
            fk[mk] = {"value": float(m[mk]), "ci_low": float(ci["lo"]), "ci_high": float(ci["hi"])}
        rows.append(row)
    shared = compute_all(obs, preds["v21"], q10=q10c, q90=q90c, p10k=fin["clf_a"].to_numpy())
    cv_rows = []
    cvd = d[(d["year"] >= 2020) & (d["year"] <= 2024)]
    for k, col in (("v21", "v21"), ("v1fix", "ens_v1fix"), ("b0", "b0")):
        per = pd.DataFrame(
            [
                {mk: compute_all(g["obs"].to_numpy(float), g[col].to_numpy(float))[mk] for mk in CV_KEYS}
                for _, g in cvd.groupby("year")
            ]
        )
        pm = compute_all(cvd["obs"].to_numpy(float), cvd[col].to_numpy(float))
        full["cv"][k] = {
            **{f"{mk}_fold_mean": float(per[mk].mean()) for mk in CV_KEYS},
            **{f"{mk}_fold_sd": float(per[mk].std()) for mk in CV_KEYS},
            **{f"{mk}_pooled": float(pm[mk]) for mk in CV_KEYS},
            "n_pooled": int(pm["n"]),
        }
        cv_rows.append(
            {
                "모델": names[k],
                **{f"{mk} 폴드평균±SD": f"{per[mk].mean():.3f} ± {per[mk].std():.3f}" for mk in CV_KEYS},
                "r2_raw 통합": f"{pm['r2_raw']:.3f}",
            }
        )
    full["shared_2025"] = {k: float(shared[k]) for k in ("picp80", "mpiw80_log", "brier_10k")}
    fit = json.loads(FIT.read_text(encoding="utf-8"))
    full["weights_v21"] = fit["weights"]
    base = json.loads(BASE.read_text(encoding="utf-8"))
    full["before"] = {
        "h2025": base["h2025"],
        "cv": base["cv"],
        "shared_2025": base["shared_2025"],
        "weights_v2": base["weights_v2"],
    }
    imp = []
    for mk in ("rmse_log", "mae_log", "r2_log", "r2_raw", "nse_raw", "f1_10k", "f1_1k"):
        imp.append(
            {
                "지표(2025, 252행)": mk,
                "v2(수정 전)": round(base["h2025"]["v2"][mk]["value"], 4),
                "v2.1": round(full["h2025"]["v21"][mk]["value"], 4),
                "Δ(v2.1−v2)": round(full["h2025"]["v21"][mk]["value"] - base["h2025"]["v2"][mk]["value"], 4),
                "v1(수정 전)": round(base["h2025"]["v1"][mk]["value"], 4),
                "v1-fix": round(full["h2025"]["v1fix"][mk]["value"], 4),
                "Δ(v1-fix−v1)": round(
                    full["h2025"]["v1fix"][mk]["value"] - base["h2025"]["v1"][mk]["value"], 4
                ),
            }
        )
    for mk in CV_KEYS:
        imp.append(
            {
                "지표(2025, 252행)": f"CV {mk} 폴드평균",
                "v2(수정 전)": round(base["cv"]["v2"][f"{mk}_fold_mean"], 4),
                "v2.1": round(full["cv"]["v21"][f"{mk}_fold_mean"], 4),
                "Δ(v2.1−v2)": round(
                    full["cv"]["v21"][f"{mk}_fold_mean"] - base["cv"]["v2"][f"{mk}_fold_mean"], 4
                ),
                "v1(수정 전)": round(base["cv"]["v1"][f"{mk}_fold_mean"], 4),
                "v1-fix": round(full["cv"]["v1fix"][f"{mk}_fold_mean"], 4),
                "Δ(v1-fix−v1)": round(
                    full["cv"]["v1fix"][f"{mk}_fold_mean"] - base["cv"]["v1"][f"{mk}_fold_mean"], 4
                ),
            }
        )
    for mk in ("picp80", "mpiw80_log", "brier_10k"):
        imp.append(
            {
                "지표(2025, 252행)": f"공통 {mk}(분위·CQR·분류기 a)",
                "v2(수정 전)": round(base["shared_2025"][mk], 4),
                "v2.1": round(full["shared_2025"][mk], 4),
                "Δ(v2.1−v2)": round(full["shared_2025"][mk] - base["shared_2025"][mk], 4),
                "v1(수정 전)": round(base["shared_2025"][mk], 4),
                "v1-fix": round(full["shared_2025"][mk], 4),
                "Δ(v1-fix−v1)": round(full["shared_2025"][mk] - base["shared_2025"][mk], 4),
            }
        )
    full["impact_table"] = imp
    w = ", ".join(f"{k} {float(x):.3f}" for k, x in fit["weights"].items())
    w0 = ", ".join(f"{k} {float(x):.3f}" for k, x in base["weights_v2"].items())
    body = (
        f"- v2.1 = 데이터 유래 상수 누수 수정판(사전등록 reports/experiments/FIX-v2.1/PREREG.md). 결합 가중치 {w} (v2: {w0}).\n"
        "- **영향 보고용**이다. v2 는 규칙 위반이므로 v2.1 을 결과와 무관하게 채택했다.\n"
        "- 같은 252행(학습 ≤2024 → 2025, 목표일 ≤ 2025-12-31)·부트스트랩 1,000회(seed 42). v2·v1 값은 수정 전 계산(2026-10-22)을 그대로 옮겼다.\n"
        f"- 분위·CQR·분류기(v2.1 재적합): PICP80(CQR) {shared['picp80']:.3f}, MPIW80_log {shared['mpiw80_log']:.3f}, Brier_10k(분류기 a) {shared['brier_10k']:.3f}.\n\n"
        "## v2 대비 v2.1 영향(같은 행)\n\n" + _md(pd.DataFrame(imp)) + "\n\n"
        "## 2025 홀드아웃(252행, 95% CI)\n\n" + _md(pd.DataFrame(rows)) + "\n\n"
        "## CV 2020~2024(연도 확장 OOF, 폴드별 수정 피처)\n\n" + _md(pd.DataFrame(cv_rows)) + "\n"
    )
    OUT.write_text(
        f"# 2025 홀드아웃·CV — v2.1(누수 수정판) vs v2·v1(수정 전), 같은 행 비교\n\n{body}",
        encoding="utf-8",
        newline="\n",
    )
    OUT_JSON.write_text(json.dumps(full, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(pd.DataFrame(imp).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
