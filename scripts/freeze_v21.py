# ruff: noqa: E501  (한국어 문서 문자열)
"""운영·제출 모델 v2.1 — 데이터 유래 상수 누수 수정판(FIX-v2.1) 학습·등록·동결 문서·제출 파일.

사전등록: reports/experiments/FIX-v2.1/PREREG.md. 구성·하이퍼파라미터·피처 목록은 v2 와 같고(R5),
수정 피처(수위 편차 as-of, 폴드별 수온 임계, ASOS D1, 보현산댐 2025~ 결측)로 데이터 적합 부분을 전부 다시 한다(R6).
분류기(b)·분위는 `python -m algaecast.models.alert --skip-tune` 이, 운영점·CQR 은 `python -m algaecast.eval.transitions`
가 같은 절차로 다시 정한다. 2026 정답·격리 파일은 읽지 않는다.

단계
--oof    : 학습 프레임 → 구성원별 연도 확장 OOF(폴드별 임계, 시드 42) → 2020~2024 OOF NNLS 가중치 → 2025 홀드아웃.
           data/processed/v21_oof.parquet, reports/experiments/FIX-v2.1/v21_fit.json 저장.
           data/processed/oof_predictions.parquet 의 점예측 열 ens 를 v2.1 OOF 로 바꾸고 v1-fix 앙상블은 ens_v1fix 로 옮긴다
           (평가 모듈 transitions·report 가 ens 를 점예측으로 쓴다).
--freeze : v21_fit.json 의 가중치로 최종 학습(기준일·목표일 ≤2025-12-31) → models/regression/<버전> 등록(current),
           models/FROZEN_v2.1.md, dist/v2/submission_v2.csv(v2 제출본 보존), submission/submission.csv(v2.1).
           current 회귀가 v1-fix(ensemble, alert --skip-tune 산출)가 아니면 중단.
git(add·commit·tag)·Release 는 사람이 한다.
사용: python scripts/freeze_v21.py --oof | --freeze [--force]
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from algaecast.collect.base import KST
from algaecast.config import CONFIG_DIR, DATA_DIR, MODELS_DIR, ROOT, SUBMISSION_PATH
from algaecast.eval.metrics import compute_all
from algaecast.features.constants import FINAL_THRESHOLD_YEAR, site_thresholds
from algaecast.models import registry as R
from algaecast.models import v2 as V2
from algaecast.models.predict import make_submission, validate_submission, write_submission
from algaecast.models.train import SEED

log = logging.getLogger("freeze_v21")
OUT = ROOT / "reports" / "experiments" / "FIX-v2.1"
FIT_JSON = OUT / "v21_fit.json"
OOF_V21 = DATA_DIR / "processed" / "v21_oof.parquet"
OOF_PATH = DATA_DIR / "processed" / "oof_predictions.parquet"
V2_COPY = ROOT / "dist" / "v2" / "submission_v2.csv"
DOC = "FROZEN_v2.1.md"
METRIC_KEYS = ("rmse_log", "r2_log", "r2_raw", "r2_pearson_raw", "nse_raw", "f1_10k")
PLACEHOLDER = "커밋 후 기입"
KEYS = ["station_id", "base_date", "target_date"]


def _key(df: pd.DataFrame) -> pd.Series:
    return (
        df["station_id"].astype(str)
        + "|"
        + pd.to_datetime(df["base_date"]).dt.strftime("%Y-%m-%d")
        + "|"
        + pd.to_datetime(df["target_date"]).dt.strftime("%Y-%m-%d")
    )


def run_oof(seed: int) -> dict:
    cfg = V2.config_v2()
    frame = V2.load_training_frame(config=cfg)
    log.info("학습 프레임 %d행(기준일 %s~%s)", len(frame), frame["base_date"].min(), frame["base_date"].max())
    oof = V2.cv_members(frame, seed, cfg)
    weights = V2.fit_weights(frame, seed, cfg, oof=oof)
    years = V2.years_of(frame)
    ens = np.full(len(frame), np.nan)  # 2020~2025 행(OOF 가 있는 연도) 전체에 같은 가중치로 결합
    has = years >= min(V2.CV_YEARS)
    ens[has] = V2.combine({k: np.asarray(oof[k])[has] for k in weights}, weights)
    obs = frame["target_cells"].to_numpy(dtype=float)
    fin = years == V2.FINAL_YEAR
    cvm = np.isin(years, V2.CV_YEARS)
    hold = {k: float(compute_all(obs[fin], ens[fin])[k]) for k in METRIC_KEYS}
    cv_by_year = {
        int(y): {k: float(compute_all(obs[years == y], ens[years == y])[k]) for k in METRIC_KEYS}
        for y in V2.CV_YEARS
    }
    cv_mean = {k: float(np.mean([cv_by_year[y][k] for y in cv_by_year])) for k in METRIC_KEYS}
    out = frame[KEYS].copy()
    for k, v in oof.items():
        out[k] = v
    out["ens"] = ens
    out["target_cells"] = obs
    out.to_parquet(OOF_V21, index=False)
    # OOF 캐시: ens(점예측) = v2.1, v1-fix 앙상블은 ens_v1fix
    o = pd.read_parquet(OOF_PATH)
    if "ens_v1fix" not in o.columns:
        o["ens_v1fix"] = o["ens"]
    m = pd.Series(ens, index=_key(frame).to_numpy())
    o["ens"] = m.reindex(_key(o).to_numpy()).to_numpy()
    n_missing = int(o["ens"].isna().sum() - o["ens_v1fix"].isna().sum())
    o.to_parquet(OOF_PATH, index=False)
    doc = {
        "computed_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "seed": seed,
        "n_rows": len(frame),
        "n_cv": int(cvm.sum()),
        "n_2025": int(fin.sum()),
        "weights": weights,
        "holdout_2025": hold,
        "cv_mean_2020_2024": cv_mean,
        "cv_by_year": cv_by_year,
        "oof_cache_rows_without_v21": n_missing,
        "site_caution_wtemp_final": site_thresholds(FINAL_THRESHOLD_YEAR),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    FIT_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                k: doc[k]
                for k in ("weights", "holdout_2025", "cv_mean_2020_2024", "oof_cache_rows_without_v21")
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return doc


def file_row(models_dir: Path, name: str, ver: str, note: str) -> dict:
    p = R.model_path(name, ver, models_dir)
    e = R.entry_for(name, ver, models_dir)
    return {
        "name": name,
        "version": ver,
        "sha256": R.file_sha256(p),
        "bytes": p.stat().st_size,
        "features_hash": e.get("features_hash", ""),
        "note": note,
    }


def frozen_md(
    rows: list[dict], model: V2.V2Model, fit: dict, sub_info: dict, frozen_at: str, vs_v2: dict
) -> str:
    cfg = model.config
    ti = model.train_info
    w = ", ".join(f"{k} {v:.6f}" for k, v in model.weights.items())
    table = "\n".join(
        f"| {r['name']} | {r['version']} | `{r['sha256']}` | {r['bytes']:,} | {r['features_hash']} | {r['note']} |"
        for r in rows
    )
    mc = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))
    th = site_thresholds(FINAL_THRESHOLD_YEAR)
    return f"""# 모델 동결 v2.1 (FROZEN_v2.1) — 데이터 유래 상수 누수 수정판(운영·제출 모델)

- 동결 커밋: `{PLACEHOLDER}` (이 커밋 이후 v2.1 모델·가중치·피처·운영점을 변경하지 않는다)
- 동결 시각(KST): {frozen_at}
- 수정 사유: 2026-10-23 참가자 지시로 데이터로 계산한 상수를 전수 점검한 결과, 수위 편차의 관측소 평균(2010~2026-10-20 전 기간),
  지점별 관심 도달 수온 임계(2026 세포수 포함 전 기간 LOESS), ASOS 관측소 선정(2026 수온 포함)이 기준일 이후 자료를 쓰고 있었고,
  보현산댐(2012607) 2025년 이후 수위가 다른 계열이었다. "기준일 이후 관측값 사용 금지" 규칙 위반이므로 사전등록
  (reports/experiments/FIX-v2.1/PREREG.md) 규칙대로 고쳤다. v2.1 은 결과와 무관하게 채택한다.
- 수정 규칙: R1 수위 편차 = 관측소별 직전 365일 평균 대비(as-of, 유효 ≥180일) · R2 wamis_ok:false 관측소 2025~ 결측 ·
  R3 수온 임계 = 학습기간 측정만(CV 폴드 V → ≤V−1, 2025 홀드아웃 → ≤2024, 최종 → ≤2025) ·
  R4 선택 결정 ≤2024 재계산(ASOS 물금·매리 257 → 288, 나머지 동일) · R5 피처 목록·하이퍼파라미터·구성원·운영점 규칙·CQR 절차 v2 와 동일 ·
  R6 데이터 적합 부분 전부 재적합(회귀 구성원·NNLS·smearing·분류기 b·분위·운영점·CQR)
- 최종 모델 수온 임계(측정 ≤2025, config/derived_constants.json): {json.dumps(th, ensure_ascii=False)}
- 운영점: {json.dumps(mc.get("operating_point"), ensure_ascii=False)}; 임계 {json.dumps(mc.get("thresholds"))};
  CQR {json.dumps(mc.get("cqr"))} (config/model.yaml, 수정 피처 OOF 로 같은 절차 재산정)
- 구성: 회귀 = c1 C1 smearing·c3 C3 hurdle·c2 C2 tweedie(v1 하이퍼파라미터) + 속별 구성원 cg(G2), 결합 = log10 공간 NNLS(합=1)
- 피처 {len(model.cols)}개 = v1 선택 30(perc75, 결측 전략 S1) + 상류 {len(cfg.extra_features)}({", ".join(cfg.extra_features)})
- 결합 가중치(2020~2024 연도 확장 CV OOF, 폴드별 임계, 시드 {ti.get("seed")}): {w}
- 학습 범위: {ti.get("rule")} — {ti.get("n_rows"):,}행, 기준일 {ti.get("base_date_min")} ~ {ti.get("base_date_max")},
  목표일 ≤ {ti.get("target_date_max")}. 지점별 {json.dumps(ti.get("rows_by_site"), ensure_ascii=False)}
- 시드: {ti.get("seed")} (config/seed.yaml)
- 2025 홀드아웃(학습 ≤2024 → 2025, 같은 가중치): {json.dumps({k: round(v, 4) for k, v in fit["holdout_2025"].items()})}
- CV 평균(2020~2024): {json.dumps({k: round(v, 4) for k, v in fit["cv_mean_2020_2024"].items()})}
- submission.csv(v2.1): {sub_info.get("rows")}행, sha256 `{sub_info.get("sha256_full")}`.
  v2 제출본 보존 dist/v2/submission_v2.csv(FROZEN_v2.md 그대로), v2 대비 |Δlog10| 중앙 {vs_v2["median_abs_log10_diff"]:.4f}·최대 {vs_v2["max_abs_log10_diff"]:.4f}
- v1(FROZEN.md)·v2(FROZEN_v2.md) 동결 문서와 모델 파일은 이력으로 보존한다.

| name | version | sha256(model.pkl) | bytes | features_hash | 비고 |
|---|---|---|---|---|---|
{table}

검증: `python scripts/verify_frozen.py` 가 FROZEN.md·FROZEN_v2.md·이 문서의 해시를 현재 파일과 대조하고,
registry current 가 이 문서의 버전과 같은지 확인한다.
"""


def run_freeze(seed: int, force: bool) -> int:
    t0 = time.time()
    if not FIT_JSON.exists():
        raise SystemExit(f"중단: {FIT_JSON} 없음 — 먼저 --oof")
    fit = json.loads(FIT_JSON.read_text(encoding="utf-8"))
    if (MODELS_DIR / DOC).exists() and not force:
        raise SystemExit(f"중단: models/{DOC} 가 이미 있다(--force 로 다시 동결).")
    if R.current_kind("regression") != "ensemble" and not force:
        raise SystemExit("중단: current 회귀가 v1-fix(ensemble, alert --skip-tune 산출)가 아니다.")
    obj, entry = R.load_current("regression")
    aux = {
        "cols": list(obj["cols"]),
        "cats": list(obj["cats"]),
        "categories": {k: list(v) for k, v in obj["categories"].items()},
        "source": f"regression/{entry['version']}",
    }
    cfg = V2.config_v2()
    frame = V2.load_training_frame(config=cfg)
    weights = {k: float(v) for k, v in fit["weights"].items()}
    model = V2.fit_final(frame, cfg, weights=weights, seed=seed)
    model.aux = aux
    cur = R.current_versions()
    version = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    R.register(
        "regression",
        model.to_registry(),
        features=model.cols,
        metrics_holdout=fit["holdout_2025"],
        meta={
            "kind": V2.KIND,
            "model_name": "v2.1",
            "train_through": 2025,
            "purpose": "submission cells (v2.1 = v2 구성 + 데이터 유래 상수 누수 수정)",
            "basis": "reports/experiments/FIX-v2.1/PREREG.md",
            "config": model.config.to_dict(),
            "weights": weights,
            "weights_basis": "2020~2024 연도 확장 CV OOF NNLS(log10, 합=1), 폴드별 수온 임계",
            "train": model.train_info,
            "seed": seed,
            "classifier_version": cur.get("classifier"),
            "quantile_version": cur.get("quantile"),
            "aux_source": aux.get("source"),
            "v1fix_regression_version": entry["version"],
        },
        version=version,
    )
    from algaecast.models import data as D

    test_feat = D.load_test_features("S1").reset_index(drop=True)
    obj2, _ = R.load_current("regression")
    reloaded = V2.V2Model.from_registry(obj2).predict(test_feat)
    roundtrip = float(np.max(np.abs(reloaded - model.predict(test_feat))))
    if roundtrip != 0.0:
        raise SystemExit(f"중단: 레지스트리 왕복 예측 차 {roundtrip}")
    if SUBMISSION_PATH.exists() and not V2_COPY.exists():
        V2_COPY.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SUBMISSION_PATH, V2_COPY)
        log.info("v2 제출본 보존: %s", V2_COPY)
    sub = make_submission()
    write_submission(sub, SUBMISSION_PATH)
    val = validate_submission(SUBMISSION_PATH)
    val["sha256_full"] = R.file_sha256(SUBMISSION_PATH)
    if not (
        val["rows"] == 124
        and val["columns"]
        and val["order_same_as_sample"]
        and val["nan"] == 0
        and val["negative"] == 0
        and val["bom"]
    ):
        raise SystemExit(f"중단: 제출 파일 검증 실패 {val}")
    v2 = pd.read_csv(V2_COPY, encoding="utf-8-sig", dtype={"station_id": str})
    d = np.log10(sub["pred_cells"].to_numpy(float) + 1) - np.log10(v2["pred_cells"].to_numpy(float) + 1)
    vs_v2 = {
        "median_abs_log10_diff": float(np.median(np.abs(d))),
        "max_abs_log10_diff": float(np.max(np.abs(d))),
    }
    frozen_at = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        file_row(MODELS_DIR, "regression", version, "ensemble_v2(c1·c3·c2·cg, 피처 35) — v2.1"),
        file_row(MODELS_DIR, "classifier", cur["classifier"], "v2.1 재적합(분류기 b, 수정 피처)"),
        file_row(MODELS_DIR, "quantile", cur["quantile"], "v2.1 재적합(q10·q50·q90, 수정 피처)"),
        file_row(
            MODELS_DIR,
            "regression",
            entry["version"],
            "v1-fix(c1·c3·c2, 피처 30) — 민감도 보고용, current 아님",
        ),
    ]
    (MODELS_DIR / DOC).write_text(
        frozen_md(rows, model, fit, val, frozen_at, vs_v2), encoding="utf-8", newline="\n"
    )
    summary = {
        "frozen_at_kst": frozen_at,
        "version": version,
        "weights": weights,
        "holdout_2025": fit["holdout_2025"],
        "files": rows,
        "submission": val,
        "vs_v2_submission": vs_v2,
        "registry_roundtrip_max_absdiff": roundtrip,
        "minutes": round((time.time() - t0) / 60, 2),
    }
    (OUT / "freeze_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=float) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=float))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--oof", action="store_true")
    g.add_argument("--freeze", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.oof:
        run_oof(SEED)
        return 0
    return run_freeze(SEED, args.force)


if __name__ == "__main__":
    sys.exit(main())
