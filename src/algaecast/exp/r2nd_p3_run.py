# ruff: noqa: E501  (한국어 표)
"""EXP-005 2차 P3 실행·판정 — reports/experiments/EXP-005/P3/PREREG_P3.md.

1) 탐색: 탐색 시드(harness2.EXPLORE_SEEDS)로 C + 묶음(T·TS·TSR)과 각 묶음의 난수 대조군을 평가하고,
   시드 평균 ΔCV r2_raw(대 C)가 가장 큰 묶음 하나를 고른다(차이 0.002 미만이면 열이 적은 묶음).
2) 판정: 판정 시드(harness2.FINAL_SEEDS)로 C_s · 후보(C + 고른 묶음) · K_s(후보의 P3 열을 같은 결측 위치의
   표준정규 난수로 바꾼 것, 생성기 (20261022, s, 열 수))를 학습해 PREREG_FINAL (a)~(c)를 계산한다.
   (d) 누수 테스트는 pytest 로 따로 실행해 기록한다. 2026 은 계산하지 않는다(2025 지표는 목표일 ≤ 2025-12-31).
사용: python -m algaecast.exp.r2nd_p3_run [--explore-only]
"""

from __future__ import annotations

import argparse
import logging
import time

import numpy as np
import pandas as pd

from algaecast.exp import confirm as CF
from algaecast.exp import harness as H
from algaecast.exp import harness2 as H2
from algaecast.exp import r2nd_p3_kmafcst as P

log = logging.getLogger(__name__)
OUT = H2.REPORT_DIR / "P3"
FEAT_CACHE = H2.EXP_DIR / "p3_grid_features.parquet"
TIE = 0.002


def p3_features(df: pd.DataFrame) -> pd.DataFrame:
    """df 행마다 P3 피처(캐시). 캐시는 기준일·지점이 같을 때만 쓴다."""
    if FEAT_CACHE.exists():
        f = pd.read_parquet(FEAT_CACHE)
        if (
            len(f) == len(df)
            and (f["station_id"].to_numpy() == df["station_id"].astype(str).to_numpy()).all()
        ):
            if (f["base_date"].astype(str).to_numpy() == df["base_date"].astype(str).to_numpy()).all():
                return f[P.FEATURE_COLS].set_axis(df.index)
    feats = P.build_features(df)
    save = feats.copy()
    save.insert(0, "base_date", df["base_date"].astype(str).to_numpy())
    save.insert(0, "station_id", df["station_id"].astype(str).to_numpy())
    FEAT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    save.to_parquet(FEAT_CACHE, index=False)
    return feats


def coverage_table(df: pd.DataFrame, feats: pd.DataFrame) -> str:
    """연도별 피처 유효 비율(행 기준)."""
    y = H.years_of(df)
    groups = {
        "발표분 있음": ["p3_fc_available"],
        "기온 +1·+2": ["p3_fc_ta_max_d1", "p3_fc_ta_max_d2", "p3_fc_ta_min_d1", "p3_fc_ta_min_d2"],
        "기온 +3": ["p3_fc_ta_max_d3", "p3_fc_ta_min_d3"],
        "POP·SKY": [c for c in P.FC_COLS if "pop" in c or "sky" in c],
        "강수량": [c for c in P.FC_COLS if "rn_day" in c],
    }
    head = "| 연도 | 행 | " + " | ".join(groups) + " |\n|---|---|" + "---|" * len(groups) + "\n"
    lines = []
    for yr in sorted(set(y)):
        m = y == yr
        cells = []
        for cols in groups.values():
            sub = feats.loc[m, cols]
            v = (
                (sub == 1.0).to_numpy().mean()
                if cols == ["p3_fc_available"]
                else sub.notna().to_numpy().mean()
            )
            cells.append(f"{v:.2f}")
        lines.append(f"| {yr} | {int(m.sum())} | " + " | ".join(cells) + " |")
    return head + "\n".join(lines) + "\n"


def builders(cols: list[str], feats: pd.DataFrame) -> tuple:
    frame = feats[cols]

    def cand(df: pd.DataFrame, seed: int) -> dict[str, np.ndarray]:
        return H2.c_pred(df, seed, extra=frame)

    def ctrl(df: pd.DataFrame, seed: int) -> dict[str, np.ndarray]:
        return H2.c_pred(df, seed, extra=H2.noise_like(frame, seed))

    return cand, ctrl


def explore(df: pd.DataFrame, feats: pd.DataFrame) -> tuple[str, dict, str]:
    base_rows = H2.baseline_c(df)
    base_mean = H2.mean_rows(base_rows, "C")
    entries = [(base_mean, base_rows)]
    res = {}
    for b, cols in P.BUNDLES.items():
        cand, ctrl = builders(cols, feats)
        rows, mean = H2.evaluate(df, f"P3G_{b}", cand)
        k_rows, k_mean = H2.evaluate(df, f"P3G_{b}_K", ctrl)
        mean["구성"], k_mean["구성"] = f"C+P3 {b}", f"C+난수 {b}"
        chk = H2.explore_check(mean, rows, base_rows, k_rows)
        res[b] = {"n_cols": len(cols), "check": chk, "mean": mean, "ctrl_mean": k_mean}
        entries += [(mean, rows), (k_mean, k_rows)]
        log.info("탐색 %s: ΔCV r2_raw %+.4f, 대조군 대비 %+.4f", b, chk["d_cv_r2_raw"], chk["d_vs_ctrl"])
    order = sorted(res, key=lambda b: (-res[b]["check"]["d_cv_r2_raw"], res[b]["n_cols"]))
    best = order[0]
    for b in order[1:]:  # 차이가 TIE 미만이면 열이 적은 묶음
        if (
            res[best]["check"]["d_cv_r2_raw"] - res[b]["check"]["d_cv_r2_raw"] < TIE
            and res[b]["n_cols"] < res[best]["n_cols"]
        ):
            best = b
    return best, res, H2.table2(entries, base_rows)


def judge(df: pd.DataFrame, feats: pd.DataFrame, bundle: str) -> dict:
    cand, ctrl = builders(P.BUNDLES[bundle], feats)
    runs = {"C": ("FINAL_C", H2.c_pred), "후보": (f"P3F_{bundle}", cand), "K": (f"P3F_{bundle}_K", ctrl)}
    rows: dict[str, list[dict]] = {k: [] for k in runs}
    preds: dict[str, list[np.ndarray]] = {k: [] for k in runs}
    for s in H2.FINAL_SEEDS:
        for name, (cache, build) in runs.items():
            out = H2.run_cached(df, cache, s, build)
            r = H2.metric_row2(df, out["pred"], out.get("q90"), f"{name} 시드 {s}")
            r["seed"] = s
            rows[name].append(r)
            preds[name].append(out["pred"])
            log.info(
                "판정 %s 시드 %d: CV r2_raw %.4f, 2025 rmse_log %.4f",
                name,
                s,
                r["cv_r2_raw"],
                r["y25_rmse_log"],
            )
    mean = {k: H2.mean_rows(v, k) for k, v in rows.items()}
    d = H2.paired_delta(rows["후보"], rows["C"], "cv_r2_raw")
    d_k = H2.paired_delta(rows["후보"], rows["K"], "cv_r2_raw")
    lo, hi, med = CF.bootstrap_ci(df, preds["후보"], preds["C"])
    c, k = mean["C"], mean["후보"]
    crit = {
        "a1 CV r2_raw 시드 평균 (후보 − C) ≥ +0.08": (d, d >= 0.08, "+0.08"),
        "a2 (연도·지점) 블록 부트스트랩 95% 하한 > 0": (lo, lo > 0, "0"),
        "a3 대조군 대비 시드 평균 (후보 − K) ≥ +0.04": (d_k, d_k >= 0.04, "+0.04"),
        "b1 2025 r2_raw ≥ C − 0.02": (
            k["y25_r2_raw"],
            k["y25_r2_raw"] >= c["y25_r2_raw"] - 0.02,
            f"{c['y25_r2_raw'] - 0.02:.4f}",
        ),
        "b2 2025 rmse_log ≤ C + 0.01": (
            k["y25_rmse_log"],
            k["y25_rmse_log"] <= c["y25_rmse_log"] + 0.01,
            f"{c['y25_rmse_log'] + 0.01:.4f}",
        ),
        "b3 2025 F1@10k ≥ C − 0.02": (
            k["y25_f1_10k"],
            k["y25_f1_10k"] >= c["y25_f1_10k"] - 0.02,
            f"{c['y25_f1_10k'] - 0.02:.4f}",
        ),
        "b4 리드타임 시드 평균 ≥ 18": (k["lead_q90"], k["lead_q90"] >= 18.0, "18"),
        "c 2025 9~10월 rmse_log ≤ C": (
            k["y25b_rmse_log"],
            k["y25b_rmse_log"] <= c["y25b_rmse_log"],
            f"{c['y25b_rmse_log']:.4f}",
        ),
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
    mean["후보"]["구성"], mean["K"]["구성"] = f"C+P3 {bundle}", f"C+난수 {bundle}"
    table = H2.table2(
        [(mean["C"], rows["C"]), (mean["후보"], rows["후보"]), (mean["K"], rows["K"])], rows["C"]
    )
    return {
        "bundle": bundle,
        "crit": crit,
        "boot": (lo, hi, med),
        "per_seed": per_seed,
        "rows": rows,
        "table": table,
        "passed_a_to_c": all(ok for _, ok, _ in crit.values()),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--explore-only", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    t0 = time.time()
    df = H.load_base()
    feats = p3_features(df)
    cov = coverage_table(df, feats)
    best, res, ex_table = explore(df, feats)
    ex_md = (
        "| 묶음 | 열 | ΔCV r2_raw(대 C) | 대조군 대비 | 2025 r2_raw | 2025 rmse_log | 2025 F1@10k | 9~10월 rmse_log |\n|---|---|---|---|---|---|---|---|\n"
        + "\n".join(
            f"| {b} | {r['n_cols']} | {r['check']['d_cv_r2_raw']:+.4f} | {r['check']['d_vs_ctrl']:+.4f} | {r['mean']['y25_r2_raw']:.4f} | {r['mean']['y25_rmse_log']:.4f} | {r['mean']['y25_f1_10k']:.4f} | {r['mean']['y25b_rmse_log']:.4f} |"
            for b, r in res.items()
        )
    )
    txt = (
        "# EXP-005 2차 P3 — 기상청 단기예보 격자 과거 발표분 피처: 실행 결과\n\n"
        "사전등록 [`PREREG_P3.md`](PREREG_P3.md). 자료 확인 [`PROBE_GRID.md`](PROBE_GRID.md). 2026 은 계산하지 않았다.\n\n"
        f"## 1. 피처 유효 비율(연도별, 실험 행 {len(df)}개)\n\n{cov}\n"
        f"## 2. 탐색(시드 {list(H2.EXPLORE_SEEDS)})\n\n{ex_md}\n\n선택 묶음: **{best}** (시드 평균 ΔCV r2_raw 최대, 차이 {TIE} 미만이면 열이 적은 묶음).\n\n"
        f"### 탐색 표준 표(시드 평균)\n\n{ex_table}\n"
    )
    payload: dict = {
        "explore": {b: {"n_cols": r["n_cols"], "check": r["check"]} for b, r in res.items()},
        "selected": best,
    }
    if not a.explore_only:
        j = judge(df, feats, best)
        lo, hi, med = j["boot"]
        crit_md = "| 조건 | 값 | 문턱 | 충족 |\n|---|---|---|---|\n" + "\n".join(
            f"| {n} | {v:+.4f} | {thr} | {'충족' if ok else '미충족'} |"
            for n, (v, ok, thr) in j["crit"].items()
        )
        seed_md = "| 시드 | C | 후보 | K | 후보 − C | 후보 − K |\n|---|---|---|---|---|---|\n" + "\n".join(
            f"| {int(r['시드'])} | {r['C']:.4f} | {r['후보']:.4f} | {r['K']:.4f} | {r['후보 − C']:+.4f} | {r['후보 − K']:+.4f} |"
            for _, r in j["per_seed"].iterrows()
        )
        txt += (
            f"## 3. 판정(시드 {list(H2.FINAL_SEEDS)}, 후보 = C + P3 {best})\n\n{crit_md}\n\n"
            f"부트스트랩 95% 구간 [{lo:+.4f}, {hi:+.4f}], 중앙 {med:+.4f}.\n\n"
            f"**(a)~(c) 결과: {'모두 충족' if j['passed_a_to_c'] else '미충족 항목 있음'}** — (d) 누수 테스트는 VERIFY 기록.\n\n"
            f"### 시드별 CV r2_raw\n\n{seed_md}\n\n### 판정 표준 표(판정 시드 평균, C 대비 시드 짝 차이)\n\n{j['table']}\n"
        )
        payload.update(
            {
                "criteria": {
                    n: {"value": v, "pass": ok, "threshold": thr} for n, (v, ok, thr) in j["crit"].items()
                },
                "bootstrap": {"lo": lo, "hi": hi, "median": med},
                "per_seed": j["per_seed"].to_dict(orient="records"),
                "rows": j["rows"],
                "passed_a_to_c": j["passed_a_to_c"],
            }
        )
    txt += f"\n소요 {(time.time() - t0) / 60:.1f}분.\n"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "RESULT.md").write_text(txt, encoding="utf-8")
    H2.write_json(OUT / "result.json", payload)
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
