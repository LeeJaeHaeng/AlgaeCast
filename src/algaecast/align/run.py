"""make align 진입점: 일 단위 달력 조인, 결측 전략 S1/S2/S3 (T3-a, docs/03 2~3절).

지점별 일 달력(2012-01-01~오늘)에
- 수문: 1차 시설(보 자체 = facility_kwater_code / 회남 = 대청댐 facility_dam_code) ``fac_*``
  + 상류 본댐 합산 ``dam_*``
  + DataON/WAMIS 연속 수위 ``level_cont_*``
- 기상: ``sites.yaml asos_by_var`` 관측소별 변수 (ta/rn/ws/hm/ss/si)
- 예보: 발표일 행에 당일 발표분 요약 ``fc_*`` (issued_at 날짜 = 행 날짜 → as_of 규칙 자동 충족)
- 수질: 측정일에만 값 (``is_obs``)
을 조인하고, 결측 플래그(``<var>_missing``)를 전략과 무관하게 유지한 뒤 전략별로 채운다.
- S1: 수질 LOCF + days_since_obs; 수문·기상 ≤3일 전진채움, 그 이상은 같은 달 **과거** 중앙값
- S2: 수질 과거 2점 사이 선형보간(측정일 사이 구간만; base_date 가 측정일일 때만 무누수 —
  features/run 이 검사), 나머지 S1 과 동일
- S3: 수질 측정행의 결측을 IterativeImputer(BayesianRidge) 로 보완하되 **연도별 과거 창**으로만 학습,
  이후 LOCF
출력: data/interim/daily_<station_id>_<S>.parquet
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

import numpy as np
import pandas as pd
import yaml

from algaecast.config import CONFIG_DIR, DATA_DIR, RAW_DIR

log = logging.getLogger(__name__)
INTERIM = DATA_DIR / "interim"
STRATEGIES = ("S1", "S2", "S3")

WQ_MAP = {
    "iem_wtrtp": "wtemp",
    "iem_ph": "ph",
    "iem_doc": "do",
    "iem_tur": "turb",
    "iem_trp": "transp",
    "iem_chla": "chla",
    "iem_bgalage_cell_co": "cells",
    "iem_geosm": "geosmin",
    "iem_mib2": "mib",
}
WQ_COLS = list(WQ_MAP.values())
HYDRO_SRC_PRIORITY = {"bundle_wamis": 0, "kwater_sluice_delist": 1, "wamis_mn_dtdata": 2, "kwater_damapi": 3}
FAC_VARS = {
    "iqty": "fac_inflow",
    "tdqty": "fac_outflow",
    "rwl": "fac_level",
    "rsvwtqy": "fac_storage",
    "rsvwtrt": "fac_storage_rate",
    "rf": "fac_rain",
}
DAM_VARS = {
    "iqty": "dam_inflow",
    "tdqty": "dam_outflow",
    "rsvwtqy": "dam_storage",
    "rsvwtrt": "dam_storage_rate",
}
WX_VARS = {
    "ta": ["avg_ta", "max_ta", "min_ta"],
    "rn": ["sum_rn"],
    "ws": ["avg_ws", "max_ws"],
    "hm": ["avg_rhm"],
    "ss": ["sum_ss_hr"],
    "si": ["sum_gsr"],
}
WX_RENAME = {
    "avg_ta": "ta_mean",
    "max_ta": "ta_max",
    "min_ta": "ta_min",
    "sum_rn": "rn",
    "avg_ws": "ws_mean",
    "max_ws": "ws_max",
    "avg_rhm": "hm",
    "sum_ss_hr": "ss",
    "sum_gsr": "si",
}
NUM_FILL_COLS = (
    list(FAC_VARS.values()) + list(DAM_VARS.values()) + list(WX_RENAME.values()) + ["level_cont_anom"]
)


def load_cfg() -> tuple[dict, dict]:
    sites = yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))
    feats = yaml.safe_load((CONFIG_DIR / "features.yaml").read_text(encoding="utf-8"))
    return sites, feats


# ---------------------------------------------------------------- 원천 적재
def load_sources() -> dict[str, pd.DataFrame]:
    algae = pd.read_parquet(RAW_DIR / "nier_algae" / "nier_algae_2012_2026.parquet")
    algae["obs_date"] = pd.to_datetime(algae["obs_date"])
    asos = pd.read_parquet(RAW_DIR / "kma_asos" / "kma_asos_daily_2012_2026.parquet")
    asos["obs_date"] = pd.to_datetime(asos["obs_date"])
    hydro = pd.read_parquet(RAW_DIR / "hydro" / "hydro_daily_long.parquet")
    hydro["obs_date"] = pd.to_datetime(hydro["obs_date"])
    hydro["prio"] = hydro["source"].map(HYDRO_SRC_PRIORITY).fillna(9)
    hydro = hydro.sort_values("prio").drop_duplicates(["facility_code", "variable", "obs_date"], keep="first")
    out = {"algae": algae, "asos": asos, "hydro": hydro}
    cont = RAW_DIR / "dataon" / "level_continuous_long.parquet"
    if cont.exists():
        c = pd.read_parquet(cont)
        c["obs_date"] = pd.to_datetime(c["obs_date"])
        out["level_cont"] = c
    fc_dir = RAW_DIR / "kma_forecast"
    if fc_dir.exists() and any(fc_dir.glob("*.csv")):
        from algaecast.collect.kma_forecast import load_all

        out["forecast"] = load_all(fc_dir)
    return out


def hydro_wide(hydro: pd.DataFrame, facility_code: str) -> pd.DataFrame:
    h = hydro[hydro["facility_code"] == facility_code]
    return h.pivot_table(index="obs_date", columns="variable", values="value")


def forecast_daily(fc: pd.DataFrame, site_code: str, cfg: dict) -> pd.DataFrame:
    """발표일(issued_at 날짜) 행에 +1~+7일 예보 요약.

    단기(ta_mean/ta_max/rn_sum/pop_max) + 중기(ta_min/ta_max/pop_max).
    """
    f = fc[fc["site_code"] == site_code].copy()
    if f.empty:
        return pd.DataFrame()
    f["issue_date"] = f["issued_at"].dt.tz_convert("Asia/Seoul").dt.normalize().dt.tz_localize(None)
    f["lead"] = (pd.to_datetime(f["target_date"]) - f["issue_date"]).dt.days
    f = f[f["lead"].between(1, 7)]
    rows = []
    for d, g in f.groupby("issue_date"):
        p = g.pivot_table(index="lead", columns="variable", values="value", aggfunc="mean")
        rows.append(
            {
                "obs_date": d,
                "fc_ta_mean_d1_7": (
                    p["ta_mean"].mean()
                    if "ta_mean" in p
                    else (
                        p[["ta_max", "ta_min"]].mean(axis=1).mean()
                        if {"ta_max", "ta_min"} <= set(p.columns)
                        else np.nan
                    )
                ),
                "fc_ta_max_d1_7": p["ta_max"].mean() if "ta_max" in p else np.nan,
                "fc_rn_sum_d1_7": p["rn_sum"].sum() if "rn_sum" in p else np.nan,
                "fc_pop_mean_d1_7": p["pop_max"].mean() if "pop_max" in p else np.nan,
                "fc_rain_days": (
                    int((p["pop_max"] >= cfg["forecast"]["pop_rain_day"]).sum()) if "pop_max" in p else np.nan
                ),
                "fc_n_leads": int(p.shape[0]),
            }
        )
    return pd.DataFrame(rows).set_index("obs_date")


# ---------------------------------------------------------------- 지점 달력 조립
def build_site_daily(
    site: dict,
    src: dict[str, pd.DataFrame],
    sites_cfg: dict,
    feat_cfg: dict,
    end: date,
    *,
    start: date | None = None,
    level_means: dict[str, float] | None = None,
) -> pd.DataFrame:
    """지점 일 달력 조립.

    ``start``(기본 calendar.start)·``level_means``(관측소별 wl_adj 전기간 평균, 증분 모드) 선택.
    """
    sid = site["station_id"]
    days = pd.date_range(start or feat_cfg["calendar"]["start"], pd.Timestamp(end))
    df = pd.DataFrame(index=days)
    df.index.name = "obs_date"
    # 수질 (측정일만)
    a = src["algae"][src["algae"]["station_id"] == sid].set_index("obs_date").sort_index()
    for src_col, dst in WQ_MAP.items():
        df[dst] = a[src_col].reindex(days)
    df["genus"] = a["dominant_genus"].reindex(days)
    df["alert_level"] = a["alert_level_2consec"].astype("float").reindex(days)
    df["is_obs"] = df.index.isin(a.index)
    # 수문 1차 시설
    hydro = src["hydro"]
    fac_code = site.get("facility_dam_code")
    if not fac_code:
        kw = site.get("facility_kwater_code")
        m = hydro.loc[hydro["kwater_code"] == kw, "facility_code"]
        fac_code = m.iloc[0] if len(m) else None
    if fac_code is not None:
        hw = hydro_wide(hydro, fac_code)
        for v, dst in FAC_VARS.items():
            df[dst] = hw[v].reindex(days) if v in hw else np.nan
    else:
        for dst in FAC_VARS.values():
            df[dst] = np.nan
    # 상류 본댐 합산
    main = {k for k, v in sites_cfg["dams"].items() if v.get("role") == "main"}
    dams = [d for d in site.get("upstream_dams", []) if d in main]
    parts = [hydro_wide(hydro, d) for d in dams]
    parts = [p for p in parts if not p.empty]
    if parts:
        st = pd.concat(parts, keys=range(len(parts)))
        g = st.groupby(level=1)
        for v, dst in DAM_VARS.items():
            if v in st.columns:
                agg = g[v].mean() if dst == "dam_storage_rate" else g[v].sum(min_count=1)
                df[dst] = agg.reindex(days)
            else:
                df[dst] = np.nan
    else:
        for dst in DAM_VARS.values():
            df[dst] = np.nan
    df["dam_n"] = len(parts)
    # 연속 수위 (DataON+WAMIS, use:true): 관측소별 평균 제거 후 지점 평균 편차
    if "level_cont" in src:
        codes = [
            str(e["code"])
            for e in site.get("dataon_stations", [])
            if isinstance(e, dict) and e.get("use", True)
        ]
        c = src["level_cont"][src["level_cont"]["station_code"].isin(codes)]
        if len(c):
            w = c.pivot_table(index="obs_date", columns="station_code", values="wl_adj")
            means = (
                pd.Series({k: level_means.get(str(k), w[k].mean()) for k in w.columns})
                if level_means
                else w.mean()
            )
            df["level_cont_anom"] = (w - means).mean(axis=1).reindex(days)
            df["level_cont_n"] = w.notna().sum(axis=1).reindex(days).fillna(0)
    if "level_cont_anom" not in df:
        df["level_cont_anom"] = np.nan
        df["level_cont_n"] = 0
    # 기상 (asos_by_var)
    by_var = site.get("asos_by_var", {})
    asos = src["asos"]
    for var, cols in WX_VARS.items():
        stn = by_var.get(var, "primary")
        stn = int(site["asos_primary"]) if stn == "primary" else int(stn)
        a_ = asos[asos["stn_id"] == stn].set_index("obs_date")
        for c in cols:
            df[WX_RENAME[c]] = a_[c].reindex(days) if c in a_ else np.nan
    # 예보 (발표일 행)
    fc_cols = [
        "fc_ta_mean_d1_7",
        "fc_ta_max_d1_7",
        "fc_rn_sum_d1_7",
        "fc_pop_mean_d1_7",
        "fc_rain_days",
        "fc_n_leads",
    ]
    if "forecast" in src:
        fd = forecast_daily(src["forecast"], site["site_code"], feat_cfg)
        for c in fc_cols:
            df[c] = fd[c].reindex(days) if c in fd else np.nan
    else:
        for c in fc_cols:
            df[c] = np.nan
    df["fc_available"] = df["fc_n_leads"].notna().astype(int)
    # 결측 플래그 (전략 무관)
    for c in NUM_FILL_COLS:
        df[f"{c}_missing"] = df[c].isna().astype(int)
    df["cells_missing"] = (df["is_obs"] & df["cells"].isna()).astype(int)
    df["station_id"] = sid
    df["site_code"] = site["site_code"]
    return df.reset_index()


# ---------------------------------------------------------------- 결측 전략
def past_month_median_fill(s: pd.Series, dates: pd.Series, limit: int) -> pd.Series:
    """≤limit 일 전진채움 후, 남은 결측은 같은 달의 **과거(직전 연도까지)** 중앙값으로 채운다."""
    out = s.ffill(limit=limit)
    if out.isna().any():
        month = dates.dt.month.to_numpy()
        year = dates.dt.year.to_numpy()
        vals = s.to_numpy()
        hist: dict[tuple[int, int], float] = {}
        for y in np.unique(year):
            past = (year < y) & ~np.isnan(vals)
            for m in range(1, 13):
                sel = past & (month == m)
                hist[(y, m)] = float(np.median(vals[sel])) if sel.any() else np.nan
        fill = np.array([hist[(y, m)] for y, m in zip(year, month, strict=True)])
        out = out.where(out.notna(), pd.Series(fill, index=out.index))
    return out


def apply_strategy(df: pd.DataFrame, strategy: str, feat_cfg: dict) -> pd.DataFrame:
    d = df.copy()
    limit = feat_cfg["imputation"]["hydro_weather_ffill_limit_days"]
    dates = pd.to_datetime(d["obs_date"])
    for c in NUM_FILL_COLS:
        if c in d:
            d[c] = past_month_median_fill(d[c], dates, limit)
    obs_dates = dates.where(d["is_obs"])
    d["days_since_obs"] = (dates - obs_dates.ffill()).dt.days
    for c in WQ_COLS + ["genus", "alert_level"]:
        d[f"{c}_obs"] = d[c]  # 측정일 원값 보존 (AR 피처·타깃은 이것만 사용, S3 보완값 제외)
    if strategy == "S3":
        d = s3_impute_measurements(d, feat_cfg)
    for c in WQ_COLS + ["genus", "alert_level"]:
        if strategy == "S2" and c in WQ_COLS:
            d[c] = d[c].interpolate(method="linear", limit_area="inside")
        else:
            d[c] = d[c].ffill()
    d["strategy"] = strategy
    return d


def s3_impute_measurements(d: pd.DataFrame, feat_cfg: dict) -> pd.DataFrame:
    """측정행(is_obs)의 수질 결측을 IterativeImputer 로 보완. 연도별로 **그 해 이전** 측정행만으로 학습."""
    from sklearn.experimental import enable_iterative_imputer  # noqa: F401
    from sklearn.impute import IterativeImputer
    from sklearn.linear_model import BayesianRidge

    d = d.copy()
    obs = d[d["is_obs"]].copy()
    if obs.empty:
        return d
    obs["cells_log"] = np.log10(obs["cells"].astype(float) + 1)
    obs["ta_ma7"] = d["ta_mean"].rolling(7, min_periods=3).mean().reindex(obs.index)
    mo = pd.to_datetime(obs["obs_date"]).dt.month
    obs["month_sin"], obs["month_cos"] = np.sin(2 * np.pi * mo / 12), np.cos(2 * np.pi * mo / 12)
    cols = [c for c in feat_cfg["imputation"]["s3_features"] if c in obs]
    years = pd.to_datetime(obs["obs_date"]).dt.year
    min_rows = feat_cfg["imputation"]["s3_min_train_rows"]
    for y in sorted(years.unique()):
        train = obs[years < y]
        cur = obs[years == y]
        if len(train) < min_rows or not cur[cols].isna().any().any():
            continue
        imp = IterativeImputer(
            estimator=BayesianRidge(),
            max_iter=10,
            random_state=42,
            sample_posterior=False,
            keep_empty_features=True,
        )
        imp.fit(train[cols])
        filled = pd.DataFrame(imp.transform(cur[cols]), index=cur.index, columns=cols)
        for c in cols:
            if c == "cells_log":
                target = "cells"
                vals = 10 ** filled[c] - 1
            else:
                target = c
                vals = filled[c]
            if target in WQ_COLS:
                mask = cur[target].isna()
                d.loc[cur.index[mask], target] = vals[mask].clip(lower=0).to_numpy()
    return d


# ---------------------------------------------------------------- 진입점
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strategy", default="S1,S2,S3", help="쉼표 구분 (S1,S2,S3)")
    ap.add_argument("--end", type=date.fromisoformat, default=date.today())
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    strategies = [s.strip().upper() for s in args.strategy.split(",") if s.strip()]
    bad = set(strategies) - set(STRATEGIES)
    if bad:
        raise SystemExit(f"알 수 없는 전략 {bad}")
    sites_cfg, feat_cfg = load_cfg()
    src = load_sources()
    INTERIM.mkdir(parents=True, exist_ok=True)
    rows = []
    for site in sites_cfg["sites"]:
        base = build_site_daily(site, src, sites_cfg, feat_cfg, args.end)
        for s in strategies:
            d = apply_strategy(base, s, feat_cfg)
            out = INTERIM / f"daily_{site['station_id']}_{s}.parquet"
            d.to_parquet(out, index=False)
            rows.append(
                {
                    "지점": site["station_id"],
                    "전략": s,
                    "일수": len(d),
                    "측정일": int(d["is_obs"].sum()),
                    "fac_inflow 결측%": round(100 * base["fac_inflow"].isna().mean(), 1),
                    "dam_inflow 결측%": round(100 * base["dam_inflow"].isna().mean(), 1),
                    "ta 결측%": round(100 * base["ta_mean"].isna().mean(), 1),
                    "si 결측%": round(100 * base["si"].isna().mean(), 1),
                    "예보 보유일": int(base["fc_available"].sum()),
                    "wtemp 채움후 결측%": round(100 * d["wtemp"].isna().mean(), 1),
                }
            )
            log.info("%s %s → %s (%d행)", site["station_id"], s, out.name, len(d))
    rep = pd.DataFrame(rows)
    print(rep.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
