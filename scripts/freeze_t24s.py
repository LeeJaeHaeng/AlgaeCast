# ruff: noqa: E501  (한국어 문구)
"""비상안 T24S(엄격판) — T24 와 모두 같고, 목표일이 2025 인 5행을 학습과 OOF 결정값에서 뺀다.

근거: reports/experiments/PREREG_contingency.md 8절(2026-10-28, 학습 전 커밋). 대상 답변: 운영사무국이
"목표일 2025 측정 5행(기준일 2024-12-30 → 목표일 2025-01-06)도 학습 불가"라고 답한 경우에만 제출 모델로 교체한다.

- 학습 행: 기준일·목표일 모두 ≤ 2024-12-31(2,305행) — freeze_t24.select_rows(rows="t24"), 수온 임계 ≤2024.
- OOF 결정값: T24 와 같은 함수(freeze_t24.decisions)를 같은 OOF 캐시(v21_oof.parquet·oof_predictions.parquet)에
  적용하되, 2024 폴드 OOF 의 목표일 2025 5행을 뺀다 → 결합 가중치·CQR 이 바뀌고, 분류기 임계·운영점은 같아야 한다.
- 하이퍼파라미터·피처·구성원·시드·as_of 는 T24(= v2.1) 그대로. 튜닝·피처 변경 없음.
- 2026 정답으로 채점하지 않는다. submission_T24S.csv 는 만들되(형식 검증만) 2026 타깃은 읽지 않는다.

사용(저장소 사본에서, PYTHONPATH=<사본>/src): python scripts/freeze_t24s.py [--force]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd

from algaecast.collect.base import KST
from algaecast.config import ROOT, SUBMISSION_PATH
from algaecast.models import classifier as C
from algaecast.models import registry as R
from algaecast.models import v2 as V2
from algaecast.models.train import SEED, _prep, feature_sets

log = logging.getLogger("freeze_t24s")


def _load_t24() -> ModuleType:
    spec = importlib.util.spec_from_file_location("freeze_t24", Path(__file__).with_name("freeze_t24.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


F = _load_t24()
NAME = "T24S"
OUT = ROOT / "reports" / "experiments" / "contingency_T24S"
SUB = SUBMISSION_PATH.parent / "submission_T24S.csv"
PREREG_COMMIT = "커밋 후 기입"
RULE = "기준일·목표일 모두 ≤ 2024-12-31 인 학습 행(T24S 엄격판, PREREG_contingency 8절) — 목표일 2025-01-06 5행 제외"


def strict_decisions(reg: pd.DataFrame, clf: pd.DataFrame) -> tuple[dict, np.ndarray]:
    """OOF 캐시로 T24 와 같은 결정 함수를 돌리되 2024 폴드의 목표일 2025 행을 뺀다."""
    cfg = V2.config_v2()
    years = V2.years_of(reg)
    obs = reg["target_cells"].to_numpy(dtype=float)
    cache_r = F._aligned_cache(F.OOF_V21, reg, [*cfg.names, "ens"])
    cache_c = F._aligned_cache(F.OOF_PATH, reg, ["clf_a", "clf_b", "q10", "q50", "q90"])
    oof_reg = {k: cache_r[k].to_numpy(dtype=float) for k in cfg.names}
    quant = {k: cache_c[k].to_numpy(dtype=float) for k in ("q10", "q50", "q90")}
    p_a = cache_c["clf_a"].to_numpy(dtype=float)
    p_b = cache_c["clf_b"].to_numpy(dtype=float)
    cross = (years == 2024) & (pd.to_datetime(reg["target_date"]) > F.T24_LAST).to_numpy()
    if int(cross.sum()) != 5:
        raise SystemExit(f"중단: 2024 폴드의 목표일 2025 행이 5행이 아니다({int(cross.sum())}).")
    dec = F.decisions(years, obs, oof_reg, clf, p_a, p_b, quant, exclude=cross)
    return dec, cross


def run(force: bool) -> dict:
    F.guard_workspace()
    t0 = time.time()
    from algaecast.db.upload import predict_registry
    from algaecast.models.predict import validate_submission, write_submission
    from algaecast.models.quantile import fit_quantiles, predict_quantiles
    from algaecast.models.tune import spec_from_params

    OUT.mkdir(parents=True, exist_ok=True)
    cur = R.current_entry("regression")
    if str(cur.get("meta", {}).get("model_name", "")) == NAME and not force:
        raise SystemExit("중단: 사본 레지스트리 current 회귀가 이미 T24S 다(--force 로 다시 등록).")
    mcfg = F.model_cfg()
    reg, clf = F.frames()
    dec, cross = strict_decisions(reg, clf)
    # 분류기 임계·운영점은 5행을 빼도 같아야 한다(T24 감사 결과) — 다르면 멈춘다
    same = {
        "thr_clf_a": abs(dec["thr_clf_a"] - float(mcfg["thresholds"]["clf_a"])) < 1e-9,
        "thr_clf_b": abs(dec["thr_clf_b"] - float(mcfg["thresholds"]["clf_b"])) < 1e-9,
        "operating_point_r3": abs(dec["operating_point_r3"] - float(mcfg["operating_point"]["threshold"]))
        < 1e-9,
    }
    if not all(same.values()):
        raise SystemExit(f"중단: 5행을 뺀 분류기 임계·운영점이 T24 와 다르다 {same} {dec}")
    ref = F.OUT / "t24_check_oof.json"
    if ref.exists():  # T24 --check-oof 가 미리 계산해 둔 같은 값과 대조(사본에만 있음)
        pre = json.loads(ref.read_text(encoding="utf-8"))["decisions_excluding_target_2025_rows"]
        d = max(abs(pre["weights"][k] - dec["weights"][k]) for k in dec["weights"])
        if d > 1e-12 or abs(pre["cqr_qhat_log10"] - dec["cqr_qhat_log10"]) > 1e-12:
            raise SystemExit(f"중단: 결정값이 t24_check_oof.json 과 다르다(가중치 최대차 {d})")
    mcfg_s = json.loads(json.dumps(mcfg))
    mcfg_s["cqr"]["qhat_log10"] = dec["cqr_qhat_log10"]
    mcfg_s["cqr"]["n_calib"] = dec["cqr_n_calib"]
    w = dec["weights"]
    cfg = V2.config_v2()
    cols30 = list(feature_sets()["perc75"])
    _, cats30 = F.D.numeric_and_categorical(cols30)
    spec_c1 = spec_from_params(mcfg["selected"]["params"], "log_w")
    tr_reg, tr_clf = F.select_rows(reg, clf, "t24")
    if len(tr_reg) != 2305:
        raise SystemExit(f"중단: 엄격판 학습 행이 2,305행이 아니다({len(tr_reg)}).")
    clf_b = C.fit_clf(tr_clf, cols30, "over_window", mcfg["alert"]["over_window"]["params"])
    clf_a = C.fit_clf(tr_clf, cols30, "over_target", mcfg["alert"]["over_target"]["params"])
    q_models = fit_quantiles(tr_clf, cols30, spec_c1)
    model = V2.fit_final(tr_reg, cfg, weights=w, seed=SEED)
    model.train_info = F.train_info(tr_reg, RULE)
    Xc = _prep(tr_clf[cols30], cats30)
    model.aux = {
        "cols": cols30,
        "cats": list(cats30),
        "categories": {c: list(Xc[c].cat.categories) for c in cats30},
        "source": "T24S 학습 행(엄격판) — 분류기·분위 입력 열·범주",
    }
    # 2025 같은 252행 확인(검증 분할 — 2026 미사용)
    va_reg, va_clf = F.valid_2025(reg, clf)
    obs = va_reg["target_cells"].to_numpy(dtype=float)
    pred = model.predict(va_reg)
    pb = C.predict_proba(clf_b, va_clf, cols30)
    pa = C.predict_proba(clf_a, va_clf, cols30)
    q = predict_quantiles(q_models, va_clf, cols30)
    ev = F.eval_2025(
        obs,
        va_clf["over_target"].to_numpy(dtype=int),
        va_clf["over_window"].to_numpy(dtype=int),
        pred,
        q,
        pa,
        pb,
        mcfg_s,
    )
    thr_b = float(mcfg["thresholds"]["clf_b"])
    meta_common = {
        "model_name": NAME,
        "train_through": 2024,
        "basis": "reports/experiments/PREREG_contingency.md 8절",
    }
    e_c = R.register(
        "classifier",
        {
            "model": clf_b,
            "cols": cols30,
            "cats": list(cats30),
            "categories": {c: list(clf_b._prep_ref[c].cat.categories) for c in cats30},
            "threshold": thr_b,
            "target": "over_window",
        },
        features=cols30,
        metrics_holdout={k: ev["clf_b"][k] for k in ("pr_auc", "brier", "f1", "thr")},
        meta={**meta_common, "target": "over_window(+4~+10일 창 ≥10k)", "train": F.train_info(tr_clf, RULE)},
        set_current=True,
    )
    e_q = R.register(
        "quantile",
        {"models": q_models, "cols": cols30, "cats": list(cats30)},
        features=cols30,
        metrics_holdout={"picp80": ev["quantile"]["picp80"], "mpiw80_log": ev["quantile"]["mpiw80_log"]},
        meta={**meta_common, "quantiles": [0.1, 0.5, 0.9], "train": F.train_info(tr_clf, RULE)},
        set_current=True,
    )
    e_r = R.register(
        "regression",
        model.to_registry(),
        features=model.cols,
        metrics_holdout={
            k: ev["regression"][k]
            for k in ("rmse_log", "r2_log", "r2_raw", "r2_pearson_raw", "nse_raw", "f1_10k")
        },
        meta={
            **meta_common,
            "kind": V2.KIND,
            "purpose": "contingency T24S cells (v2.1 구성, 최종 적합·OOF 결정값 모두 목표일 ≤2024-12-31)",
            "config": model.config.to_dict(),
            "weights": w,
            "weights_basis": "2020~2024 연도 확장 CV OOF NNLS(log10, 합=1)에서 2024 폴드의 목표일 2025 5행 제외",
            "cqr": {"qhat_log10": dec["cqr_qhat_log10"], "n_calib": dec["cqr_n_calib"]},
            "train": model.train_info,
            "seed": SEED,
            "classifier_version": e_c["version"],
            "quantile_version": e_q["version"],
            "aux_source": model.aux["source"],
        },
        set_current=True,
    )
    files = []
    for e in (e_r, e_c, e_q):
        d = F.MODELS_DIR / e["name"] / e["version"]
        files.append(
            {
                "name": e["name"],
                "version": e["version"],
                "sha256_model_pkl": R.file_sha256(d / "model.pkl"),
                "bytes_model_pkl": (d / "model.pkl").stat().st_size,
                "sha256_meta_json": R.file_sha256(d / "meta.json"),
            }
        )
    # 레지스트리 왕복 + submission(형식 검증만, 2026 타깃 미사용)
    pr25 = predict_registry(va_reg.copy())
    rt = {"pred_cell_count": F.diff_stats(pr25["pred_cell_count"].to_numpy(), pred)}
    sub, test_t = F.build_submission()
    rt["test_pred_cell_count"] = F.diff_stats(
        predict_registry(test_t)["pred_cell_count"].to_numpy(), model.predict(test_t)
    )
    bad = {k: v for k, v in rt.items() if v["max_abs"] != 0.0 or v["nan_mismatch"]}
    if bad:
        raise SystemExit(f"중단: 레지스트리 왕복 예측 차 {bad}")
    write_submission(sub, SUB)
    val = validate_submission(SUB)
    val["sha256_full"] = R.file_sha256(SUB)
    if not (val["rows"] == 124 and val["columns"] and val["order_same_as_sample"] and not val["nan"]):
        raise SystemExit(f"중단: submission_T24S 검증 실패 {val}")
    t24 = pd.read_csv(F.SUB_T24, encoding="utf-8-sig", dtype={"station_id": str})
    dl = np.log10(sub["pred_cells"].to_numpy(float) + 1) - np.log10(t24["pred_cells"].to_numpy(float) + 1)
    out = {
        "model_name": NAME,
        "rule": RULE,
        "train_regression": model.train_info,
        "train_classifier_quantile": F.train_info(tr_clf, RULE),
        "excluded_rows": reg.loc[cross, F.KEYS].astype(str).to_dict("records"),
        "site_thresholds_year": F.THRESHOLD_YEAR,
        "decisions": dec,
        "decisions_same_as_t24": same,
        "eval_2025": F.flat(ev),
        "registry_roundtrip": rt,
        "files": files,
        "submission_T24S": {
            **val,
            "path": "submission/submission_T24S.csv",
            "vs_t24_median_abs_log10_diff": float(np.median(np.abs(dl))),
            "vs_t24_max_abs_log10_diff": float(np.max(np.abs(dl))),
            "t24_sha256": R.file_sha256(F.SUB_T24),
            "scored_on_2026": False,
        },
        "registry_current": R.current_versions(),
        "frozen_at_kst": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "minutes": round((time.time() - t0) / 60, 2),
    }
    (OUT / "t24s_fit.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {k: out[k] for k in ("model_name", "decisions", "files", "submission_T24S")},
            ensure_ascii=False,
            indent=1,
            default=float,
        )
    )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
