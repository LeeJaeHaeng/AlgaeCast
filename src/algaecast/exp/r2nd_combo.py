# ruff: noqa: E501  (한국어 표)
"""원단위 고도화 2차 종합(COMBO): 기준 모델 C 위에 효과가 보인 구성 요소를 누적 결합해 최종 후보를 CV 로 고른다.

- 후보 요소(P1·P4·P5 결과에서 C 대비 CV 이득이 양수인 것): KF = P4 칼만 7일 예측 구성원(로컬 레벨+수온, 중앙값),
  D = P1 변화량 타깃 LightGBM 구성원, G = P5 국면별 NNLS 게이트(결합 방식). P3(수집 불가)·P6(이득 없음)·P2(미적용)는 제외.
- 선택: 탐색 시드(harness2.EXPLORE_SEEDS) 평균 CV r2_raw 최대, 조건 = 시드 평균 ΔCV rmse_log(대 C) ≤ +0.01 과
  리드타임 ≥ 18(분위는 v1 동결이라 항상 18). 단계 증가가 +0.01 미만이면 멈춘다. 2025 는 표에 보고만 한다.
- 결과: reports/experiments/EXP-005/COMBO/README.md·metrics.json, 최종 후보 FINAL_CANDIDATE.md(판정 전 고정·커밋).
사용: python -m algaecast.exp.r2nd_combo
"""

from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd

from algaecast.exp import harness as H
from algaecast.exp import harness2 as H2

log = logging.getLogger(__name__)
OUT = H2.REPORT_DIR / "COMBO"
MIN_GAIN = 0.01
ELEMENTS = ("KF", "D", "G")
LABEL = {"KF": "P4 칼만 구성원", "D": "P1 변화량 구성원", "G": "P5 국면 게이트"}

_KF: dict[str, np.ndarray] = {}
_P1F: dict[str, object] = {}


def kf_member(df: pd.DataFrame) -> np.ndarray:
    """P4 선택 설정의 칼만 구성원(시드 무관) — 한 번만 계산."""
    if "kf" not in _KF:
        from algaecast.exp import r2nd_p4_kalman as P4

        _KF["kf"] = np.asarray(P4.kf_member(df), dtype=float)
    return _KF["kf"]


def d_member(df: pd.DataFrame, seed: int) -> np.ndarray:
    """P1 선택 설정의 변화량 타깃 LightGBM 구성원 d(원단위, 복원 보정 없음)."""
    from algaecast.exp import r2nd_p1_change as P1

    if "feats" not in _P1F:
        _P1F["feats"] = P1.Feats(df)
    return np.asarray(P1.members(df, seed, _P1F["feats"])["d"], dtype=float)


def members_for(df: pd.DataFrame, seed: int, combo: tuple[str, ...]) -> dict[str, np.ndarray]:
    """C 구성원(캐시) + 선택 요소 구성원."""
    c = H2.run_cached(df, "C", seed, H2.c_pred)
    mem = {k: c[f"m_{k}"] for k in H2.C_NAMES}
    if "KF" in combo:
        mem["kf"] = kf_member(df)
    if "D" in combo:
        mem["d"] = d_member(df, seed)
    return mem


def make_builder(combo: tuple[str, ...]) -> H2.Builder:
    def build(df: pd.DataFrame, seed: int) -> dict[str, np.ndarray]:
        mem = members_for(df, seed, combo)
        names = tuple(mem)
        if "G" in combo:
            from algaecast.exp import r2nd_p5_regime_analog as P5

            pred, _ = P5.gated_ensemble(df, mem, P5.regime_groups(df), names=names)
        else:
            pred, _ = H.ensemble_expanding(df, mem, names=names)
        return {"pred": pred, "q90": None, **{f"m_{k}": v for k, v in mem.items()}}

    return build


def key_of(combo: tuple[str, ...]) -> str:
    return "COMBO_" + ("C" if not combo else "C+" + "+".join(combo))


def label_of(combo: tuple[str, ...]) -> str:
    return "C" if not combo else "C + " + " + ".join(LABEL[e] for e in combo)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    t0 = time.time()
    df = H.load_base()
    base_rows = H2.baseline_c(df)
    base_mean = H2.mean_rows(base_rows, "C(기준 모델)")
    results: dict[tuple[str, ...], tuple[dict, list[dict]]] = {(): (base_mean, base_rows)}
    steps: list[dict] = []
    current: tuple[str, ...] = ()
    while True:
        cands = [tuple(sorted(current + (e,), key=ELEMENTS.index)) for e in ELEMENTS if e not in current]
        if not cands:
            break
        scored = []
        for cb in cands:
            if cb not in results:
                rows, mean = H2.evaluate(df, key_of(cb), make_builder(cb))
                mean["구성"] = label_of(cb)
                results[cb] = (mean, rows)
            mean, rows = results[cb]
            d_r2 = H2.paired_delta(rows, base_rows, "cv_r2_raw")
            d_rmse = H2.paired_delta(rows, base_rows, "cv_rmse_log")
            ok = d_rmse <= 0.01 and mean["lead_q90"] >= 18.0
            inc = mean["cv_r2_raw"] - results[current][0]["cv_r2_raw"]
            scored.append((cb, d_r2, d_rmse, ok, inc))
            steps.append(
                {
                    "단계": len(current) + 1,
                    "후보": label_of(cb),
                    "ΔC CV r2_raw": d_r2,
                    "ΔC CV rmse_log": d_rmse,
                    "적격": ok,
                    "증가": inc,
                }
            )
        ok_c = [s for s in scored if s[3]]
        if not ok_c:
            break
        best = max(ok_c, key=lambda s: s[1])
        if best[4] < MIN_GAIN:
            steps.append(
                {
                    "단계": len(current) + 1,
                    "후보": "(종료)",
                    "ΔC CV r2_raw": float("nan"),
                    "ΔC CV rmse_log": float("nan"),
                    "적격": False,
                    "증가": best[4],
                }
            )
            break
        current = best[0]
    final = current
    fmean, frows = results[final]
    entries = [results[()]] + [results[k] for k in results if k != ()]
    explore = H2.explore_check(fmean, frows, base_rows)
    step_tbl = pd.DataFrame(steps)
    OUT.mkdir(parents=True, exist_ok=True)
    txt = (
        "# 원단위 고도화 2차 종합(COMBO) — 누적 결합(탐색 시드)\n\n"
        f"시드 {list(H2.EXPLORE_SEEDS)} 평균, 선택은 CV 2020~2024 만. 요소: KF(P4 칼만 구성원), D(P1 변화량 구성원), G(P5 국면 게이트). "
        "P3 은 수집 불가(API허브 활용신청 미승인), P6 은 이득 없음, P2 는 사전등록 조건 미충족으로 제외했다.\n\n"
        "## 단계별 전진 선택\n\n"
        + "| 단계 | 후보 | ΔC CV r2_raw | ΔC CV rmse_log | 적격(rmse ≤ +0.01·리드 ≥ 18) | 직전 대비 증가 |\n|---|---|---|---|---|---|\n"
        + "\n".join(
            f"| {r['단계']} | {r['후보']} | {r['ΔC CV r2_raw']:+.4f} | {r['ΔC CV rmse_log']:+.4f} | {'예' if r['적격'] else '아니오'} | {r['증가']:+.4f} |"
            for r in steps
        )
        + f"\n\n**최종 후보: {label_of(final)}**\n\n## 표준 표(시드 평균, C 대비 시드 짝 차이)\n\n"
        + H2.table2(entries, base_rows)
        + "\n## 탐색 판정(참고 — 최종 판정이 아님)\n\n"
        + "| 항목 | 값 |\n|---|---|\n"
        + "\n".join(f"| {k} | {v} |" for k, v in explore.items())
        + f"\n\n소요 {(time.time() - t0) / 60:.1f}분.\n"
    )
    (OUT / "README.md").write_text(txt, encoding="utf-8")
    H2.write_json(
        OUT / "metrics.json",
        {
            "steps": steps,
            "final": list(final),
            "explore": explore,
            "rows": {key_of(k): v[1] for k, v in results.items()},
        },
    )
    print(txt)
    _ = step_tbl
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
