# ruff: noqa: E501  (한국어 표)
"""EXP-confirm 판정 커밋 뒤 1회: 채택 모델 C 의 2026 test 124 조합 사후 계산(PREREG.md 규칙).

- 실행 조건: reports/experiments/EXP-confirm/RESULT.md 가 '판정: **채택' 으로 git 에 커밋돼 있어야 한다(아니면 중단).
- 최종 모델: 시드 42(config/seed.yaml), 학습 = v1 학습·검증 행 전체(기준일 ≤ 2025-12-31, v1 동결 모델과 같은 범위).
  회귀 C1(smearing)·C3·C2 = v1 하이퍼파라미터, 피처 v1 30 + R2 상류 5열. 속별 cg = R3 G2(log, smearing), 같은 35열.
  결합 가중치 = 시드 42 의 2020~2024 CV OOF NNLS(harness.ensemble_expanding 의 2025 가중치). 분위는 v1 동결 모델 그대로.
- 비교: v1 제출본(submission/submission.csv), B0 지속성. 2026 결과로 판정을 번복하지 않는다.
사용: python -m algaecast.exp.confirm_2026
"""

from __future__ import annotations

import json
import subprocess
import time

import numpy as np
import pandas as pd

from algaecast.config import ROOT, SUBMISSION_PATH
from algaecast.eval.live import load_test_targets
from algaecast.eval.metrics import compute_all
from algaecast.exp import confirm as CF
from algaecast.exp import harness as H
from algaecast.exp import r2_upstream as R2
from algaecast.exp import r3_genus as R3
from algaecast.models import data as D
from algaecast.models.ensemble import combine
from algaecast.models.train import SEED, fit_predict

OUT = H.EXP_DATA / "EXP-confirm"
RESULT = "reports/experiments/EXP-confirm/RESULT.md"
METRICS = ("r2_raw", "r2_pearson_raw", "nse_raw", "rmse_log", "r2_log", "f1_10k")


def judgment_committed() -> bool:
    """RESULT.md 의 커밋된 내용(HEAD)이 '채택' 판정인지."""
    r = subprocess.run(
        ["git", "show", f"HEAD:{RESULT}"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
    )
    return r.returncode == 0 and "판정: **채택" in r.stdout


def final_fit_predict(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> dict[str, np.ndarray]:
    """2025 까지 전체 행으로 학습해 test 행을 예측(구성원별 원단위)."""
    sp = H.v1_specs()
    out = {}
    f = fit_predict(train, test, cols, sp["c1"], SEED)
    out["c1"] = f.raw * f.smear
    out["c3"] = fit_predict(train, test, cols, sp["c3"], SEED).raw
    out["c2"] = fit_predict(train, test, cols, sp["c2"], SEED).raw
    tg = R3.genus_targets(train, R3.load_algae())
    parts = []
    for p in R3.LAYOUTS[R3.CHOSEN["layout"]]:
        tr = R3._fold_train(train, R3.part_target(tg, p), np.arange(len(train)))
        g = fit_predict(tr, test, cols, sp["c1"], SEED)
        parts.append(np.clip(g.raw * g.smear, 0, None))
    out["cg"] = np.sum(parts, axis=0)
    return {k: np.clip(np.nan_to_num(v, nan=0.0), 0, None) for k, v in out.items()}


def main() -> int:
    if not judgment_committed():
        raise SystemExit(
            f"중단: {RESULT} 가 '채택' 판정으로 커밋돼 있지 않다(PREREG: 2026 은 판정 커밋 뒤 채택 모델에만 1회)."
        )
    t0 = time.time()
    df = H.load_base()
    f2 = CF.f2_frame(df)
    cols = H.base_columns() + list(f2.columns)
    # 결합 가중치: 시드 42 의 2020~2024 CV OOF NNLS
    mem42 = CF.config_members(df, f2, SEED, genus=True)
    _, w = H.ensemble_expanding(df, mem42, names=("c1", "c3", "c2", "cg"))
    weights = w[2025]
    # 학습 = 2025 까지 전체, 예측 = 2026 test 124 조합(여기서부터 2026 사용 — 판정 커밋 뒤 1회)
    train = pd.concat([df, f2], axis=1)
    te = D.load_test_features("S1").reset_index(drop=True)
    algae_all = R2.load_algae(last=pd.Timestamp("2026-12-31"))
    f2_te = R2.build_variant_features(te, str(R2.CHOSEN["lag_mode"]), algae=algae_all)[list(f2.columns)]
    test = pd.concat([te, f2_te], axis=1)
    mem = final_fit_predict(train, test, cols)
    pred_c = combine({k: mem[k] for k in ("c1", "c3", "c2", "cg")}, weights)
    # 정답·비교 대상
    tt = load_test_targets(i_know_this_is_for_post_hoc_only=True)
    key = ["station_id", "base_date"]
    test["base_date"] = pd.to_datetime(test["base_date"]).dt.date
    sub = pd.read_csv(SUBMISSION_PATH, encoding="utf-8-sig")
    sub["base_date"] = pd.to_datetime(sub["base_date"]).dt.date
    frame = test[key + ["cell_log_t0"]].assign(pred_c=pred_c, **{f"m_{k}": v for k, v in mem.items()})
    frame = frame.merge(
        sub[key + ["pred_cells"]].rename(columns={"pred_cells": "pred_v1"}), on=key, how="left"
    )
    frame = frame.merge(tt[key + ["target_cells"]], on=key, how="left")
    frame["b0"] = np.clip(10 ** frame["cell_log_t0"].fillna(0).to_numpy(float) - 1, 0, None)
    ok = frame["target_cells"].notna() & frame["pred_v1"].notna()
    obs = frame.loc[ok, "target_cells"].to_numpy(float)
    rows = []
    for name, col in (
        ("v1 제출본(동결)", "pred_v1"),
        ("C(채택 모델, 시드 42)", "pred_c"),
        ("B0 지속성", "b0"),
    ):
        m = compute_all(obs, frame.loc[ok, col].to_numpy(float))
        rows.append({"구성": name, "n": int(ok.sum()), **{k: float(m[k]) for k in METRICS}})
    OUT.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OUT / "posthoc_2026_C.parquet", index=False)
    res = {"weights": weights, "rows": rows, "minutes": round((time.time() - t0) / 60, 1)}
    (OUT / "posthoc_2026.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8"
    )
    head = "| 구성 | n | " + " | ".join(METRICS) + " |\n|" + "---|" * (len(METRICS) + 2)
    print(head)
    for r in rows:
        print(f"| {r['구성']} | {r['n']} | " + " | ".join(f"{r[k]:.3f}" for k in METRICS) + " |")
    print("가중치", {k: round(v, 3) for k, v in weights.items()}, "소요", res["minutes"], "분")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
