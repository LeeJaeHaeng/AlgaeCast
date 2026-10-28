# ruff: noqa: E501  (한국어 설명)
"""데이터 유래 상수 — 계산 자료·기간 메타데이터와 함께 ``config/derived_constants.json`` 에 둔다 (FIX-v2.1).

사전등록: reports/experiments/FIX-v2.1/PREREG.md (R3·R4). 규칙
- 지점별 관심 도달 수온 임계(T2 S6 정의): NIER 조류경보 측정에서 지점별 (수온, log10(세포수+1))
  결측 없는 측정행 → statsmodels lowess(frac=0.4) → LOESS ≥ 3 인 최소 수온(소수 첫째 자리), 없으면 결측.
  계산 자료 = 측정일 연도 ≤ Y. 사용: CV 폴드(검증 V) Y = V−1, 2025 홀드아웃 Y = 2024,
  제출 모델 T24(대회 split=train, 2026-10-28 전환)·2026 예측·운영 Y = 2024, v2.1 이력(2026-10-23~27 제출·운영) Y = 2025.
- 선택 결정(≤2024 재계산): D1 ASOS 주 관측소, D2 일사 관측소, D3 보 1차 수문(T2 S4), D4 hurdle 후보(T2 S1).

사용: python -m algaecast.features.constants --build   (원자료 필요, 결과 JSON 을 다시 쓴다)
      python -m algaecast.features.constants --check   (JSON 과 원자료 재계산 대조)
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from algaecast.collect.algae_source import load_algae_source, source_path
from algaecast.config import CONFIG_DIR, RAW_DIR

log = logging.getLogger(__name__)

DERIVED_PATH = CONFIG_DIR / "derived_constants.json"
NIER_PATH = RAW_DIR / "nier_algae" / "nier_algae_2012_2026.parquet"
SITE_ORDER = ["HP", "GJGR", "CS", "MGMR", "DCHN"]
THRESHOLD_YEARS = tuple(range(2019, 2026))  # CV 폴드 2020~2024 → 2019~2023, 홀드아웃·T24 2024, v2.1 이력 2025
# 제출 모델 T24(학습 = 대회 번들 split=train, 기준일 ≤2024)·2026 예측·일일 운영 — 운영사무국 답변 2026-10-28 '학습은 24년까지'
FINAL_THRESHOLD_YEAR = 2024
V21_THRESHOLD_YEAR = 2025  # v2.1 이력(최종 학습 ≤2025) 재현 전용 — freeze_v21·alert 최종 적합·posthoc_v21
DECISION_YEAR = 2024  # 선택 결정 재계산 자료 끝 연도
LOESS_FRAC = 0.4
CAUTION_LOG = 3.0  # 관심 1,000 cells/mL → log10(1000+1) ≈ 3


def threshold_year_for_valid(valid_year: int) -> int:
    """검증 연도 V 인 폴드(학습 ≤ V−1)가 쓰는 임계 계산 자료 끝 연도."""
    return int(valid_year) - 1


# ---------------------------------------------------------------- 수온 임계 (R3)
def load_nier(path: Path | None = None, max_year: int | None = None) -> pd.DataFrame:
    """조류경보제 측정(수온·세포수). path 가 None 이면 원천 선택(collect/algae_source.py)을 따른다."""
    cols = ["station_id", "obs_date", "iem_wtrtp", "iem_bgalage_cell_co"]
    a = load_algae_source(cols) if path is None else pd.read_parquet(path, columns=cols)
    a["obs_date"] = pd.to_datetime(a["obs_date"])
    if max_year is not None:
        a = a[a["obs_date"].dt.year <= max_year]  # 이후 연도 값은 읽지 않는다
    return a[a["station_id"].isin(SITE_ORDER)].copy()


def loess_threshold(wtemp: np.ndarray, log_cells: np.ndarray) -> float | None:
    """T2 S6: lowess(log_cells ~ wtemp, frac=0.4) 가 3 이상인 최소 수온(소수 첫째 자리)."""
    import statsmodels.api as sm

    if len(wtemp) < 10:
        return None
    lo = sm.nonparametric.lowess(log_cells, wtemp, frac=LOESS_FRAC)
    over = lo[lo[:, 1] >= CAUTION_LOG]
    return round(float(over[:, 0].min()), 1) if len(over) else None


def compute_site_thresholds(max_year: int, algae: pd.DataFrame | None = None) -> dict:
    """측정일 연도 ≤ max_year 자료만으로 지점별 임계와 메타데이터."""
    a = load_nier(max_year=max_year) if algae is None else algae[algae["obs_date"].dt.year <= max_year]
    a = a.assign(log_cells=np.log10(a["iem_bgalage_cell_co"].astype(float) + 1))
    values, n, last = {}, {}, {}
    for sid in SITE_ORDER:
        g = a[a["station_id"] == sid][["obs_date", "iem_wtrtp", "log_cells"]].dropna()
        values[sid] = loess_threshold(g["iem_wtrtp"].to_numpy(float), g["log_cells"].to_numpy(float))
        n[sid] = int(len(g))
        last[sid] = str(g["obs_date"].max().date()) if len(g) else None
    used = [d for d in last.values() if d]
    return {
        "values": values,
        "n": n,
        "data_source": f"{source_path()} (iem_wtrtp, iem_bgalage_cell_co)",
        "data_max_year": int(max_year),
        "data_last_date": max(used) if used else None,
        "data_last_date_by_site": last,
        "method": f"T2 S6: statsmodels lowess(log10(cells+1) ~ wtemp, frac={LOESS_FRAC}), 값 ≥ {CAUTION_LOG} 인 최소 수온(0.1℃)",
    }


# ---------------------------------------------------------------- 선택 결정 (R4)
def decision_asos(max_year: int, sites_cfg: dict) -> dict:
    """D1 ASOS 주 관측소(7일 평균기온–번들 수온 Spearman 최대), D2 일사 관측소(결측률 <5% 중 최근접)."""
    from algaecast.collect import competition as comp
    from algaecast.collect.kma_asos import station_choice

    asos = pd.read_parquet(RAW_DIR / "kma_asos" / "kma_asos_daily_2012_2026.parquet")
    asos["obs_date"] = pd.to_datetime(asos["obs_date"])
    asos = asos[asos["obs_date"].dt.year <= max_year]
    algae = comp.load_algae()
    algae["obs_date"] = pd.to_datetime(algae["obs_date"])
    algae = algae[algae["obs_date"].dt.year <= max_year]
    tbl = station_choice(asos, sites_cfg, algae)
    out = {}
    for site in sites_cfg["sites"]:
        sid = site["station_id"]
        t = tbl[tbl["station_id"] == sid]
        prim = int(t.sort_values("spearman 7일평균기온", ascending=False).iloc[0]["stn_id"])
        ok = t[t["일사 보유율 %"] > 95.0]
        si = int(
            (ok.sort_values("거리 km") if len(ok) else t.sort_values("일사 보유율 %", ascending=False)).iloc[
                0
            ]["stn_id"]
        )
        cur_si = site.get("asos_by_var", {}).get("si", "primary")
        out[sid] = {
            "asos_primary": prim,
            "asos_primary_current": int(site["asos_primary"]),
            "si": si,
            "si_current": int(site["asos_primary"]) if cur_si == "primary" else int(cur_si),
            "table": t[["stn_id", "stn_nm", "거리 km", "n", "spearman 7일평균기온", "일사 보유율 %"]].to_dict(
                "records"
            ),
        }
    return {
        "data_max_year": int(max_year),
        "data_last_date": str(max(asos["obs_date"].max(), algae["obs_date"].max()).date()),
        "rule": "D1: 후보 중 spearman(7일 평균기온, 번들 측정 수온) 최대 / D2: 일사 보유율 >95% 중 최근접, 없으면 보유율 최대",
        "sites": out,
    }


def decision_hydro(max_year: int, sites_cfg: dict, algae: pd.DataFrame | None = None) -> dict:
    """D3(T2 S4 정의): 측정일 세포수(원단위)와 상류 본댐 유입량 합·총방류량 합의 Pearson r, 낙동강 4지점."""
    from scipy import stats

    a = load_nier(max_year=max_year) if algae is None else algae[algae["obs_date"].dt.year <= max_year]
    hydro = pd.read_parquet(RAW_DIR / "hydro" / "hydro_daily_long.parquet")
    hydro["obs_date"] = pd.to_datetime(hydro["obs_date"])
    hydro = hydro[hydro["obs_date"].dt.year <= max_year]
    prio = {"bundle_wamis": 0, "kwater_sluice_delist": 1, "wamis_mn_dtdata": 2, "kwater_damapi": 3}
    hydro = hydro.assign(prio=hydro["source"].map(prio).fillna(9)).sort_values("prio")
    hydro = hydro.drop_duplicates(["facility_code", "variable", "obs_date"], keep="first")
    hw = hydro.pivot_table(index=["facility_code", "obs_date"], columns="variable", values="value")
    main = {k for k, v in sites_cfg["dams"].items() if v.get("role") == "main"}
    rows = {}
    for site in sites_cfg["sites"]:
        sid = site["station_id"]
        if sid == "DCHN":
            continue
        dams = [d for d in site.get("upstream_dams", []) if d in main and d in hw.index.get_level_values(0)]
        stack = pd.concat([hw.loc[d] for d in dams], keys=range(len(dams))).groupby(level=1)
        g = a[a["station_id"] == sid][["obs_date", "iem_bgalage_cell_co"]].dropna()
        cells = g["iem_bgalage_cell_co"].astype(float).to_numpy()
        res = {}
        for v, name in (("iqty", "inflow"), ("tdqty", "discharge")):
            x = stack[v].sum(min_count=1).reindex(g["obs_date"]).to_numpy()
            ok = ~np.isnan(x)
            res[name] = round(float(stats.pearsonr(x[ok], cells[ok])[0]), 4) if ok.sum() >= 20 else None
            res[f"n_{name}"] = int(ok.sum())
        rows[sid] = res
    vals = [
        abs(v) for r in rows.values() for k, v in r.items() if k in ("inflow", "discharge") and v is not None
    ]
    return {
        "data_max_year": int(max_year),
        "rule": "8개 |r| 모두 < 0.1 이면 T2 결정(본댐 합산 ≈0 → 보 자체 1차)과 같음",
        "sites": rows,
        "max_abs_r": round(max(vals), 4) if vals else None,
        "same_decision": bool(vals) and max(vals) < 0.1,
    }


def decision_zero(max_year: int, algae: pd.DataFrame | None = None) -> dict:
    """D4(T2 S1 정의): 5지점 측정 세포수의 0값 비율."""
    a = load_nier(max_year=max_year) if algae is None else algae[algae["obs_date"].dt.year <= max_year]
    c = a["iem_bgalage_cell_co"].astype(float).dropna()
    r = float((c == 0).mean())
    return {
        "data_max_year": int(max_year),
        "zero_ratio": round(r, 4),
        "n": int(len(c)),
        "rule": "0값 비율 ≥ 10% 이면 hurdle 후보 결정과 같음",
        "same_decision": r >= 0.10,
    }


# ---------------------------------------------------------------- 저장·읽기
def build(path: Path = DERIVED_PATH) -> dict:
    sites_cfg = yaml.safe_load((CONFIG_DIR / "sites.yaml").read_text(encoding="utf-8"))
    algae = load_nier(max_year=max(THRESHOLD_YEARS))
    doc = {
        "_about": "데이터로 계산한 상수와 계산 자료·기간(FIX-v2.1 PREREG R3·R4). 사용 규칙: CV 폴드(검증 V) → site_caution_wtemp[V−1], 2025 홀드아웃 → [2024], 제출 모델 T24·2026 예측·일일 운영 → [2024](2026-10-28 전환), v2.1 이력 → [2025]. 테스트(tests/test_derived_constants.py)가 사용 시점보다 늦은 자료를 막는다.",
        "computed_at": datetime.now().isoformat(timespec="seconds"),
        "site_caution_wtemp": {str(y): compute_site_thresholds(y, algae) for y in THRESHOLD_YEARS},
        "decisions": {
            "asos": decision_asos(DECISION_YEAR, sites_cfg),
            "hydro_primary": decision_hydro(DECISION_YEAR, sites_cfg, algae),
            "hurdle_candidate": decision_zero(DECISION_YEAR, algae),
        },
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return doc


_CACHE: dict | None = None


def load(path: Path = DERIVED_PATH) -> dict:
    global _CACHE
    if _CACHE is None or path != DERIVED_PATH:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if path != DERIVED_PATH:
            return doc
        _CACHE = doc
    return _CACHE


def site_thresholds(year: int) -> dict[str, float | None]:
    """측정일 연도 ≤ year 자료로 계산한 지점별 관심 도달 수온 임계."""
    sets = load()["site_caution_wtemp"]
    if str(year) not in sets:
        raise KeyError(f"수온 임계 {year} 없음 — python -m algaecast.features.constants --build")
    return sets[str(year)]["values"]


def check(path: Path = DERIVED_PATH) -> list[str]:
    """JSON 값이 원자료 재계산과 같은지(원자료가 있을 때)."""
    doc = load(path)
    algae = load_nier(max_year=max(THRESHOLD_YEARS))
    bad = []
    for y in THRESHOLD_YEARS:
        got = compute_site_thresholds(y, algae)["values"]
        if got != doc["site_caution_wtemp"][str(y)]["values"]:
            bad.append(f"site_caution_wtemp[{y}] {doc['site_caution_wtemp'][str(y)]['values']} != {got}")
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.build:
        doc = build()
        for y, s in doc["site_caution_wtemp"].items():
            print(y, s["values"], "자료 끝", s["data_last_date"])
        print(
            json.dumps(
                {k: {kk: vv for kk, vv in v.items() if kk != "sites"} for k, v in doc["decisions"].items()},
                ensure_ascii=False,
            )
        )
    if args.check:
        bad = check()
        print("일치" if not bad else "\n".join(bad))
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DERIVED_PATH",
    "FINAL_THRESHOLD_YEAR",
    "V21_THRESHOLD_YEAR",
    "THRESHOLD_YEARS",
    "build",
    "compute_site_thresholds",
    "load",
    "site_thresholds",
    "threshold_year_for_valid",
]


# ---------------------------------------------------------------- 폴드별 임계 적용 (R3)
THRESH_COLS = ("wtemp_minus_site_thresh", "wtemp_over_site_thresh_days")
WTEMP_LAST = "_wtemp_last"  # 기준일의 일 단위 수온(S1 채움) — 임계 피처 재계산용 메타 열
_DAILY_WT: dict[tuple[str, str], pd.Series] = {}


def _daily_wtemp(station_id: str, strategy: str) -> pd.Series | None:
    from algaecast.config import INTERIM_DIR

    key = (station_id, strategy)
    if key not in _DAILY_WT:
        p = INTERIM_DIR / f"daily_{station_id}_{strategy}.parquet"
        if not p.exists():
            return None
        d = pd.read_parquet(p, columns=["obs_date", "wtemp"])
        _DAILY_WT[key] = d.set_index(pd.to_datetime(d["obs_date"]))["wtemp"].astype(float)
    return _DAILY_WT[key]


def apply_site_thresholds(frame: pd.DataFrame, year: int, strategy: str = "S1") -> pd.DataFrame:
    """임계 피처를 측정일 연도 ≤ year 자료의 임계로 다시 계산한 사본(행·열 순서 그대로).

    wtemp_minus_site_thresh = 기준일 일 수온 − 임계, wtemp_over_site_thresh_days = 최근 30일 중 임계 초과 일수.
    """
    if WTEMP_LAST not in frame.columns:
        raise KeyError(f"{WTEMP_LAST} 열이 없다 — features.run 으로 피처를 다시 만든다")
    th = site_thresholds(year)
    out = frame.copy()
    t = out["station_id"].astype(str).map(lambda s: th.get(s)).astype(float)
    out["wtemp_minus_site_thresh"] = out[WTEMP_LAST].astype(float) - t
    if "wtemp_over_site_thresh_days" in out.columns:
        vals = np.full(len(out), np.nan)
        for sid, idx in out.groupby(out["station_id"].astype(str)).indices.items():
            s = _daily_wtemp(sid, strategy)
            tv = th.get(sid)
            if s is None or tv is None:
                continue
            w = s.rolling(30, min_periods=1)
            over = (s > tv).astype(float).where(s.notna()).rolling(30, min_periods=1).sum()
            cnt = w.count()
            bd = pd.to_datetime(out["base_date"].iloc[idx])
            v = over.reindex(bd).to_numpy()
            c = cnt.reindex(bd).to_numpy()
            vals[idx] = np.where(c > 0, v, np.nan)
        out["wtemp_over_site_thresh_days"] = vals
    return out
