# ruff: noqa: E501  (한국어 표)
"""2025 홀드아웃·CV 비교 — v2(운영·제출 모델 C) vs v1(블라인드 검증 모델), 같은 행.

- v2: 동결 레지스트리(models/FROZEN_v2.md)의 가중치로 연도 확장 OOF(models.v2.cv_members, 시드 42)를 결합.
  동결 때(scripts/freeze_v2.py)와 같은 계산이다.
- v1: data/processed/oof_predictions.parquet 의 v1 앙상블 OOF(동결 파이프라인 산출물).
- 행: 학습·검증 2,562행(목표일 ≤ 2025-12-31). 2025 = 252행. v1 공개 표(tbl_holdout_2025.md)는 2026-10-22 격리 전 계산이라
  목표일 2026-01-05 인 4행을 포함한 256행이다. 이 표는 두 모델을 같은 252행에서 비교한다.
- 2026 은 읽지 않는다. 분위·CQR·분류기는 두 모델 공통(v1 동결본)이다.
- 출력: reports/eval/tbl_holdout_2025_v2.md
사용: python -m algaecast.eval.holdout_v2
"""

from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd
import yaml

from algaecast.config import CONFIG_DIR, DATA_DIR, ROOT
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
from algaecast.models import registry as R
from algaecast.models import v2 as V2

log = logging.getLogger(__name__)
EVAL = ROOT / "reports" / "eval"
OUT = EVAL / "tbl_holdout_2025_v2.md"
OUT_JSON = EVAL / "tbl_holdout_2025_v2.json"  # 전체 정밀도 값(화면·문서 숫자는 이 값에서 한 번만 반올림)
OOF_V1 = DATA_DIR / "processed" / "oof_predictions.parquet"
FNS = {
    "rmse_log": rmse_log,
    "mae_log": mae_log,
    "r2_log": r2_log,
    "r2_raw": r2_raw,
    "r2_pearson_raw": r2_pearson_raw,
    "nse_raw": nse_raw,
    "f1_10k": lambda a, b: f1_at(a, b, 10_000)["f1"],
    "f1_1k": lambda a, b: f1_at(a, b, 1_000)["f1"],
}
CV_KEYS = ("rmse_log", "r2_log", "r2_raw", "nse_raw", "f1_10k")


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


def v2_oof(frame: pd.DataFrame) -> tuple[np.ndarray, dict[str, float]]:
    """동결 v2 가중치로 2020~2025 OOF 앙상블(원단위)."""
    obj, entry = R.load_current("regression")
    if obj.get("kind") != V2.KIND:
        raise SystemExit("중단: current 회귀가 v2 가 아니다.")
    weights = {k: float(v) for k, v in obj["weights"].items()}
    cfg = V2.V2Config.from_dict(obj["config"])
    oof = V2.cv_members(frame, cfg.seed, cfg)
    yrs = V2.years_of(frame)
    ens = np.full(len(frame), np.nan)
    m = yrs >= 2020
    ens[m] = V2.combine({k: np.asarray(oof[k])[m] for k in weights}, weights)
    log.info("v2 가중치(동결 %s) %s", entry["version"], weights)
    return ens, weights


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    frame = V2.load_training_frame()
    ens2, weights = v2_oof(frame)
    key = frame[["station_id", "base_date"]].copy()
    key["station_id"] = key["station_id"].astype(str)
    key["base_date"] = pd.to_datetime(key["base_date"])
    o = pd.read_parquet(OOF_V1)
    o["station_id"] = o["station_id"].astype(str)
    o["base_date"] = pd.to_datetime(o["base_date"])
    d = key.assign(v2=ens2, year=V2.years_of(frame), obs=frame["target_cells"].to_numpy(dtype=float)).merge(
        o[["station_id", "base_date", "ens", "b0", "q10", "q90", "clf_a"]],
        on=["station_id", "base_date"],
        how="left",
    )
    if len(d) != len(frame) or d.loc[d["year"] >= 2020, ["ens", "v2"]].isna().any().any():
        raise SystemExit("중단: v1 OOF 와 학습 프레임 행이 맞지 않는다.")
    cfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))
    qhat = cfg.get("cqr", {}).get("qhat_log10", 0.0)
    fin = d[d["year"] == 2025].reset_index(drop=True)
    obs = fin["obs"].to_numpy(dtype=float)
    q10c = np.clip(10 ** (np.log10(fin["q10"].to_numpy() + 1) - qhat) - 1, 0, None)
    q90c = 10 ** (np.log10(fin["q90"].to_numpy() + 1) + qhat) - 1
    preds = {
        "v2 앙상블 C(운영·제출)": fin["v2"].to_numpy(dtype=float),
        "v1 앙상블(블라인드 검증)": fin["ens"].to_numpy(dtype=float),
        "B0 지속성": fin["b0"].to_numpy(dtype=float),
    }
    rows = []
    full: dict = {"h2025": {}, "cv": {}}
    keys = {"v2 앙상블 C(운영·제출)": "v2", "v1 앙상블(블라인드 검증)": "v1", "B0 지속성": "b0"}
    for name, p in preds.items():
        m = compute_all(obs, p)
        row = {"모델": name, "n": m["n"]}
        fk = full["h2025"].setdefault(keys[name], {"n": int(m["n"])})
        for k, fn in FNS.items():
            ci = bootstrap_ci(obs, p, fn, n=1000, seed=42)
            row[k] = f"{m[k]:.3f} [{ci['lo']:.3f}, {ci['hi']:.3f}]"
            fk[k] = {"value": float(m[k]), "ci_low": float(ci["lo"]), "ci_high": float(ci["hi"])}
        rows.append(row)
    shared = compute_all(
        obs, preds["v2 앙상블 C(운영·제출)"], q10=q10c, q90=q90c, p10k=fin["clf_a"].to_numpy()
    )
    cv_rows = []
    for name, col in (
        ("v2 앙상블 C(운영·제출)", "v2"),
        ("v1 앙상블(블라인드 검증)", "ens"),
        ("B0 지속성", "b0"),
    ):
        per = []
        for _y, g in d[(d["year"] >= 2020) & (d["year"] <= 2024)].groupby("year"):
            mm = compute_all(g["obs"].to_numpy(dtype=float), g[col].to_numpy(dtype=float))
            per.append({k: mm[k] for k in CV_KEYS})
        per = pd.DataFrame(per)
        pooled = d[(d["year"] >= 2020) & (d["year"] <= 2024)]
        pm = compute_all(pooled["obs"].to_numpy(dtype=float), pooled[col].to_numpy(dtype=float))
        full["cv"][keys[name]] = {
            **{f"{k}_fold_mean": float(per[k].mean()) for k in CV_KEYS},
            **{f"{k}_fold_sd": float(per[k].std()) for k in CV_KEYS},
            **{f"{k}_pooled": float(pm[k]) for k in CV_KEYS},
            "n_pooled": int(pm["n"]),
        }
        cv_rows.append(
            {
                "모델": name,
                **{f"{k} 폴드평균±SD": f"{per[k].mean():.3f} ± {per[k].std():.3f}" for k in CV_KEYS},
                "r2_raw 통합(OOF 1,278행)": f"{pm['r2_raw']:.3f}",
            }
        )
    w = ", ".join(f"{k} {v:.3f}" for k, v in weights.items())
    body = (
        "- v2 = 최종 모델 C(models/FROZEN_v2.md, 동결 커밋 9dca86c), 결합 가중치 "
        + w
        + ". v1 = 2026-10-21 동결 모델(models/FROZEN.md).\n"
        "- 두 모델을 **같은 행**(학습 ≤2024 → 2025, 목표일 ≤ 2025-12-31 인 252행)에서 비교한다. v1 공개 표 `tbl_holdout_2025.md` 는 "
        "목표일 2026-01-05 인 4행을 포함한 256행이라 v1 값이 소수 셋째 자리에서 조금 다르다.\n"
        "- 부트스트랩 95% CI: 1,000회, 행 재표본(seed 42) — `tbl_holdout_2025.md` 와 같은 방식. 2026 은 쓰지 않았다.\n"
        f"- 분위·CQR·분류기는 두 모델 공통(v1 동결본): PICP80(CQR) {shared['picp80']:.3f}, MPIW80_log {shared['mpiw80_log']:.3f}, "
        f"Brier_10k(분류기 a) {shared['brier_10k']:.3f}.\n\n"
        "## 2025 홀드아웃(252행)\n\n" + _md(pd.DataFrame(rows)) + "\n\n"
        "## CV 2020~2024(연도 확장 OOF, 폴드 5개)\n\n" + _md(pd.DataFrame(cv_rows)) + "\n\n"
        "v2 결합 가중치는 이 CV OOF 로 적합했으므로 CV 행의 v2 값은 가중치 선택에 쓴 자료에서 잰 값이다(v1 의 model.yaml 가중치도 같은 방식으로 정했다).\n"
    )
    OUT.write_text(
        f"# 2025 홀드아웃·CV — v2 vs v1 봉인본(수정 전 이력, 2026-10-22 계산), 같은 행 비교 — 제출·운영 v2.1 은 tbl_holdout_2025_v21.md\n\n{body}",
        encoding="utf-8",
        newline="\n",
    )
    full["shared_2025"] = {k: float(shared[k]) for k in ("picp80", "mpiw80_log", "brier_10k")}
    full["weights_v2"] = {k: float(v) for k, v in weights.items()}
    OUT_JSON.write_text(json.dumps(full, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(pd.DataFrame(rows).to_string(index=False))
    print(pd.DataFrame(cv_rows).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
