# ruff: noqa: E501  (한국어 표·보고서 문자열)
"""EXP-009(R6) 수질자동측정망 일 단위 7일 추세 피처.

원자료: 국립환경과학원 수질 DB `getRealTimeWaterQualityList`(수질자동측정망 운영결과, 일평균) —
수집기 `algaecast.collect.nier_autowq` → `data/raw/nier_autowq/autowq_daily.parquet`.
5지점마다 최근접 본류 자동측정소(PRIMARY: 해평 S02012·다산 S02009·칠서 S02007·상동 S02017·대청호 S03003)를
쓰고, 'fill' 변형은 주 측정소 결측일을 차순위 본류 측정소(SECONDARY) 값으로 채운다(해평·칠서는 TN·TP 를 측정하지 않아
도개·청암 값이 들어간다).

새 피처(변수 v, 창 = [as_of − lag − 6, as_of − lag] 7일, 일평균 기준)
- aw_{v}_mean7  : 창 안 유효 일평균의 평균
- aw_{v}_slope7 : 창 안 일평균의 OLS 기울기(단위/일, 유효 3일 이상)
- aw_{v}_miss7  : 창 안 결측 일수 비율(0~1)
v ∈ wtemp(수온)·ph·do(용존산소)·ec(전기전도도)·toc·chla(클로로필-a)·turb(탁도)·tn·tp·do_pct(DO 포화도 %, 수온으로 계산).
묶음(BUNDLES)은 위 열의 부분집합 — bio4·core6·core6_nut(평균·기울기·결측률 모두), lvl3(chla·turb·toc 평균),
chla_ms(chla 평균·기울기), mean8(core6_nut 변수 평균).

as_of 규칙: 피처 함수는 진입 직후 features.base.cut_as_of(daily, as_of) 로 기준일 이후 행을 버리고, 다시 창으로 자른다.
lag=0 은 기준일 당일 일평균까지(v1 기상 일자료 *_t0 와 같은 규약), lag=1 은 전날까지만 쓴다. 원자료의 2026 행은 읽는 즉시
버린다(harness.LAST_DATE).

선택(CHOSEN, 2026-10-21): lag=1·lvl3·primary = aw_chla_mean7·aw_turb_mean7·aw_toc_mean7(전날까지 7일 평균).
채택 기준(CV r2_raw +0.10) 미달 — 보고서 reports/experiments/EXP-009/README.md.

공개 함수(종합 단계 재사용)
- build_features(df) -> DataFrame : df = harness.load_base() 형식, 같은 인덱스로 선택 설정(CHOSEN)의 새 열만 반환.
- build_variant_features(df, lag, source, variables) -> DataFrame : 임의 설정의 새 열.
- autowq_features(daily, as_of, lag, variables) -> dict : 순수 함수(한 지점·한 기준일).
- load_daily(source) -> DataFrame : 지점(station_id)별 일평균(2025-12-31 까지).

실행: python -m algaecast.exp.r6_autowq  (변형 OOF 는 data/processed/exp/EXP-009/variants/ 에 캐시)
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from collections.abc import Sequence
from datetime import date, datetime

import numpy as np
import pandas as pd

from algaecast.collect.nier_autowq import PRIMARY, SECONDARY, UNIFIED, haversine_km
from algaecast.config import RAW_DIR
from algaecast.eval.metrics import compute_all
from algaecast.exp import harness as H
from algaecast.features.base import cut_as_of

log = logging.getLogger(__name__)

EXP_ID = "EXP-009"
OUT_DATA = H.EXP_DATA / EXP_ID
OUT_REPORT = H.EXP_REPORTS / EXP_ID
RAW_PATH = RAW_DIR / "nier_autowq" / "autowq_daily.parquet"
STATIONS_PATH = RAW_DIR / "nier_autowq" / "stations.csv"
BUDGET_HOURS = 8.0
WINDOW = 7
MIN_SLOPE_POINTS = 3
SITES = ("HP", "GJGR", "CS", "MGMR", "DCHN")
SITE_NAMES = {"HP": "해평", "GJGR": "강정·고령", "CS": "칠서", "MGMR": "물금·매리", "DCHN": "회남(대청호)"}
# 조류경보 지점 좌표(WGS84) — 물환경정보시스템 GIS 층 I002 '상수원구간'(2026-10-21 조회)
SITE_COORDS: dict[str, tuple[float, float]] = {
    "HP": (36.1949, 128.3652),
    "GJGR": (35.8660, 128.3839),
    "CS": (35.3853, 128.4489),
    "MGMR": (35.3483, 128.9335),
    "DCHN": (36.4314, 127.5522),
}
DAILY_VARS = ("wtemp", "ph", "do", "ec", "toc", "chla", "turb", "tn", "tp", "do_pct")
STATS = ("mean7", "slope7", "miss7")
SOURCES = ("primary", "fill")
VAR_SETS: dict[str, tuple[str, ...]] = {
    "bio4": ("chla", "do_pct", "ph", "wtemp"),
    "core6": ("wtemp", "ph", "do", "ec", "toc", "chla"),
    "core6_nut": ("wtemp", "ph", "do", "ec", "toc", "chla", "tn", "tp"),
}


def columns_for(variables: Sequence[str]) -> list[str]:
    """변수 목록 → 평균·기울기·결측률 3종 열 이름."""
    return [f"aw_{v}_{s}" for v in variables for s in STATS]


def variables_of(cols: Sequence[str]) -> list[str]:
    """열 이름(aw_{v}_{stat}) → 변수 목록(순서 유지, 중복 제거)."""
    out: list[str] = []
    for c in cols:
        v = c[3:].rsplit("_", 1)[0]
        if v not in out:
            out.append(v)
    return out


# 묶음 = 새 피처 열 집합
BUNDLES: dict[str, tuple[str, ...]] = {
    **{k: tuple(columns_for(v)) for k, v in VAR_SETS.items()},
    # 2차(1차 8변형이 모두 기준선 미만 → 열 수를 줄인 묶음. 근거: CV 행의 v1 잔차–피처 순위상관 진단, 보고서 3절)
    "lvl3": ("aw_chla_mean7", "aw_turb_mean7", "aw_toc_mean7"),
    "chla_ms": ("aw_chla_mean7", "aw_chla_slope7"),
    "mean8": tuple(f"aw_{v}_mean7" for v in VAR_SETS["core6_nut"]),
}
# (lag, 묶음, 원천) — 1차 2 × 4 = 8 변형 + 2차 2 × 3 = 6 변형
VARIANTS_1: tuple[tuple[int, str, str], ...] = tuple(
    (lag, b, s)
    for lag in (0, 1)
    for b, s in (("bio4", "primary"), ("core6", "primary"), ("core6_nut", "primary"), ("core6_nut", "fill"))
)
VARIANTS_2: tuple[tuple[int, str, str], ...] = tuple(
    (lag, b, s) for lag in (0, 1) for b, s in (("lvl3", "primary"), ("chla_ms", "primary"), ("mean8", "fill"))
)
VARIANTS = VARIANTS_1 + VARIANTS_2
DIAG_SEEDS = (43, 44)  # v1 피처 그대로 시드만 바꾼 재학습(잡음 폭 진단, 선택에 쓰지 않음)
TOP_SEED_CHECK = 3  # CV r2_raw 상위 변형도 같은 시드로 재학습해 시드 평균 비교(진단)
# 선택 결과(2026-10-21 main() 실행, EXP-PLAN 4절 규칙: 기준 만족 변형 없음 → CV r2_raw 최대 변형, '기준 미달')
CHOSEN: dict[str, object] = {"lag": 1, "bundle": "lvl3", "source": "primary"}


# ---------------------------------------------------------------- 원자료
def do_saturation(wtemp: np.ndarray | pd.Series) -> np.ndarray:
    """담수·1기압 DO 포화농도(mg/L), Benson & Krause(1984) 식(APHA 4500-O; 20 ℃ → 9.09 mg/L)."""
    tk = np.asarray(wtemp, dtype=float) + 273.15
    return np.exp(
        -139.34411 + 1.575701e5 / tk - 6.642308e7 / tk**2 + 1.243800e10 / tk**3 - 8.621949e11 / tk**4
    )


def add_derived(daily: pd.DataFrame) -> pd.DataFrame:
    """일평균 행 단위 파생(행 안에서만 계산 → as_of 규칙과 무관): do_pct = DO / 포화농도 × 100."""
    out = daily.copy()
    out["do_pct"] = 100.0 * out["do"].astype(float) / do_saturation(out["wtemp"])
    return out


def load_raw(last: pd.Timestamp = H.LAST_DATE) -> pd.DataFrame:
    """수집 원자료(측정소·일) — 2025-12-31 이후 행은 읽은 즉시 버린다."""
    raw = pd.read_parquet(RAW_PATH, columns=["site_id", "obs_date", *UNIFIED])
    raw["obs_date"] = pd.to_datetime(raw["obs_date"]).dt.normalize()
    return raw[raw["obs_date"] <= last].reset_index(drop=True)


def load_daily(source: str = "primary", raw: pd.DataFrame | None = None) -> pd.DataFrame:
    """지점(station_id)별 일평균. source='fill' 이면 주 측정소 결측 칸을 차순위 측정소 값으로 채운다."""
    if source not in SOURCES:
        raise ValueError(source)
    raw = load_raw() if raw is None else raw
    raw = raw[raw["obs_date"] <= H.LAST_DATE]
    cols = list(UNIFIED)
    frames = []
    for sid in SITES:
        p = raw[raw["site_id"] == PRIMARY[sid]].set_index("obs_date")[cols].sort_index()
        if source == "fill":
            s = raw[raw["site_id"] == SECONDARY[sid]].set_index("obs_date")[cols].sort_index()
            p = p.combine_first(s)
        p = add_derived(p.reset_index())
        p["station_id"] = sid
        frames.append(p)
    return pd.concat(frames, ignore_index=True).sort_values(["station_id", "obs_date"]).reset_index(drop=True)


# ---------------------------------------------------------------- 순수 피처 함수
def autowq_features(
    daily: pd.DataFrame, as_of: date, *, lag: int = 0, variables: Sequence[str] = VAR_SETS["core6"]
) -> dict[str, float]:
    """한 지점 일평균(obs_date + 변수 열) → 창 [as_of − lag − 6, as_of − lag] 의 평균·기울기·결측률.

    진입 직후 cut_as_of(as_of) 로 기준일 이후 행을 버린다(lag ≥ 0 이므로 창은 항상 as_of 이전).
    """
    if lag < 0:
        raise ValueError("lag 는 0 이상")
    d = cut_as_of(daily, as_of)
    end = pd.Timestamp(as_of) - pd.Timedelta(days=int(lag))
    start = end - pd.Timedelta(days=WINDOW - 1)
    od = pd.to_datetime(d["obs_date"]).dt.normalize()
    w = d.loc[(od >= start) & (od <= end)]
    x = (pd.to_datetime(w["obs_date"]).dt.normalize() - end).dt.days.to_numpy(dtype=float)
    out: dict[str, float] = {}
    for v in variables:
        y = w[v].to_numpy(dtype=float) if v in w.columns else np.full(len(w), np.nan)
        ok = np.isfinite(y)
        n_days = len(np.unique(x[ok]))
        out[f"aw_{v}_mean7"] = float(y[ok].mean()) if ok.any() else math.nan
        if n_days >= MIN_SLOPE_POINTS:
            out[f"aw_{v}_slope7"] = float(np.polyfit(x[ok], y[ok], 1)[0])
        else:
            out[f"aw_{v}_slope7"] = math.nan
        out[f"aw_{v}_miss7"] = 1.0 - n_days / WINDOW
    return out


# ---------------------------------------------------------------- 표 단위 생성
def build_variant_features(
    df: pd.DataFrame,
    lag: int,
    source: str,
    variables: Sequence[str] = DAILY_VARS,
    *,
    daily: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """df(load_base 형식)의 각 행에 autowq_features 를 적용(같은 인덱스)."""
    H.guard_no_2026(df)
    daily = load_daily(source) if daily is None else daily
    by_site = {s: g.reset_index(drop=True) for s, g in daily.groupby("station_id")}
    empty = daily.iloc[0:0]
    recs = [
        autowq_features(by_site.get(sid, empty), bd, lag=lag, variables=variables)
        for sid, bd in zip(df["station_id"].astype(str), pd.to_datetime(df["base_date"]).dt.date, strict=True)
    ]
    return pd.DataFrame(recs, index=df.index)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """선택한 설정(CHOSEN)의 새 피처만(같은 인덱스). df = harness.load_base() 형식."""
    cols = list(BUNDLES[str(CHOSEN["bundle"])])
    full = build_variant_features(df, int(CHOSEN["lag"]), str(CHOSEN["source"]), variables_of(cols))
    return full[cols]


# ---------------------------------------------------------------- 실험 실행
def variant_label(lag: int, bundle: str, source: str) -> str:
    return f"R6 lag={lag} {bundle} {source}"


def _variant_key(lag: int, bundle: str, source: str) -> str:
    return f"lag{lag}_{bundle}_{source}"


def run_variant(
    df: pd.DataFrame, feats: pd.DataFrame, lag: int, bundle: str, source: str, *, seed: int | None = None
) -> tuple[dict, dict[str, np.ndarray]]:
    """v1 30개 + 새 피처로 C1·C3·C2·분위 재학습 → 확장 NNLS 앙상블 → 표준 지표(캐시 사용).

    seed=None 이면 v1 시드(config/seed.yaml), 정수면 LightGBM 시드만 바꾼 진단용 재학습.
    """
    new_cols = list(BUNDLES[bundle])
    key = _variant_key(lag, bundle, source) + ("" if seed is None else f"_seed{seed}")
    sig = hashlib.sha1(
        pd.util.hash_pandas_object(feats[new_cols], index=False).to_numpy().tobytes()
    ).hexdigest()[:12]
    cache = OUT_DATA / "variants" / f"{key}_{sig}.parquet"
    if cache.exists():
        o = pd.read_parquet(cache)
        mem = {k: o[k].to_numpy(dtype=float) for k in o.columns if k not in ("station_id", "base_date")}
    else:
        d2 = pd.concat([df, feats[new_cols]], axis=1)
        H.guard_no_2026(d2)
        kw = {} if seed is None else {"seeds": (seed,)}
        mem = H.run_members(d2, H.base_columns() + new_cols, **kw)
        ens, _ = H.ensemble_expanding(d2, mem)
        mem["ens"] = ens
        cache.parent.mkdir(parents=True, exist_ok=True)
        o = df[["station_id", "base_date"]].astype(str).copy()
        for k, v in mem.items():
            o[k] = v
        o.to_parquet(cache, index=False)
    label = variant_label(lag, bundle, source) + ("" if seed is None else f" (진단·시드 {seed})")
    row = H.metric_row(df, mem["ens"], mem["q90"], label)
    row.update({"lag": lag, "bundle": bundle, "source": source, "n_new": len(new_cols)})
    return row, mem


def run_seed_diag(df: pd.DataFrame, seed: int) -> dict:
    """진단: v1 피처·설정 그대로 LightGBM 시드만 바꾼 재학습(분위 q90 은 시드 인자가 없어 v1 과 같다)."""
    cache = OUT_DATA / "variants" / f"diag_v1_seed{seed}.parquet"
    if cache.exists():
        o = pd.read_parquet(cache)
        mem = {k: o[k].to_numpy(dtype=float) for k in o.columns if k not in ("station_id", "base_date")}
    else:
        mem = H.run_members(df, H.base_columns(), seeds=(seed,))
        mem["ens"], _ = H.ensemble_expanding(df, mem)
        cache.parent.mkdir(parents=True, exist_ok=True)
        o = df[["station_id", "base_date"]].astype(str).copy()
        for k, v in mem.items():
            o[k] = v
        o.to_parquet(cache, index=False)
    return H.metric_row(df, mem["ens"], mem["q90"], f"(진단) v1 피처·시드 {seed}")


def _seed_summary(label: str, per_seed: list[dict]) -> dict:
    """시드 42(v1)·43·44 의 CV r2_raw·rmse_log 와 평균(진단)."""
    seeds = (42, *DIAG_SEEDS)
    rec: dict = {"구성": label}
    for s, r in zip(seeds, per_seed, strict=False):
        rec[f"r2_raw 시드{s}"] = float(r["cv_r2_raw"])
    rec["r2_raw 평균"] = float(np.mean([r["cv_r2_raw"] for r in per_seed]))
    rec["rmse_log 평균"] = float(np.mean([r["cv_rmse_log"] for r in per_seed]))
    rec["리드타임(q90)"] = f"{per_seed[0].get('lead_q90')}/{per_seed[0].get('lead_n')}"
    return rec


def choose(base: dict, rows: list[dict]) -> tuple[dict, dict, bool]:
    """EXP-PLAN 4절: 채택 기준을 만족하는 변형 중 CV r2_raw 최대, 없으면 CV r2_raw 최대(기준 미달)."""
    ok = [r for r in rows if H.adoption(base, r)["pass"]]
    pool = ok or rows
    best = max(pool, key=lambda r: r["cv_r2_raw"])
    return best, H.adoption(base, best), bool(ok)


# ---------------------------------------------------------------- 보고용 집계(행 단위 값 노출 없음)
def station_table() -> pd.DataFrame:
    """5지점별 최근접 자동측정소 3곳(GIS 좌표 기준 직선거리)."""
    st = pd.read_csv(STATIONS_PATH, encoding="utf-8-sig", dtype={"install_year": str})
    st = st.dropna(subset=["lat", "lon"])
    st["location_note"] = st["location_note"].fillna("")
    st["install_year"] = st["install_year"].fillna("")
    out = []
    for sid in SITES:
        la, lo = SITE_COORDS[sid]
        dist = st.apply(
            lambda r, la=la, lo=lo: haversine_km(la, lo, float(r["lat"]), float(r["lon"])), axis=1
        )
        top = st.assign(km=dist).sort_values("km").head(3)
        for rank, (_, r) in enumerate(top.iterrows(), start=1):
            role = (
                "주(PRIMARY)"
                if r["site_id"] == PRIMARY[sid]
                else ("차순위(SECONDARY)" if r["site_id"] == SECONDARY[sid] else "–")
            )
            out.append(
                {
                    "지점": f"{SITE_NAMES[sid]}({sid})",
                    "순위": rank,
                    "측정소": f"{r['site_name']}({r['site_id']})",
                    "거리 km": float(r["km"]),
                    "설치": str(r.get("install_year", "")),
                    "위치 설명": str(r.get("location_note") or "")[:40],
                    "역할": role,
                }
            )
        if SECONDARY[sid] not in set(top["site_id"]):
            r = st[st["site_id"] == SECONDARY[sid]].iloc[0]
            out.append(
                {
                    "지점": f"{SITE_NAMES[sid]}({sid})",
                    "순위": "–",
                    "측정소": f"{r['site_name']}({r['site_id']})",
                    "거리 km": haversine_km(la, lo, float(r["lat"]), float(r["lon"])),
                    "설치": str(r.get("install_year", "")),
                    "위치 설명": str(r.get("location_note") or "")[:40],
                    "역할": "차순위(SECONDARY)",
                }
            )
    return pd.DataFrame(out)


def availability_table(raw: pd.DataFrame, years: tuple[int, int] = (2016, 2025)) -> pd.DataFrame:
    """주·차순위 측정소별 항목 가용성: 첫·끝 연도와 years 구간 일 단위 가용률(%)."""
    y0, y1 = years
    out = []
    n_days = (pd.Timestamp(f"{y1}-12-31") - pd.Timestamp(f"{y0}-01-01")).days + 1
    for sid in SITES:
        for role, code in (("주", PRIMARY[sid]), ("차순위", SECONDARY[sid])):
            g = raw[raw["site_id"] == code]
            rec: dict = {"지점": sid, "역할": role, "측정소": code}
            yr = g["obs_date"].dt.year
            in_rng = g[(yr >= y0) & (yr <= y1)]
            for v in ("wtemp", "ph", "do", "ec", "toc", "chla", "turb", "tn", "tp"):
                ok = g[v].notna()
                if ok.any():
                    rec[v] = f"{100 * in_rng[v].notna().sum() / n_days:.0f}% ({yr[ok].min()}~)"
                else:
                    rec[v] = "없음"
            out.append(rec)
    return pd.DataFrame(out)


def coverage_table(df: pd.DataFrame, feats: pd.DataFrame, variables: Sequence[str]) -> pd.DataFrame:
    """학습·검증 행(≤2025) 중 각 변수 mean7 이 있는 행 비율(지점별)."""
    sid = df["station_id"].astype(str)
    out = []
    for s in SITES:
        m = sid == s
        rec: dict = {"지점": s, "행": int(m.sum())}
        for v in variables:
            rec[v] = float(feats.loc[m, f"aw_{v}_mean7"].notna().mean()) if m.any() else math.nan
        out.append(rec)
    return pd.DataFrame(out)


def site_metrics(df: pd.DataFrame, preds: dict[str, np.ndarray]) -> pd.DataFrame:
    """지점별 CV(2020~2024) r2_raw·rmse_log(집계값만)."""
    cv_mask, _ = H.masks(df)
    obs = df["target_cells"].to_numpy(dtype=float)
    sid = df["station_id"].astype(str).to_numpy()
    out = []
    for s in SITES:
        m = cv_mask & (sid == s)
        rec: dict = {"지점": s, "n": int(m.sum())}
        for name, p in preds.items():
            mm = compute_all(obs[m], p[m])
            rec[f"{name} r2_raw"] = float(mm["r2_raw"])
            rec[f"{name} rmse_log"] = float(mm["rmse_log"])
        out.append(rec)
    return pd.DataFrame(out)


def residual_corr(df: pd.DataFrame, base_pred: np.ndarray, feats: pd.DataFrame) -> pd.DataFrame:
    """진단: CV(2020~2024) 행에서 각 새 피처(평균·기울기)와 log10 타깃·v1 log 잔차의 Spearman 상관."""
    cv_mask, _ = H.masks(df)
    obs = np.log10(df["target_cells"].to_numpy(dtype=float) + 1)
    res = obs - np.log10(np.asarray(base_pred, dtype=float) + 1)
    out = []
    for c in feats.columns:
        if c.endswith("miss7"):
            continue
        x = feats[c].to_numpy(dtype=float)
        m = cv_mask & np.isfinite(x)
        out.append(
            {
                "피처": c,
                "n": int(m.sum()),
                "ρ(log 타깃)": float(pd.Series(obs[m]).corr(pd.Series(x[m]), method="spearman")),
                "ρ(v1 잔차)": float(pd.Series(res[m]).corr(pd.Series(x[m]), method="spearman")),
            }
        )
    t = pd.DataFrame(out)
    return t.reindex(t["ρ(v1 잔차)"].abs().sort_values(ascending=False).index).reset_index(drop=True)


def bootstrap_delta(
    df: pd.DataFrame, base: np.ndarray, cand: np.ndarray, n: int = 1000, seed: int = 42
) -> dict[str, float]:
    """CV 행 재표본(복원) 1,000회로 Δr2_raw·Δrmse_log 의 2.5·97.5% 구간(진단용, 선택에 쓰지 않음)."""
    cv_mask, _ = H.masks(df)
    obs = df["target_cells"].to_numpy(dtype=float)[cv_mask]
    b, c = base[cv_mask], cand[cv_mask]
    rng = np.random.default_rng(seed)

    def r2(o: np.ndarray, p: np.ndarray) -> float:
        return 1.0 - float(np.sum((o - p) ** 2)) / float(np.sum((o - o.mean()) ** 2))

    def rmse_log(o: np.ndarray, p: np.ndarray) -> float:
        return float(np.sqrt(np.mean((np.log10(o + 1) - np.log10(p + 1)) ** 2)))

    d_r2, d_rm = [], []
    for _ in range(n):
        i = rng.integers(0, len(obs), len(obs))
        d_r2.append(r2(obs[i], c[i]) - r2(obs[i], b[i]))
        d_rm.append(rmse_log(obs[i], c[i]) - rmse_log(obs[i], b[i]))
    return {
        "d_r2_raw_lo": float(np.percentile(d_r2, 2.5)),
        "d_r2_raw_hi": float(np.percentile(d_r2, 97.5)),
        "p_d_r2_raw_le0": float(np.mean(np.array(d_r2) <= 0)),
        "d_rmse_log_lo": float(np.percentile(d_rm, 2.5)),
        "d_rmse_log_hi": float(np.percentile(d_rm, 97.5)),
    }


def md_table(t: pd.DataFrame, nd: int = 3) -> str:
    cols = list(t.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "---|" * len(cols)]
    for _, r in t.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, float | np.floating):
                cells.append("–" if not np.isfinite(v) else f"{v:.{nd}f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    budget = H.Budget(BUDGET_HOURS, EXP_ID)
    started = datetime.now()
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.mkdir(parents=True, exist_ok=True)

    df = H.load_base()
    H.guard_no_2026(df)
    _, bl = H.load_baseline()
    base_row = H.metric_row(df, bl["ens"], bl["q90"], "v1 기준(하네스 재현)")

    raw = load_raw()
    feats: dict[tuple[int, str], pd.DataFrame] = {}
    t0 = time.time()
    for source in SOURCES:
        daily = load_daily(source, raw)
        for lag in (0, 1):
            feats[(lag, source)] = build_variant_features(df, lag, source, DAILY_VARS, daily=daily)
    log.info("피처 생성 %.1f초", time.time() - t0)

    rows: list[dict] = []
    mems: dict[str, dict[str, np.ndarray]] = {}
    status = "completed"
    try:
        for lag, bundle, source in VARIANTS:
            budget.check()
            t1 = time.time()
            row, mem = run_variant(df, feats[(lag, source)], lag, bundle, source)
            rows.append(row)
            mems[_variant_key(lag, bundle, source)] = mem
            log.info(
                "%s: CV r2_raw %.3f rmse_log %.3f lead %s/%s | 2025 r2_raw %.3f (%.0fs)",
                row["구성"],
                row["cv_r2_raw"],
                row["cv_rmse_log"],
                row.get("lead_q90"),
                row.get("lead_n"),
                row["y2025_r2_raw"],
                time.time() - t1,
            )
    except H.BudgetExceeded as e:
        log.warning("%s", e)
        status = "time_cap"

    diag_rows: list[dict] = []
    seed_tab: list[dict] = []
    if status == "completed":
        try:
            for sd in DIAG_SEEDS:
                budget.check()
                diag_rows.append(run_seed_diag(df, sd))
                log.info("%s: CV r2_raw %.3f", diag_rows[-1]["구성"], diag_rows[-1]["cv_r2_raw"])
            seed_tab.append(_seed_summary("v1 기준", [base_row, *diag_rows]))
            for r in sorted(rows, key=lambda r: -r["cv_r2_raw"])[:TOP_SEED_CHECK]:
                per = [r]
                for sd in DIAG_SEEDS:
                    budget.check()
                    rr, _ = run_variant(
                        df, feats[(r["lag"], r["source"])], r["lag"], r["bundle"], r["source"], seed=sd
                    )
                    diag_rows.append(rr)
                    per.append(rr)
                    log.info("%s: CV r2_raw %.3f", rr["구성"], rr["cv_r2_raw"])
                seed_tab.append(_seed_summary(r["구성"], per))
        except H.BudgetExceeded as e:
            log.warning("%s", e)
            status = "time_cap"
    seed_t = pd.DataFrame(seed_tab)

    best, adop, met = choose(base_row, rows)
    bkey = _variant_key(best["lag"], best["bundle"], best["source"])
    bmem = mems[bkey]
    H.save_oof(
        df,
        {k: bmem[k] for k in ("c1", "c3", "c2", "q10", "q50", "q90")} | {"pred": bmem["ens"]},
        OUT_DATA / "chosen_oof.parquet",
    )
    fsel = feats[(best["lag"], best["source"])]
    fout = df[["station_id", "base_date"]].astype(str).copy()
    for c in BUNDLES[best["bundle"]]:
        fout[c] = fsel[c].to_numpy()
    fout.to_parquet(OUT_DATA / "features.parquet", index=False)

    site_t = site_metrics(df, {"v1": bl["ens"], "R6": bmem["ens"]})
    boot = bootstrap_delta(df, bl["ens"], bmem["ens"])
    cov = coverage_table(df, feats[(0, "fill")], VAR_SETS["core6_nut"])
    cov_p = coverage_table(df, feats[(0, "primary")], VAR_SETS["core6_nut"])
    resid = residual_corr(df, bl["ens"], feats[(0, "fill")])
    stt = station_table()
    avail = availability_table(raw)
    meta = {
        "exp_id": EXP_ID,
        "status": status,
        "started": started.isoformat(timespec="seconds"),
        "finished": datetime.now().isoformat(timespec="seconds"),
        "elapsed_hours_run": budget.elapsed_h,
        "budget_hours": BUDGET_HOURS,
        "chosen": {"lag": best["lag"], "bundle": best["bundle"], "source": best["source"]},
        "chosen_label": best["구성"],
        "criteria_met_by_any": met,
        "adoption": adop,
        "bootstrap_cv_delta": boot,
    }
    (OUT_REPORT / "metrics.json").write_text(
        json.dumps(
            {"meta": meta, "rows": [base_row, *rows], "diagnostic_rows": diag_rows},
            ensure_ascii=False,
            indent=1,
            default=float,
        )
        + "\n",
        encoding="utf-8",
    )
    tables = {
        "stations": stt.to_dict(orient="records"),
        "availability": avail.to_dict(orient="records"),
        "coverage_fill_lag0": cov.to_dict(orient="records"),
        "coverage_primary_lag0": cov_p.to_dict(orient="records"),
        "site_metrics": site_t.to_dict(orient="records"),
        "residual_corr": resid.to_dict(orient="records"),
        "seed_check": seed_t.to_dict(orient="records"),
    }
    (OUT_DATA / "tables.json").write_text(
        json.dumps(tables, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8"
    )
    _write_draft(
        base_row, rows + diag_rows, best, adop, met, site_t, boot, stt, avail, cov, cov_p, meta, resid, seed_t
    )
    print(H.standard_table([base_row, best]))
    print(json.dumps(meta, ensure_ascii=False, indent=1, default=float))
    return 0


def _write_draft(
    base_row: dict,
    rows: list[dict],
    best: dict,
    adop: dict,
    met: bool,
    site_t: pd.DataFrame,
    boot: dict,
    stt: pd.DataFrame,
    avail: pd.DataFrame,
    cov: pd.DataFrame,
    cov_p: pd.DataFrame,
    meta: dict,
    resid: pd.DataFrame,
    seed_t: pd.DataFrame,
) -> None:
    """표·수치 초안(OUT_DATA/report_draft.md). 최종 README 는 이 초안을 바탕으로 해석을 덧붙여 쓴다."""
    srt = sorted(rows, key=lambda r: -r["cv_r2_raw"])
    grid = pd.DataFrame(
        [
            {
                "구성": r["구성"],
                "lag": r.get("lag", "–"),
                "묶음": r.get("bundle", "–"),
                "원천": r.get("source", "–"),
                "새 열": r.get("n_new", 0),
                "CV r2_raw": r["cv_r2_raw"],
                "CV nse_raw": r["cv_nse_raw"],
                "CV rmse_log": r["cv_rmse_log"],
                "CV r2_log": r["cv_r2_log"],
                "CV F1@10k": r["cv_f1_10k"],
                "리드타임": f"{r.get('lead_q90')}/{r.get('lead_n')}",
                "채택 기준": "통과" if H.adoption(base_row, r)["pass"] else "미달",
            }
            for r in srt
        ]
    )
    others = [r for r in rows if r is not best]
    txt = f"""# {EXP_ID} 초안

## 측정소

{md_table(stt, 1)}
## 가용성

{md_table(avail)}
## 행 커버리지(fill, lag0)

{md_table(cov, 2)}
## 행 커버리지(primary, lag0)

{md_table(cov_p, 2)}
## 표준 표

{H.standard_table([base_row, best, *others])}
## 보조 표

{H.detail_table([base_row, best, *others])}
## 전체 변형

{md_table(grid)}
## 지점별 CV

{md_table(site_t)}
## 시드 점검(진단, CV)

{md_table(seed_t) if len(seed_t) else "(없음)"}
## 잔차 상관(CV 행, v1 log 잔차 vs 새 피처, Spearman)

{md_table(resid)}
## 부트스트랩

{json.dumps(boot, ensure_ascii=False)}

## 판정

선택: {best['구성']} / {json.dumps(adop, ensure_ascii=False, default=float)} / 기준 만족 변형 존재: {met}

## 메타

{json.dumps(meta, ensure_ascii=False, default=float)}
"""
    (OUT_DATA / "report_draft.md").write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
