"""2026 사후 검증 (모델 동결 후, 모델 선택·튜닝에 미사용) — eval/live.load_test_targets 가 유일한 타깃 통로.

- 2026 base_date 전체(측정일) 에 대해 동결 레지스트리(≤2025 학습) 예측: ens·q10/q50/q90(+CQR)·p_alert·tier
- 지표: test 조합(124)만 타깃이 있으므로 전체 지표·전환 분해는 124건, 리드타임은 2026 경계 사건
전부(경보 지시자는 타깃 불필요)
- 출력: reports/eval/tbl_holdout_2026_posthoc.md, data/processed/posthoc_2026.parquet, Supabase
bloom_events/transition_metrics/model_metrics 갱신(--upload)
"""

from __future__ import annotations

import argparse
import json
import re

import numpy as np
import pandas as pd
import yaml

from algaecast.config import CONFIG_DIR, DATA_DIR, MODELS_DIR, ROOT
from algaecast.db.upload import predict_registry
from algaecast.eval.live import load_test_targets
from algaecast.eval.metrics import compute_all
from algaecast.eval.transitions import SEGMENTS, T1K, T10K, official_events
from algaecast.models import data as D

EVAL = ROOT / "reports" / "eval"
OUT = DATA_DIR / "processed" / "posthoc_2026.parquet"


def frozen_commit() -> str:
    text = (MODELS_DIR / "FROZEN.md").read_text(encoding="utf-8")
    m = re.search(r"동결 커밋: `([0-9a-f]+)`", text)
    return m.group(1)[:12] if m else "unknown"


def _md(t: pd.DataFrame, nd: int = 3) -> str:
    d = t.copy()
    for c in d.columns:
        if d[c].dtype.kind == "f":
            d[c] = d[c].round(nd)
    return (
        "| "
        + " | ".join(map(str, d.columns))
        + " |\n|"
        + "---|" * len(d.columns)
        + "\n"
        + "\n".join(
            "| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |"
            for r in d.itertuples(index=False)
        )
    )


def predict_2026(threshold_year: int | None = None) -> pd.DataFrame:
    """threshold_year: 2026 행 수온 임계 자료 끝 연도(None = 피처 파일 값 그대로, v2.1 이력 재현은 2025)."""
    feat = pd.read_parquet(D._features_path("S1"))
    feat["base_date"] = pd.to_datetime(feat["base_date"])
    feat["target_date"] = pd.to_datetime(feat["target_date"])
    f26 = feat[feat["base_date"].dt.year == 2026].reset_index(drop=True)
    if threshold_year is not None:
        from algaecast.features.constants import apply_site_thresholds

        f26 = apply_site_thresholds(f26, threshold_year)
    pr = predict_registry(f26)
    out = pd.concat(
        [f26[["station_id", "site_code", "base_date", "target_date", "split", "cell_log_t0"]], pr], axis=1
    )
    tt = load_test_targets(i_know_this_is_for_post_hoc_only=True)
    tt["base_date"] = pd.to_datetime(tt["base_date"])
    out = out.merge(
        tt[["station_id", "base_date", "target_cells"]], on=["station_id", "base_date"], how="left"
    )
    out["station_id"] = out["station_id"].astype(str)
    return out


def leadtime_2026(
    pred: pd.DataFrame, level: float = T10K, lookback_days: int = 28, point: bool = False
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """point=True 면 점예측(pred_cell_count≥임계) 규칙을 더한다(v2 사후 비교용; 기본은 v1 표와 같음)."""
    ev = official_events(level, start_year=2026)
    meas = pd.read_parquet(DATA_DIR / "raw" / "nier_algae" / "nier_algae_2012_2026.parquet")
    meas["obs_date"] = pd.to_datetime(meas["obs_date"])
    meas["cells"] = meas["iem_bgalage_cell_co"].astype(float)
    b0 = np.clip(10 ** pred["cell_log_t0"].fillna(0).to_numpy() - 1, 0, None)
    rules = {
        "B0 지속성": b0 >= level,
        "감시(q90_cqr≥임계)": pred["q90_cqr"].to_numpy() >= level,
        "경보(p_alert≥운영점)": pred["alert_flag"].to_numpy().astype(bool),
        "q50≥임계": pred["q50"].to_numpy() >= level,
    }
    if point:
        rules["점예측≥임계"] = pred["pred_cell_count"].to_numpy() >= level
    rows, detail = [], []
    for name, al in rules.items():
        al_s = pd.Series(al, index=pred.index)
        leads_E, leads_D, det, n_ev = [], [], 0, 0
        for e in ev.itertuples():
            E, Dd = pd.Timestamp(e._3), pd.Timestamp(e._2)
            prev = meas[
                (meas["station_id"] == e.station_id) & (meas["obs_date"] < E) & (meas["cells"] >= level)
            ]["obs_date"]
            start = E - pd.Timedelta(days=lookback_days)
            if len(prev):
                start = max(start, prev.max() + pd.Timedelta(days=1))
            cand = pred[
                (pred["station_id"] == e.station_id) & (pred["base_date"] < E) & (pred["base_date"] >= start)
            ]
            if cand.empty:
                continue
            n_ev += 1
            fired = cand[al_s.loc[cand.index]]
            if len(fired):
                det += 1
                b = fired["base_date"].min()
                leads_E.append((E - b).days)
                leads_D.append((Dd - b).days)
                detail.append(
                    {
                        "방식": name,
                        "지점": e.station_id,
                        "E": E.date(),
                        "D": Dd.date(),
                        "첫 경보 base_date": b.date(),
                        "리드(E)": (E - b).days,
                        "리드(D)": (Dd - b).days,
                    }
                )
        rows.append(
            {
                "방식": name,
                "사건 수": n_ev,
                "선행 탐지 수": det,
                "선행 탐지 비율": det / n_ev if n_ev else np.nan,
                "중앙 리드(E, 일)": float(np.median(leads_E)) if leads_E else np.nan,
                "중앙 리드(D, 일)": float(np.median(leads_D)) if leads_D else np.nan,
                "경보 총수(2026)": int(al.sum()),
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(detail)


def transitions_2026(pred: pd.DataFrame, level: float, point: bool = False) -> pd.DataFrame:
    t = pred[pred["target_cells"].notna()].copy()
    s0 = (np.clip(10 ** t["cell_log_t0"].fillna(0).to_numpy() - 1, 0, None) >= level).astype(int)
    s1 = (t["target_cells"].to_numpy() >= level).astype(int)
    seg = np.array([SEGMENTS[(a, b)] for a, b in zip(s0, s1, strict=True)])
    rules = {
        "B0 지속성": s0.astype(bool),
        "감시(q90_cqr≥임계)": t["q90_cqr"].to_numpy() >= level,
        "경보(p_alert≥운영점)": t["alert_flag"].to_numpy().astype(bool),
        "q50≥임계": t["q50"].to_numpy() >= level,
    }
    if point:
        rules["점예측≥임계"] = t["pred_cell_count"].to_numpy() >= level
    rows = []
    for name, al in rules.items():
        a = al.astype(int)
        tp, fp, fn = (
            int(((a == 1) & (s1 == 1)).sum()),
            int(((a == 1) & (s1 == 0)).sum()),
            int(((a == 0) & (s1 == 1)).sum()),
        )
        prec = tp / (tp + fp) if tp + fp else np.nan
        rec = tp / (tp + fn) if tp + fn else np.nan
        row = {
            "방식": name,
            "n": len(t),
            "Precision": prec,
            "Recall": rec,
            "F1": 2 * prec * rec / (prec + rec) if prec and rec and prec + rec > 0 else 0.0,
        }
        for sname in SEGMENTS.values():
            m = seg == sname
            row[f"{sname} n"] = int(m.sum())
            row[f"{sname} 경보율"] = float(a[m].mean()) if m.any() else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def gjgr_may18(pred: pd.DataFrame) -> pd.DataFrame:
    """강정·고령 2026-05-18 이례 조기 '관심' 발령 — 1k 기준 감시(q90_cqr≥1k)·q50≥1k·경보(p_alert) "
    "점등 시점."""
    g = pred[
        (pred["station_id"] == "GJGR")
        & (pred["base_date"] >= "2026-04-01")
        & (pred["base_date"] <= "2026-06-15")
    ].sort_values("base_date")
    out = g[
        ["base_date", "target_date", "target_cells", "q50", "q10_cqr", "q90_cqr", "p_alert", "tier"]
    ].copy()
    out["감시(1k): q90_cqr≥1k"] = out["q90_cqr"] >= T1K
    out["q50≥1k"] = out["q50"] >= T1K
    out["최근 관측"] = np.clip(10 ** g["cell_log_t0"].fillna(0).to_numpy() - 1, 0, None)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--upload", action="store_true", help="Supabase bloom_events/transition_metrics/model_metrics 갱신"
    )
    args = ap.parse_args(argv)
    fc = frozen_commit()
    note = f"**사후 검증 — 모델 선택·튜닝에 미사용, 동결 커밋 {fc}** (models/FROZEN.md)"
    pred = predict_2026()
    pred.to_parquet(OUT, index=False)
    has = pred[pred["target_cells"].notna()]
    obs, p = has["target_cells"].to_numpy(dtype=float), has["pred_cell_count"].to_numpy(dtype=float)
    m_all = compute_all(
        obs, p, q10=has["q10_cqr"].to_numpy(), q90=has["q90_cqr"].to_numpy(), p10k=has["p_alert"].to_numpy()
    )
    b0 = np.clip(10 ** has["cell_log_t0"].fillna(0).to_numpy() - 1, 0, None)
    m_b0 = compute_all(obs, b0)
    keys = ["n", "rmse_log", "mae_log", "r2_log", "r2_raw", "r2_pearson_raw", "nse_raw", "f1_10k", "f1_1k"]
    overall = pd.DataFrame(
        [
            {
                "모델": "동결 앙상블(≤2025 학습)",
                **{k: m_all[k] for k in keys},
                "PICP80(CQR)": m_all["picp80"],
                "MPIW80_log": m_all["mpiw80_log"],
                "Brier(p_alert vs ≥10k)": m_all["brier_10k"],
            },
            {"모델": "B0 지속성", **{k: m_b0[k] for k in keys}},
        ]
    )
    site_rows = []
    for sid, g in has.groupby("station_id"):
        mm = compute_all(g["target_cells"].to_numpy(dtype=float), g["pred_cell_count"].to_numpy(dtype=float))
        site_rows.append({"station_id": sid, **{k: mm[k] for k in keys}})
    tr10, tr1 = transitions_2026(pred, T10K), transitions_2026(pred, T1K)
    lt10, det10 = leadtime_2026(pred, T10K)
    lt1, det1 = leadtime_2026(pred, T1K)
    gj = gjgr_may18(pred)
    ev26 = official_events(T10K, start_year=2026)
    (EVAL / "tbl_holdout_2026_posthoc.md").write_text(
        f"# 2026 사후 검증 (test 조합 {len(has)}건 타깃 + 2026 base_date {len(pred)}건 예측)\n\n- {note}\n"
        "- 2026 타깃은 eval/live.load_test_targets(명시 플래그) 로만 읽었고 학습·튜닝·임계 결정에 "
        "쓰지 않았다. "
        "리드타임은 경보 지시자만 필요하므로 2026 측정일 전체(타깃 없는 base_date 포함)로 계산.\n\n"
        "## 전체 지표 (test 124 조합)\n"
        + _md(overall)
        + "\n\n## 지점별\n"
        + _md(pd.DataFrame(site_rows))
        + "\n\n"
        "## 전환 분해 — 경계 10k\n" + _md(tr10) + "\n\n## 전환 분해 — 관심 1k\n" + _md(tr1) + "\n\n"
        f"## 리드타임 — 2026 경계 사건 {len(ev26)}건\n"
        + _md(lt10)
        + "\n\n### 사건별 상세(10k)\n"
        + _md(det10)
        + "\n\n"
        "## 리드타임 — 2026 관심(1k) 사건\n" + _md(lt1) + "\n\n"
        "## 강정·고령 2026-05-18 이례 조기 관심 발령 — 1k 기준 점등 시점\n"
        + _md(gj)
        + "\n\n### 관심(1k) 사건별 상세\n"
        + _md(det1)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(overall.round(3).to_string(index=False))
    print(lt10.round(3).to_string(index=False))
    print(gj.round(2).to_string(index=False))
    if args.upload:
        from algaecast.db.upload import client, upsert

        sb = client()
        sid_map = {
            s["station_id"]: s["site_code"]
            for s in yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))["sites"]
        }
        w = det10[det10["방식"] == "감시(q90_cqr≥임계)"].set_index(["지점", "E"])
        a = det10[det10["방식"] == "경보(p_alert≥운영점)"].set_index(["지점", "E"])
        rows = []
        for e in ev26.itertuples():
            key = (e.station_id, e._3)
            ww = w.loc[key] if key in w.index else None
            aa = a.loc[key] if key in a.index else None
            rows.append(
                {
                    "site_id": sid_map[e.station_id],
                    "event_id": f"{e.station_id}-{e._3}",
                    "first_exceed_date": str(e._3),
                    "official_alert_date": str(e._2),
                    "first_watch_date": None if ww is None else str(ww["첫 경보 base_date"]),
                    "first_alert_date": None if aa is None else str(aa["첫 경보 base_date"]),
                    "lead_days_watch_e": None if ww is None else int(ww["리드(E)"]),
                    "lead_days_alert_e": None if aa is None else int(aa["리드(E)"]),
                    "lead_days_watch_d": None if ww is None else int(ww["리드(D)"]),
                    "lead_days_alert_d": None if aa is None else int(aa["리드(D)"]),
                    "detected_watch": ww is not None,
                    "detected_alert": aa is not None,
                }
            )
        n1 = upsert(sb, "bloom_events", rows, "site_id,event_id", False)
        trows = []
        seg_map = {
            "유지-미만": "stay_below",
            "유지-초과": "stay_above",
            "진입(onset)": "onset",
            "이탈(offset)": "offset",
        }
        for level, t in ((T10K, tr10), (T1K, tr1)):
            for d in t.to_dict("records"):
                trows.append(
                    {
                        "split": "posthoc2026",
                        "method": d["방식"],
                        "segment": "all",
                        "threshold": level,
                        "n": int(d["n"]),
                        "recall": None if pd.isna(d["Recall"]) else d["Recall"],
                        "precision": None if pd.isna(d["Precision"]) else d["Precision"],
                        "f1": d["F1"],
                        "false_alarm_rate": None,
                    }
                )
                for ko, seg in seg_map.items():
                    pos = seg in ("onset", "stay_above")
                    rate = d[f"{ko} 경보율"]
                    rate = None if pd.isna(rate) else float(rate)
                    trows.append(
                        {
                            "split": "posthoc2026",
                            "method": d["방식"],
                            "segment": seg,
                            "threshold": level,
                            "n": int(d[f"{ko} n"]),
                            "recall": rate if pos else None,
                            "precision": None,
                            "f1": None,
                            "false_alarm_rate": None if pos else rate,
                        }
                    )
        n2 = upsert(sb, "transition_metrics", trows, "split,method,segment,threshold", False)
        run = (
            sb.table("model_runs")
            .select("run_id")
            .eq("status", "success")
            .order("run_at", desc=True)
            .limit(1)
            .execute()
            .data[0]["run_id"]
        )
        mrows = [
            {
                "run_id": run,
                "split": "posthoc2026",
                "site_id": None,
                "metric": k,
                "value": float(m_all[k]),
                "ci_low": None,
                "ci_high": None,
            }
            for k in keys[1:]
        ]
        lt_w = lt10[lt10["방식"].str.startswith("감시")].iloc[0]
        mrows += [
            {
                "run_id": run,
                "split": "posthoc2026",
                "site_id": None,
                "metric": k,
                "value": float(v),
                "ci_low": None,
                "ci_high": None,
            }
            for k, v in (
                ("leadtime_events", lt_w["사건 수"]),
                ("leadtime_detected_watch", lt_w["선행 탐지 수"]),
                (
                    "leadtime_median_days_watch_E",
                    lt_w["중앙 리드(E, 일)"] if np.isfinite(lt_w["중앙 리드(E, 일)"]) else -1,
                ),
            )
        ]
        n3 = upsert(sb, "model_metrics", mrows, None, False)
        print(
            json.dumps(
                {"bloom_events": n1, "transition_metrics": n2, "model_metrics": n3}, ensure_ascii=False
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
