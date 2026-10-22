"""운영 모델 v2(최종 모델 C) 학습·등록·동결 문서·제출 파일 생성.

구성: models.v2.config_v2() — v1 로그 앙상블(C1·C3·C2) + 상류 피처 5열 + 속별 구성원 cg, 결합 가중치는
2020~2024 CV OOF(시드 42) NNLS. 최종 학습 = 기준일·목표일 ≤ 2025-12-31 인 학습·검증 행 전체,
시드 = config/seed.yaml.
분류기·분위·CQR·운영점은 v1 동결본을 그대로 current 로 둔다. 2026 정답·격리 파일은 읽지 않는다.

모드(둘 중 하나)
--dry-run : data/processed/exp/v2_dryrun/ 아래에만 쓴다(models/·submission/ 은 건드리지 않음).
            models/(임시 registry.json = 현재 registry 사본 + v2 회귀 항목,
            regression/<버전>/model.pkl·meta.json,
            classifier·quantile v1 파일 사본, FROZEN_v2.md 초안), submission_v2.csv, summary.json
--freeze  : models/regression/<버전>/model.pkl·meta.json, models/registry.json current.regression 갱신,
            models/FROZEN_v2.md(동결 커밋은 '커밋 후 기입' 자리표시),
            dist/v1/submission_v1.csv(v1 제출본 보존 사본),
            submission/submission.csv(v2).
            이미 FROZEN_v2.md 가 있거나 current 회귀가 v1 이 아니면 중단(--force 로 무시).
git 명령(add·commit·tag)은 실행하지 않는다. 동결 커밋·Release 는 사람이 한다(reports/v2/BUILD.md).
사용: python scripts/freeze_v2.py --dry-run | --freeze [--force]
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

from algaecast.collect.base import KST
from algaecast.config import DATA_DIR, MODELS_DIR, ROOT, SUBMISSION_PATH
from algaecast.eval.metrics import compute_all
from algaecast.models import registry as R
from algaecast.models import v2 as V2
from algaecast.models.predict import make_submission, validate_submission, write_submission
from algaecast.models.train import SEED

log = logging.getLogger("freeze_v2")
DRY_DIR = DATA_DIR / "processed" / "exp" / "v2_dryrun"
V1_COPY = ROOT / "dist" / "v1" / "submission_v1.csv"
METRIC_KEYS = ("rmse_log", "r2_log", "r2_raw", "r2_pearson_raw", "nse_raw", "f1_10k")
PLACEHOLDER = "커밋 후 기입"


# ---------------------------------------------------------------- 학습
def train_v2(seed: int) -> tuple[V2.V2Model, dict[str, float], dict, pd.DataFrame]:
    """학습 프레임 → CV OOF → 가중치 → 2025 홀드아웃 지표 → 최종 모델."""
    cfg = V2.config_v2()
    frame = V2.load_training_frame(config=cfg)
    log.info("학습 프레임 %d행(기준일 %s~%s)", len(frame), frame["base_date"].min(), frame["base_date"].max())
    oof = V2.cv_members(frame, seed, cfg)
    weights = V2.fit_weights(frame, seed, cfg, oof=oof)
    ens = V2.oof_ensemble(frame, oof, weights)
    fin = V2.years_of(frame) == V2.FINAL_YEAR
    mm = compute_all(frame["target_cells"].to_numpy(dtype=float)[fin], ens[fin])
    metrics = {k: float(mm[k]) for k in METRIC_KEYS}
    log.info("가중치 %s, 2025 홀드아웃(학습 ≤2024) %s", weights, metrics)
    model = V2.fit_final(frame, cfg, weights=weights, seed=seed)
    return model, weights, metrics, frame


def aux_from_v1(models_dir: Path) -> dict:
    """분류기·분위 입력용 v1 열·범주(현재 current 회귀가 v1 ensemble 이면 그 값, v2 면 그 aux)."""
    obj, entry = R.load_current("regression", reg_dir=models_dir)
    if obj.get("kind") == V2.KIND:
        return dict(obj.get("aux", {}))
    return {
        "cols": list(obj["cols"]),
        "cats": list(obj["cats"]),
        "categories": {k: list(v) for k, v in obj["categories"].items()},
        "source": f"regression/{entry['version']}",
    }


# ---------------------------------------------------------------- 레지스트리·문서
def prepare_dry_registry(dst: Path) -> None:
    """임시 레지스트리: 현재 registry.json 사본 + classifier·quantile current 파일 사본.

    v1 회귀 pickle 은 복사하지 않는다(current 회귀는 새 v2 항목).
    """
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    shutil.copy2(R.registry_path(), dst / "registry.json")
    for name, ver in R.current_versions().items():
        if name == "regression":
            continue
        shutil.copytree(MODELS_DIR / name / ver, dst / name / ver)


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


def frozen_v2_md(
    rows: list[dict], model: V2.V2Model, metrics: dict, sub_info: dict, frozen_at: str, dry: bool
) -> str:
    cfg = model.config
    ti = model.train_info
    w = ", ".join(f"{k} {v:.6f}" for k, v in model.weights.items())
    table = "\n".join(
        f"| {r['name']} | {r['version']} | `{r['sha256']}` | {r['bytes']:,} | "
        f"{r['features_hash']} | {r['note']} |"
        for r in rows
    )
    head = "# 모델 동결 v2 (FROZEN_v2) — 운영 모델 C" + (" — dry-run 초안(동결 아님)" if dry else "")
    return f"""{head}

- 동결 커밋: `{PLACEHOLDER}` (이 커밋 이후 v2 모델·가중치·피처·운영점을 변경하지 않는다)
- 동결 시각(KST): {frozen_at}
- 근거: 사전등록 확인 실험 EXP-confirm 통과(reports/experiments/EXP-confirm/RESULT.md),
  설계·동등성 reports/v2/BUILD.md
- 구성: 회귀 = v1 로그 앙상블(c1 C1 smearing·c3 C3 hurdle·c2 C2 tweedie, v1 하이퍼파라미터) + 속별 구성원 cg
  (G2 = Microcystis + 나머지 3속, 부분별 log 회귀(C1 설정)·smearing), 결합 = log10 공간 NNLS(합=1)
- 피처 {len(model.cols)}개 = v1 선택 30(perc75, 결측 전략 S1)
  + 상류 {len(cfg.extra_features)}({", ".join(cfg.extra_features)};
  lag 0, 상류 1단계, 해평·회남 NaN). 모든 구성원이 같은 열을 쓴다.
- 결합 가중치(2020~2024 연도 확장 CV OOF, 시드 {ti.get("seed")}): {w}
- 학습 범위: {ti.get("rule")} — {ti.get("n_rows"):,}행,
  기준일 {ti.get("base_date_min")} ~ {ti.get("base_date_max")},
  목표일 ≤ {ti.get("target_date_max")}. 지점별 {json.dumps(ti.get("rows_by_site"), ensure_ascii=False)}
- 시드: {ti.get("seed")} (config/seed.yaml)
- 2025 홀드아웃(학습 ≤2024 → 2025, 같은 가중치): {json.dumps({k: round(v, 4) for k, v in metrics.items()})}
- 분류기·분위·CQR·운영점: v1 동결본 그대로
  (아래 classifier·quantile 버전, config/model.yaml cqr·operating_point).
  v1 동결 문서 models/FROZEN.md 와 v1 회귀 파일은 보존한다(v1 제출본 사본 dist/v1/submission_v1.csv).
- submission.csv(v2): {sub_info.get("rows")}행, sha256 `{sub_info.get("sha256_full")}`

| name | version | sha256(model.pkl) | bytes | features_hash | 비고 |
|---|---|---|---|---|---|
{table}

검증: `python scripts/verify_frozen.py` 가 models/FROZEN.md(v1)와 이 문서의 해시를 현재 파일과 대조하고,
registry current 가 이 문서의 버전과 같은지 확인한다.
"""


# ---------------------------------------------------------------- 실행
def run(dry: bool, force: bool) -> int:
    t0 = time.time()
    seed = SEED
    target_dir = DRY_DIR / "models" if dry else MODELS_DIR
    if not dry:
        if (MODELS_DIR / "FROZEN_v2.md").exists() and not force:
            raise SystemExit("중단: models/FROZEN_v2.md 가 이미 있다(--force 로 다시 동결).")
        if R.current_kind("regression") != "ensemble" and not force:
            raise SystemExit("중단: current 회귀가 v1(ensemble)이 아니다(--force 로 무시).")
        if SUBMISSION_PATH.exists() and V1_COPY.exists():
            if R.file_sha256(SUBMISSION_PATH) != R.file_sha256(V1_COPY) and not force:
                raise SystemExit(f"중단: {V1_COPY} 가 현재 submission.csv 와 다르다(v1 보존본 확인 필요).")
    aux = aux_from_v1(MODELS_DIR)
    model, weights, metrics, frame = train_v2(seed)
    model.aux = aux
    test_feat = None
    if dry:
        prepare_dry_registry(target_dir)
    cur = R.current_versions(target_dir)
    version = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    entry = R.register(
        "regression",
        model.to_registry(),
        features=model.cols,
        metrics_holdout=metrics,
        meta={
            "kind": V2.KIND,
            "train_through": 2025,
            "purpose": "submission cells (v2 운영 모델 C)",
            "basis": "EXP-confirm 사전등록 확인 실험 통과(reports/experiments/EXP-confirm/RESULT.md)",
            "config": model.config.to_dict(),
            "weights": weights,
            "weights_basis": "2020~2024 연도 확장 CV OOF NNLS(log10, 합=1)",
            "train": model.train_info,
            "seed": seed,
            "classifier_version": cur.get("classifier"),
            "quantile_version": cur.get("quantile"),
            "aux_source": aux.get("source"),
        },
        reg_dir=target_dir,
        version=version,
    )
    log.info("등록: regression/%s → %s", version, entry["path"])
    # 레지스트리에서 다시 읽은 모델로 제출 파일(운영 경로) + 메모리 모델과 대조
    from algaecast.models import data as D

    test_feat = D.load_test_features("S1").reset_index(drop=True)
    obj, _ = R.load_current("regression", reg_dir=target_dir)
    reloaded = V2.V2Model.from_registry(obj).predict(test_feat)
    in_mem = model.predict(test_feat)
    roundtrip = float(np.max(np.abs(reloaded - in_mem)))
    if roundtrip != 0.0:
        raise SystemExit(f"중단: 레지스트리 왕복 예측 차 {roundtrip}")
    sub = make_submission(reg_dir=target_dir)
    if dry:
        sub_path = DRY_DIR / "submission_v2.csv"
    else:
        if SUBMISSION_PATH.exists() and not V1_COPY.exists():
            V1_COPY.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SUBMISSION_PATH, V1_COPY)
            log.info("v1 제출본 보존: %s", V1_COPY)
        sub_path = SUBMISSION_PATH
    write_submission(sub, sub_path)
    val = validate_submission(sub_path)
    val["sha256_full"] = R.file_sha256(sub_path)
    ok_fmt = (
        val["rows"] == 124
        and val["columns"]
        and val["order_same_as_sample"]
        and val["nan"] == 0
        and val["negative"] == 0
        and val["bom"]
    )
    if not ok_fmt:
        raise SystemExit(f"중단: 제출 파일 검증 실패 {val}")
    # v1 제출본과의 차이(예측끼리, 2026 정답 미사용)
    v1_path = V1_COPY if V1_COPY.exists() else SUBMISSION_PATH
    v1 = pd.read_csv(v1_path, encoding="utf-8-sig", dtype={"station_id": str})
    d = np.log10(sub["pred_cells"].to_numpy(float) + 1) - np.log10(v1["pred_cells"].to_numpy(float) + 1)
    vs_v1 = {
        "median_abs_log10_diff": float(np.median(np.abs(d))),
        "max_abs_log10_diff": float(np.max(np.abs(d))),
    }
    frozen_at = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        file_row(target_dir, "regression", version, "ensemble_v2(c1·c3·c2·cg, 피처 35)"),
        file_row(target_dir, "classifier", cur["classifier"], "v1 동결본(분류기 b)"),
        file_row(target_dir, "quantile", cur["quantile"], "v1 동결본(q10·q50·q90)"),
    ]
    (target_dir / "FROZEN_v2.md").write_text(
        frozen_v2_md(rows, model, metrics, val, frozen_at, dry), encoding="utf-8", newline="\n"
    )
    summary = {
        "mode": "dry-run" if dry else "freeze",
        "frozen_at_kst": frozen_at,
        "registry_dir": R._rel(target_dir),
        "version": version,
        "weights": weights,
        "holdout_2025": metrics,
        "train": model.train_info,
        "files": rows,
        "submission": {k: v for k, v in val.items()},
        "submission_path": R._rel(sub_path),
        "vs_v1_submission": vs_v1,
        "registry_roundtrip_max_absdiff": roundtrip,
        "minutes": round((time.time() - t0) / 60, 2),
    }
    if dry:
        (DRY_DIR / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8"
        )
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=float))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="data/processed/exp/v2_dryrun/ 에만 쓴다")
    g.add_argument("--freeze", action="store_true", help="models/·submission/·dist/v1/ 에 쓴다(실제 동결)")
    ap.add_argument("--force", action="store_true", help="--freeze 의 안전 확인을 건너뛴다")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run(dry=bool(args.dry_run), force=bool(args.force))


if __name__ == "__main__":
    sys.exit(main())
