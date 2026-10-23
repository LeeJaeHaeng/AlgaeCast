# ruff: noqa: E501  (한국어 표)
"""2026 사후 계산 — v2.1(누수 수정판, 운영·제출 모델)을 v1·v2 와 나란히. v2.1 동결 커밋 뒤 한 번만 실행한다.

- v2.1 예측: 레지스트리 current(회귀 v2.1·분류기·분위, models/FROZEN_v2.1.md)로 2026 base_date 전체(eval.posthoc.predict_2026).
- v1 예측: data/processed/posthoc_2026.parquet(v1 봉인본, 2026-10-21), v2 예측: posthoc_2026_v2.parquet(2026-10-22). 다시 계산하지 않는다.
- v1-fix: v1 구성(c1·c3·c2, 피처 30)을 수정 피처로 다시 적합한 회귀(FROZEN_v2.1.md 표의 두 번째 regression 행).
  감시·경보는 v2.1 과 같은 분류기·분위이므로 회귀(점예측) 지표만 따로 보고한다.
- 타깃: eval.live.load_test_targets(명시 플래그)뿐. 전체 지표·전환 분해는 test 124 조합, 리드타임은 2026 경계 사건 전부.
- 모든 표 위 고지: 수정본(v2.1·v1-fix)은 블라인드가 아니다(팀은 v1·v2 의 2026 결과를 이미 봄). 결과와 상관없이 모델·판정을 바꾸지 않는다.
- 출력: reports/eval/tbl_holdout_2026_posthoc_v21.md, data/processed/posthoc_2026_v21.parquet, posthoc_2026_v21_summary.json
사용: python -m algaecast.eval.posthoc_v21 [--force]
"""

from __future__ import annotations

import argparse
import json
import re

import numpy as np
import pandas as pd

from algaecast.config import DATA_DIR, MODELS_DIR, ROOT
from algaecast.eval import posthoc as PH
from algaecast.eval.metrics import compute_all
from algaecast.eval.transitions import T1K, T10K, official_events
from algaecast.models import data as D
from algaecast.models import registry as R

EVAL = ROOT / "reports" / "eval"
OUT_MD = EVAL / "tbl_holdout_2026_posthoc_v21.md"
OUT_JSON = EVAL / "posthoc_2026_v21_summary.json"
OUT_PQ = DATA_DIR / "processed" / "posthoc_2026_v21.parquet"
V1_PQ = DATA_DIR / "processed" / "posthoc_2026.parquet"
V2_PQ = DATA_DIR / "processed" / "posthoc_2026_v2.parquet"
KEYS = ["n", "rmse_log", "mae_log", "r2_log", "r2_raw", "r2_pearson_raw", "nse_raw", "f1_10k", "f1_1k"]
DOC = MODELS_DIR / "FROZEN_v2.1.md"
ROW = re.compile(r"\| regression \| (\d+_\d+) \| `[0-9a-f]{64}` \|")


def frozen_commit() -> str:
    m = re.search(r"동결 커밋: `([0-9a-f]{7,40})`", DOC.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit(
            "중단: models/FROZEN_v2.1.md 의 동결 커밋이 아직 기입되지 않았다(동결 커밋 뒤에 실행)."
        )
    return m.group(1)


def notice(commit: str) -> str:
    return (
        "> 수정본(v2.1·v1-fix)의 2026 은 블라인드가 아니다: 모델 선택·수정 규칙에 2026 을 쓰지 않았지만 팀은 v1·v2 의 2026 결과를 이미 봤다. "
        f"v2.1 동결 커밋 `{commit[:12]}` 뒤 한 번만 계산했다.\n\n"
    )


def v1fix_point(feat: pd.DataFrame) -> np.ndarray:
    """v1-fix 회귀(v1 구성 앙상블, 수정 피처) 점예측 — db.upload.predict_registry 의 ensemble 분기와 같은 계산."""
    versions = ROW.findall(DOC.read_text(encoding="utf-8"))
    if len(versions) < 2:
        raise SystemExit("중단: FROZEN_v2.1.md 에 v1-fix 회귀 행이 없다.")
    import pickle

    with R.model_path("regression", versions[1]).open("rb") as f:
        reg = pickle.load(f)
    X = feat[reg["cols"]].copy()
    for c in reg["cats"]:
        X[c] = pd.Categorical(X[c].astype(str), categories=reg["categories"][c])
    parts = {}
    for name, m in reg["members"].items():
        if m["kind"] == "log_w":
            parts[name] = np.clip(10 ** np.clip(m["model"].predict(X), 0, 7) - 1, 0, None) * m["smear"]
        elif m["kind"] == "hurdle":
            p = m["clf"].predict_proba(X)[:, 1]
            hi = np.clip(10 ** np.clip(m["hi"].predict(X), 0, 7) - 1, 0, None)
            lo = np.clip(10 ** np.clip(m["lo"].predict(X), 0, 7) - 1, 0, None)
            parts[name] = p * hi + (1 - p) * lo
        else:
            parts[name] = np.clip(m["model"].predict(X), 0, None)
    z = sum(reg["weights"][n] * np.log10(parts[n] + 1) for n in parts)
    return np.clip(10**z - 1, 0, None)


def overall(pred: pd.DataFrame, label: str, point_col: str = "pred_cell_count", alerts: bool = True) -> dict:
    has = pred[pred["target_cells"].notna()]
    obs = has["target_cells"].to_numpy(dtype=float)
    kw = {}
    if alerts:
        kw = {
            "q10": has["q10_cqr"].to_numpy(),
            "q90": has["q90_cqr"].to_numpy(),
            "p10k": has["p_alert"].to_numpy(),
        }
    m = compute_all(obs, has[point_col].to_numpy(dtype=float), **kw)
    row = {"모델": label, **{k: m[k] for k in KEYS}}
    if alerts:
        row.update(
            {
                "PICP80(CQR)": m["picp80"],
                "MPIW80_log": m["mpiw80_log"],
                "Brier(p_alert vs ≥10k)": m["brier_10k"],
            }
        )
    return row


def watch_summary(p: pd.DataFrame) -> dict:
    lt, det = PH.leadtime_2026(p, T10K, point=True)
    out = {}
    for rule, short in (
        ("감시(q90_cqr≥임계)", "watch"),
        ("경보(p_alert≥운영점)", "alert"),
        ("점예측≥임계", "point"),
    ):
        d = det[det["방식"] == rule] if len(det) else pd.DataFrame()
        leads = d["리드(E)"].astype(float).tolist() if len(d) else []
        out[short] = {"detected": len(leads), "median_lead_e": float(np.median(leads)) if leads else None}
    return out


def event_detail(models: dict[str, pd.DataFrame]) -> pd.DataFrame:
    ev = official_events(T10K, start_year=2026)
    out = pd.DataFrame(
        {
            "지점": [e.station_id for e in ev.itertuples()],
            "E": [pd.Timestamp(e._3).date() for e in ev.itertuples()],
        }
    )
    for lab, p in models.items():
        _, det = PH.leadtime_2026(p, T10K, point=True)
        for rule, short in (
            ("감시(q90_cqr≥임계)", "감시"),
            ("경보(p_alert≥운영점)", "경보"),
            ("점예측≥임계", "점예측"),
        ):
            d = det[det["방식"] == rule].set_index(["지점", "E"]) if len(det) else pd.DataFrame()
            out[f"{lab} {short}"] = [
                (int(d.loc[(s, e), "리드(E)"]) if (s, e) in d.index else None)
                for s, e in zip(out["지점"], out["E"], strict=True)
            ]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="이미 계산했어도 다시 쓴다(재현 확인용)")
    a = ap.parse_args(argv)
    if OUT_MD.exists() and not a.force:
        raise SystemExit(
            f"중단: {OUT_MD} 가 이미 있다 — v2.1 사후 계산은 한 번만 한다(--force 는 재현 확인용)."
        )
    if R.current_kind("regression") != "ensemble_v2":
        raise SystemExit("중단: current 회귀가 v2.1(ensemble_v2)이 아니다 — 동결 뒤 실행.")
    commit = frozen_commit()
    v21 = PH.predict_2026()
    feat = pd.read_parquet(D._features_path("S1"))
    feat["base_date"] = pd.to_datetime(feat["base_date"])
    f26 = feat[feat["base_date"].dt.year == 2026].reset_index(drop=True)
    if not f26["station_id"].astype(str).equals(v21["station_id"]) or not f26["base_date"].equals(
        v21["base_date"]
    ):
        raise SystemExit("중단: v1-fix 입력 행과 v2.1 예측 행이 다르다.")
    v21["pred_v1fix"] = v1fix_point(f26)
    v21.to_parquet(OUT_PQ, index=False)
    v1 = pd.read_parquet(V1_PQ)
    v2 = pd.read_parquet(V2_PQ)
    for d in (v1, v2):
        d["station_id"] = d["station_id"].astype(str)
        d["base_date"] = pd.to_datetime(d["base_date"])
    key = ["station_id", "base_date"]
    if not (
        v1[key].astype(str).equals(v21[key].astype(str)) and v2[key].astype(str).equals(v21[key].astype(str))
    ):
        raise SystemExit("중단: v1·v2 사후 예측과 v2.1 의 (지점, 기준일) 행이 다르다.")
    has = v21[v21["target_cells"].notna()]
    b0 = np.clip(10 ** has["cell_log_t0"].fillna(0).to_numpy() - 1, 0, None)
    m_b0 = compute_all(has["target_cells"].to_numpy(dtype=float), b0)
    tab = pd.DataFrame(
        [
            overall(v21, "v2.1 운영·제출(누수 수정, ≤2025 학습)"),
            overall(v2, "v2(2026-10-22 동결, 누수 상수 포함)"),
            overall(v1, "v1 봉인본(2026-10-21, 누수 상수 포함)"),
            overall(
                v21,
                "v1-fix 회귀(v1 구성 + 수정 피처) — 감시·경보는 v2.1 과 같음",
                point_col="pred_v1fix",
                alerts=False,
            ),
            {"모델": "B0 지속성", **{k: m_b0[k] for k in KEYS}},
        ]
    )
    models = {"v2.1": v21, "v2": v2, "v1": v1}
    lt = pd.concat(
        [PH.leadtime_2026(p, T10K, point=True)[0].assign(모델=lab) for lab, p in models.items()],
        ignore_index=True,
    )
    lt = lt[["모델", *[c for c in lt.columns if c != "모델"]]]
    v1fix_pt = v21.assign(pred_cell_count=v21["pred_v1fix"])
    summary = {lab: watch_summary(p) for lab, p in models.items()}
    summary["v1-fix"] = {
        "point": watch_summary(v1fix_pt)["point"],
        "watch_alert": "v2.1 과 같음(같은 분류기·분위)",
    }
    summary["n_events"] = len(official_events(T10K, start_year=2026))
    summary["overall"] = {
        r["모델"]: {k: (None if pd.isna(r.get(k)) else float(r.get(k))) for k in KEYS if k in r}
        for r in tab.to_dict("records")
    }
    summary["frozen_commit"] = commit
    ev = event_detail({**models, "v1-fix": v1fix_pt})
    tr10 = pd.concat(
        [PH.transitions_2026(p, T10K, point=True).assign(모델=lab) for lab, p in models.items()],
        ignore_index=True,
    )
    tr1 = pd.concat(
        [PH.transitions_2026(p, T1K, point=True).assign(모델=lab) for lab, p in models.items()],
        ignore_index=True,
    )
    nt = notice(commit)
    md = (
        f"# 2026 사후 계산 — v2.1(누수 수정판) · v2 · v1 (test 조합 {len(has)}건 타깃 + 2026 base_date {len(v21)}건 예측)\n\n"
        f"{nt}"
        "- v2.1 = 데이터 유래 상수 누수 수정판(models/FROZEN_v2.1.md, 사전등록 reports/experiments/FIX-v2.1/PREREG.md). 분류기·분위·CQR·운영점도 수정 피처로 다시 적합했다.\n"
        "- v1 봉인본(2026-10-21)·v2(2026-10-22)는 봉인·동결 당시 일부 상수(지점별 수온 임계 등)가 2026 자료를 포함한 전 기간으로 계산돼 있었음을 사후에 발견했다(점검표: PREREG 1절). 두 모델의 값은 이력으로만 남긴다.\n"
        "- 2026 타깃은 eval/live.load_test_targets(명시 플래그)로만 읽었다.\n\n"
        "## 1. 전체 지표(test 124 조합)\n\n" + nt + PH._md(tab) + "\n\n"
        f"## 2. 리드타임 — 2026 경계(10k) 사건 {summary['n_events']}건\n\n" + nt + PH._md(lt) + "\n\n"
        "### 사건별 첫 경보 리드(E, 일; 빈칸 = 사건 전 28일 안 경보 없음)\n\n" + nt + PH._md(ev) + "\n\n"
        "## 3. 전환 분해 — 경계 10k(test 124 조합)\n\n" + nt + PH._md(tr10) + "\n\n"
        "## 4. 전환 분해 — 관심 1k(test 124 조합)\n\n" + nt + PH._md(tr1) + "\n"
    )
    OUT_MD.write_text(md, encoding="utf-8", newline="\n")
    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=float) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(tab.round(4).to_string(index=False))
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "overall"}, ensure_ascii=False, indent=1, default=float
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
