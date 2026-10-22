# ruff: noqa: E501  (한국어 표)
"""원단위 고도화 2차 최종 판정 — reports/experiments/EXP-005/PREREG_FINAL.md 기준 (a)~(c) 계산.

최종 후보(COMBO/FINAL_CANDIDATE.md): C + P4 칼만 구성원. 판정 시드 harness2.FINAL_SEEDS.
비교: C_s(같은 시드), 대조군 K_s = C + 표준정규 난수 5열(생성기 (20261022, s, 5)). 분위는 v1 동결.
(d) 누수 테스트는 pytest 로 따로 실행해 결과를 기록한다. 2026 은 계산하지 않는다.
사용: python -m algaecast.exp.r2nd_final
"""

from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd

from algaecast.exp import confirm as CF
from algaecast.exp import harness as H
from algaecast.exp import harness2 as H2
from algaecast.exp import r2nd_combo as CB
from algaecast.exp import r_combo as RC

log = logging.getLogger(__name__)
OUT = H2.REPORT_DIR / "FINAL"


def k_builder(df: pd.DataFrame, seed: int) -> dict[str, np.ndarray]:
    """대조군 K_s: C + 표준정규 난수 5열(결측 없음)."""
    noise = RC.control_columns(df.index, 5, seed)
    return H2.c_pred(df, seed, extra=noise)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    t0 = time.time()
    df = H.load_base()
    cand_build = CB.make_builder(("KF",))
    runs = {"C": H2.c_pred, "후보": cand_build, "K": k_builder}
    rows: dict[str, list[dict]] = {k: [] for k in runs}
    preds: dict[str, list[np.ndarray]] = {k: [] for k in runs}
    for s in H2.FINAL_SEEDS:
        for name, build in runs.items():
            out = H2.run_cached(df, f"FINAL_{ {'C': 'C', '후보': 'CAND', 'K': 'K'}[name] }", s, build)
            r = H2.metric_row2(df, out["pred"], out.get("q90"), f"{name} 시드 {s}")
            r["seed"] = s
            rows[name].append(r)
            preds[name].append(out["pred"])
            log.info("%s 시드 %d: CV r2_raw %.4f, 2025 r2_raw %.4f", name, s, r["cv_r2_raw"], r["y25_r2_raw"])
    mean = {k: H2.mean_rows(v, k) for k, v in rows.items()}
    d = H2.paired_delta(rows["후보"], rows["C"], "cv_r2_raw")
    d_k = H2.paired_delta(rows["후보"], rows["K"], "cv_r2_raw")
    lo, hi, med = CF.bootstrap_ci(df, preds["후보"], preds["C"])
    c, k = mean["C"], mean["후보"]
    crit = {
        "a1 CV r2_raw 시드 평균 (후보 − C) ≥ +0.08": (d, d >= 0.08),
        "a2 (연도·지점) 블록 부트스트랩 95% 하한 > 0": (lo, lo > 0),
        "a3 대조군 대비 시드 평균 (후보 − K) ≥ +0.04": (d_k, d_k >= 0.04),
        "b1 2025 r2_raw ≥ C − 0.02": (k["y25_r2_raw"], k["y25_r2_raw"] >= c["y25_r2_raw"] - 0.02),
        "b2 2025 rmse_log ≤ C + 0.01": (k["y25_rmse_log"], k["y25_rmse_log"] <= c["y25_rmse_log"] + 0.01),
        "b3 2025 F1@10k ≥ C − 0.02": (k["y25_f1_10k"], k["y25_f1_10k"] >= c["y25_f1_10k"] - 0.02),
        "b4 리드타임 시드 평균 ≥ 18": (k["lead_q90"], k["lead_q90"] >= 18.0),
        "c 2025 9~10월 rmse_log ≤ C": (k["y25b_rmse_log"], k["y25b_rmse_log"] <= c["y25b_rmse_log"]),
    }
    ref = {
        "b1 2025 r2_raw ≥ C − 0.02": c["y25_r2_raw"] - 0.02,
        "b2 2025 rmse_log ≤ C + 0.01": c["y25_rmse_log"] + 0.01,
        "b3 2025 F1@10k ≥ C − 0.02": c["y25_f1_10k"] - 0.02,
        "c 2025 9~10월 rmse_log ≤ C": c["y25b_rmse_log"],
    }
    per_seed = pd.DataFrame(
        {
            "시드": list(H2.FINAL_SEEDS),
            "C": [r["cv_r2_raw"] for r in rows["C"]],
            "후보": [r["cv_r2_raw"] for r in rows["후보"]],
            "K": [r["cv_r2_raw"] for r in rows["K"]],
        }
    )
    per_seed["후보 − C"] = per_seed["후보"] - per_seed["C"]
    per_seed["후보 − K"] = per_seed["후보"] - per_seed["K"]
    crit_md = "| 조건 | 값 | 문턱 | 충족 |\n|---|---|---|---|\n" + "\n".join(
        f"| {name} | {v:+.4f} | {(f'{ref[name]:.4f}') if name in ref else name.split(' ')[-1]} | {'충족' if ok else '미충족'} |"
        for name, (v, ok) in crit.items()
    )
    seed_md = "| 시드 | C | 후보 | K | 후보 − C | 후보 − K |\n|---|---|---|---|---|---|\n" + "\n".join(
        f"| {int(r['시드'])} | {r['C']:.4f} | {r['후보']:.4f} | {r['K']:.4f} | {r['후보 − C']:+.4f} | {r['후보 − K']:+.4f} |"
        for _, r in per_seed.iterrows()
    )
    table = H2.table2(
        [(mean["C"], rows["C"]), (mean["후보"], rows["후보"]), (mean["K"], rows["K"])], rows["C"]
    )
    passed = all(ok for _, ok in crit.values())
    txt = (
        "# 원단위 고도화 2차 최종 판정 계산(판정 시드)\n\n"
        f"판정 시드 {list(H2.FINAL_SEEDS)}, 사전등록 `../PREREG_FINAL.md`, 최종 후보 `../COMBO/FINAL_CANDIDATE.md`(C + P4 칼만 구성원).\n\n"
        f"## (a)~(c) 판정 값\n\n{crit_md}\n\n부트스트랩 95% 구간 [{lo:+.4f}, {hi:+.4f}], 중앙 {med:+.4f}.\n\n"
        f"**(a)~(c) 결과: {'모두 충족' if passed else '미충족 항목 있음'}** — (d) 누수 테스트는 별도 기록.\n\n"
        f"## 시드별 CV r2_raw\n\n{seed_md}\n\n## 표준 표(판정 시드 평균, C 대비 시드 짝 차이)\n\n{table}\n"
        f"소요 {(time.time() - t0) / 60:.1f}분.\n"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "README.md").write_text(txt, encoding="utf-8")
    H2.write_json(
        OUT / "results.json",
        {
            "criteria": {k: {"value": v, "pass": ok} for k, (v, ok) in crit.items()},
            "bootstrap": {"lo": lo, "hi": hi, "median": med},
            "per_seed": per_seed.to_dict(orient="records"),
            "rows": rows,
            "passed_a_to_c": passed,
        },
    )
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
