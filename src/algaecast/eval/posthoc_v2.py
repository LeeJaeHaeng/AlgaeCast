# ruff: noqa: E501  (한국어 표)
"""2026 사후 계산 — v2(운영·제출 모델 C) 를 v1(블라인드 검증 모델)과 나란히. v2 동결 커밋 뒤 한 번만 실행한다.

- v2 예측: 레지스트리 current(ensemble_v2, models/FROZEN_v2.md)로 2026 base_date 전체를 예측한다(eval.posthoc.predict_2026).
- v1 예측: data/processed/posthoc_2026.parquet(v1 동결 모델의 사후 검증 산출물, 2026-10-21)을 그대로 쓴다.
- 타깃: eval.live.load_test_targets(명시 플래그)뿐. 전체 지표·전환 분해는 test 124 조합, 리드타임은 2026 경계 사건 전부.
- 감시(q90_cqr)·경보(p_alert)는 v2 도 v1 동결 분위·분류기를 쓰므로 같다. v2 에서 달라지는 것은 점예측이다.
- 모든 표 위에 고지문을 붙인다: "모델 선택에 2026 미사용. 단 팀은 v1의 2026 결과를 이미 본 뒤 v2를 선택함(블라인드 아님).
  동결 커밋 <hash>". 결과와 상관없이 모델·판정은 바꾸지 않는다.
- 출력: reports/eval/tbl_holdout_2026_posthoc_v2.md, data/processed/posthoc_2026_v2.parquet.
사용: python -m algaecast.eval.posthoc_v2 [--force]
"""

from __future__ import annotations

import argparse
import re

import numpy as np
import pandas as pd

from algaecast.config import DATA_DIR, MODELS_DIR, ROOT
from algaecast.eval import posthoc as PH
from algaecast.eval.metrics import compute_all
from algaecast.eval.transitions import T1K, T10K, official_events
from algaecast.models import registry as R

EVAL = ROOT / "reports" / "eval"
OUT_MD = EVAL / "tbl_holdout_2026_posthoc_v2.md"
OUT_V2 = DATA_DIR / "processed" / "posthoc_2026_v2.parquet"
V1_PARQUET = DATA_DIR / "processed" / "posthoc_2026.parquet"
KEYS = ["n", "rmse_log", "mae_log", "r2_log", "r2_raw", "r2_pearson_raw", "nse_raw", "f1_10k", "f1_1k"]


def v2_frozen_commit() -> str:
    text = (MODELS_DIR / "FROZEN_v2.md").read_text(encoding="utf-8")
    m = re.search(r"동결 커밋: `([0-9a-f]{7,40})`", text)
    if not m:
        raise SystemExit(
            "중단: models/FROZEN_v2.md 의 동결 커밋이 아직 기입되지 않았다(동결 커밋 뒤에 실행)."
        )
    return m.group(1)


def notice(commit: str) -> str:
    return (
        f"> 모델 선택에 2026 미사용. 단 팀은 v1의 2026 결과를 이미 본 뒤 v2를 선택함(블라인드 아님). "
        f"동결 커밋 `{commit[:12]}`\n\n"
    )


def overall(pred: pd.DataFrame, label: str) -> dict:
    has = pred[pred["target_cells"].notna()]
    obs = has["target_cells"].to_numpy(dtype=float)
    m = compute_all(
        obs,
        has["pred_cell_count"].to_numpy(dtype=float),
        q10=has["q10_cqr"].to_numpy(),
        q90=has["q90_cqr"].to_numpy(),
        p10k=has["p_alert"].to_numpy(),
    )
    return {
        "모델": label,
        **{k: m[k] for k in KEYS},
        "PICP80(CQR)": m["picp80"],
        "MPIW80_log": m["mpiw80_log"],
        "Brier(p_alert vs ≥10k)": m["brier_10k"],
    }


def by_site(v1: pd.DataFrame, v2: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sid in sorted(set(v2["station_id"])):
        r = {"지점": sid}
        for lab, p in (("v1", v1), ("v2", v2)):
            g = p[(p["station_id"] == sid) & p["target_cells"].notna()]
            m = compute_all(
                g["target_cells"].to_numpy(dtype=float), g["pred_cell_count"].to_numpy(dtype=float)
            )
            r["n"] = int(m["n"])
            for k in ("r2_raw", "rmse_log", "r2_log", "f1_10k"):
                r[f"{lab} {k}"] = m[k]
        rows.append(r)
    return pd.DataFrame(rows)


def stacked(fn, v1: pd.DataFrame, v2: pd.DataFrame, **kw: object) -> pd.DataFrame:  # noqa: ANN001
    a, b = fn(v1, **kw), fn(v2, **kw)
    a.insert(0, "모델", "v1")
    b.insert(0, "모델", "v2")
    return pd.concat([b, a], ignore_index=True)


def event_detail(v1: pd.DataFrame, v2: pd.DataFrame, level: float) -> pd.DataFrame:
    """2026 경계 사건별 첫 경보 base_date·리드(E) — v1·v2 × 감시·경보·점예측."""
    ev = official_events(level, start_year=2026)
    out = pd.DataFrame(
        {
            "지점": [e.station_id for e in ev.itertuples()],
            "E": [pd.Timestamp(e._3).date() for e in ev.itertuples()],
        }
    )
    out["D"] = [pd.Timestamp(e._2).date() for e in ev.itertuples()]
    for lab, p in (("v1", v1), ("v2", v2)):
        _, det = PH.leadtime_2026(p, level, point=True)
        for rule, short in (
            ("감시(q90_cqr≥임계)", "감시"),
            ("경보(p_alert≥운영점)", "경보"),
            ("점예측≥임계", "점예측"),
        ):
            d = det[det["방식"] == rule].set_index(["지점", "E"]) if len(det) else pd.DataFrame()
            out[f"{lab} {short} 리드(E)"] = [
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
            f"중단: {OUT_MD} 가 이미 있다 — v2 사후 계산은 한 번만 한다(--force 는 재현 확인용)."
        )
    if R.current_kind("regression") != "ensemble_v2":
        raise SystemExit("중단: current 회귀가 v2(ensemble_v2)가 아니다 — 동결 뒤 실행.")
    commit = v2_frozen_commit()
    v1 = pd.read_parquet(V1_PARQUET)
    v1["station_id"] = v1["station_id"].astype(str)
    v1["base_date"] = pd.to_datetime(v1["base_date"])
    v2 = PH.predict_2026()
    v2.to_parquet(OUT_V2, index=False)
    key = ["station_id", "base_date"]
    same = v1[key].astype(str).equals(v2[key].astype(str))
    has = v2[v2["target_cells"].notna()]
    b0 = np.clip(10 ** has["cell_log_t0"].fillna(0).to_numpy() - 1, 0, None)
    m_b0 = compute_all(has["target_cells"].to_numpy(dtype=float), b0)
    tab_all = pd.DataFrame(
        [
            overall(v2, "v2 운영·제출 모델 C(≤2025 학습)"),
            overall(v1, "v1 블라인드 검증 모델(≤2025 학습)"),
            {"모델": "B0 지속성", **{k: m_b0[k] for k in KEYS}},
        ]
    )
    if not same:
        raise SystemExit("중단: v1 사후 예측과 v2 의 (지점, 기준일) 행이 다르다.")
    q90_diff = float(np.nanmax(np.abs(v2["q90_cqr"].to_numpy() - v1["q90_cqr"].to_numpy())))
    alert_mis = int(
        (v2["alert_flag"].to_numpy().astype(bool) != v1["alert_flag"].to_numpy().astype(bool)).sum()
    )
    lt10 = pd.concat(
        [
            PH.leadtime_2026(v2, T10K, point=True)[0].assign(모델="v2"),
            PH.leadtime_2026(v1, T10K, point=True)[0].assign(모델="v1"),
        ],
        ignore_index=True,
    )
    lt10 = lt10[["모델", *[c for c in lt10.columns if c != "모델"]]]
    ev_det = event_detail(v1, v2, T10K)
    tr10 = stacked(PH.transitions_2026, v1, v2, level=T10K, point=True)
    tr1 = stacked(PH.transitions_2026, v1, v2, level=T1K, point=True)
    d_log = np.abs(
        np.log10(v2["pred_cell_count"].to_numpy() + 1) - np.log10(v1["pred_cell_count"].to_numpy() + 1)
    )
    n_ev = len(official_events(T10K, start_year=2026))
    nt = notice(commit)
    md = (
        f"# 2026 사후 계산 — v2 vs v1 봉인본(수정 전 이력, 2026-10-22 계산; 제출·운영 v2.1 은 tbl_holdout_2026_posthoc_v21.md) (test 조합 {len(has)}건 타깃 + 2026 base_date {len(v2)}건 예측)\n\n"
        f"{nt}"
        "- v2 = 최종 모델 C(models/FROZEN_v2.md). v1 은 2026-10-21 09:44 KST 봉인 뒤 2026 을 처음 계산했다. 두 모델 모두 일부 데이터 유래 상수가 2026 자료를 포함해 계산된 사실을 2026-10-23 사후 발견해 이력으로만 남긴다(reports/experiments/FIX-v2.1/RESULT.md)"
        "(reports/eval/tbl_holdout_2026_posthoc.md).\n"
        "- 2026 타깃은 eval/live.load_test_targets(명시 플래그)로만 읽었다. 이 계산은 v2 동결 뒤 한 번만 했고, 결과와 상관없이 모델·판정을 바꾸지 않는다.\n"
        f"- 감시(q90_cqr)·경보(p_alert)는 v2 도 v1 동결 분위·분류기를 쓴다 → 2026 base_date {len(v2)}행에서 v1 대비 q90_cqr 최대 차 {q90_diff:.3g}, 경보 불일치 {alert_mis}행. "
        f"v2 에서 달라지는 것은 점예측(회귀)이다: v1 대비 |Δlog10| 중앙 {np.median(d_log):.3f}, 최대 {np.max(d_log):.3f}(행 키·순서 일치).\n\n"
        "## 1. 전체 지표(test 124 조합)\n\n" + nt + PH._md(tab_all) + "\n\n"
        "## 2. 지점별(점예측)\n\n" + nt + PH._md(by_site(v1, v2)) + "\n\n"
        f"## 3. 리드타임 — 2026 경계(10k) 사건 {n_ev}건\n\n" + nt + PH._md(lt10) + "\n\n"
        "### 사건별 첫 경보 리드(E, 일; 빈칸 = 사건 전 28일 안 경보 없음)\n\n" + nt + PH._md(ev_det) + "\n\n"
        "## 4. 전환 분해 — 경계 10k(test 124 조합)\n\n" + nt + PH._md(tr10) + "\n\n"
        "## 5. 전환 분해 — 관심 1k(test 124 조합)\n\n" + nt + PH._md(tr1) + "\n"
    )
    OUT_MD.write_text(md, encoding="utf-8", newline="\n")
    print(tab_all.round(4).to_string(index=False))
    print(lt10.round(2).to_string(index=False))
    print(ev_det.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
