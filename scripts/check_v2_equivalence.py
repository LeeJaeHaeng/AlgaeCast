"""운영 v2 경로(models.v2)와 실험 코드(EXP-confirm C)의 동등성 검증 — 결과는 수치(JSON)만 남긴다.

(u) 상류 피처: features.upstream.build_upstream == exp.r2_upstream.build_features
    (load_base 전체, NaN 위치 포함), test 124행: build_upstream == confirm_2026 방식
    (r2_upstream.build_variant_features, lag 0)
(a) 폴드 모드: V2(학습 ≤2024 → 2025 예측) vs C 시드 42 의 2025 OOF
    (confirm.config_members(df, f2, 42, genus=True) + harness.ensemble_expanding(c1,c3,c2,cg) 를
    새로 계산, 캐시 미사용) + 구성원별 OOF(2020~2025) 대조
(b) fit_weights(시드 42) vs ensemble_expanding 의 2025 가중치
(c) 최종 모드: V2.fit_final(학습 2,562행) 의 test 124행 예측
    vs confirm_2026.final_fit_predict + combine(같은 학습 행)
    (판정 커밋 가드가 있는 confirm_2026.main 은 실행하지 않는다. 2026 정답은 읽지 않는다 — 예측끼리만 비교)
    + 레지스트리 저장 형식(pickle 왕복) 예측 대조
(d) v1 구성(피처 30, 구성원 3, config/model.yaml 가중치)과 v1 제출본(submission/submission.csv)
    d1 운영 예측 경로: v1 동결 회귀 구성원을 V2Model 로 감싸(from_v1_registry) predict →
       정수 반올림이 v1 제출본과 같은지
    d2 운영 학습 경로: V2.fit_final(v1 구성, 현재 학습 2,562행)
       vs confirm_2026.final_fit_predict 의 c1·c3·c2 + 같은 가중치
    d3 재학습 재현: d2 의 예측을 정수 반올림해 v1 제출본과 비교. v1 동결 모델은 2026-10-21 학습 프레임
       (2,566행 — 목표일 2026-01-05 인 4행 포함, 2026-10-22 격리로 정답이 빠짐)으로 학습했으므로
       현재 프레임으로는 정확히 같을 수 없다. 학습 표본 수 차이는 LightGBM 첫 트리의 leaf_count 합
       (배깅 표본 수)으로 2026 정답 없이 확인한다.

사용: python scripts/check_v2_equivalence.py [--out data/processed/exp/v2_dryrun/equivalence.json]
(약 수 분: C 시드 42 OOF·V2 OOF·폴드·최종·v1 재학습을 모두 새로 계산한다)
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
import time
from pathlib import Path

import numpy as np
import pandas as pd

from algaecast.config import DATA_DIR, SUBMISSION_PATH
from algaecast.features.upstream import UPSTREAM_COLS, build_upstream
from algaecast.models import data as D
from algaecast.models import v2 as V2
from algaecast.models.ensemble import combine
from algaecast.models.predict import DEFAULT_SAMPLE

log = logging.getLogger("v2_equivalence")
OUT = DATA_DIR / "processed" / "exp" / "v2_dryrun" / "equivalence.json"
NAMES = ("c1", "c3", "c2", "cg")


def _logdiff(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    if (np.isfinite(a) != np.isfinite(b)).any():
        return float("inf")
    return float(np.max(np.abs(np.log10(a[ok] + 1) - np.log10(b[ok] + 1)))) if ok.any() else float("nan")


def _frame_equal(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    x, y = a.to_numpy(dtype=float), b.to_numpy(dtype=float)
    return {
        "rows": int(len(a)),
        "nan_same": bool((np.isnan(x) == np.isnan(y)).all()),
        "exact": bool(np.array_equal(x, y, equal_nan=True)),
        "max_abs_diff": float(np.nanmax(np.abs(x - y))) if np.isfinite(x - y).any() else 0.0,
    }


def check_upstream(df: pd.DataFrame, te: pd.DataFrame) -> dict:
    from algaecast.exp import r2_upstream as R2

    out = {"train": _frame_equal(R2.build_features(df)[UPSTREAM_COLS], build_upstream(df))}
    algae_all = R2.load_algae(last=pd.Timestamp("2026-12-31"))
    f2_te = R2.build_variant_features(te, str(R2.CHOSEN["lag_mode"]), algae=algae_all)[UPSTREAM_COLS]
    out["test"] = _frame_equal(f2_te, build_upstream(te))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from algaecast.exp import confirm as CF
    from algaecast.exp import confirm_2026 as C26
    from algaecast.exp import harness as H

    t0 = time.time()
    res: dict = {}
    df = H.load_base()
    frame = V2.load_training_frame()
    key_same = bool(
        len(df) == len(frame)
        and (df["station_id"].astype(str).to_numpy() == frame["station_id"].astype(str).to_numpy()).all()
        and (
            pd.to_datetime(df["base_date"]).to_numpy() == pd.to_datetime(frame["base_date"]).to_numpy()
        ).all()
    )
    res["train_rows"] = {"load_base": int(len(df)), "v2_frame": int(len(frame)), "same_keys_order": key_same}
    te = D.load_test_features("S1").reset_index(drop=True)
    res["test_rows"] = int(len(te))

    # (u) 상류 피처
    res["u_upstream"] = check_upstream(df, te)
    log.info("(u) %s", res["u_upstream"])

    # C 시드 42 OOF(실험 경로, 새로 계산)
    t1 = time.time()
    f2 = CF.f2_frame(df)
    mem_c = CF.config_members(df, f2, 42, genus=True)
    ens_c, w_c = H.ensemble_expanding(df, mem_c, names=NAMES)
    res["minutes_c_oof"] = round((time.time() - t1) / 60, 2)

    # V2 OOF·가중치(운영 경로)
    t1 = time.time()
    cfg = V2.config_v2()
    oof = V2.cv_members(frame, 42, cfg)
    w_v2 = V2.fit_weights(frame, 42, cfg, oof=oof)
    res["minutes_v2_oof"] = round((time.time() - t1) / 60, 2)
    res["b_weights"] = {
        "v2_fit_weights": w_v2,
        "harness_2025": {k: float(v) for k, v in w_c[2025].items()},
        "max_abs_diff": float(max(abs(w_v2[k] - w_c[2025][k]) for k in NAMES)),
        "order": list(w_v2) == list(w_c[2025]),
    }
    years = V2.years_of(frame)
    m6 = years >= 2020
    res["a_members_oof_2020_2025_logdiff"] = {k: _logdiff(oof[k][m6], mem_c[k][m6]) for k in NAMES}

    # (a) 폴드 모드: 학습 ≤2024 → 2025
    t1 = time.time()
    tr = frame[years <= 2024].reset_index(drop=True)
    va = frame[years == 2025].reset_index(drop=True)
    fold = V2.fit_final(tr, cfg, weights=w_v2, seed=42)
    pred25 = fold.predict(va)
    fin = H.years_of(df) == 2025
    res["a_fold_2025"] = {
        "rows": int(fin.sum()),
        "max_logdiff_vs_C_oof": _logdiff(pred25, ens_c[fin]),
        "max_logdiff_vs_v2_oof_combine": _logdiff(pred25, V2.oof_ensemble(frame, oof, w_v2)[years == 2025]),
        "train_rows": int(len(tr)),
    }
    res["minutes_fold"] = round((time.time() - t1) / 60, 2)
    log.info("(a) %s (b) %s", res["a_fold_2025"], res["b_weights"]["max_abs_diff"])

    # (c) 최종 모드: 같은 학습 행으로 confirm_2026.final_fit_predict
    t1 = time.time()
    cols = H.base_columns() + list(f2.columns)
    train_c = pd.concat([df, f2], axis=1)
    from algaecast.exp import r2_upstream as R2

    algae_all = R2.load_algae(last=pd.Timestamp("2026-12-31"))
    f2_te = R2.build_variant_features(te, str(R2.CHOSEN["lag_mode"]), algae=algae_all)[list(f2.columns)]
    mem_te = C26.final_fit_predict(train_c, pd.concat([te, f2_te], axis=1), cols)
    pred_c = combine({k: mem_te[k] for k in NAMES}, w_c[2025])
    final = V2.fit_final(frame, cfg, weights=w_v2, seed=42)
    pred_v2 = final.predict(te)
    rt = V2.V2Model.from_registry(pickle.loads(pickle.dumps(final.to_registry())))
    pred_rt = rt.predict(te)
    res["c_final_test"] = {
        "rows": int(len(te)),
        "max_logdiff_vs_confirm_2026": _logdiff(pred_v2, pred_c),
        "max_absdiff_cells": float(np.max(np.abs(pred_v2 - pred_c))),
        "members_max_logdiff": {k: _logdiff(final.predict_members(te)[k], mem_te[k]) for k in NAMES},
        "pickle_roundtrip_max_absdiff": float(np.max(np.abs(pred_rt - pred_v2))),
    }
    res["minutes_final"] = round((time.time() - t1) / 60, 2)
    log.info("(c) %s", res["c_final_test"])

    # (d) v1 구성 ↔ v1 제출본
    t1 = time.time()
    from algaecast.db.upload import predict_registry
    from algaecast.models.registry import load_current

    reg_obj, reg_entry = load_current("regression")
    v1_reg_pred = predict_registry(te)["pred_cell_count"].to_numpy(dtype=float)
    # d1 운영 예측 경로(v1 동결 구성원, 재학습 없음)
    wrapped = V2.from_v1_registry(reg_obj)
    p_wrap = wrapped.predict(te)
    res["d1_v1_frozen_via_v2_predict"] = {
        "registry_version": reg_entry["version"],
        **_vs_submission(te, p_wrap),
        "max_logdiff_vs_v1_predict_registry": _logdiff(p_wrap, v1_reg_pred),
    }
    # d2 운영 학습 경로(같은 학습 행) vs confirm_2026.final_fit_predict
    c1cfg = V2.config_v1()
    frame_v1 = V2.load_training_frame(config=c1cfg)
    m_v1 = V2.fit_final(frame_v1, c1cfg)
    p_v1 = m_v1.predict(te)
    mem_v1 = C26.final_fit_predict(df, te, H.base_columns())
    w1 = c1cfg.fixed_weights()
    p_v1_exp = combine({k: mem_v1[k] for k in w1}, w1)
    res["d2_v1_retrain_vs_confirm_2026_procedure"] = {
        "train_rows": int(len(frame_v1)),
        "weights": w1,
        "max_logdiff": _logdiff(p_v1, p_v1_exp),
        "members_max_logdiff": {k: _logdiff(m_v1.predict_members(te)[k], mem_v1[k]) for k in w1},
    }
    # d3 재학습(현재 2,562행) → v1 제출본, 학습 표본 수 차이(leaf_count 합)
    frozen = {m.name: wrapped.members[m.name] for m in V2.V1_MEMBERS}
    res["d3_v1_retrain_vs_submission"] = {
        **_vs_submission(te, p_v1),
        "max_logdiff_vs_v1_frozen": _logdiff(p_v1, v1_reg_pred),
        "first_tree_leaf_count_sum": {
            "frozen_v1": {
                "c1": _leaf_n(frozen["c1"]["model"]),
                "c2": _leaf_n(frozen["c2"]["model"]),
                "c3_clf": _leaf_n(frozen["c3"]["clf"]),
            },
            "retrain_2562": {
                "c1": _leaf_n(m_v1.members["c1"]["model"]),
                "c2": _leaf_n(m_v1.members["c2"]["model"]),
                "c3_clf": _leaf_n(m_v1.members["c3"]["clf"]),
            },
        },
        "train_rows_now": int(len(frame_v1)),
        "train_rows_with_quarantined_target": int(len(D.load_train_valid("S1", drop_missing_target=False))),
    }
    res["minutes_v1"] = round((time.time() - t1) / 60, 2)
    res["minutes_total"] = round((time.time() - t0) / 60, 2)
    log.info("(d) %s", {k: v for k, v in res.items() if k.startswith("d")})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    ok = (
        res["a_fold_2025"]["max_logdiff_vs_C_oof"] < 1e-9
        and res["b_weights"]["max_abs_diff"] < 1e-12
        and res["c_final_test"]["max_logdiff_vs_confirm_2026"] < 1e-9
        and res["d1_v1_frozen_via_v2_predict"]["rounded_match"]
        and res["d2_v1_retrain_vs_confirm_2026_procedure"]["max_logdiff"] < 1e-9
        and res["u_upstream"]["train"]["exact"]
        and res["u_upstream"]["test"]["exact"]
    )
    print("동등성(u·a·b·c·d1·d2):", "모두 충족" if ok else "미충족 항목 있음")
    print("d3 재학습 반올림 일치:", res["d3_v1_retrain_vs_submission"]["rounded_equal"], "/ 124")
    return 0 if ok else 1


def _vs_submission(te: pd.DataFrame, pred: np.ndarray) -> dict:
    """test 행 예측을 sample 순서로 정수 반올림해 v1 제출본(submission/submission.csv)과 비교."""
    sub = pd.read_csv(SUBMISSION_PATH, encoding="utf-8-sig", dtype={"station_id": str})
    sample = pd.read_csv(DEFAULT_SAMPLE, encoding="utf-8-sig", dtype={"station_id": str})
    key = ["station_id", "base_date", "target_date"]
    pr = pd.DataFrame(
        {
            "station_id": te["station_id"].astype(str).to_numpy(),
            "base_date": pd.to_datetime(te["base_date"]).dt.strftime("%Y-%m-%d").to_numpy(),
            "target_date": pd.to_datetime(te["target_date"]).dt.strftime("%Y-%m-%d").to_numpy(),
            "pred": np.asarray(pred, dtype=float),
        }
    )
    m = sample[key].merge(pr, on=key, how="left").merge(sub, on=key, how="left")
    rounded = np.clip(np.round(m["pred"].to_numpy()), 0, None).astype("int64")
    v1 = m["pred_cells"].to_numpy(dtype="int64")
    return {
        "rows": int(len(m)),
        "rounded_equal": int((rounded == v1).sum()),
        "rounded_match": bool((rounded == v1).all()),
        "max_abs_diff_rounded": int(np.max(np.abs(rounded - v1))),
    }


def _leaf_n(model: object) -> int:
    """LightGBM 첫 트리의 leaf_count 합(그 트리가 본 학습 표본 수 — 배깅 적용 후)."""

    def s(n: dict) -> int:
        return int(n["leaf_count"]) if "leaf_count" in n else s(n["left_child"]) + s(n["right_child"])

    return s(model.booster_.dump_model()["tree_info"][0]["tree_structure"])  # type: ignore[attr-defined]


if __name__ == "__main__":
    raise SystemExit(main())
