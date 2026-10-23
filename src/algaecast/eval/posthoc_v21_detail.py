# ruff: noqa: E501  (한국어 표)
"""2026 사후 계산(v2.1) 세부 집계 — 저장된 v2.1 사후 예측을 다시 집계만 한다(예측을 다시 하지 않는다).

- 입력: data/processed/posthoc_2026_v21.parquet(eval.posthoc_v21 이 v2.1 동결 커밋 뒤 1회 만든 2026 예측·타깃),
  2026 공식 사건(eval.transitions.official_events, 측정 원자료).
- 출력: reports/eval/tbl_holdout_2026_posthoc_v21_detail.md, posthoc_2026_v21_detail.json
  1) 지점별 2026 지표(v2.1 점예측·v1-fix 점예측·B0 지속성, test 124 조합)
  2) 2026 관심(1k) 사건 리드타임(감시·경보·q50·점예측·B0)과 사건별 상세
  3) 강정·고령 2026-05-18 이례 조기 관심 발령 — 1k 기준 점등 시점
- 블라인드 아님: 모델 선택·수정 규칙에 2026 을 쓰지 않았지만 팀은 수정 전 v1·v2 의 2026 결과를 이미 봤다.
사용: python -m algaecast.eval.posthoc_v21_detail
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from algaecast.config import ROOT
from algaecast.eval import posthoc as PH
from algaecast.eval import posthoc_v21 as P21
from algaecast.eval.metrics import compute_all
from algaecast.eval.transitions import T1K, official_events

EVAL = ROOT / "reports" / "eval"
OUT_MD = EVAL / "tbl_holdout_2026_posthoc_v21_detail.md"
OUT_JSON = EVAL / "posthoc_2026_v21_detail.json"
KEYS = ["n", "rmse_log", "mae_log", "r2_log", "r2_raw", "r2_pearson_raw", "nse_raw", "f1_10k", "f1_1k"]
SITE_KO = {"HP": "해평", "GJGR": "강정·고령", "CS": "칠서", "MGMR": "물금·매리", "DCHN": "회남"}


def load_pred() -> pd.DataFrame:
    """v2.1 동결 뒤 1회 만든 2026 사후 예측(저장본). 없으면 중단 — 여기서 예측을 새로 만들지 않는다."""
    if not P21.OUT_PQ.exists():
        raise SystemExit(f"{P21.OUT_PQ} 가 없다. 2026 사후 예측은 eval.posthoc_v21 로 1회만 만든다.")
    pred = pd.read_parquet(P21.OUT_PQ)
    pred["base_date"] = pd.to_datetime(pred["base_date"])
    pred["target_date"] = pd.to_datetime(pred["target_date"])
    pred["station_id"] = pred["station_id"].astype(str)
    return pred


def site_table(pred: pd.DataFrame) -> pd.DataFrame:
    """지점별 2026 지표(test 124 조합, 타깃 있는 행)."""
    has = pred[pred["target_cells"].notna()]
    rows = []
    for sid in ["HP", "GJGR", "CS", "MGMR", "DCHN"]:
        g = has[has["station_id"] == sid]
        if g.empty:
            continue
        obs = g["target_cells"].to_numpy(dtype=float)
        b0 = np.clip(10 ** g["cell_log_t0"].fillna(0).to_numpy() - 1, 0, None)
        for label, p in (
            ("v2.1", g["pred_cell_count"].to_numpy(dtype=float)),
            ("v1-fix", g["pred_v1fix"].to_numpy(dtype=float)),
            ("B0 지속성", b0),
        ):
            m = compute_all(obs, p)
            rows.append({"지점": SITE_KO[sid], "station_id": sid, "모델": label, **{k: m[k] for k in KEYS}})
    return pd.DataFrame(rows)


def main() -> int:
    pred = load_pred()
    commit = P21.frozen_commit()
    sites = site_table(pred)
    lt1, det1 = PH.leadtime_2026(pred, T1K, point=True)
    gj = PH.gjgr_may18(pred)
    ev1 = official_events(T1K, start_year=2026)
    gj_ev = ev1[ev1["station_id"] == "GJGR"]
    note = (
        f"- v2.1 동결 커밋 {commit} 뒤 1회 만든 2026 사후 예측(`data/processed/posthoc_2026_v21.parquet`)을 다시 집계한 표다. "
        "예측은 다시 하지 않았다. 블라인드 아님(모델 선택·수정 규칙에 2026 을 쓰지 않았지만 팀은 수정 전 v1·v2 의 2026 결과를 이미 봤다).\n"
        "- 리드타임 정의는 2026 경계 사건 표와 같다(첫 초과 측정일 E 이전 28일 안, 직전 초과 다음 날부터). 관심 = 1,000 cells/mL.\n"
    )
    OUT_MD.write_text(
        "# 2026 사후 계산 세부 — v2.1(지점별·관심 1k 리드타임·강정·고령 5월)\n\n"
        + note
        + "\n## 1. 지점별 2026 지표(test 124 조합)\n"
        + PH._md(sites.drop(columns=["station_id"]))
        + f"\n\n## 2. 리드타임 — 2026 관심(1k) 사건 {len(ev1)}건\n"
        + PH._md(lt1)
        + "\n\n### 관심(1k) 사건별 상세\n"
        + PH._md(det1)
        + "\n\n## 3. 강정·고령 2026-05-18 이례 조기 관심 발령 — 1k 기준 점등 시점(v2.1)\n"
        + PH._md(gj)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    first_watch = gj[gj["감시(1k): q90_cqr≥1k"]]["base_date"].min()
    summary = {
        "commit": commit,
        "source": "data/processed/posthoc_2026_v21.parquet (재집계, 예측 재실행 없음)",
        "sites": sites.to_dict(orient="records"),
        "lead_1k": lt1.to_dict(orient="records"),
        "events_1k": int(len(ev1)),
        "gjgr_events_1k": [{"E": str(r._3), "D": str(r._2)} for r in gj_ev.itertuples()],
        "gjgr_first_watch_1k_base_date": (
            None if pd.isna(first_watch) else str(pd.Timestamp(first_watch).date())
        ),
    }
    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8"
    )
    print(sites.round(3).to_string(index=False))
    print(lt1.round(3).to_string(index=False))
    print(gj.round(2).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
