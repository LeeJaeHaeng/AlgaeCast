"""Supabase 업로드 (T6): service_role 키로 upsert. 대시보드는 읽기 전용.

적재 대상
- sites(seed 와 동일 upsert), stations(asos/dam/weir/wq 매핑)
- observations(전체 수질 측정), hydrology_daily·weather_daily(최근 730일, interim S1 달력)
- model_runs(이번 run), predictions(2025 홀드아웃 OOF 전부 + 2026 test 조합 + 최신 as-of 예측;
tier/flag/CQR/p_alert 포함)
- shap_contributions(최신 as-of, 지점별 상위 8), recommendations(최신 as-of 우선순위),
model_metrics(2025 홀드아웃·CV)
- bloom_events(tbl_leadtime 상세), transition_metrics(tbl_transitions)
사용: python -m algaecast.db.upload [--days 730] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd
import yaml

from algaecast.collect.base import KST
from algaecast.config import CONFIG_DIR, DATA_DIR, ROOT, get_env
from algaecast.eval import decision as DEC
from algaecast.eval.transitions import T10K, leadtime_table, load_oof, official_events, transition_table
from algaecast.models import data as D
from algaecast.models.registry import current_versions, load_current

log = logging.getLogger(__name__)
INTERIM = DATA_DIR / "interim"
BATCH = 1000
SEG_MAP = {
    "유지-미만": "stay_below",
    "유지-초과": "stay_above",
    "진입(onset)": "onset",
    "이탈(offset)": "offset",
}


def client() -> Any:
    from supabase import create_client

    url = get_env("SUPABASE_URL", required=True)
    key = get_env("SUPABASE_SERVICE_ROLE_KEY", required=True)
    return create_client(url, key)


INT_COLS = {
    "horizon_days", "pred_alert_level", "alert_level", "rank", "priority_rank", "n",
    "lead_days_watch_e", "lead_days_alert_e", "lead_days_watch_d", "lead_days_alert_d",
}  # fmt: skip


def _clean(df: pd.DataFrame) -> list[dict]:
    d = df.replace({np.nan: None})
    for c in d.columns:
        if c in INT_COLS:
            d[c] = d[c].map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else int(v))
        if d[c].dtype.kind == "M" or c.endswith("_date") or c == "obs_date":
            d[c] = d[c].map(
                lambda v: v.isoformat()[:10] if isinstance(v, (pd.Timestamp, datetime, date)) else v
            )

    def fix(v: object) -> object:
        if isinstance(v, (np.floating, float)):
            return None if not np.isfinite(float(v)) else float(v)
        if isinstance(v, np.integer):
            return int(v)
        if isinstance(v, np.bool_):
            return bool(v)
        return v

    def fix_int(k: str, v: object) -> object:
        v = fix(v)
        return int(v) if (k in INT_COLS and v is not None) else v

    return [{k: fix_int(k, v) for k, v in r.items()} for r in d.to_dict("records")]


def upsert(sb: Any, table: str, rows: list[dict], on_conflict: str | None, dry: bool) -> int:
    if dry or not rows:
        return len(rows)
    for i in range(0, len(rows), BATCH):
        q = sb.table(table)
        if on_conflict:
            q.upsert(rows[i : i + BATCH], on_conflict=on_conflict).execute()
        else:
            q.insert(rows[i : i + BATCH]).execute()
    return len(rows)


# ---------------------------------------------------------------- 원천 테이블
def sites_rows(cfg: dict) -> list[dict]:
    rows = []
    for st in cfg["sites"]:
        dam = st.get("facility_dam_code")
        spec = cfg["dams"].get(dam or "", {}) or cfg["weirs"].get(st.get("facility_kwater_code") or "", {})
        rows.append(
            {
                "site_id": st["site_code"],
                "name": st["name"],
                "basin": st["basin"],
                "facility_type": "dam" if dam else "weir",
                "facility_name": (cfg["dams"][dam]["name"] + "댐") if dam else st.get("facility"),
                "lat": st["lat"],
                "lon": st["lon"],
                "intake_weight": st.get("intake_weight", 0.5),
                "intake_capacity_tpd": st.get("intake_capacity_tpd"),
                "catchment_area_km2": spec.get("catchment_km2"),
                "meta": {"station_id": st["station_id"]},
            }
        )
    return rows


def stations_rows(cfg: dict) -> list[dict]:
    rows = []
    for st in cfg["sites"]:
        sid = st["site_code"]
        for c in st.get("asos_candidates", []):
            rows.append(
                {
                    "site_id": sid,
                    "kind": "asos",
                    "station_code": str(c["stn_id"]),
                    "station_name": c["name"],
                    "source": "KMA ASOS" + (" (primary)" if c["stn_id"] == st.get("asos_primary") else ""),
                }
            )
        for d in st.get("upstream_dams", []):
            rows.append(
                {
                    "site_id": sid,
                    "kind": "dam",
                    "station_code": d,
                    "station_name": cfg["dams"].get(d, {}).get("name"),
                    "source": "WAMIS/K-water",
                }
            )
        if st.get("facility_kwater_code"):
            rows.append(
                {
                    "site_id": sid,
                    "kind": "weir",
                    "station_code": st["facility_kwater_code"],
                    "station_name": st.get("facility"),
                    "source": "K-water delist",
                }
            )
        rows.append(
            {
                "site_id": sid,
                "kind": "wq",
                "station_code": sid,
                "station_name": st["name"],
                "source": "NIER 조류경보제",
            }
        )
    return rows


def observations_rows(cfg: dict) -> list[dict]:
    a = pd.read_parquet(DATA_DIR / "raw" / "nier_algae" / "nier_algae_2012_2026.parquet")
    df = pd.DataFrame(
        {
            "site_id": a["site_code"],
            "obs_date": pd.to_datetime(a["obs_date"]),
            "cell_count": a["iem_bgalage_cell_co"],
            "water_temp": a["iem_wtrtp"],
            "ph": a["iem_ph"],
            "do_mgl": a["iem_doc"],
            "turbidity": a["iem_tur"],
            "transparency": a["iem_trp"],
            "chla": a["iem_chla"],
            "dominant_genus": a["dominant_genus"],
            "alert_level": pd.to_numeric(a["alert_level_2consec"], errors="coerce").clip(0, 3),
            "source": "NIER 조류경보제 API",
            "fetched_at": a["fetched_at"].astype(str),
        }
    )
    df = df.drop_duplicates(["site_id", "obs_date"], keep="last")
    return _clean(df)


def daily_rows(cfg: dict, days: int) -> tuple[list[dict], list[dict]]:
    hy, wx = [], []
    cutoff = pd.Timestamp(date.today()) - pd.Timedelta(days=days)
    for st in cfg["sites"]:
        d = pd.read_parquet(INTERIM / f"daily_{st['station_id']}_S1.parquet")
        d["obs_date"] = pd.to_datetime(d["obs_date"])
        d = d[d["obs_date"] >= cutoff]
        hy.append(
            pd.DataFrame(
                {
                    "site_id": st["site_code"],
                    "obs_date": d["obs_date"],
                    "rainfall_mm": d["fac_rain"],
                    "inflow_cms": d["fac_inflow"],
                    "outflow_cms": d["fac_outflow"],
                    "storage_mcm": d["fac_storage"],
                    "storage_rate": d["fac_storage_rate"],
                    "water_level": d["level_cont_anom"],
                    "weir_level": d["fac_level"],
                    "source": "K-water delist/WAMIS/DataON (S1 보간)",
                }
            )
        )
        wx.append(
            pd.DataFrame(
                {
                    "site_id": st["site_code"],
                    "obs_date": d["obs_date"],
                    "ta_mean": d["ta_mean"],
                    "ta_max": d["ta_max"],
                    "ta_min": d["ta_min"],
                    "rn_sum": d["rn"],
                    "ws_mean": d["ws_mean"],
                    "hm_mean": d["hm"],
                    "ss_sum": d["ss"],
                    "si_sum": d["si"],
                    "fc_ta_mean_d1_7": d["fc_ta_mean_d1_7"],
                    "fc_rn_sum_d1_7": d["fc_rn_sum_d1_7"],
                    "source": "KMA ASOS (asos_by_var) / 단기·중기예보",
                }
            )
        )
    return _clean(pd.concat(hy)), _clean(pd.concat(wx))


# ---------------------------------------------------------------- 예측
def predict_registry(feat: pd.DataFrame, cols_hint: list[str] | None = None) -> pd.DataFrame:
    """레지스트리 current(회귀 앙상블/단일 · 분류기 b · 분위)로 feat 행 예측 → q10/q50/q90(+CQR), "
    "p_alert, tier."""
    reg, _ = load_current("regression")
    clf, _ = load_current("classifier")
    qm, _ = load_current("quantile")
    mcfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))
    qhat = mcfg.get("cqr", {}).get("qhat_log10", 0.0)
    op = mcfg.get("operating_point", {"prob_source": "clf_b", "cost_ratio": 3, "threshold": 0.5})
    cols, cats = reg["cols"], reg["cats"]

    def prep(X: pd.DataFrame, categories: dict) -> pd.DataFrame:
        X = X[cols].copy()
        for c in cats:
            X[c] = pd.Categorical(X[c].astype(str), categories=categories[c])
        return X

    X = prep(feat, reg["categories"])
    if reg.get("kind") == "ensemble":
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
        pred = np.clip(10**z - 1, 0, None)
    else:
        pred = np.clip(10 ** np.clip(reg["model"].predict(X), 0, 7) - 1, 0, None) * reg["smear"]
    Xq = prep(feat, qm.get("categories", reg["categories"]))
    lp = {q: np.asarray(m.predict(Xq), dtype=float) for q, m in qm["models"].items()}
    lo, hi = np.minimum(lp[0.1], lp[0.9]), np.maximum(lp[0.1], lp[0.9])
    mid = np.clip(lp[0.5], lo, hi)
    q10, q50, q90 = (np.clip(10 ** np.clip(v, 0, 7) - 1, 0, None) for v in (lo, mid, hi))
    q10c = np.clip(10 ** (np.log10(q10 + 1) - qhat) - 1, 0, None)
    q90c = 10 ** (np.log10(q90 + 1) + qhat) - 1
    Xc = prep(feat, clf["categories"])
    p_alert = clf["model"].predict_proba(Xc)[:, 1]
    watch = q90c >= T10K
    alert = p_alert >= op["threshold"]
    tier = np.where(alert, "alert", np.where(watch, "watch", "normal"))
    return pd.DataFrame(
        {
            "pred_cell_count": pred,
            "pred_log": np.log10(pred + 1),
            "q10": q10,
            "q50": q50,
            "q90": q90,
            "q10_cqr": q10c,
            "q90_cqr": q90c,
            "p_alert": p_alert,
            "watch_flag": watch,
            "alert_flag": alert,
            "tier": tier,
            "operating_point": [json.dumps({**op, "watch_rule": "q90_cqr>=10000"})] * len(feat),
        },
        index=feat.index,
    )


def level_of(cells: np.ndarray) -> np.ndarray:
    return np.select([cells >= 1_000_000, cells >= 10_000, cells >= 1_000], [3, 2, 1], 0)


def predictions_rows(
    run_id: str, cfg: dict, oof: pd.DataFrame, mcfg: dict
) -> tuple[list[dict], pd.DataFrame]:
    sid_map = {s["station_id"]: s["site_code"] for s in cfg["sites"]}
    qhat = mcfg.get("cqr", {}).get("qhat_log10", 0.0)
    op = mcfg.get("operating_point", {"threshold": 0.5})
    rows = []
    # (1) 2025 홀드아웃 OOF 전부
    f = oof[oof["year"] == 2025].copy()
    q10c = np.clip(10 ** (np.log10(f["q10"] + 1) - qhat) - 1, 0, None)
    q90c = 10 ** (np.log10(f["q90"] + 1) + qhat) - 1
    f_rows = pd.DataFrame(
        {
            "run_id": run_id,
            "site_id": f["station_id"].map(sid_map),
            "base_date": f["base_date"],
            "target_date": f["target_date"],
            "horizon_days": (pd.to_datetime(f["target_date"]) - pd.to_datetime(f["base_date"])).dt.days,
            "pred_cell_count": f["ens"],
            "pred_log": np.log10(f["ens"] + 1),
            "q10": f["q10"],
            "q50": f["q50"],
            "q90": f["q90"],
            "q10_cqr": q10c,
            "q90_cqr": q90c,
            "p_over_10k": f["clf_a"],
            "p_alert": f["clf_b"],
            "watch_flag": q90c >= T10K,
            "alert_flag": f["clf_b"] >= op["threshold"],
            "pred_alert_level": level_of(f["ens"].to_numpy()),
            "obs_cell_count": f["target_cells"],
        }
    )
    f_rows["tier"] = np.where(
        f_rows["alert_flag"], "alert", np.where(f_rows["watch_flag"], "watch", "normal")
    )
    f_rows["operating_point"] = json.dumps({**op, "watch_rule": "q90_cqr>=10000", "note": "2025 holdout OOF"})
    f_rows["horizon_days"] = f_rows["horizon_days"].astype(int)
    f_rows["pred_alert_level"] = f_rows["pred_alert_level"].astype(int)
    rows += _clean(f_rows)
    # (2) 2026 test 조합 + (3) 최신 as-of (각 지점 마지막 base_date) — 레지스트리 모델
    feat = pd.read_parquet(D.PROCESSED / "features_S1.parquet")
    feat["base_date"] = pd.to_datetime(feat["base_date"])
    feat["target_date"] = pd.to_datetime(feat["target_date"])
    test = feat[feat["split"] == "test"]
    latest = feat.sort_values("base_date").groupby("station_id", observed=True).tail(1)
    sel = pd.concat([test, latest]).drop_duplicates(["station_id", "base_date"])
    pr = predict_registry(sel)
    t_rows = pd.DataFrame(
        {
            "run_id": run_id,
            "site_id": sel["site_code"].astype(str),
            "base_date": sel["base_date"],
            "target_date": sel["target_date"].fillna(sel["base_date"] + pd.Timedelta(days=7)),
            "horizon_days": sel["horizon_days"].fillna(7),
        }
    )
    for c in pr.columns:
        t_rows[c] = pr[c].to_numpy()
    t_rows["pred_alert_level"] = level_of(t_rows["pred_cell_count"].to_numpy()).astype(int)
    t_rows["horizon_days"] = t_rows["horizon_days"].astype(int)
    t_rows["p_over_10k"] = None
    t_rows["obs_cell_count"] = None  # 2026 실측은 backfill_obs 가 채움 (test 타깃 격리 준수)
    rows += _clean(t_rows)
    return rows, latest


def shap_and_reco_rows(run_id: str, cfg: dict, latest: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    import shap

    reg, _ = load_current("regression")
    clf, _ = load_current("classifier")
    c1 = reg["members"]["회귀 C1(smearing)"] if reg.get("kind") == "ensemble" else reg
    cols, cats = c1["cols"], c1["cats"]
    X = latest[cols].copy()
    for c in cats:
        X[c] = pd.Categorical(X[c].astype(str), categories=c1["categories"][c])
    sv = pd.DataFrame(shap.TreeExplainer(c1["model"]).shap_values(X), columns=cols, index=latest.index)
    pr = predict_registry(latest)
    shap_rows, reco = [], []
    for i, r in latest.iterrows():
        s = sv.loc[i]
        top = s.abs().sort_values(ascending=False).head(8)
        for rank, fname in enumerate(top.index, 1):
            fv = r[fname]
            shap_rows.append(
                {
                    "run_id": run_id,
                    "site_id": r["site_code"],
                    "base_date": r["base_date"],
                    "feature_name": fname,
                    "feature_group": DEC.group_of(fname),
                    "shap_value": float(s[fname]),
                    "feature_value": (
                        float(fv)
                        if isinstance(fv, (int, float, np.floating, np.integer)) and np.isfinite(float(fv))
                        else None
                    ),
                    "rank": rank,
                }
            )
    sids = latest["station_id"].astype(str).to_numpy()
    p = pd.Series(pr["p_alert"].to_numpy(), index=sids)
    tier_s = pd.Series(pr["tier"].to_numpy(), index=sids)
    prio = DEC.deployment_priority(p, tier=tier_s)  # 단계 → p_alert 내림차순, 가중치 미사용
    sid_map = {s["station_id"]: s["site_code"] for s in cfg["sites"]}
    base_by_sid = dict(zip(latest["station_id"].astype(str), latest["base_date"], strict=True))
    for k, r in prio.iterrows():
        row_idx = latest.index[latest["station_id"].astype(str) == r["station_id"]][0]
        sentence = DEC.explain_sentence(sv.loc[row_idx])
        action = {"alert": "deploy_remover", "watch": "monitor", "normal": "monitor"}[r["tier"]]
        reco.append(
            {
                "run_id": run_id,
                "site_id": sid_map[r["station_id"]],
                "base_date": base_by_sid[r["station_id"]],
                "priority_score": float(r["우선도"]),
                "priority_rank": int(k + 1),
                "action": action,
                "rationale_ko": (
                    f"[{ {'alert': '경보', 'watch': '감시', 'normal': '정상'}[r['tier']] }] {r['권고']} — "
                    f"p_alert {r['p_over_10k']:.2f}. {sentence}"
                ),
            }
        )
    return _clean(pd.DataFrame(shap_rows)), _clean(pd.DataFrame(reco))


def metrics_rows(run_id: str) -> list[dict]:
    rows = []
    hold = ROOT / "reports" / "eval" / "tbl_holdout_2025.md"
    if hold.exists():
        for ln in hold.read_text(encoding="utf-8").splitlines():
            if ln.startswith("| 앙상블(채택)"):
                cells = [c.strip() for c in ln.strip("|").split("|")]
                names = [
                    "rmse_log",
                    "mae_log",
                    "r2_log",
                    "r2_raw",
                    "r2_pearson_raw",
                    "nse_raw",
                    "f1_10k",
                    "f1_1k",
                ]
                for name, cell in zip(names, cells[2 : 2 + len(names)], strict=True):
                    v, lo, hi = cell.replace("[", "").replace("]", "").replace(",", "").split()
                    rows.append(
                        {
                            "run_id": run_id,
                            "split": "holdout2025",
                            "site_id": None,
                            "metric": name,
                            "value": float(v),
                            "ci_low": float(lo),
                            "ci_high": float(hi),
                        }
                    )
    mcfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))
    for k, v in mcfg["selected"].get("cv", {}).items():
        rows.append(
            {
                "run_id": run_id,
                "split": "cv",
                "site_id": None,
                "metric": k,
                "value": float(v),
                "ci_low": None,
                "ci_high": None,
            }
        )
    for k, v in (
        ("leadtime_detected_watch", 18),
        ("leadtime_events", 20),
        ("leadtime_median_days_watch_E", 14),
    ):
        rows.append(
            {
                "run_id": run_id,
                "split": "holdout2025",
                "site_id": None,
                "metric": k,
                "value": float(v),
                "ci_low": None,
                "ci_high": None,
            }
        )
    return rows


def events_rows(cfg: dict) -> list[dict]:
    o, thr = load_oof()
    ev = official_events(T10K)
    _, det = leadtime_table(o, thr, T10K)
    sid_map = {s["station_id"]: s["site_code"] for s in cfg["sites"]}
    watch = det[det["방식"] == "q90≥임계"].set_index(["지점", "E"])
    alert = det[det["방식"] == "분류기(b)"].set_index(["지점", "E"])
    rows = []
    for e in ev.itertuples():
        key = (e.station_id, e._3)
        w = watch.loc[key] if key in watch.index else None
        a = alert.loc[key] if key in alert.index else None
        rows.append(
            {
                "site_id": sid_map[e.station_id],
                "event_id": f"{e.station_id}-{e._3}",
                "first_exceed_date": e._3,
                "official_alert_date": e._2,
                "first_watch_date": None if w is None else w["첫 경보 base_date"],
                "first_alert_date": None if a is None else a["첫 경보 base_date"],
                "lead_days_watch_e": None if w is None else int(w["리드(E) 일"]),
                "lead_days_alert_e": None if a is None else int(a["리드(E) 일"]),
                "lead_days_watch_d": None if w is None else int(w["리드(D) 일"]),
                "lead_days_alert_d": None if a is None else int(a["리드(D) 일"]),
                "detected_watch": w is not None,
                "detected_alert": a is not None,
            }
        )
    return _clean(pd.DataFrame(rows))


def transition_rows() -> list[dict]:
    o, thr = load_oof()
    rows = []
    for level in (T10K, 1_000.0):
        t = transition_table(o, thr, level)
        for d in t.to_dict("records"):
            split = "cv" if str(d["구간"]).startswith("CV") else "holdout2025"
            rows.append(
                {
                    "split": split,
                    "method": d["방식"],
                    "segment": "all",
                    "threshold": level,
                    "n": int(d["n"]),
                    "recall": d["전체 Recall"],
                    "precision": d["전체 Precision"],
                    "f1": d["전체 F1"],
                    "false_alarm_rate": None,
                }
            )
            for ko, seg in SEG_MAP.items():
                n = int(d[f"{ko} n"])
                rate = d[f"{ko} 경보율"]
                pos = seg in ("onset", "stay_above")
                rows.append(
                    {
                        "split": split,
                        "method": d["방식"],
                        "segment": seg,
                        "threshold": level,
                        "n": n,
                        "recall": rate if pos else None,
                        "precision": None,
                        "f1": None,
                        "false_alarm_rate": None if pos else rate,
                    }
                )
    return _clean(pd.DataFrame(rows))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))
    mcfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))
    sb = None if args.dry_run else client()
    counts: dict[str, int] = {}
    counts["sites"] = upsert(sb, "sites", sites_rows(cfg), "site_id", args.dry_run)
    counts["stations"] = upsert(sb, "stations", stations_rows(cfg), "site_id,kind,station_code", args.dry_run)
    counts["observations"] = upsert(
        sb, "observations", observations_rows(cfg), "site_id,obs_date", args.dry_run
    )
    hy, wx = daily_rows(cfg, args.days)
    counts["hydrology_daily"] = upsert(sb, "hydrology_daily", hy, "site_id,obs_date", args.dry_run)
    counts["weather_daily"] = upsert(sb, "weather_daily", wx, "site_id,obs_date", args.dry_run)
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
        ).stdout.strip()
    except OSError:
        commit = None
    versions = current_versions()
    run = {
        "run_at": datetime.now(tz=KST).isoformat(),
        "model_name": "algaecast7-ensemble",
        "model_version": versions.get("regression", "n/a"),
        "git_commit": commit,
        "features_hash": None,
        "hyperparams": json.dumps(
            {"registry": versions, "operating_point": mcfg.get("operating_point"), "cqr": mcfg.get("cqr")}
        ),
        "status": "success",
        "notes": "T6 initial upload: 2025 holdout OOF + 2026 test combos + latest as-of",
    }
    if args.dry_run:
        run_id = "00000000-0000-0000-0000-000000000000"
    else:
        res = sb.table("model_runs").insert(run).execute()
        run_id = res.data[0]["run_id"]
    counts["model_runs"] = 1
    oof, _ = load_oof()
    pred_rows, latest = predictions_rows(run_id, cfg, oof, mcfg)
    counts["predictions"] = upsert(
        sb, "predictions", pred_rows, "run_id,site_id,base_date,target_date", args.dry_run
    )
    shap_rows, reco_rows = shap_and_reco_rows(run_id, cfg, latest)
    counts["shap_contributions"] = upsert(sb, "shap_contributions", shap_rows, None, args.dry_run)
    counts["recommendations"] = upsert(sb, "recommendations", reco_rows, None, args.dry_run)
    counts["model_metrics"] = upsert(sb, "model_metrics", metrics_rows(run_id), None, args.dry_run)
    counts["bloom_events"] = upsert(sb, "bloom_events", events_rows(cfg), "site_id,event_id", args.dry_run)
    counts["transition_metrics"] = upsert(
        sb, "transition_metrics", transition_rows(), "split,method,segment,threshold", args.dry_run
    )
    print(json.dumps({"run_id": run_id, "rows": counts}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
