"""T5-1 상태 전환 구간 평가·리드타임·운영점·CQR (OOF 캐시 data/processed/oof_predictions.parquet 사용).

출력: reports/eval/tbl_transitions.md, tbl_leadtime.md, tbl_operating_points.md, tbl_cqr.md
사용: python -m algaecast.eval.transitions
"""

from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd
import yaml

from algaecast.collect.algae_source import load_algae_source
from algaecast.collect.nier_algae import two_consecutive_levels
from algaecast.collect.nier_forecast import level_from_cells
from algaecast.config import CONFIG_DIR, DATA_DIR, ROOT
from algaecast.eval.metrics import mpiw, picp

log = logging.getLogger(__name__)
EVAL = ROOT / "reports" / "eval"
OOF_PATH = DATA_DIR / "processed" / "oof_predictions.parquet"
T10K, T1K = 10_000.0, 1_000.0
SEGMENTS = {(0, 0): "유지-미만", (1, 1): "유지-초과", (0, 1): "진입(onset)", (1, 0): "이탈(offset)"}


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


def load_oof() -> tuple[pd.DataFrame, dict]:
    o = pd.read_parquet(OOF_PATH)
    o["base_date"] = pd.to_datetime(o["base_date"])
    o["target_date"] = pd.to_datetime(o["target_date"])
    cfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))
    return o, cfg["thresholds"]


def alarm_methods(o: pd.DataFrame, thr: dict, level: float = T10K) -> dict[str, np.ndarray]:
    """방식별 경보 지시자 (1/0, NaN 예측은 0)."""
    out = {"B0 지속성": (o["b0"].to_numpy() >= level).astype(float)}
    if level == T10K:
        out["분류기(a)"] = (o["clf_a"].to_numpy() >= thr["clf_a"]).astype(float)
        out["분류기(b)"] = (o["clf_b"].to_numpy() >= thr["clf_b"]).astype(float)
        out["스태킹(a)"] = (o["stack_a"].to_numpy() >= thr["stack_a"]).astype(float)
    out["q90≥임계"] = (o["q90"].to_numpy() >= level).astype(float)
    out["회귀 C1≥임계"] = (o["reg_c1"].to_numpy() >= level).astype(float)
    out["앙상블≥임계"] = (o["ens"].to_numpy() >= level).astype(float)
    for k, v in out.items():
        src = {
            "분류기(a)": "clf_a",
            "분류기(b)": "clf_b",
            "스태킹(a)": "stack_a",
            "q90≥임계": "q90",
            "회귀 C1≥임계": "reg_c1",
            "앙상블≥임계": "ens",
        }.get(k)
        if src:
            v[~np.isfinite(o[src].to_numpy())] = np.nan
    return out


# ---------------------------------------------------------------- 1) 전환 분해
def transition_table(o: pd.DataFrame, thr: dict, level: float) -> pd.DataFrame:
    s0 = (o["b0"].to_numpy() >= level).astype(int)
    s1 = (o["target_cells"].to_numpy() >= level).astype(int)
    seg = np.array([SEGMENTS[(a, b)] for a, b in zip(s0, s1, strict=True)])
    rows = []
    for scope, m in (
        ("CV OOF 2020~2024", (o["year"] >= 2020) & (o["year"] <= 2024)),
        ("2025", o["year"] == 2025),
    ):
        m = m.to_numpy()
        for name, al in alarm_methods(o, thr, level).items():
            ok = m & np.isfinite(al)
            y, a = s1[ok], al[ok].astype(int)
            tp, fp, fn = (
                int(((a == 1) & (y == 1)).sum()),
                int(((a == 1) & (y == 0)).sum()),
                int(((a == 0) & (y == 1)).sum()),
            )
            prec = tp / (tp + fp) if tp + fp else np.nan
            rec = tp / (tp + fn) if tp + fn else np.nan
            row = {
                "구간": scope,
                "방식": name,
                "n": int(ok.sum()),
                "전체 Precision": prec,
                "전체 Recall": rec,
                "전체 F1": (
                    (2 * prec * rec / (prec + rec))
                    if prec and rec and np.isfinite(prec) and np.isfinite(rec) and prec + rec > 0
                    else 0.0
                ),
            }
            for sname in SEGMENTS.values():
                sm = ok & (seg == sname)
                n = int(sm.sum())
                rate = float(al[sm].mean()) if n else np.nan
                row[f"{sname} n"] = n
                row[f"{sname} 경보율"] = rate  # 양성 구간에서는 Recall, 음성 구간에서는 헛경보율
            rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 2) 리드타임
def official_events(level: float = T10K, start_year: int = 2020) -> pd.DataFrame:
    """2회 연속 규칙 산출 '경계' 발령 사건: 지점별 측정 시계열에서 2consec 단계가 2 미만→2 이상으로
    바뀐 측정일(D)과
    그 사건의 첫 초과 측정일(E, D 직전 연속 초과 시작)."""
    a = load_algae_source()  # 저장소 = API parquet, 제출 패키지 = 대회 번들(collect/algae_source.py)
    a["obs_date"] = pd.to_datetime(a["obs_date"])
    a = a[a["obs_date"].dt.year >= start_year - 1]
    ev = []
    lvl_needed = 2 if level == T10K else 1
    for sid, g in a.sort_values("obs_date").groupby("station_id"):
        cells = g["iem_bgalage_cell_co"].astype(float)
        single = level_from_cells(cells)
        two = two_consecutive_levels(single).astype(float).to_numpy()
        dates = g["obs_date"].to_numpy()
        cv = cells.to_numpy()
        for i in range(1, len(g)):
            if two[i] >= lvl_needed and two[i - 1] < lvl_needed:
                D = dates[i]
                j = i
                while j - 1 >= 0 and np.isfinite(cv[j - 1]) and cv[j - 1] >= level:
                    j -= 1
                E = dates[j]
                if pd.Timestamp(D).year >= start_year:
                    ev.append(
                        {
                            "station_id": sid,
                            "발령 측정일 D": pd.Timestamp(D).date(),
                            "첫 초과 측정일 E": pd.Timestamp(E).date(),
                        }
                    )
    return pd.DataFrame(ev)


def leadtime_table(
    o: pd.DataFrame, thr: dict, level: float = T10K, lookback_days: int = 28
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ev = official_events(level)
    methods = alarm_methods(o, thr, level)
    rows, detail = [], []
    o = o[o["year"] >= 2020]
    meas = load_algae_source()
    meas["obs_date"] = pd.to_datetime(meas["obs_date"])
    meas["cells"] = meas["iem_bgalage_cell_co"].astype(float)

    def window_start(sid: str, E: pd.Timestamp) -> pd.Timestamp:
        """E 이전 lookback 일, 단 직전 초과 측정(이전 사건의 꼬리) 이후부터 — B0 가 이전 사건으로 "
        "'선행'하는 착시 제거."""
        prev = meas[(meas["station_id"] == sid) & (meas["obs_date"] < E) & (meas["cells"] >= level)][
            "obs_date"
        ]
        start = E - pd.Timedelta(days=lookback_days)
        if len(prev):
            start = max(start, prev.max() + pd.Timedelta(days=1))
        return start

    for name, al in methods.items():
        al_s = pd.Series(al, index=o.index) if len(al) == len(o) else pd.Series(al[o.index], index=o.index)
        leads_E, leads_D, detected, n_ev = [], [], 0, 0
        for e in ev.itertuples():
            E, D = pd.Timestamp(e._3), pd.Timestamp(e._2)
            cand = o[
                (o["station_id"] == e.station_id)
                & (o["base_date"] < E)
                & (o["base_date"] >= window_start(e.station_id, E))
            ]
            if cand.empty:
                continue
            n_ev += 1
            fired = cand[al_s.loc[cand.index].fillna(0) >= 1]
            if len(fired):
                detected += 1
                b = fired["base_date"].min()
                leads_E.append((E - b).days)
                leads_D.append((D - b).days)
                detail.append(
                    {
                        "방식": name,
                        "지점": e.station_id,
                        "E": E.date(),
                        "D": D.date(),
                        "첫 경보 base_date": b.date(),
                        "리드(E) 일": (E - b).days,
                        "리드(D) 일": (D - b).days,
                    }
                )
        # 헛경보: 경보를 냈는데 target 이 임계 미만이고, 이후 14일 내 사건 시작(E) 도 없는 base_date 수
        fa = 0
        al_all = al_s.fillna(0).to_numpy() >= 1
        tgt_neg = o["target_cells"].to_numpy() < level
        for idx in np.where(al_all & tgt_neg)[0]:
            r = o.iloc[idx]
            near = ev[
                (ev["station_id"] == r["station_id"])
                & (pd.to_datetime(ev["첫 초과 측정일 E"]) >= r["base_date"])
                & (pd.to_datetime(ev["첫 초과 측정일 E"]) <= r["base_date"] + pd.Timedelta(days=14))
            ]
            if near.empty:
                fa += 1
        rows.append(
            {
                "방식": name,
                "사건 수": n_ev,
                "선행 탐지 수": detected,
                "선행 탐지 비율": detected / n_ev if n_ev else np.nan,
                "중앙 리드타임(E 기준, 일)": float(np.median(leads_E)) if leads_E else np.nan,
                "중앙 리드타임(D 기준, 일)": float(np.median(leads_D)) if leads_D else np.nan,
                "헛경보 수(2020~2025)": fa,
                "경보 총수": int(al_all.sum()),
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(detail)


# ---------------------------------------------------------------- 3) 운영점
def operating_points(
    o: pd.DataFrame, prob_col: str, y_col: str, ratios: tuple[int, ...] = (1, 2, 3, 5)
) -> pd.DataFrame:
    cv = o[(o["year"] >= 2020) & (o["year"] <= 2024) & np.isfinite(o[prob_col])]
    fin = o[(o["year"] == 2025) & np.isfinite(o[prob_col])]
    s0 = (fin["b0"].to_numpy() >= T10K).astype(int)
    onset = (s0 == 0) & (fin[y_col].to_numpy() == 1)
    grid = np.linspace(0.02, 0.98, 97)
    rows = []
    for r in ratios:
        costs = []
        for t in grid:
            pred = cv[prob_col].to_numpy() >= t
            y = cv[y_col].to_numpy() == 1
            costs.append(r * int((~pred & y).sum()) + int((pred & ~y).sum()))
        t_best = float(grid[int(np.argmin(costs))])
        pred = fin[prob_col].to_numpy() >= t_best
        y = fin[y_col].to_numpy() == 1
        tp, fp, fn = int((pred & y).sum()), int((pred & ~y).sum()), int((~pred & y).sum())
        prec = tp / (tp + fp) if tp + fp else np.nan
        rec = tp / (tp + fn) if tp + fn else np.nan
        rows.append(
            {
                "확률 소스": prob_col,
                "r(놓침/헛경보 비용)": r,
                "CV 최적 임계": t_best,
                "2025 TP": tp,
                "2025 FP": fp,
                "2025 FN": fn,
                "Precision": prec,
                "Recall": rec,
                "F1": 2 * prec * rec / (prec + rec) if prec and rec and prec + rec > 0 else 0.0,
                "진입 Recall": float(pred[onset].mean()) if onset.any() else np.nan,
                "2025 기대비용(r·FN+FP)": r * fn + fp,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 4) CQR
def cqr(
    o: pd.DataFrame, alpha: float = 0.2, calib_years: tuple[int, int] = (2020, 2024)
) -> tuple[pd.DataFrame, dict]:
    """Conformalized quantile regression: CV OOF(calib_years) 비순응 점수 s = max(lo−y, y−hi) (log10 공간) 의
    (1−α)(1+1/n) 분위를 폭 보정량으로 2025 구간에 적용."""
    cv = o[(o["year"] >= calib_years[0]) & (o["year"] <= calib_years[1]) & np.isfinite(o["q10"])]
    fin = o[(o["year"] == 2025) & np.isfinite(o["q10"])]
    ly = np.log10(cv["target_cells"].to_numpy() + 1)
    lo, hi = np.log10(cv["q10"].to_numpy() + 1), np.log10(cv["q90"].to_numpy() + 1)
    s = np.maximum(lo - ly, ly - hi)
    n = len(s)
    qhat = float(np.quantile(s, min(1.0, np.ceil((n + 1) * (1 - alpha)) / n)))
    rows = []
    for scope, d in ((f"보정 표본 {calib_years[0]}~{calib_years[1]}", cv), ("2025", fin)):
        y = d["target_cells"].to_numpy()
        l0, h0 = d["q10"].to_numpy(), d["q90"].to_numpy()
        l1 = np.clip(10 ** (np.log10(l0 + 1) - qhat) - 1, 0, None)
        h1 = 10 ** (np.log10(h0 + 1) + qhat) - 1
        rows.append(
            {
                "구간": scope,
                "n": len(d),
                "보정": "전",
                "PICP80": picp(y, l0, h0),
                "MPIW80_log": mpiw(l0, h0, log=True),
                "MPIW80_raw": mpiw(l0, h0, log=False),
            }
        )
        rows.append(
            {
                "구간": scope,
                "n": len(d),
                "보정": f"CQR 후 (q̂={qhat:.3f} log10)",
                "PICP80": picp(y, l1, h1),
                "MPIW80_log": mpiw(l1, h1, log=True),
                "MPIW80_raw": mpiw(l1, h1, log=False),
            }
        )
    return pd.DataFrame(rows), {
        "alpha": alpha,
        "qhat_log10": qhat,
        "n_calib": n,
        "calib_years": list(calib_years),
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    o, thr = load_oof()
    EVAL.mkdir(parents=True, exist_ok=True)
    t10 = transition_table(o, thr, T10K)
    t1 = transition_table(o, thr, T1K)
    (EVAL / "tbl_transitions.md").write_text(
        "# 상태 전환 구간 평가 (base_date 상태 → target_date 상태)\n\n"
        "- 경보율 = 해당 구간 샘플 중 경보를 낸 비율: 유지-초과·진입 구간에서는 **Recall**, "
        "유지-미만·이탈 구간에서는 헛경보율. "
        "B0 는 base 상태를 그대로 내므로 진입 Recall = 0, 이탈 헛경보율 = 1 이 정의상 성립.\n"
        f"- 임계: 분류기(a) {thr['clf_a']:.2f} / (b) {thr['clf_b']:.2f} / 스태킹 {thr['stack_a']:.2f} "
        "(CV OOF F1 최대, 2025 로 조정하지 않음). "
        "스태킹은 2021~ 만 OOF 존재.\n\n"
        "## 경계 10,000 cells/mL\n"
        + _md(t10)
        + "\n\n## 관심 1,000 cells/mL (회귀·q90 만 해당)\n"
        + _md(t1)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    lt, det = leadtime_table(o, thr, T10K)
    lt1, _ = leadtime_table(o, thr, T1K)
    ev = official_events(T10K)
    (EVAL / "tbl_leadtime.md").write_text(
        "# 리드타임 — 2회 연속 규칙 산출 '경계' 발령 사건 (2020~2025)\n\n"
        f"- 사건 정의: 2consec 단계가 2 미만→2 이상으로 바뀐 측정일 D, 그 직전 연속 초과의 첫 측정일 E. "
        f"총 {len(ev)}건 "
        f"({ev['station_id'].value_counts().to_dict()}).\n"
        "- 선행 탐지: E 이전 28일 이내 base_date 에서 방식이 처음 경보(≥임계)를 낸 시점. 리드 = E − "
        "base_date (B0 는 정의상 0 → 탐지 불가), "
        "D 기준 리드도 병기. 헛경보 = 경보를 냈으나 target <임계이고 14일 내 사건 시작도 없는 base_date "
        "수.\n\n"
        "## 경계(10k)\n"
        + _md(lt)
        + "\n\n## 관심(1k) 사건\n"
        + _md(lt1)
        + "\n\n## 사건별 상세(10k)\n"
        + _md(det)
        + "\n\n## 사건 목록(10k)\n"
        + _md(ev)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    op = pd.concat(
        [
            operating_points(o, "clf_a", "over_target"),
            operating_points(o, "clf_b", "over_window"),
            operating_points(o, "stack_a", "over_target"),
        ],
        ignore_index=True,
    )
    rec = op[(op["확률 소스"] == "clf_b") & (op["r(놓침/헛경보 비용)"] == 3)].iloc[0]
    (EVAL / "tbl_operating_points.md").write_text(
        "# 운영점 — 놓침/헛경보 비용비 r 별 CV 기대비용 최소 임계 → 2025 고정 평가\n\n"
        f"- **대시보드 기본 운영점 제안: 분류기(b, +4~+10일 창) r=3 → 임계 {rec['CV 최적 임계']:.2f}** "
        f"(2025 Recall {rec['Recall']:.2f}, Precision {rec['Precision']:.2f}, "
        f"진입 Recall {rec['진입 Recall']:.2f}). 근거: 경계 발령 시 고도정수·취수 조정 비용보다 "
        "미탐지(발령 후 대응) 비용이 크고(리드타임 상실), r=5 는 헛경보가 급증해 운영 피로를 유발. r 은 "
        "config/model.yaml operating_point 로 조정 가능.\n\n" + _md(op) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    cq_all, meta_all = cqr(o, calib_years=(2020, 2024))
    cq_recent, meta = cqr(o, calib_years=(2023, 2024))  # 채택: 직전 2개년 보정(사전 규칙, 2025 미참조)
    cq = pd.concat(
        [cq_all.assign(보정표본="2020~2024"), cq_recent.assign(보정표본="2023~2024")], ignore_index=True
    )
    (EVAL / "tbl_cqr.md").write_text(
        "# 분위 구간 보정 — Conformalized Quantile Regression (CV OOF 로 보정량 적합, 2025 고정 평가)\n\n"
        f"- α=0.2(80% 구간). 보정량 q̂: 전체(2020~24) {meta_all['qhat_log10']:.3f} / "
        f"직전 2개년(2023~24) {meta['qhat_log10']:.3f} (log10).\n"
        "- **채택: 직전 2개년 보정** — '보정 표본은 직전 2개년' 규칙을 사전에 두어 2025 를 참조하지 않음. "
        "2025 PICP 가 0.78~0.82 를 벗어나면 그대로 보고.\n\n" + _md(cq) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    cfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))
    cfg["operating_point"] = {
        "prob_source": "clf_b",
        "cost_ratio": 3,
        "threshold": float(rec["CV 최적 임계"]),
    }
    cfg["cqr"] = meta
    (CONFIG_DIR / "model.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8"
    )
    print(
        t10[t10["구간"] == "2025"][
            [
                "방식",
                "n",
                "전체 F1",
                "진입(onset) n",
                "진입(onset) 경보율",
                "이탈(offset) 경보율",
                "유지-미만 경보율",
            ]
        ]
        .round(3)
        .to_string(index=False)
    )
    print(lt.round(3).to_string(index=False))
    print(cq.round(3).to_string(index=False))
    print(json.dumps(cfg["operating_point"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
