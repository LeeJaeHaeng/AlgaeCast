"""make features 진입점: (site, base_date) 샘플·타깃 매칭(±3일)·splits.json (T3-b).

- 샘플: 지점별 **측정일 전부**를 base_date 로 (S2 보간의 무누수 조건),
  target_date = base+7 에 가장 가까운 측정일
  (|차| ≤ 3, 동률은 이른 날 — 대회 규칙 재현). 타깃 없는 base_date 는 행은 남기되 target NaN(학습 제외).
- 피처: features/{ar,water,hydro,weather,forecast,time_site}.make_*_features(df_daily, as_of, site_code)
  + horizon_days.
- 분할: train ≤2024 / valid 2025 / test = sample_submission (station_id, base_date, target_date) 조합.
- 출력: data/processed/features_<S>.parquet, splits.json, reports/features/feature_catalog.md
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy import stats

from algaecast.collect import competition as comp
from algaecast.config import CONFIG_DIR, DATA_DIR, REPORTS_DIR
from algaecast.features.ar import make_ar_features
from algaecast.features.forecast import make_forecast_features
from algaecast.features.hydro import make_hydro_features
from algaecast.features.time_site import make_time_site_features
from algaecast.features.water import make_water_features
from algaecast.features.weather import make_weather_features

log = logging.getLogger(__name__)
INTERIM = DATA_DIR / "interim"
PROCESSED = DATA_DIR / "processed"
# DataON 연속 수위: 원자료(CC BY-NC-SA)가 없으면 가공 피처 파일(지점·기준일별 수위 피처 2열)로 두 열을 채운다.
# 원자료가 있으면 원자료부터 다시 계산한다(align.run → features.run).
# 가공 파일은 export_level_cont() 로 만든다.
DATAON_RAW = DATA_DIR / "raw" / "dataon" / "level_continuous_long.parquet"
LEVEL_FEATURES = ("level_cont_t0", "level_cont_diff7")
GROUPS: dict[str, Callable[[pd.DataFrame, date, str], dict]] = {
    "ar": make_ar_features,
    "water": make_water_features,
    "hydro": make_hydro_features,
    "weather": make_weather_features,
    "forecast": make_forecast_features,
    "time_site": make_time_site_features,
}
META_COLS = [
    "station_id",
    "site_code",
    "base_date",
    "target_date",
    "horizon_days",
    "target_cells",
    "target_log",
    "split",
]
CAT_COLS = ["dominant_genus", "site_code", "station_id", "basin", "facility_type"]


def match_target(
    base: pd.Timestamp, obs_dates: pd.DatetimeIndex, horizon: int, tol: int
) -> pd.Timestamp | None:
    """base+horizon 에 가장 가까운 측정일(|차| ≤ tol, 동률은 이른 날)."""
    goal = base + pd.Timedelta(days=horizon)
    cand = obs_dates[(obs_dates > base) & (abs(obs_dates - goal) <= pd.Timedelta(days=tol))]
    if len(cand) == 0:
        return None
    diffs = abs(cand - goal)
    best = diffs.min()
    return cand[diffs == best].min()


def build_samples(daily: pd.DataFrame, site: dict, cfg: dict) -> pd.DataFrame:
    sid = site["station_id"]
    obs = daily[daily["is_obs"].astype(bool)].copy()
    obs_dates = pd.DatetimeIndex(pd.to_datetime(obs["obs_date"]))
    cells = obs.set_index(pd.to_datetime(obs["obs_date"]))["cells_obs"].astype(float)
    h, tol = cfg["target"]["horizon_days"], cfg["target"]["match_tolerance_days"]
    rows = []
    for base in obs_dates:
        tgt = match_target(base, obs_dates, h, tol)
        y = float(cells.get(tgt, np.nan)) if tgt is not None else np.nan
        feats: dict = {}
        for fn in GROUPS.values():
            feats.update(fn(daily, base.date(), site["site_code"]))
        feats.update(
            {
                "station_id": sid,
                "site_code": site["site_code"],
                "base_date": base.date(),
                "target_date": tgt.date() if tgt is not None else None,
                "horizon_days": float((tgt - base).days) if tgt is not None else np.nan,
                "target_cells": y,
                "target_log": np.log10(y + 1) if np.isfinite(y) else np.nan,
            }
        )
        rows.append(feats)
    return pd.DataFrame(rows)


def assign_split(df: pd.DataFrame, cfg: dict, submission: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    yr = pd.to_datetime(d["base_date"]).dt.year
    d["split"] = np.where(
        yr <= cfg["splits"]["train_max_year"],
        "train",
        np.where(yr == cfg["splits"]["valid_year"], "valid", "none"),
    )
    key = set(
        zip(
            submission["station_id"],
            pd.to_datetime(submission["base_date"]).dt.date,
            pd.to_datetime(submission["target_date"]).dt.date,
            strict=True,
        )
    )
    is_test = [
        (s, b, t) in key for s, b, t in zip(d["station_id"], d["base_date"], d["target_date"], strict=True)
    ]
    d.loc[is_test, "split"] = "test"
    d.loc[(d["split"].isin(["train", "valid"])) & d["target_log"].isna(), "split"] = "none"
    return d


def catalog(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    tr = df[df["split"] == "train"]
    rows = []
    for c in feature_cols:
        if c in CAT_COLS:
            rows.append(
                {
                    "피처": c,
                    "그룹": group_of(c),
                    "결측률 %": round(100 * df[c].isna().mean(), 1),
                    "타깃 Spearman": np.nan,
                    "비고": "범주",
                }
            )
            continue
        x = pd.to_numeric(tr[c], errors="coerce")
        ok = x.notna() & tr["target_log"].notna()
        rho = (
            stats.spearmanr(x[ok], tr.loc[ok, "target_log"]).correlation
            if ok.sum() > 30 and x[ok].nunique() > 1
            else np.nan
        )
        rows.append(
            {
                "피처": c,
                "그룹": group_of(c),
                "결측률 %": round(100 * df[c].isna().mean(), 1),
                "타깃 Spearman": round(float(rho), 3) if np.isfinite(rho) else np.nan,
                "비고": "",
            }
        )
    return pd.DataFrame(rows)


_GROUP_PREFIX = {
    "ar": (
        "cell_",
        "days_since_obs",
        "dominant_genus",
        "alert_level_t0",
        "consecutive_over_1k",
        "chla_",
        "cells_missing",
    ),
    "water": ("wtemp", "ph_t0", "do_t0", "turb_t0", "transp_t0"),
    "hydro": (
        "weir_",
        "inflow",
        "outflow",
        "storage",
        "residence",
        "upstream_dam",
        "dam_release",
        "level_cont",
        "hydro_fac",
    ),
    "weather": ("ta_", "rn_", "dry_days", "ss_sum", "si_sum", "ws_", "hm_", "si_missing"),
    "forecast": ("fc_",),
    "time_site": (
        "month_",
        "doy_",
        "season_day",
        "year",
        "site_code",
        "station_id",
        "basin",
        "facility_type",
        "intake_",
        "catchment",
        "total_storage",
        "n_upstream",
        "horizon_days",
    ),
}


def group_of(col: str) -> str:
    for g, prefixes in _GROUP_PREFIX.items():
        if any(col.startswith(p) for p in prefixes):
            return g
    return "etc"


TEST_TARGETS_PATH = PROCESSED / "test_targets_DO_NOT_USE.parquet"
TARGET_COLS = ["target_cells", "target_log"]


QUARANTINE_TARGET_FROM = date(2026, 1, 1)  # 정답이 2026 측정인 행은 split 과 무관하게 격리한다


def level_cont_path(strategy: str) -> Path:
    return PROCESSED / f"level_cont_features_{strategy}.parquet"


def level_cont_mode(strategy: str) -> str:
    """'raw'(DataON 원자료로 계산) · 'derived'(가공 피처 파일로 채움) · 'missing'(둘 다 없음 → 결측)."""
    if DATAON_RAW.exists():
        return "raw"
    return "derived" if level_cont_path(strategy).exists() else "missing"


def apply_level_cont_derived(feats: pd.DataFrame, strategy: str) -> pd.DataFrame:
    """가공 피처 파일의 level_cont_t0·level_cont_diff7 로 두 열을 채운다.

    키는 station_id·base_date, 열 순서는 그대로 둔다.
    """
    d = pd.read_parquet(level_cont_path(strategy))
    key = feats["station_id"].astype(str) + "|" + pd.to_datetime(feats["base_date"]).dt.strftime("%Y-%m-%d")
    dk = d["station_id"].astype(str) + "|" + pd.to_datetime(d["base_date"]).dt.strftime("%Y-%m-%d")
    d = d.set_axis(dk.to_numpy())
    out = feats.copy()
    for c in LEVEL_FEATURES:
        out[c] = d[c].reindex(key.to_numpy()).to_numpy(dtype=float)
    miss = int(out[list(LEVEL_FEATURES)].isna().all(axis=1).sum())
    log.info(
        "DataON 원자료 없음 → 가공 수위 피처 %s 로 %s 채움(키 없음 %d행)",
        level_cont_path(strategy).name,
        LEVEL_FEATURES,
        miss,
    )
    return out


def export_level_cont(strategy: str = "S1") -> Path:
    """원자료로 만든 features_<S>.parquet 에서 수위 피처 2열만 내보낸다(DataON 가공물, CC BY-NC-SA)."""
    if level_cont_mode(strategy) != "raw":
        raise SystemExit("중단: DataON 원자료가 없어 원자료 기준 수위 피처를 내보낼 수 없다.")
    f = pd.read_parquet(
        PROCESSED / f"features_{strategy}.parquet", columns=["station_id", "base_date", *LEVEL_FEATURES]
    )
    f["station_id"] = f["station_id"].astype(str)
    f["base_date"] = pd.to_datetime(f["base_date"]).dt.strftime("%Y-%m-%d")
    out = level_cont_path(strategy)
    f.to_parquet(out, index=False)
    log.info("가공 수위 피처 %d행 → %s", len(f), out)
    return out


def quarantine_test_targets(feats: pd.DataFrame, path: Path = TEST_TARGETS_PATH) -> pd.DataFrame:
    """test split 과 '목표일이 2026 이상인 행'(예: 기준일 2025-12-29 → 목표일 2026-01-05)의 타깃을
    별도 파일로 분리 저장하고 피처 프레임에서는 NaN 으로 비운다.

    분리 파일은 사후 검증 전용(eval/live). 열 ``quarantine`` = "test" | "target_2026".
    목표일 2026 행은 타깃이 비므로 학습·검증 로더(drop_missing_target)에서 빠진다.
    """
    d = feats.copy()
    is_test = d["split"] == "test"
    is_2026 = pd.to_datetime(d["target_date"]) >= pd.Timestamp(QUARANTINE_TARGET_FROM)
    q = is_test | is_2026
    tt = d.loc[q, ["station_id", "site_code", "base_date", "target_date", *TARGET_COLS]].copy()
    tt["quarantine"] = np.where(is_test[q].to_numpy(), "test", "target_2026")
    if path.exists():
        prev = pd.read_parquet(path)
        prev["base_date"] = pd.to_datetime(prev["base_date"]).dt.date
        if "quarantine" not in prev.columns:
            prev["quarantine"] = "test"
        tt = pd.concat([prev, tt]).drop_duplicates(["station_id", "base_date"], keep="last")
    path.parent.mkdir(parents=True, exist_ok=True)
    tt.to_parquet(path, index=False)
    d.loc[q, TARGET_COLS] = np.nan
    return d


def _md(t: pd.DataFrame) -> str:
    hdr = "| " + " | ".join(map(str, t.columns)) + " |\n|" + "---|" * len(t.columns)
    return (
        hdr
        + "\n"
        + "\n".join(
            "| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |"
            for r in t.itertuples(index=False)
        )
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strategy", default="S1,S2,S3")
    ap.add_argument(
        "--export-level-cont", action="store_true", help="수위 피처 2열을 가공 파일로 내보내기(원자료 필요)"
    )
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.export_level_cont:
        for s in [x.strip().upper() for x in args.strategy.split(",") if x.strip()]:
            export_level_cont(s)
        return 0
    cfg = yaml.safe_load((CONFIG_DIR / "features.yaml").read_text(encoding="utf-8"))
    sites = yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))["sites"]
    submission = comp.load_sample_submission()
    PROCESSED.mkdir(parents=True, exist_ok=True)
    splits: dict = {}
    summary = []
    for s in [x.strip().upper() for x in args.strategy.split(",") if x.strip()]:
        frames = []
        for site in sites:
            path = INTERIM / f"daily_{site['station_id']}_{s}.parquet"
            if not path.exists():
                log.warning("%s 없음 — make align 먼저", path.name)
                continue
            daily = pd.read_parquet(path)
            daily["obs_date"] = pd.to_datetime(daily["obs_date"])
            df = build_samples(daily, site, cfg)
            frames.append(df)
            log.info(
                "%s %s: 샘플 %d (타깃 %d)",
                s,
                site["station_id"],
                len(df),
                int(df["target_log"].notna().sum()),
            )
        feats = pd.concat(frames, ignore_index=True)
        mode = level_cont_mode(s)
        if mode == "derived":
            feats = apply_level_cont_derived(feats, s)
        elif mode == "missing":
            log.warning("%s: DataON 원자료·가공 수위 피처 파일이 모두 없어 %s 가 결측", s, LEVEL_FEATURES)
        feats = assign_split(feats, cfg, submission)
        feats = quarantine_test_targets(feats)
        feature_cols = [c for c in feats.columns if c not in META_COLS] + ["horizon_days"]
        feature_cols = list(dict.fromkeys(feature_cols))
        for c in CAT_COLS:
            if c in feats:
                feats[c] = feats[c].astype("category")
        out = PROCESSED / f"features_{s}.parquet"
        feats.to_parquet(out, index=False)
        n_test_found = int((feats["split"] == "test").sum())
        if n_test_found != len(submission):
            log.warning(
                "%s: sample_submission %d 조합 중 %d 만 샘플에 존재", s, len(submission), n_test_found
            )
        splits[s] = {
            sp: [
                [r.station_id, str(r.base_date), str(r.target_date)]
                for r in feats[feats["split"] == sp].itertuples()
            ]
            for sp in ("train", "valid", "test")
        }
        cat = catalog(feats, feature_cols)
        if s == "S1":
            rep = REPORTS_DIR / "features" / "feature_catalog.md"
            rep.parent.mkdir(parents=True, exist_ok=True)
            by_year = (
                feats[feats["split"].isin(["train", "valid", "test"])]
                .groupby([pd.to_datetime(feats["base_date"]).dt.year, "station_id"], observed=False)
                .size()
                .unstack(fill_value=0)
            )
            top = (
                cat.dropna(subset=["타깃 Spearman"])
                .assign(a=lambda d: d["타깃 Spearman"].abs())
                .sort_values("a", ascending=False)
                .drop(columns="a")
                .head(15)
            )
            rep.write_text(
                "# 피처 카탈로그 (T3-b, 전략 S1 기준)\n\n"
                f"- 샘플 {len(feats):,} (train {int((feats['split'] == 'train').sum())}, "
                f"valid {int((feats['split'] == 'valid').sum())}, test {n_test_found}, "
                f"타깃 없음/제외 {int((feats['split'] == 'none').sum())}), 피처 {len(feature_cols)}개\n"
                "- 정의는 docs/03 4절 + config/features.yaml. "
                "타깃 Spearman 은 train(≤2024) 의 log10(세포수+1) 기준.\n\n"
                "## 연도 × 지점 샘플 수 (train/valid/test)\n"
                + _md(by_year.reset_index().rename(columns={"base_date": "연도"}))
                + "\n\n"
                "## 타깃 상관 상위 15\n" + _md(top) + "\n\n## 전체\n" + _md(cat) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        summary.append(
            {
                "전략": s,
                "샘플": len(feats),
                "train": int((feats["split"] == "train").sum()),
                "valid": int((feats["split"] == "valid").sum()),
                "test": n_test_found,
                "피처": len(feature_cols),
            }
        )
    sp_path = PROCESSED / "splits.json"
    merged = json.loads(sp_path.read_text(encoding="utf-8")) if sp_path.exists() else {}
    merged.update(splits)
    sp_path.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    print(pd.DataFrame(summary).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
