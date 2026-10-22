# ruff: noqa: E501  (한국어 표)
"""EXP-confirm: 사전등록(reports/experiments/EXP-confirm/PREREG.md)대로 견고성 대안 C 를 1회 판정 계산한다.

구성 C = v1 로그 앙상블(C1·C3·C2) + R2 상류 피처 5열 + R3 속별 구성원 cg, 분위는 v1 동결 OOF(시드 42) 고정.
비교 v1_s(같은 시드 v1), 대조군 K_s(상류 피처 → 같은 결측 위치의 난수 5열). 시드 (101, 202, 303, 404, 505).
판정 값만 계산하고 결과를 data/processed/exp/EXP-confirm/results.json 에 쓴다(판정 보고서는 별도 작성·커밋).
사용: python -m algaecast.exp.confirm
"""

from __future__ import annotations

import json
import logging
import time

import numpy as np
import pandas as pd

from algaecast.exp import harness as H
from algaecast.exp import r2_upstream as R2
from algaecast.exp import r_combo as RC

log = logging.getLogger(__name__)
SEEDS: tuple[int, ...] = (101, 202, 303, 404, 505)
N_BOOT = 2000
BOOT_SEED = 20261022
OUT = H.EXP_DATA / "EXP-confirm"
THRESH = {"d_mean": 0.08, "d_ctrl": 0.04}
NONINF = {"r2_raw": -0.02, "rmse_log": 0.01, "f1_10k": -0.02}


def f2_frame(df: pd.DataFrame) -> pd.DataFrame:
    """R2 선택 설정의 상류 피처 5열(as_of 규칙 함수)."""
    return R2.build_features(df)[RC.f2_cols()]


def control_frame(df: pd.DataFrame, f2: pd.DataFrame, seed: int) -> pd.DataFrame:
    """대조군: 상류 피처와 같은 결측 위치의 표준정규 난수 5열, 생성기 시드 (20261022, seed, 5)."""
    return RC.control_columns(df.index, 5, seed, mask=f2.notna().to_numpy())


def config_members(
    df: pd.DataFrame, extra: pd.DataFrame | None, seed: int, genus: bool
) -> dict[str, np.ndarray]:
    """회귀 C1·C3·C2(+ 속별 cg) 시드 OOF. 분위는 학습하지 않는다(v1 동결 분위 사용)."""
    dfx = pd.concat([df, extra], axis=1) if extra is not None else df
    H.guard_no_2026(dfx)
    cols = H.base_columns() + (list(extra.columns) if extra is not None else [])
    mem = H.run_members(dfx, cols, seeds=(seed,), quantiles=False)
    if genus:
        mem.update(RC.genus_members(dfx, cols, seed))
    return mem


def bootstrap_ci(df: pd.DataFrame, a: list[np.ndarray], b: list[np.ndarray]) -> tuple[float, float, float]:
    """(연도·지점) 블록 부트스트랩: 반복마다 시드별 r2_raw(a_s) − r2_raw(b_s) 를 뽑힌 행으로 다시 계산해 평균."""
    cv_mask, _ = H.masks(df)
    years = H.years_of(df)
    sites = df["station_id"].astype(str).to_numpy()
    idx = np.where(cv_mask)[0]
    blocks = {}
    for i in idx:
        blocks.setdefault((int(years[i]), sites[i]), []).append(i)
    keys = sorted(blocks)
    obs = df["target_cells"].to_numpy(dtype=float)
    rng = np.random.default_rng(BOOT_SEED)
    out = np.empty(N_BOOT)

    def r2(o: np.ndarray, p: np.ndarray) -> float:
        return 1.0 - float(np.sum((o - p) ** 2)) / float(np.sum((o - o.mean()) ** 2))

    for k in range(N_BOOT):
        pick = rng.integers(0, len(keys), len(keys))
        rows = np.concatenate([blocks[keys[j]] for j in pick])
        o = obs[rows]
        out[k] = np.mean([r2(o, x[rows]) - r2(o, y[rows]) for x, y in zip(a, b, strict=True)])
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)), float(np.median(out))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    df, base = H.load_baseline()  # v1 동결 OOF(시드 42): 분위 q10·q50·q90 고정용
    H.guard_no_2026(df)
    q90_v1 = base["q90"]
    f2 = f2_frame(df)
    rows: list[dict] = []
    ens = {"C": [], "v1": [], "K": []}
    for s in SEEDS:
        for name, extra, genus, names in (
            ("v1", None, False, ("c1", "c3", "c2")),
            ("C", f2, True, ("c1", "c3", "c2", "cg")),
            ("K", control_frame(df, f2, s), True, ("c1", "c3", "c2", "cg")),
        ):
            mem = config_members(df, extra, s, genus)
            pred, w = H.ensemble_expanding(df, mem, names=names)
            r = H.metric_row(df, pred, q90_v1, f"{name} 시드 {s}")
            r.update({"config": name, "seed": s, "weights_2025": w[2025]})
            rows.append(r)
            ens[name].append(pred)
            H.save_oof(
                df,
                {**{k: mem[k] for k in names}, "pred": pred, "q90": q90_v1},
                OUT / f"oof_{name}_{s}.parquet",
            )
            log.info(
                "%s 시드 %d: CV r2_raw %.4f, 2025 r2_raw %.4f", name, s, r["cv_r2_raw"], r["y2025_r2_raw"]
            )
    tab = pd.DataFrame(rows)

    def per_seed(cfg: str, col: str) -> np.ndarray:
        return tab[tab["config"] == cfg].sort_values("seed")[col].to_numpy(dtype=float)

    d = per_seed("C", "cv_r2_raw") - per_seed("v1", "cv_r2_raw")
    d_ctrl = per_seed("C", "cv_r2_raw") - per_seed("K", "cv_r2_raw")
    lo, hi, med = bootstrap_ci(df, ens["C"], ens["v1"])
    v1f = json.loads((H.EXP_REPORTS / "EXP-baseline" / "baseline_metrics.json").read_text(encoding="utf-8"))
    c25 = {k: float(per_seed("C", f"y2025_{k}").mean()) for k in ("r2_raw", "rmse_log", "f1_10k")}
    lead_c = int(per_seed("C", "lead_q90").min())
    crit = {
        "a1_mean_delta": {
            "value": float(d.mean()),
            "need": ">= 0.08",
            "pass": bool(d.mean() >= THRESH["d_mean"]),
        },
        "a2_boot_lower": {"value": lo, "ci": [lo, hi], "median": med, "need": "> 0", "pass": bool(lo > 0)},
        "a3_vs_control": {
            "value": float(d_ctrl.mean()),
            "need": ">= 0.04",
            "pass": bool(d_ctrl.mean() >= THRESH["d_ctrl"]),
        },
        "b1_r2_raw_2025": {
            "value": c25["r2_raw"],
            "v1": v1f["y2025_r2_raw"],
            "need": f">= {v1f['y2025_r2_raw'] - 0.02:.6f}",
            "pass": bool(c25["r2_raw"] >= v1f["y2025_r2_raw"] + NONINF["r2_raw"]),
        },
        "b2_rmse_log_2025": {
            "value": c25["rmse_log"],
            "v1": v1f["y2025_rmse_log"],
            "need": f"<= {v1f['y2025_rmse_log'] + 0.01:.6f}",
            "pass": bool(c25["rmse_log"] <= v1f["y2025_rmse_log"] + NONINF["rmse_log"]),
        },
        "b3_f1_2025": {
            "value": c25["f1_10k"],
            "v1": v1f["y2025_f1_10k"],
            "need": f">= {v1f['y2025_f1_10k'] - 0.02:.6f}",
            "pass": bool(c25["f1_10k"] >= v1f["y2025_f1_10k"] + NONINF["f1_10k"]),
        },
        "b4_lead": {"value": lead_c, "v1": v1f["lead_q90"], "need": ">= 18", "pass": bool(lead_c >= 18)},
    }
    res = {
        "seeds": list(SEEDS),
        "per_seed_delta": d.tolist(),
        "per_seed_delta_vs_control": d_ctrl.tolist(),
        "criteria": crit,
        "rows": rows,
        "minutes": round((time.time() - t0) / 60, 1),
    }
    (OUT / "results.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8"
    )
    for k, v in crit.items():
        print(f"{k}: {v['value']:.4f} ({v['need']}) → {'충족' if v['pass'] else '미충족'}")
    print("소요", res["minutes"], "분")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
