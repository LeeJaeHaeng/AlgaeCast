# ruff: noqa: E501  (한국어 표)
"""2026 사후 계산 — 비상안 T24(v2.1 구성, 최종 적합 ≤2024)를 v2.1 과 나란히. T24 동결 커밋 뒤 한 번만, 저장소 사본에서 실행한다.

사전등록: reports/experiments/PREREG_contingency.md 7절(평가 순서 3 — 동결 커밋 뒤 2026 사후 계산 1회).
- T24 예측: 사본 레지스트리 current(회귀·분류기 b·분위)로 2026 base_date 전체. current 버전과 model.pkl·meta.json sha256,
  submission_T24.csv sha256 을 동결 문서(reports/experiments/contingency_T24/FROZEN_T24.md)와 대조한 뒤에만 예측한다.
  수온 임계는 T24 학습기간 측정(≤2024)으로 다시 계산한다(scripts/freeze_t24.py 와 같음). CQR·운영점은 config/model.yaml
  (v2.1 과 같은 값). test 124조합의 T24 예측(반올림)이 submission_T24.csv 와 같고 (지점, 기준일) 행이 v2.1 과 같아야
  그다음에 2026 타깃을 읽는다(점검이 실패하면 타깃을 읽지 않고 중단).
- v2.1: data/processed/posthoc_2026_v21.parquet(2026-10-23, eval.posthoc_v21)을 읽기만 한다(다시 계산하지 않음).
- 타깃: eval.live.load_test_targets(명시 플래그)뿐. 전체 지표·전환 분해는 test 124 조합, 리드타임은 2026 경계 사건 전부.
- 저장소 본체(.git 있음)에서는 실행하지 않는다(본체 레지스트리 current 는 v2.1).
- 출력(사본): reports/experiments/contingency_T24/tbl_holdout_2026_posthoc_T24.md · posthoc_2026_T24_summary.json,
  data/processed/posthoc_2026_T24.parquet
사용: python -m algaecast.eval.posthoc_t24 --dry-check            (사전 점검, 2026 타깃 미사용)
      python -m algaecast.eval.posthoc_t24 --commit <T24 동결 커밋> [--force]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from algaecast.config import DATA_DIR, ROOT, SUBMISSION_PATH
from algaecast.models import registry as R

OUT_DIR = ROOT / "reports" / "experiments" / "contingency_T24"
DOC = OUT_DIR / "FROZEN_T24.md"
OUT_MD = OUT_DIR / "tbl_holdout_2026_posthoc_T24.md"
OUT_JSON = OUT_DIR / "posthoc_2026_T24_summary.json"
OUT_PQ = DATA_DIR / "processed" / "posthoc_2026_T24.parquet"
V21_PQ = DATA_DIR / "processed" / "posthoc_2026_v21.parquet"
SUB_T24 = SUBMISSION_PATH.parent / "submission_T24.csv"
THRESHOLD_YEAR = 2024  # T24 학습기간 수온 임계(측정 ≤2024)
NAMES = ("regression", "classifier", "quantile")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
FILE_ROW = re.compile(
    r"^\| (regression|classifier|quantile) \| (\d{8}_\d{6}) \| `([0-9a-f]{64})` \| ([\d,]+) \| `([0-9a-f]{64})` \|",
    re.M,
)
SUB_ROW = re.compile(r"submission_T24\.csv\(124행\) sha256 `([0-9a-f]{64})`")


def guard_workspace(root: Path = ROOT) -> None:
    """저장소 본체(.git 이 있는 폴더)에서는 중단한다."""
    if (Path(root) / ".git").exists():
        raise SystemExit(f"중단: {root} 는 저장소 본체(.git 있음)다. T24 사후 계산은 사본에서만 한다.")


def parse_frozen(text: str) -> dict:
    """FROZEN_T24.md 에서 동결 파일 표(이름·버전·sha256·크기)와 submission_T24 sha256 을 읽는다."""
    files = [
        {
            "name": m.group(1),
            "version": m.group(2),
            "sha256_model_pkl": m.group(3),
            "bytes_model_pkl": int(m.group(4).replace(",", "")),
            "sha256_meta_json": m.group(5),
        }
        for m in FILE_ROW.finditer(text)
    ]
    sub = SUB_ROW.search(text)
    return {"files": files, "submission_sha256": sub.group(1) if sub else None}


def verify_frozen(text: str, reg_dir: Path | None = None, sub_path: Path = SUB_T24) -> dict:
    """레지스트리 current 3개(회귀·분류기·분위)의 버전·파일 해시와 submission_T24 해시가 동결 문서와 같은지 확인한다."""
    doc = parse_frozen(text)
    by_name = {f["name"]: f for f in doc["files"]}
    if sorted(by_name) != sorted(NAMES) or len(doc["files"]) != len(NAMES):
        raise SystemExit(f"중단: 동결 문서의 파일 표가 회귀·분류기·분위 각 1행이 아니다: {doc['files']}")
    base = R.REG_DIR if reg_dir is None else Path(reg_dir)
    current = R.current_versions(reg_dir)
    for name in NAMES:
        f = by_name[name]
        cur = current.get(name)
        if cur != f["version"]:
            raise SystemExit(f"중단: current {name} {cur} ≠ 동결 문서 {f['version']}")
        d = base / name / f["version"]
        if R.file_sha256(d / "model.pkl") != f["sha256_model_pkl"]:
            raise SystemExit(f"중단: {name}/{f['version']}/model.pkl sha256 이 동결 문서와 다르다.")
        if R.file_sha256(d / "meta.json") != f["sha256_meta_json"]:
            raise SystemExit(f"중단: {name}/{f['version']}/meta.json sha256 이 동결 문서와 다르다.")
    if not doc["submission_sha256"] or R.file_sha256(sub_path) != doc["submission_sha256"]:
        raise SystemExit("중단: submission_T24.csv sha256 이 동결 문서와 다르다.")
    return doc


def predict_t24_2026() -> pd.DataFrame:
    """2026 base_date 전체를 current(T24)로 예측(타깃 없음, eval.posthoc.predict_2026 과 같은 형식). 수온 임계는 ≤2024."""
    from algaecast.db.upload import predict_registry
    from algaecast.features.constants import apply_site_thresholds
    from algaecast.models import data as D

    feat = pd.read_parquet(D._features_path("S1"))
    feat["base_date"] = pd.to_datetime(feat["base_date"])
    feat["target_date"] = pd.to_datetime(feat["target_date"])
    f26 = feat[feat["base_date"].dt.year == 2026].reset_index(drop=True)
    pr = predict_registry(apply_site_thresholds(f26, THRESHOLD_YEAR))
    out = pd.concat(
        [f26[["station_id", "site_code", "base_date", "target_date", "split", "cell_log_t0"]], pr], axis=1
    )
    out["station_id"] = out["station_id"].astype(str)
    return out


def attach_targets(pred: pd.DataFrame) -> pd.DataFrame:
    """test 124조합에만 2026 타깃을 붙인다 — eval.live.load_test_targets(명시 플래그)가 유일한 통로."""
    from algaecast.eval.live import load_test_targets

    tt = load_test_targets(i_know_this_is_for_post_hoc_only=True)
    tt["station_id"] = tt["station_id"].astype(str)
    tt["base_date"] = pd.to_datetime(tt["base_date"])
    out = pred.merge(
        tt[["station_id", "base_date", "target_cells"]], on=["station_id", "base_date"], how="left"
    )
    if len(out) != len(pred):
        raise SystemExit("중단: 타깃 결합 뒤 행 수가 바뀌었다.")
    return out


def v21_keys() -> pd.DataFrame:
    """v2.1 사후 예측 파일의 (지점, 기준일) 열만 읽는다(타깃 열은 읽지 않음)."""
    k = pd.read_parquet(V21_PQ, columns=["station_id", "base_date"])
    k["station_id"] = k["station_id"].astype(str)
    k["base_date"] = pd.to_datetime(k["base_date"])
    return k


def check_submission(pred: pd.DataFrame, sub_path: Path = SUB_T24) -> int:
    """test 124조합의 예측(반올림)이 submission_T24.csv 와 같은지 — 다른 행 수(0 이어야 한다)."""
    sub = pd.read_csv(sub_path, encoding="utf-8-sig", dtype={"station_id": str})
    sub["base_date"] = pd.to_datetime(sub["base_date"])
    t = pred[pred["split"] == "test"][["station_id", "base_date", "pred_cell_count"]]
    m = sub.merge(t, on=["station_id", "base_date"], how="left")
    rounded = np.clip(np.round(m["pred_cell_count"].to_numpy(dtype=float)), 0, None)
    return int(m["pred_cell_count"].isna().sum() + (rounded != m["pred_cells"].to_numpy(dtype=float)).sum())


def notice(commit: str) -> str:
    return (
        "> T24 의 2026 은 블라인드가 아니다: 팀은 v2.1 의 2026 결과를 이미 봤다. T24 는 사전등록(PREREG_contingency 7절, 커밋 960d76f)대로 "
        f"학습·동결했고(동결 커밋 `{commit[:12]}`), 2026 사후 계산은 그 뒤 한 번만 했다. 결과와 무관하게 모델·전환 규칙을 바꾸지 않는다.\n\n"
    )


def main(argv: list[str] | None = None) -> int:
    from algaecast.eval import posthoc as PH
    from algaecast.eval import posthoc_v21 as PV
    from algaecast.eval.metrics import compute_all
    from algaecast.eval.transitions import T1K, T10K, official_events

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--commit", help="T24 동결 커밋(FROZEN_T24.md 를 담은 커밋, push 된 것) — 본 계산에 필수")
    ap.add_argument(
        "--dry-check",
        action="store_true",
        help="사전 점검만: 동결 해시 대조·2026 기준일 예측·submission_T24 대조·행 대조(2026 타깃을 읽지 않음)",
    )
    ap.add_argument("--force", action="store_true", help="이미 계산했어도 다시 쓴다(재현 확인용)")
    a = ap.parse_args(argv)
    guard_workspace()
    if not a.dry_check and not (a.commit and COMMIT_RE.match(a.commit)):
        raise SystemExit(f"중단: --commit 에 동결 커밋 해시를 준다(받은 값: {a.commit}).")
    if OUT_MD.exists() and not a.force and not a.dry_check:
        raise SystemExit(
            f"중단: {OUT_MD} 가 이미 있다 — T24 사후 계산은 한 번만 한다(--force 는 재현 확인용)."
        )
    frozen = verify_frozen(DOC.read_text(encoding="utf-8"))
    t24 = predict_t24_2026()
    n_bad = check_submission(t24)
    if n_bad:
        raise SystemExit(f"중단: test 조합 T24 예측이 submission_T24.csv 와 {n_bad}행 다르다.")
    key = ["station_id", "base_date"]
    if not v21_keys()[key].astype(str).equals(t24[key].astype(str)):
        raise SystemExit("중단: v2.1 사후 예측과 T24 의 (지점, 기준일) 행이 다르다.")
    if a.dry_check:
        print(
            json.dumps(
                {"dry_check": "통과(2026 타깃 미사용)", "rows_2026": len(t24), "files": frozen["files"]},
                ensure_ascii=False,
                indent=1,
            )
        )
        return 0
    t24 = attach_targets(t24)
    v21 = pd.read_parquet(V21_PQ)
    v21["station_id"] = v21["station_id"].astype(str)
    v21["base_date"] = pd.to_datetime(v21["base_date"])
    t24.to_parquet(OUT_PQ, index=False)
    has = t24[t24["target_cells"].notna()]
    b0 = np.clip(10 ** has["cell_log_t0"].fillna(0).to_numpy() - 1, 0, None)
    m_b0 = compute_all(has["target_cells"].to_numpy(dtype=float), b0)
    tab = pd.DataFrame(
        [
            PV.overall(t24, "T24 비상안(v2.1 구성, ≤2024 학습)"),
            PV.overall(v21, "v2.1 운영·제출(≤2025 학습)"),
            {"모델": "B0 지속성", **{k: m_b0[k] for k in PV.KEYS}},
        ]
    )
    models = {"T24": t24, "v2.1": v21}
    lt = pd.concat(
        [PH.leadtime_2026(p, T10K, point=True)[0].assign(모델=lab) for lab, p in models.items()],
        ignore_index=True,
    )
    lt = lt[["모델", *[c for c in lt.columns if c != "모델"]]]
    summary: dict = {lab: PV.watch_summary(p) for lab, p in models.items()}
    summary["n_events"] = len(official_events(T10K, start_year=2026))
    summary["overall"] = {
        r["모델"]: {k: (None if pd.isna(r.get(k)) else float(r.get(k))) for k in PV.KEYS if k in r}
        for r in tab.to_dict("records")
    }
    summary["overall_intervals"] = {
        r["모델"]: {
            k: float(r[k])
            for k in ("PICP80(CQR)", "MPIW80_log", "Brier(p_alert vs ≥10k)")
            if k in r and pd.notna(r[k])
        }
        for r in tab.to_dict("records")
    }
    summary["frozen_commit"] = a.commit
    summary["frozen_files"] = frozen["files"]
    summary["submission_T24_sha256"] = frozen["submission_sha256"]
    ev = PV.event_detail(models)
    tr10 = pd.concat(
        [PH.transitions_2026(p, T10K, point=True).assign(모델=lab) for lab, p in models.items()],
        ignore_index=True,
    )
    tr1 = pd.concat(
        [PH.transitions_2026(p, T1K, point=True).assign(모델=lab) for lab, p in models.items()],
        ignore_index=True,
    )
    nt = notice(a.commit)
    md = (
        f"# 2026 사후 계산 — 비상안 T24(≤2024 학습) · v2.1 (test 조합 {len(has)}건 타깃 + 2026 base_date {len(t24)}건 예측)\n\n"
        f"{nt}"
        "- T24 = v2.1 과 피처·구성원·하이퍼파라미터·결합 가중치·분류기 임계·운영점·CQR 이 같고 최종 적합만 기준일 연도 ≤ 2024 인 학습 행(2025 홀드아웃 Final 폴드와 같음, 목표일 2025-01-06 5행 포함)으로 한 모델"
        "(reports/experiments/contingency_T24/FROZEN_T24.md). 수온 임계는 측정 ≤2024.\n"
        "- v2.1 값은 data/processed/posthoc_2026_v21.parquet(2026-10-23 계산)을 그대로 읽었다.\n"
        "- 2026 타깃은 eval/live.load_test_targets(명시 플래그)로만 읽었다.\n\n"
        "## 1. 전체 지표(test 124 조합)\n\n" + nt + PH._md(tab) + "\n\n"
        f"## 2. 리드타임 — 2026 경계(10k) 사건 {summary['n_events']}건\n\n" + nt + PH._md(lt) + "\n\n"
        "### 사건별 첫 경보 리드(E, 일; 빈칸 = 사건 전 28일 안 경보 없음)\n\n" + nt + PH._md(ev) + "\n\n"
        "## 3. 전환 분해 — 경계 10k(test 124 조합)\n\n" + nt + PH._md(tr10) + "\n\n"
        "## 4. 전환 분해 — 관심 1k(test 124 조합)\n\n" + nt + PH._md(tr1) + "\n"
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(md, encoding="utf-8", newline="\n")
    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=float) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(tab.round(4).to_string(index=False))
    print(
        json.dumps(
            {k: summary[k] for k in ("T24", "v2.1", "n_events", "frozen_commit")},
            ensure_ascii=False,
            indent=1,
            default=float,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
