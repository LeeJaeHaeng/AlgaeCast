"""as-of 예측 파이프라인 (T8): 대회 번들·모델 학습 없이 공공 API 최근 N일 증분 수집 → 일 달력 →
피처 → 동결 모델 예측.

- 수집: 조류경보제(NIER), K-water delist(보·댐), WAMIS wl_dtdata(연속 수위 관측소), ASOS, 예보 CSV(저장소)
- 연속 수위 편차는 config/level_cont_stats.json(전기간 평균·오프셋 집계값)으로 계산
- base_date = 오늘 이전 가장 최근 조류 측정일(지점별). 새 측정 없으면 해당 지점 건너뜀
- ``validate_against_bundle`` 는 로컬에서 번들 기반 features_S1 과 최근 30 base_date 의 피처 일치율을 계산
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from algaecast.align.run import apply_strategy, build_site_daily
from algaecast.collect.base import CollectError
from algaecast.collect.kma_asos import KmaAsosCollector
from algaecast.collect.kma_forecast import load_all as load_forecast
from algaecast.collect.kwater_dam import KwaterSluiceCollector, facility_catalog
from algaecast.collect.nier_algae import NierAlgaeCollector
from algaecast.collect.wamis import WamisLevelCollector
from algaecast.config import CONFIG_DIR, RAW_DIR
from algaecast.features.run import GROUPS

log = logging.getLogger(__name__)
LEVEL_STATS = CONFIG_DIR / "level_cont_stats.json"
FAST_TIMEOUT = int(
    os.environ.get("ASOF_HTTP_TIMEOUT", "20")
)  # 증분 모드: 요청 20초·재시도 1회 (러너 네트워크 지연 대비)
FAST_RETRIES = int(os.environ.get("ASOF_HTTP_RETRIES", "1"))
WAMIS_BUDGET_S = int(os.environ.get("ASOF_WAMIS_BUDGET_S", "240"))  # 연속 수위 수집 전체 시간 예산


def _fast(col: object) -> object:
    col.timeout = FAST_TIMEOUT  # type: ignore[attr-defined]
    col.retries = FAST_RETRIES  # type: ignore[attr-defined]
    return col


def load_cfgs() -> tuple[dict, dict]:
    sites = yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))
    feats = yaml.safe_load((CONFIG_DIR / "features.yaml").read_text(encoding="utf-8"))
    return sites, feats


# ---------------------------------------------------------------- 증분 수집
def collect_recent(sites_cfg: dict, start: date, end: date) -> dict[str, pd.DataFrame]:
    """API 만으로 ``start``~``end`` 구간 원천을 모은다 (실패한 개별 소스는 로그 후 빈 프레임)."""
    out: dict[str, pd.DataFrame] = {}
    # 조류경보제 (전 지점) — 2consec 단계는 창 내 계산값(피처에 미사용)
    frames = []
    col = _fast(NierAlgaeCollector())
    for s in sites_cfg["sites"]:
        try:
            frames.append(col.fetch(s["site_code"], start, end))
        except CollectError as exc:
            log.warning("algae %s: %s", s["station_id"], exc)
    out["algae"] = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    out["algae"]["obs_date"] = pd.to_datetime(out["algae"]["obs_date"])
    # K-water delist: 보(facility_kwater_code) + 상류 본댐 + 대청댐
    cat = facility_catalog()
    k2f = dict(zip(cat["kwater_code"].astype(str), cat["facility_code"].astype(str), strict=True))
    main = {k for k, v in sites_cfg["dams"].items() if v.get("role") == "main"}
    codes: set[str] = set()
    for s in sites_cfg["sites"]:
        if s.get("facility_kwater_code"):
            codes.add(str(s["facility_kwater_code"]))
        for d in s.get("upstream_dams", []):
            if d in main:
                kw = cat.loc[cat["facility_code"].astype(str) == d, "kwater_code"]
                if len(kw):
                    codes.add(str(kw.iloc[0]))
        if s.get("facility_dam_code"):
            kw = cat.loc[cat["facility_code"].astype(str) == s["facility_dam_code"], "kwater_code"]
            if len(kw):
                codes.add(str(kw.iloc[0]))
    sl = _fast(KwaterSluiceCollector())
    longs = []
    for kw in sorted(codes):
        try:
            d = sl.fetch(kw, start, end)
        except CollectError as exc:
            log.warning("delist %s: %s", kw, exc)
            continue
        if d.empty:
            continue
        fc = k2f.get(kw, kw)
        for v in ("rwl", "iqty", "tdqty", "rf", "rsvwtqy", "rsvwtrt"):
            if v in d:
                longs.append(
                    pd.DataFrame(
                        {
                            "facility_code": fc,
                            "kwater_code": kw,
                            "obs_date": pd.to_datetime(d["obs_date"]),
                            "variable": v,
                            "value": d[v].astype(float),
                            "source": "kwater_sluice_delist",
                        }
                    )
                )
    out["hydro"] = (
        pd.concat(longs, ignore_index=True)
        if longs
        else pd.DataFrame(columns=["facility_code", "kwater_code", "obs_date", "variable", "value", "source"])
    )
    # 연속 수위 (WAMIS 관측소, 집계 통계로 wl_adj 계산)
    stats = json.loads(LEVEL_STATS.read_text(encoding="utf-8")) if LEVEL_STATS.exists() else None
    if stats:
        wl = _fast(WamisLevelCollector())
        rows = []
        t0, fails = time.monotonic(), 0
        for code in sorted({c for v in stats["site_stations"].values() for c in v}):
            if time.monotonic() - t0 > WAMIS_BUDGET_S or fails >= 3:
                log.warning(
                    "wamis wl: 시간 예산/연속 실패 초과 — 나머지 관측소 생략 (level_cont 는 가용분만)"
                )
                break
            try:
                d = wl.fetch(code, start, end)
                fails = 0
            except (CollectError, OSError) as exc:
                fails += 1
                log.warning("wamis wl %s: %s", code, exc)
                continue
            if d.empty:
                continue
            off = float(stats["wamis_offset_m"].get(code, 0.0))
            rows.append(
                pd.DataFrame(
                    {
                        "station_code": code,
                        "obs_date": pd.to_datetime(d["obs_date"]),
                        "wl_adj": d["wl"].astype(float) + off,
                    }
                )
            )
        if rows:
            out["level_cont"] = pd.concat(rows, ignore_index=True)
    # ASOS: asos_by_var 관측소 전부
    stns: set[int] = set()
    for s in sites_cfg["sites"]:
        for v in s.get("asos_by_var", {}).values():
            stns.add(int(s["asos_primary"]) if v == "primary" else int(v))
        stns.add(int(s["asos_primary"]))
    ka = _fast(KmaAsosCollector())
    frames = []
    for stn in sorted(stns):
        try:
            frames.append(ka.fetch(str(stn), start, end))
        except CollectError as exc:
            log.warning("asos %s: %s", stn, exc)
    out["asos"] = pd.concat(frames, ignore_index=True)
    out["asos"]["obs_date"] = pd.to_datetime(out["asos"]["obs_date"])
    # 예보 (저장소 CSV)
    fc_dir = RAW_DIR / "kma_forecast"
    if fc_dir.exists() and any(fc_dir.glob("*.csv")):
        out["forecast"] = load_forecast(fc_dir)
    return out


# ---------------------------------------------------------------- 달력·피처
def build_daily(
    sites_cfg: dict, feat_cfg: dict, src: dict[str, pd.DataFrame], start: date, end: date
) -> dict[str, pd.DataFrame]:
    stats = json.loads(LEVEL_STATS.read_text(encoding="utf-8")) if LEVEL_STATS.exists() else {}
    means = {str(k): float(v) for k, v in stats.get("station_mean_wl_adj", {}).items()}
    out = {}
    for site in sites_cfg["sites"]:
        base = build_site_daily(site, src, sites_cfg, feat_cfg, end, start=start, level_means=means)
        d = apply_strategy(base, "S1", feat_cfg)
        d["obs_date"] = pd.to_datetime(d["obs_date"])
        out[site["station_id"]] = d
    return out


def latest_base_dates(daily: dict[str, pd.DataFrame], today: date) -> dict[str, date]:
    out = {}
    for sid, d in daily.items():
        obs = d.loc[d["is_obs"].astype(bool) & (d["obs_date"] <= pd.Timestamp(today)), "obs_date"]
        if len(obs):
            out[sid] = obs.max().date()
    return out


def feature_rows(
    daily: dict[str, pd.DataFrame], sites_cfg: dict, bases: dict[str, date], horizon: int = 7
) -> pd.DataFrame:
    rows = []
    for s in sites_cfg["sites"]:
        sid = s["station_id"]
        if sid not in bases:
            continue
        b = bases[sid]
        feats: dict = {}
        for fn in GROUPS.values():
            feats.update(fn(daily[sid], b, s["site_code"]))
        feats.update(
            {
                "station_id": sid,
                "site_code": s["site_code"],
                "base_date": pd.Timestamp(b),
                "target_date": pd.Timestamp(b + timedelta(days=horizon)),
                "horizon_days": float(horizon),
            }
        )
        rows.append(feats)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 검증
def validate_against_bundle(days: int = 120, n_base: int = 30, cols: list[str] | None = None) -> pd.DataFrame:
    """번들 기반 features_S1 의 최근 n_base 개 base_date 를 API-only 증분 달력으로 재계산해 일치율을 낸다."""
    sites_cfg, feat_cfg = load_cfgs()
    from algaecast.models import data as D
    from algaecast.models.train import feature_sets

    feat = pd.read_parquet(D.PROCESSED / "features_S1.parquet")
    feat["base_date"] = pd.to_datetime(feat["base_date"])
    cols = cols or feature_sets()["perc75"]
    recent = feat.sort_values("base_date").groupby("station_id", observed=True).tail(n_base // 5 + 1)
    end = recent["base_date"].max().date()
    start = end - timedelta(days=days)
    src = collect_recent(sites_cfg, start, end)
    daily = build_daily(sites_cfg, feat_cfg, src, start, end)
    rows = []
    for r in recent.itertuples():
        sid = str(r.station_id)
        if sid not in daily:
            continue
        b = r.base_date.date()
        site = next(s for s in sites_cfg["sites"] if s["station_id"] == sid)
        f: dict = {}
        for fn in GROUPS.values():
            f.update(fn(daily[sid], b, site["site_code"]))
        for c in cols:
            v_b, v_a = getattr(r, c, None), f.get(c)
            if c in ("dominant_genus", "facility_type", "basin"):
                ok = str(v_b) == str(v_a)
                rel = np.nan
            else:
                vb, va = float(v_b) if v_b is not None and pd.notna(v_b) else np.nan, (
                    float(v_a) if v_a is not None and pd.notna(v_a) else np.nan
                )
                if np.isnan(vb) and np.isnan(va):
                    ok, rel = True, 0.0
                elif np.isnan(vb) or np.isnan(va):
                    ok, rel = False, np.nan
                else:
                    rel = abs(vb - va) / (abs(vb) + 1e-9)
                    ok = abs(vb - va) <= 1e-6 or rel <= 0.01
            rows.append(
                {
                    "station_id": sid,
                    "base_date": b,
                    "feature": c,
                    "bundle": v_b,
                    "api": v_a,
                    "rel_diff": rel,
                    "match_1pct": bool(ok),
                }
            )
    return pd.DataFrame(rows)


def write_validation_report(df: pd.DataFrame, path: Path) -> dict:
    per_feat = (
        df.groupby("feature")
        .agg(n=("match_1pct", "size"), match=("match_1pct", "mean"), max_rel=("rel_diff", "max"))
        .reset_index()
        .sort_values("match")
    )
    overall = float(df["match_1pct"].mean())
    exact = float((df["rel_diff"].fillna(1) <= 1e-9).mean())
    lines = [
        "# as-of 피처 재현 검증 — 대회 번들 없이 공공 API 최근 120일만으로 재계산",
        "",
        f"- 비교 대상: 번들 기반 features_S1 의 최근 {df['base_date'].nunique()}개 base_date × "
        f"5지점 × 피처 {df['feature'].nunique()}개 = {len(df):,} 값",
        f"- **일치율(허용오차 |상대차| ≤ 1% 또는 |차| ≤ 1e-6): {100 * overall:.1f}%**, 완전 "
        f"일치(≤1e-9) {100 * exact:.1f}%",
        "- 불일치의 주원인: 120일 창 밖 이력이 필요한 피처(consecutive_over_1k 장기 연속, 과거 연도 "
        "월 중앙값 채움), 수집 시점 차이(API 갱신·보정), 2consec 단계는 피처 미사용.",
        "",
        "| 피처 | n | 일치율 | 최대 상대차 |",
        "|---|---|---|---|",
    ] + [
        f"| {r.feature} | {int(r.n)} | {100 * r.match:.1f}% | "
        f"{'' if pd.isna(r.max_rel) else f'{r.max_rel:.3g}'} |"
        for r in per_feat.itertuples()
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return {"overall": overall, "exact": exact, "n": int(len(df))}
