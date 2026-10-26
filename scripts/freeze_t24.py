# ruff: noqa: E501  (한국어 문서 문자열·표)
"""비상안 T24 모델 — v2.1 과 모두 같고 최종 적합 범위만 ≤2024(기준일·목표일 ≤ 2024-12-31).

사전등록: reports/experiments/PREREG_contingency.md 2절·7절(커밋 960d76f). 운영사무국이 "최종 모델은 2024년까지
자료로만 학습"이라고 답한 경우에만 제출 모델을 T24 로 바꾼다. T24 모델·submission_T24.csv 는 제출 패키지에 넣지 않는다.

같게 두는 것(v2.1): 피처 35(선별 30 + 상류 5)·구성원 c1·c3·c2·cg·하이퍼파라미터(config/model.yaml)·결합 가중치
(reports/experiments/FIX-v2.1/v21_fit.json, 2020~2024 연도 확장 CV OOF NNLS)·시드 42·분류기 b 하이퍼파라미터와 임계·
운영점(r=3)·CQR(config/model.yaml)·as_of = 기준일.
바꾸는 것: 최종 학습 행(기준일·목표일 ≤ 2024-12-31)과 수온 임계(T24 학습기간 측정 ≤2024 — 학습·2025 확인·2026 예측 행 모두).

**저장소 사본에서만 실행한다.** `.git` 이 있는 저장소 본체에서는 중단한다(본체 models/·config/·submission/ 을 건드리지 않음).

단계
--check-oof : (1) 사본 레지스트리 current(v2.1)로 submission 을 다시 만들어 submission/submission.csv 와 바이트 비교
              (2) 연도 확장 OOF(F1~F5 + Final: 기준일 연도 ≤2024 → 2025) — 회귀 구성원 c1·c3·c2·cg, 분류기 a·b,
                  분위 q10/50/90 — 를 다시 계산해 캐시(data/processed/v21_oof.parquet·oof_predictions.parquet)와 비교
              (3) 다시 계산한 OOF 로 결합 가중치·분류기 임계·운영점·CQR 을 다시 정해 v2.1 값과 비교, CV·2025 지표 비교
              (4) 참고: 2024 폴드 OOF 에서 목표일이 2025 인 행(기준일 2024-12-30, 5행)을 뺐을 때의 같은 값
              Final 폴드가 2025 홀드아웃 보고값(tbl_holdout_2025_v21·tbl_alert_classification·tbl_quantile·tbl_cqr)을
              만든 ≤2024 학습 경로다(학습 행 = 기준일 연도 ≤2024, 2,310행).
--fit       : T24 학습(회귀·분류기 b·분위) → 사본 레지스트리 등록(current) → 2025 같은 252행 지표(v2.1 보고값과 비교)
              → submission/submission_T24.csv(124행) → contingency_T24/FROZEN_T24.md 초안.
              --rows fold 는 Final 폴드와 같은 행(기준일 연도 ≤2024, 목표일 2025-01-06 5행 포함)으로 같은 경로를
              돌려 2025 지표만 비교한다(레지스트리 등록·제출 파일·동결 문서 없음). --rows fold --register 를 주면
              그 모델을 T24 대신 등록(current)·제출 파일·동결 문서까지 만든다(정의를 Final 폴드로 정할 때만).
출력: reports/experiments/contingency_T24/(t24_check_oof.json, t24_fit.json 또는 t24_fit_fold.json, FROZEN_T24.md),
      submission/submission_T24.csv. 2026 정답·격리 파일은 읽지 않는다.
사용: python scripts/freeze_t24.py --check-oof | --fit [--rows t24|fold] [--register] [--force]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from algaecast.collect.base import KST
from algaecast.config import CONFIG_DIR, DATA_DIR, MODELS_DIR, ROOT, SUBMISSION_PATH
from algaecast.eval.metrics import bootstrap_ci, compute_all
from algaecast.features.constants import apply_site_thresholds, site_thresholds
from algaecast.models import classifier as C
from algaecast.models import data as D
from algaecast.models import registry as R
from algaecast.models import v2 as V2
from algaecast.models.train import SEED, _prep, feature_sets

log = logging.getLogger("freeze_t24")

T24_LAST = pd.Timestamp("2024-12-31")  # T24 학습 행의 기준일·목표일 상한
THRESHOLD_YEAR = 2024  # T24 학습기간 수온 임계(측정 ≤2024) = 2025 홀드아웃 폴드와 같은 값
FINAL_YEAR = 2025  # 확인용 2025 행(같은 252행)
T10K = 10_000.0
KEYS = ["station_id", "base_date", "target_date"]
OUT = ROOT / "reports" / "experiments" / "contingency_T24"
FIT_V21 = ROOT / "reports" / "experiments" / "FIX-v2.1" / "v21_fit.json"
HOLD_V21 = ROOT / "reports" / "eval" / "tbl_holdout_2025_v21.json"
OOF_V21 = DATA_DIR / "processed" / "v21_oof.parquet"
OOF_PATH = DATA_DIR / "processed" / "oof_predictions.parquet"
SUB_T24 = SUBMISSION_PATH.parent / "submission_T24.csv"
SAMPLE = DATA_DIR / "raw" / "competition" / "algae_contest_2026" / "sample_submission.csv"
DOC = OUT / "FROZEN_T24.md"
PLACEHOLDER = "커밋 후 기입"
PREREG_COMMIT = "960d76f"
REG_KEYS = ("rmse_log", "mae_log", "r2_log", "r2_raw", "r2_pearson_raw", "nse_raw", "f1_10k", "f1_1k")
CV_KEYS = ("rmse_log", "r2_log", "r2_raw", "nse_raw", "f1_10k")
T24_RULE = "기준일 ≤ 2024-12-31 이면서 목표일 ≤ 2024-12-31 인 학습 행(T24, PREREG_contingency 7절)"
FOLD_RULE = "기준일 연도 ≤ 2024 인 학습 행(2025 홀드아웃 Final 폴드와 같음, 목표일 2025-01-06 5행 포함)"


# ---------------------------------------------------------------- 가드·행 선택
def guard_workspace(root: Path = ROOT) -> None:
    """저장소 본체(.git 이 있는 폴더)에서는 중단한다 — T24 는 사본에서만 학습·등록한다."""
    if (Path(root) / ".git").exists():
        raise SystemExit(
            f"중단: {root} 는 저장소 본체(.git 있음)다. T24 는 저장소 사본에서만 실행한다(본체 models/·submission/ 보호)."
        )


def t24_mask(df: pd.DataFrame) -> np.ndarray:
    """T24 학습 행: 기준일·목표일 모두 2024-12-31 이하."""
    bd, td = pd.to_datetime(df["base_date"]), pd.to_datetime(df["target_date"])
    return ((bd <= T24_LAST) & (td <= T24_LAST)).to_numpy()


def fold_mask(df: pd.DataFrame) -> np.ndarray:
    """2025 홀드아웃 Final 폴드 학습 행: 기준일 연도 ≤ 2024(models.cv.year_folds 와 같은 규칙)."""
    return (pd.to_datetime(df["base_date"]).dt.year <= FINAL_YEAR - 1).to_numpy()


def guard_t24(df: pd.DataFrame) -> None:
    """T24 학습 프레임 가드: 기준일·목표일 ≤ 2024-12-31, test 분할 없음, 타깃 있음."""
    for col in ("base_date", "target_date"):
        d = pd.to_datetime(df[col])
        if (d > T24_LAST).any():
            raise RuntimeError(f"{col} > 2024-12-31 인 행 {int((d > T24_LAST).sum())}개 — T24 학습 금지")
    if "split" in df.columns and (df["split"] == "test").any():
        raise RuntimeError("test 분할 행이 T24 학습 프레임에 섞임")
    if not np.isfinite(df["target_cells"].to_numpy(dtype=float)).all():
        raise RuntimeError("타깃 결측 행이 T24 학습 프레임에 섞임")


def diff_stats(a: np.ndarray, b: np.ndarray) -> dict:
    """두 배열의 최대 절대차(둘 다 값이 있는 칸)와 결측 위치 불일치 수."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    na, nb = np.isnan(a), np.isnan(b)
    both = ~na & ~nb
    return {
        "n": int(both.sum()),
        "nan_mismatch": int((na != nb).sum()),
        "max_abs": float(np.max(np.abs(a[both] - b[both]))) if both.any() else 0.0,
    }


def cqr_band(q10: np.ndarray, q90: np.ndarray, qhat: float) -> tuple[np.ndarray, np.ndarray]:
    """CQR 보정 구간(log10 공간 ±q̂) — db.upload.predict_registry·holdout_v21 과 같은 계산."""
    lo = np.clip(10 ** (np.log10(np.asarray(q10, dtype=float) + 1) - qhat) - 1, 0, None)
    hi = 10 ** (np.log10(np.asarray(q90, dtype=float) + 1) + qhat) - 1
    return lo, hi


def b0_of(df: pd.DataFrame) -> np.ndarray:
    """B0 지속성(기준일 측정 세포수)."""
    return np.clip(10 ** df["cell_log_t0"].fillna(0).to_numpy(dtype=float) - 1, 0, None)


# ---------------------------------------------------------------- 설정·프레임
def model_cfg() -> dict:
    return yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))


def v21_weights() -> dict[str, float]:
    return {k: float(v) for k, v in json.loads(FIT_V21.read_text(encoding="utf-8"))["weights"].items()}


def frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """(회귀 프레임: v2 학습 행 + 상류 5열, 분류기·분위 프레임: 같은 행 + 분류 타깃 a·b). 행 순서가 같아야 한다."""
    reg = V2.load_training_frame(config=V2.config_v2())
    clf = C.add_targets(D.load_train_valid("S1"))
    if not (reg[KEYS].astype(str).to_numpy() == clf[KEYS].astype(str).to_numpy()).all():
        raise SystemExit("중단: 회귀 프레임과 분류기 프레임의 행 순서가 다르다.")
    return reg, clf


def select_rows(reg: pd.DataFrame, clf: pd.DataFrame, rows: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """학습 행 선택 + 수온 임계(측정 ≤2024) 재적용. rows = t24(기준일·목표일 ≤2024-12-31) | fold(기준일 연도 ≤2024)."""
    m = t24_mask(reg) if rows == "t24" else fold_mask(reg)
    tr_reg = apply_site_thresholds(reg[m].reset_index(drop=True), THRESHOLD_YEAR)
    tr_clf = apply_site_thresholds(clf[m].reset_index(drop=True), THRESHOLD_YEAR)
    if rows == "t24":
        guard_t24(tr_reg)
        guard_t24(tr_clf)
    return tr_reg, tr_clf


def valid_2025(reg: pd.DataFrame, clf: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """2025 같은 252행(홀드아웃 Final 폴드 검증 행) — 수온 임계는 ≤2024(폴드와 같음)."""
    m = (pd.to_datetime(reg["base_date"]).dt.year == FINAL_YEAR).to_numpy()
    return (
        apply_site_thresholds(reg[m].reset_index(drop=True), THRESHOLD_YEAR),
        apply_site_thresholds(clf[m].reset_index(drop=True), THRESHOLD_YEAR),
    )


# ---------------------------------------------------------------- 2025 지표(같은 함수로 T24·v2.1 캐시 모두)
def eval_2025(
    obs: np.ndarray,
    y_a: np.ndarray,
    y_b: np.ndarray,
    pred: np.ndarray,
    q: dict[str, np.ndarray],
    p_a: np.ndarray,
    p_b: np.ndarray,
    mcfg: dict,
) -> dict:
    """회귀·분위·CQR·분류기 a/b·운영점의 2025 지표(holdout_v21·alert·transitions 표와 같은 정의)."""
    thr = mcfg["thresholds"]
    qhat = float(mcfg["cqr"]["qhat_log10"])
    op = float(mcfg["operating_point"]["threshold"])
    m = compute_all(obs, pred)
    q10c, q90c = cqr_band(q["q10"], q["q90"], qhat)
    sh = compute_all(obs, pred, q10=q10c, q90=q90c, p10k=p_a)
    qm = compute_all(obs, q["q50"], q10=q["q10"], q90=q["q90"])
    ca = C.cls_metrics(y_a, p_a, float(thr["clf_a"]))
    cb = C.cls_metrics(y_b, p_b, float(thr["clf_b"]))
    pr, yy = p_b >= op, y_b == 1
    tp, fp, fn = int((pr & yy).sum()), int((pr & ~yy).sum()), int((~pr & yy).sum())
    return {
        "regression": {k: float(m[k]) for k in REG_KEYS},
        "cqr_shared": {
            "picp80_cqr": float(sh["picp80"]),
            "mpiw80_log_cqr": float(sh["mpiw80_log"]),
            "brier_10k_clf_a": float(sh["brier_10k"]),
        },
        "quantile": {
            "q50_rmse_log": float(qm["rmse_log"]),
            "picp80": float(qm["picp80"]),
            "mpiw80_log": float(qm["mpiw80_log"]),
            "mpiw80_raw": float(qm["mpiw80_raw"]),
            "q90_10k_f1_a": float(C.cls_metrics(y_a, (q["q90"] >= T10K).astype(float), 0.5)["f1"]),
        },
        "clf_b": {k: float(cb[k]) for k in ("pr_auc", "brier", "f1", "precision", "recall", "thr")},
        "clf_a": {k: float(ca[k]) for k in ("pr_auc", "brier", "f1", "precision", "recall", "thr")},
        "operating_point": {
            "threshold": op,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else float("nan"),
            "recall": tp / (tp + fn) if tp + fn else float("nan"),
        },
    }


def flat(d: dict, prefix: str = "") -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(flat(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out


def cache_2025(reg: pd.DataFrame) -> dict[str, np.ndarray]:
    """v2.1 OOF 캐시의 2025 행(Final 폴드 = ≤2024 학습 모델의 2025 예측) — ens·clf_a·clf_b·q10/50/90."""
    v = pd.read_parquet(OOF_V21)
    o = pd.read_parquet(OOF_PATH)
    for d in (v, o):
        d["station_id"] = d["station_id"].astype(str)
        for c in ("base_date", "target_date"):
            d[c] = pd.to_datetime(d[c]).dt.strftime("%Y-%m-%d")
    k = pd.DataFrame(
        {
            "station_id": reg["station_id"].astype(str).to_numpy(),
            "base_date": pd.to_datetime(reg["base_date"]).dt.strftime("%Y-%m-%d").to_numpy(),
            "target_date": pd.to_datetime(reg["target_date"]).dt.strftime("%Y-%m-%d").to_numpy(),
        }
    )
    d = k.merge(v[[*KEYS, "ens"]], on=KEYS, how="left").merge(
        o[[*KEYS, "clf_a", "clf_b", "q10", "q50", "q90"]], on=KEYS, how="left"
    )
    if len(d) != len(reg):
        raise SystemExit("중단: OOF 캐시 키가 학습 프레임과 1:1 이 아니다.")
    fin = (pd.to_datetime(reg["base_date"]).dt.year == FINAL_YEAR).to_numpy()
    return {c: d.loc[fin, c].to_numpy(dtype=float) for c in ("ens", "clf_a", "clf_b", "q10", "q50", "q90")}


def v21_cache_2025(reg: pd.DataFrame, clf: pd.DataFrame, mcfg: dict) -> dict:
    """v2.1 2025 보고값을 OOF 캐시(Final 폴드)에서 같은 함수로 다시 계산(보고 표의 원 정밀도)."""
    c = cache_2025(reg)
    fin = (pd.to_datetime(reg["base_date"]).dt.year == FINAL_YEAR).to_numpy()
    return eval_2025(
        reg.loc[fin, "target_cells"].to_numpy(dtype=float),
        clf.loc[fin, "over_target"].to_numpy(dtype=int),
        clf.loc[fin, "over_window"].to_numpy(dtype=int),
        c["ens"],
        {k: c[k] for k in ("q10", "q50", "q90")},
        c["clf_a"],
        c["clf_b"],
        mcfg,
    )


# ---------------------------------------------------------------- --check-oof
def _aligned_cache(path: Path, frame: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    c = pd.read_parquet(path)
    c["station_id"] = c["station_id"].astype(str)
    for k in ("base_date", "target_date"):
        c[k] = pd.to_datetime(c[k]).dt.strftime("%Y-%m-%d")
    key = pd.DataFrame(
        {
            "station_id": frame["station_id"].astype(str).to_numpy(),
            "base_date": pd.to_datetime(frame["base_date"]).dt.strftime("%Y-%m-%d").to_numpy(),
            "target_date": pd.to_datetime(frame["target_date"]).dt.strftime("%Y-%m-%d").to_numpy(),
        }
    )
    out = key.merge(c[[*KEYS, *cols]], on=KEYS, how="left")
    if len(out) != len(frame):
        raise SystemExit(f"중단: 캐시 {path.name} 키가 학습 프레임과 1:1 이 아니다.")
    return out


def decisions(
    years: np.ndarray,
    obs: np.ndarray,
    oof_reg: dict[str, np.ndarray],
    clf: pd.DataFrame,
    p_a: np.ndarray,
    p_b: np.ndarray,
    quant: dict[str, np.ndarray],
    exclude: np.ndarray | None = None,
) -> dict:
    """OOF 로 정하는 값 — 결합 가중치(2020~2024 NNLS), 분류기 임계(CV F1 최대), 운영점(r=3), CQR(2023~2024)."""
    from algaecast.eval import transitions as TR
    from algaecast.models.ensemble import nnls_weights

    keep = np.ones(len(years), dtype=bool) if exclude is None else ~exclude
    cv = np.isin(years, V2.CV_YEARS) & keep
    w = nnls_weights({k: np.asarray(v)[cv] for k, v in oof_reg.items()}, obs[cv])
    y_a = clf["over_target"].to_numpy(dtype=int)
    y_b = clf["over_window"].to_numpy(dtype=int)
    thr_a = C.best_threshold(y_a[cv], p_a[cv])
    thr_b = C.best_threshold(y_b[cv], p_b[cv])
    o = pd.DataFrame(
        {
            "year": years,
            "b0": b0_of(clf),
            "clf_b": p_b,
            "over_window": y_b,
            "q10": quant["q10"],
            "q90": quant["q90"],
            "target_cells": obs,
        }
    )[keep | (years == FINAL_YEAR)]
    op = TR.operating_points(o, "clf_b", "over_window", ratios=(3,))
    _, cq = TR.cqr(o, calib_years=(2023, 2024))
    return {
        "weights": {k: float(v) for k, v in w.items()},
        "thr_clf_a": float(thr_a),
        "thr_clf_b": float(thr_b),
        "operating_point_r3": float(op.iloc[0]["CV 최적 임계"]),
        "cqr_qhat_log10": float(cq["qhat_log10"]),
        "cqr_n_calib": int(cq["n_calib"]),
        "n_cv_rows": int(cv.sum()),
    }


def run_check_oof() -> dict:
    guard_workspace()
    t0 = time.time()
    from algaecast.models.predict import make_submission, write_submission
    from algaecast.models.quantile import cv_quantiles
    from algaecast.models.tune import spec_from_params

    OUT.mkdir(parents=True, exist_ok=True)
    mcfg = model_cfg()
    res: dict = {"computed_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"), "root": str(ROOT)}
    # (1) 사본 레지스트리 current(v2.1)로 submission 재현
    cur = R.current_entry("regression")
    tmp = OUT / "_baseline_submission_v21.csv"
    write_submission(make_submission(), tmp)
    same = tmp.read_bytes() == SUBMISSION_PATH.read_bytes()
    res["baseline_submission"] = {
        "current_regression": cur["version"],
        "model_name": cur.get("meta", {}).get("model_name"),
        "sha256": R.file_sha256(tmp),
        "same_bytes_as_submission_csv": bool(same),
    }
    tmp.unlink()
    log.info("기준 제출 파일 재현: %s", same)
    # (2) OOF 재계산
    cfg = V2.config_v2()
    reg, clf = frames()
    years = V2.years_of(reg)
    obs = reg["target_cells"].to_numpy(dtype=float)
    oof_reg = V2.cv_members(reg, SEED, cfg)
    cols30 = list(feature_sets()["perc75"])
    p_a, _ = C.cv_proba(clf, cols30, "over_target", mcfg["alert"]["over_target"]["params"])
    p_b, _ = C.cv_proba(clf, cols30, "over_window", mcfg["alert"]["over_window"]["params"])
    spec_c1 = spec_from_params(mcfg["selected"]["params"], "log_w")
    quant = cv_quantiles(clf, cols30, spec_c1)
    cache_r = _aligned_cache(OOF_V21, reg, [*cfg.names, "ens"])
    cache_c = _aligned_cache(OOF_PATH, reg, ["clf_a", "clf_b", "q10", "q50", "q90"])
    has = years >= min(V2.CV_YEARS)
    fin = years == FINAL_YEAR
    cmp_all, cmp_fin = {}, {}
    new_cols = {**{k: oof_reg[k] for k in cfg.names}, "clf_a": p_a, "clf_b": p_b, **quant}
    for k, arr in new_cols.items():
        ref = cache_r[k] if k in cache_r.columns else cache_c[k]
        cmp_all[k] = diff_stats(np.asarray(arr)[has], ref.to_numpy(dtype=float)[has])
        cmp_fin[k] = diff_stats(np.asarray(arr)[fin], ref.to_numpy(dtype=float)[fin])
    # (3) OOF 로 정하는 값
    dec = decisions(years, obs, oof_reg, clf, p_a, p_b, quant)
    w_v21 = v21_weights()
    ens = np.full(len(reg), np.nan)
    ens[has] = V2.combine({k: np.asarray(oof_reg[k])[has] for k in w_v21}, w_v21)
    cmp_all["ens"] = diff_stats(ens[has], cache_r["ens"].to_numpy(dtype=float)[has])
    cmp_fin["ens"] = diff_stats(ens[fin], cache_r["ens"].to_numpy(dtype=float)[fin])
    per = pd.DataFrame(
        [{k: compute_all(obs[years == y], ens[years == y])[k] for k in CV_KEYS} for y in V2.CV_YEARS]
    )
    hold = json.loads(HOLD_V21.read_text(encoding="utf-8"))
    cv_rep = {k: hold["cv"]["v21"][f"{k}_fold_mean"] for k in CV_KEYS}
    res["oof_vs_cache_2020_2025"] = cmp_all
    res["oof_vs_cache_final_2025"] = cmp_fin
    res["decisions_recomputed"] = dec
    res["decisions_v21"] = {
        "weights": w_v21,
        "thr_clf_a": float(mcfg["thresholds"]["clf_a"]),
        "thr_clf_b": float(mcfg["thresholds"]["clf_b"]),
        "operating_point_r3": float(mcfg["operating_point"]["threshold"]),
        "cqr_qhat_log10": float(mcfg["cqr"]["qhat_log10"]),
        "cqr_n_calib": int(mcfg["cqr"]["n_calib"]),
    }
    res["weights_max_abs_diff"] = float(max(abs(dec["weights"][k] - w_v21[k]) for k in w_v21))
    res["cv_fold_mean_recomputed"] = {k: float(per[k].mean()) for k in CV_KEYS}
    res["cv_fold_mean_reported"] = cv_rep
    res["final_2025_recomputed"] = flat(
        eval_2025(
            obs[fin],
            clf.loc[fin, "over_target"].to_numpy(dtype=int),
            clf.loc[fin, "over_window"].to_numpy(dtype=int),
            ens[fin],
            {k: np.asarray(v)[fin] for k, v in quant.items()},
            p_a[fin],
            p_b[fin],
            mcfg,
        )
    )
    res["final_2025_cache"] = flat(v21_cache_2025(reg, clf, mcfg))
    # (4) 참고: 2024 폴드 OOF 에서 목표일이 2025 인 행을 뺀 값
    cross = (years == 2024) & (pd.to_datetime(reg["target_date"]) > T24_LAST).to_numpy()
    res["rows_2024_fold_target_2025"] = reg.loc[cross, KEYS].astype(str).to_dict("records")
    res["decisions_excluding_target_2025_rows"] = decisions(
        years, obs, oof_reg, clf, p_a, p_b, quant, exclude=cross
    )
    res["minutes"] = round((time.time() - t0) / 60, 2)
    (OUT / "t24_check_oof.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {
                k: res[k]
                for k in (
                    "baseline_submission",
                    "oof_vs_cache_final_2025",
                    "decisions_recomputed",
                    "decisions_v21",
                    "decisions_excluding_target_2025_rows",
                )
            },
            ensure_ascii=False,
            indent=1,
            default=float,
        )
    )
    return res


# ---------------------------------------------------------------- --fit
def train_info(df: pd.DataFrame, rule: str) -> dict:
    bd, td = pd.to_datetime(df["base_date"]), pd.to_datetime(df["target_date"])
    return {
        "n_rows": int(len(df)),
        "base_date_min": str(bd.min().date()),
        "base_date_max": str(bd.max().date()),
        "target_date_max": str(td.max().date()),
        "rule": rule,
        "rows_by_site": {
            str(k): int(v) for k, v in df["station_id"].astype(str).value_counts().sort_index().items()
        },
        "threshold_year": THRESHOLD_YEAR,
        "seed": SEED,
    }


def build_submission(sample_path: Path = SAMPLE) -> tuple[pd.DataFrame, pd.DataFrame]:
    """레지스트리 current(T24)로 test 124조합 예측 — make_submission 과 같은 형식, test 피처의 수온 임계만 ≤2024."""
    from algaecast.db.upload import predict_registry

    sample = pd.read_csv(sample_path, encoding="utf-8-sig", dtype={"station_id": str})
    test = apply_site_thresholds(D.load_test_features("S1"), THRESHOLD_YEAR)
    test["base_date"] = pd.to_datetime(test["base_date"]).dt.strftime("%Y-%m-%d")
    test["target_date"] = pd.to_datetime(test["target_date"]).dt.strftime("%Y-%m-%d")
    pr = predict_registry(test)
    pred = pd.DataFrame(
        {
            "station_id": test["station_id"].astype(str),
            "base_date": test["base_date"],
            "target_date": test["target_date"],
            "pred_cells": np.clip(np.round(pr["pred_cell_count"].to_numpy()), 0, None).astype("int64"),
        }
    )
    out = sample[["station_id", "base_date", "target_date"]].merge(
        pred, on=["station_id", "base_date", "target_date"], how="left"
    )
    if out["pred_cells"].isna().any():
        raise RuntimeError("sample_submission 조합의 예측이 비었다")
    out["pred_cells"] = out["pred_cells"].astype("int64")
    if list(out.columns) != list(sample.columns) or len(out) != len(sample):
        raise RuntimeError("제출 형식이 sample_submission 과 다르다")
    return out, test


def run_fit(rows: str, force: bool, register: bool = False) -> dict:
    guard_workspace()
    t0 = time.time()
    from algaecast.db.upload import predict_registry
    from algaecast.eval.holdout_v2 import FNS
    from algaecast.models.predict import validate_submission, write_submission
    from algaecast.models.quantile import fit_quantiles, predict_quantiles
    from algaecast.models.tune import spec_from_params

    OUT.mkdir(parents=True, exist_ok=True)
    cur = R.current_entry("regression")
    set_cur = rows == "t24" or register
    if set_cur and str(cur.get("meta", {}).get("model_name", "")).startswith("T24") and not force:
        raise SystemExit("중단: 사본 레지스트리 current 회귀가 이미 T24 다(--force 로 다시 등록).")
    mcfg = model_cfg()
    cfg = V2.config_v2()
    w = v21_weights()
    cols30 = list(feature_sets()["perc75"])
    _, cats30 = D.numeric_and_categorical(cols30)
    spec_c1 = spec_from_params(mcfg["selected"]["params"], "log_w")
    reg, clf = frames()
    tr_reg, tr_clf = select_rows(reg, clf, rows)
    rule = T24_RULE if rows == "t24" else FOLD_RULE
    log.info(
        "%s: 학습 %d행(기준일 %s~%s)", rows, len(tr_reg), tr_reg["base_date"].min(), tr_reg["base_date"].max()
    )
    # 분류기 b(등록)·a(2025 Brier 확인용, 등록 안 함)·분위
    clf_b = C.fit_clf(tr_clf, cols30, "over_window", mcfg["alert"]["over_window"]["params"])
    clf_a = C.fit_clf(tr_clf, cols30, "over_target", mcfg["alert"]["over_target"]["params"])
    q_models = fit_quantiles(tr_clf, cols30, spec_c1)
    # 회귀(v2.1 가중치 고정)
    model = V2.fit_final(tr_reg, cfg, weights=w, seed=SEED)
    model.train_info = train_info(tr_reg, rule)
    Xc = _prep(tr_clf[cols30], cats30)
    model.aux = {
        "cols": cols30,
        "cats": list(cats30),
        "categories": {c: list(Xc[c].cat.categories) for c in cats30},
        "source": f"T24 학습 행({rows}) — 분류기·분위 입력 열·범주",
    }
    # 2025 같은 252행 확인
    va_reg, va_clf = valid_2025(reg, clf)
    obs = va_reg["target_cells"].to_numpy(dtype=float)
    y_a = va_clf["over_target"].to_numpy(dtype=int)
    y_b = va_clf["over_window"].to_numpy(dtype=int)
    pred = model.predict(va_reg)
    pb = C.predict_proba(clf_b, va_clf, cols30)
    pa = C.predict_proba(clf_a, va_clf, cols30)
    q = predict_quantiles(q_models, va_clf, cols30)
    ev = eval_2025(obs, y_a, y_b, pred, q, pa, pb, mcfg)
    ci = {
        k: {
            kk: float(vv)
            for kk, vv in bootstrap_ci(obs, pred, fn, n=1000, seed=42).items()
            if kk in ("lo", "hi")
        }
        for k, fn in FNS.items()
    }
    ref = v21_cache_2025(reg, clf, mcfg)
    c25 = cache_2025(reg)
    vs_cache = {
        "ens": diff_stats(pred, c25["ens"]),
        "clf_b": diff_stats(pb, c25["clf_b"]),
        "clf_a": diff_stats(pa, c25["clf_a"]),
        **{k: diff_stats(q[k], c25[k]) for k in ("q10", "q50", "q90")},
        "median_abs_log10_ens": float(np.median(np.abs(np.log10(pred + 1) - np.log10(c25["ens"] + 1)))),
        "max_abs_log10_ens": float(np.max(np.abs(np.log10(pred + 1) - np.log10(c25["ens"] + 1)))),
    }
    # 레지스트리 등록(분류기 → 분위 → 회귀) — T24(또는 --register 를 준 fold)만. 비교용 fold 는 등록하지 않는다
    name = "T24" if rows == "t24" else ("T24-fold" if register else "T24-fold(참고, 미등록)")
    thr_b = float(mcfg["thresholds"]["clf_b"])
    out: dict = {
        "rows": rows,
        "model_name": name,
        "rule": rule,
        "train_regression": model.train_info,
        "train_classifier_quantile": train_info(tr_clf, rule),
        "site_thresholds_year": THRESHOLD_YEAR,
        "site_thresholds": site_thresholds(THRESHOLD_YEAR),
        "weights": w,
        "thresholds": mcfg["thresholds"],
        "operating_point": mcfg["operating_point"],
        "cqr": mcfg["cqr"],
        "eval_2025": flat(ev),
        "eval_2025_ci95": ci,
        "eval_2025_v21_cache": flat(ref),
        "eval_2025_delta": {k: float(flat(ev)[k] - flat(ref)[k]) for k in flat(ev)},
        "pred_2025_vs_v21_oof_final": vs_cache,
        "files": [],
    }
    if set_cur:
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
            meta={
                "model_name": name,
                "train_through": 2024,
                "target": "over_window(+4~+10일 창 ≥10k)",
                "purpose": "contingency T24 probability",
                "basis": "reports/experiments/PREREG_contingency.md 7절",
                "train": train_info(tr_clf, rule),
            },
            set_current=set_cur,
        )
        e_q = R.register(
            "quantile",
            {"models": q_models, "cols": cols30, "cats": list(cats30)},
            features=cols30,
            metrics_holdout={"picp80": ev["quantile"]["picp80"], "mpiw80_log": ev["quantile"]["mpiw80_log"]},
            meta={
                "model_name": name,
                "train_through": 2024,
                "quantiles": [0.1, 0.5, 0.9],
                "basis": "reports/experiments/PREREG_contingency.md 7절",
                "train": train_info(tr_clf, rule),
            },
            set_current=set_cur,
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
                "kind": V2.KIND,
                "model_name": name,
                "train_through": 2024,
                "purpose": "contingency T24 cells (v2.1 구성·가중치, 최종 적합 ≤2024)",
                "basis": "reports/experiments/PREREG_contingency.md 7절",
                "config": model.config.to_dict(),
                "weights": w,
                "weights_basis": "v2.1 과 같음 — 2020~2024 연도 확장 CV OOF NNLS(log10, 합=1), reports/experiments/FIX-v2.1/v21_fit.json",
                "train": model.train_info,
                "seed": SEED,
                "classifier_version": e_c["version"],
                "quantile_version": e_q["version"],
                "aux_source": model.aux["source"],
            },
            set_current=set_cur,
        )
        for e, note in (
            (e_r, f"{name} 회귀(c1·c3·c2·cg, 피처 35, v2.1 가중치)"),
            (e_c, f"{name} 분류기 b(피처 30)"),
            (e_q, f"{name} 분위 q10·q50·q90(피처 30)"),
        ):
            d = MODELS_DIR / e["name"] / e["version"]
            out["files"].append(
                {
                    "name": e["name"],
                    "version": e["version"],
                    "sha256_model_pkl": R.file_sha256(d / "model.pkl"),
                    "bytes_model_pkl": (d / "model.pkl").stat().st_size,
                    "sha256_meta_json": R.file_sha256(d / "meta.json"),
                    "bytes_meta_json": (d / "meta.json").stat().st_size,
                    "features_hash": e["features_hash"],
                    "note": note,
                    "current": set_cur,
                }
            )
    if set_cur:
        # 레지스트리 왕복(운영 예측 경로 predict_registry) — 2025 행과 test 행 모두 메모리 모델과 같아야 한다
        pr25 = predict_registry(va_reg.copy())
        rt = {
            "pred_cell_count": diff_stats(pr25["pred_cell_count"].to_numpy(), pred),
            "p_alert": diff_stats(pr25["p_alert"].to_numpy(), pb),
            **{k: diff_stats(pr25[k].to_numpy(), q[k]) for k in ("q10", "q50", "q90")},
        }
        sub, test_t = build_submission()
        rt["test_pred_cell_count"] = diff_stats(
            predict_registry(test_t)["pred_cell_count"].to_numpy(), model.predict(test_t)
        )
        out["registry_roundtrip"] = rt
        bad = {k: v for k, v in rt.items() if v["max_abs"] != 0.0 or v["nan_mismatch"]}
        if bad:
            raise SystemExit(f"중단: 레지스트리 왕복 예측 차 {bad}")
        write_submission(sub, SUB_T24)
        val = validate_submission(SUB_T24)
        val["sha256_full"] = R.file_sha256(SUB_T24)
        ok = val["rows"] == 124 and val["columns"] and val["order_same_as_sample"] and not val["nan"]
        if not (ok and val["negative"] == 0 and val["bom"]):
            raise SystemExit(f"중단: submission_T24 검증 실패 {val}")
        v21 = pd.read_csv(SUBMISSION_PATH, encoding="utf-8-sig", dtype={"station_id": str})
        dl = np.log10(sub["pred_cells"].to_numpy(float) + 1) - np.log10(v21["pred_cells"].to_numpy(float) + 1)
        out["submission_T24"] = {
            **val,
            "path": "submission/submission_T24.csv",
            "vs_v21_median_abs_log10_diff": float(np.median(np.abs(dl))),
            "vs_v21_max_abs_log10_diff": float(np.max(np.abs(dl))),
            "v21_sha256": R.file_sha256(SUBMISSION_PATH),
        }
        out["registry_current"] = R.current_versions()
    out["frozen_at_kst"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    out["minutes"] = round((time.time() - t0) / 60, 2)
    fn = (
        "t24_fit.json"
        if rows == "t24"
        else ("t24_fit_fold_registered.json" if register else "t24_fit_fold.json")
    )
    (OUT / fn).write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8", newline="\n"
    )
    if set_cur:
        DOC.write_text(frozen_md(out), encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                k: out[k]
                for k in (
                    "model_name",
                    "train_regression",
                    "files",
                    "eval_2025_delta",
                    "pred_2025_vs_v21_oof_final",
                )
                if k in out
            },
            ensure_ascii=False,
            indent=1,
            default=float,
        )
    )
    return out


# ---------------------------------------------------------------- 동결 문서 초안
CHECK_ROWS: tuple[tuple[str, str], ...] = (
    ("regression.rmse_log", "회귀 rmse_log"),
    ("regression.mae_log", "회귀 mae_log"),
    ("regression.r2_log", "회귀 r2_log"),
    ("regression.r2_raw", "회귀 r2_raw(= nse_raw)"),
    ("regression.r2_pearson_raw", "회귀 r2_pearson_raw"),
    ("regression.f1_10k", "회귀 F1@10k"),
    ("regression.f1_1k", "회귀 F1@1k"),
    ("clf_b.pr_auc", "분류기 b PR-AUC(창 ≥1만)"),
    ("clf_b.brier", "분류기 b Brier"),
    ("clf_b.f1", "분류기 b F1(임계 0.87)"),
    ("operating_point.recall", "경보(p_alert ≥ 0.46) Recall(창 ≥1만)"),
    ("operating_point.precision", "경보 Precision"),
    ("quantile.q50_rmse_log", "분위 q50 rmse_log"),
    ("quantile.picp80", "분위 PICP80(보정 전)"),
    ("quantile.mpiw80_log", "분위 MPIW80_log(보정 전)"),
    ("quantile.q90_10k_f1_a", "q90 ≥1만 F1(타깃 a)"),
    ("cqr_shared.picp80_cqr", "CQR PICP80"),
    ("cqr_shared.mpiw80_log_cqr", "CQR MPIW80_log"),
    ("cqr_shared.brier_10k_clf_a", "Brier_10k(분류기 a, 확인용)"),
)


def frozen_md(s: dict) -> str:
    """FROZEN_T24.md 초안(형식은 contingency_S/FROZEN_S.md). 동결 커밋 칸은 비워 둔다."""
    tr = s["train_regression"]
    w = " · ".join(f"{k} {v:.6f}" for k, v in s["weights"].items())
    files = "\n".join(
        f"| {f['name']} | {f['version']} | `{f['sha256_model_pkl']}` | {f['bytes_model_pkl']:,} | `{f['sha256_meta_json']}` | {f['note']} |"
        for f in s["files"]
    )
    ev, ref, dl = s["eval_2025"], s["eval_2025_v21_cache"], s["eval_2025_delta"]
    chk = "\n".join(
        f"| {lab} | {ev[k]:.4f} | {ref[k]:.4f} | {dl[k]:+.4f} |" for k, lab in CHECK_ROWS if k in ev
    )
    sub = s["submission_T24"]
    th = json.dumps(s["site_thresholds"], ensure_ascii=False)
    return f"""# 모델 동결 T24 (FROZEN_T24) — 비상용: v2.1 구성, 최종 적합만 ≤2024

- 근거: `reports/experiments/PREREG_contingency.md` 2절·7절(사전등록 커밋 {PREREG_COMMIT}, 학습 전 push). T24 모델은 **제출 패키지에 넣지 않는다.** 2절 전환 규칙(운영사무국이 '최종 모델은 2024년까지 자료로만 학습'으로 답한 경우)에서만 제출 모델로 교체한다.
- 동결 커밋: `{PLACEHOLDER}` (이 문서를 담은 커밋이 T24 동결 커밋이다. 2026 사후 계산은 이 커밋 뒤에만 1회 한다.)
- 동결 시각(KST): {s["frozen_at_kst"]}
- 정의: v2.1 과 피처 35개(선별 30 + 상류 5)·구성원(c1·c3·c2·cg)·하이퍼파라미터·결합 가중치(2020~2024 CV OOF NNLS, v2.1 값 그대로)·시드 42·분류기 b 하이퍼파라미터·분류기 임계·운영점(r=3)·CQR(2023~2024 OOF)·as_of = 기준일이 모두 같다. 바꾼 것은 최종 적합 범위({s['rule']})와 그 학습기간의 수온 임계(측정 ≤2024: {th}) 둘뿐이다. 수온 임계는 학습·2025 확인·2026 예측 행에 모두 같은 값(≤2024)을 쓴다.
- 학습 범위: {tr["rule"]} — {tr["n_rows"]:,}행, 기준일 {tr["base_date_min"]} ~ {tr["base_date_max"]}, 목표일 ≤ {tr["target_date_max"]}. 지점별 {json.dumps(tr["rows_by_site"], ensure_ascii=False)}
- 실행: 저장소 사본에서 `python scripts/freeze_t24.py --check-oof`(OOF·가중치·임계·운영점·CQR 재현 확인) → `python scripts/freeze_t24.py --fit`(학습·사본 레지스트리 등록·2025 확인·submission_T24). 저장소의 v2.1 모델·레지스트리·config·submission.csv 는 건드리지 않았다.

## 동결 파일 (사본 `models/`, current)

| name | version | sha256(model.pkl) | bytes | sha256(meta.json) | 비고 |
|---|---|---|---|---|---|
{files}

- 결합 가중치(v2.1 과 같음): {w}
- 분류기 임계(CV OOF F1 최대): a {float(s["thresholds"]["clf_a"]):.2f} · b {float(s["thresholds"]["clf_b"]):.2f}. 운영점(r=3): {float(s["operating_point"]["threshold"]):.2f}. CQR q̂(2023~2024, n={int(s["cqr"]["n_calib"])}): {float(s["cqr"]["qhat_log10"]):.4f} — 모두 v2.1 값.
- submission_T24.csv(124행) sha256 `{sub["sha256_full"]}`(v2.1 대비 |Δlog10| 중앙 {sub["vs_v21_median_abs_log10_diff"]:.3f}·최대 {sub["vs_v21_max_abs_log10_diff"]:.3f})

## 2025 확인(같은 252행, 2026 미사용)

| 지표(2025) | T24 | v2.1 보고값(OOF Final 폴드) | Δ(T24 − 보고값) |
|---|---|---|---|
{chk}

## 2026 사후

- 동결 커밋 뒤 1회. 사본에서 `python -m algaecast.eval.posthoc_t24 --commit <동결 커밋>`.
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check-oof", action="store_true")
    g.add_argument("--fit", action="store_true")
    ap.add_argument("--rows", choices=("t24", "fold"), default="t24")
    ap.add_argument("--register", action="store_true", help="--rows fold 모델을 T24 대신 등록(current)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.check_oof:
        run_check_oof()
        return 0
    run_fit(args.rows, args.force, args.register)
    return 0


if __name__ == "__main__":
    sys.exit(main())
