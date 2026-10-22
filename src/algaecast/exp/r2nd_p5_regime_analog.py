# ruff: noqa: E501  (한국어 표·보고서 문자열)
"""EXP-005(2차) P5 — 국면 분류·국면별 회귀(mixture of experts), 아날로그 kNN 구성원, 전년도·평년 대비 피처.

기준 모델 C(harness2: v1 로그 앙상블 + R2 상류 5열 + R3 속별 구성원 cg, 분위 v1 동결)에 세 갈래를 각각 더해 비교한다.
선택은 2020~2024 CV OOF 의 탐색 시드(harness2.EXPLORE_SEEDS) 평균만으로 하고, 2025 는 보고만 한다(판정 시드 미사용).

A. 국면(as_of 까지의 측정만, 규칙 기반 — 결과를 보기 전에 고정)
   L0·L1 = base_date 이하 최근 두 유효 측정의 log10(세포수+1), d = L0 − L1.
   증가: d ≥ 0.3 이고 L0 ≥ 2.0 / 감소: d ≤ −0.3 이고 L1 ≥ 3.0 / 정점(고수준 정체): |d| < 0.3 이고 L0 ≥ 3.0 / 평온: 그 밖.
   변형: A1 국면 코드 피처 1열 / A2 국면별 NNLS 가중치(게이트) / A3 국면별 C1 전문가 4개(E4)를 NNLS 구성원으로 /
   A4 평온·활성 전문가 2개(E2). 대조군: 피처는 같은 결측 위치 난수, 게이트·전문가는 같은 비율의 무작위 국면 표지.
B. 아날로그 kNN 구성원: 각 폴드의 학습 행(기준일 연도 < 검증 연도)만 이웃 후보, 이웃의 목표값으로 예측.
   거리 = 최근 3회 궤적(L0·L1·L2)·계절(기준일 doy sin·cos)·수온(wtemp_t0)·체류시간(log1p weir_residence_proxy,
   지점별 표준화)의 결측 인지 가중 유클리드(표준화 통계는 후보 행으로만). 지점: site = 같은 지점 우선(부족하면 다른 지점),
   all = 다른 지점에 벌점 2.0. 집계: log = 이웃 목표 log10 평균, raw = 원단위 평균, delta = 자기 L0 + 이웃 (목표 − L0) 평균.
   k ∈ {5, 10, 20, 40} × 지점 × 집계를 CV(C + kNN NNLS 의 시드 평균 CV r2_raw)로 고른다. 대조군: 같은 풀의 무작위 k 이웃.
C. 전년도·평년 피처(as_of 규칙, 평년은 기준일 연도 이전 연도만 → 어느 폴드에서도 검증 연도 제외):
   hy_prev_max(전년도 최고 log10 세포수), hy_ytd_mean(올해 1/1~as_of 일 단위 이월 log10 평균 = 누적 강도),
   hy_ytd_max(같은 구간 최고), hy_ytd_mean_anom·hy_ytd_max_anom(과거 연도의 같은 날짜까지 값의 평균 대비, 2년 이상).
   변형 H1 = 전년도 최고 1열, H2 = 올해 누적 4열, H3 = 5열 전부. 대조군: 같은 열 수·결측 위치의 난수.

선택 규칙(CV 만, 결과 보기 전 고정): 시드 평균 ΔC CV r2_raw 최대, 단 (i) ΔC CV rmse_log ≤ +0.01,
(ii) 리드타임 시드 평균 ≥ 18, (iii) 고유 효과 Δ − Δ(대조군) > 0. 적격 변형이 없으면 C 유지.
이어 다른 갈래의 최고 적격 변형을 하나씩 더해 보고, 시드 평균 CV r2_raw 가 +0.01 이상 오르고 (i)~(iii)을 지키면 결합한다.

공개 함수(종합 단계 재사용)
- build_features(df) -> DataFrame: 선택 설정(CHOSEN)의 새 피처 열(같은 인덱스, 선택 설정에 피처가 없으면 열 0개).
- members(df, seed) -> dict: 선택 설정의 OOF 구성원(c1·c3·c2·cg + knn/moe).
- builder(df, seed) -> {"pred", "q90": None(= v1 동결), "m_*"}: harness2.Builder 형식.
- make_builder(cfg) / P5Config / KnnCfg: 임의 설정의 Builder.
- state_features·history_features: (원자료 한 지점, as_of) -> dict 순수 함수(진입 직후 cut_as_of).
- knn_member·gated_ensemble·expert_member, regime_groups(df) -> 국면 코드(게이트의 groups).
- 선택 설정(CHOSEN) = A2 국면별 NNLS 게이트: C 구성원 그대로, 결합만 gated_ensemble(df, mem, regime_groups(df)).

실행: python -m algaecast.exp.r2nd_p5_regime_analog → reports/experiments/EXP-005/P5/(tables.md·metrics.json),
data/processed/exp/EXP-005b/P5/(피처·kNN 구성원·선택 OOF), 캐시 data/processed/exp/EXP-005b/cache/P5_*.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache

import numpy as np
import pandas as pd

from algaecast.exp import confirm as CF
from algaecast.exp import harness as H
from algaecast.exp import harness2 as H2
from algaecast.exp import r2_upstream as R2
from algaecast.exp import r_combo as RC
from algaecast.features.base import cut_as_of
from algaecast.models.ensemble import combine, nnls_weights

log = logging.getLogger(__name__)

PX = "P5"
OUT_DATA = H2.EXP_DIR / PX
OUT_REPORT = H2.REPORT_DIR / PX
FEATURES_PATH = OUT_DATA / "features.parquet"
BUDGET_HOURS = 8.0
TASK_START = "2026-10-22 12:11:58"  # 작업 착수(KST) — 시간 상한 기준

# ---------------------------------------------------------------- A. 국면
HIGH = 3.0  # log10(1,000+1) 근처 — 관심 단계
RISE_FLOOR = 2.0  # 증가 판정 최소 수준(log10 ≈ 100 세포/mL)
DELTA = 0.3  # log10 변화 문턱(약 2배)
REGIMES: dict[int, str] = {0: "평온", 1: "증가", 2: "정점", 3: "감소"}
STATE_COLS = ["st_L0", "st_L1", "st_L2", "st_d01", "st_max4w", "st_regime"]
MIN_EXPERT_ROWS = 100  # 국면 전문가 학습 행 최소(미만이면 C 의 c1 으로 대신)
MIN_GATE_ROWS = 50  # 국면별 NNLS 적합 행 최소(미만이면 전체 가중치)

# ---------------------------------------------------------------- B. kNN
KNN_KS: tuple[int, ...] = (5, 10, 20, 40)
KNN_POOLS: tuple[str, ...] = ("site", "all")
KNN_AGGS: tuple[str, ...] = ("log", "raw", "delta")
SITE_PENALTY = 2.0  # pool=all 에서 다른 지점 이웃의 거리 벌점(가중 제곱거리 단위)
OTHER_SITE_FAR = 1e6  # pool=site 에서 다른 지점은 같은 지점 후보가 모자랄 때만
KNN_DIMS: tuple[str, ...] = ("L0", "L1", "L2", "s_sin", "s_cos", "wtemp", "res")
KNN_W = np.array([1.0, 1.0, 1.0, 0.5, 0.5, 1.0, 1.0])

# ---------------------------------------------------------------- C. 전년도·평년
HIST_COLS = ["hy_prev_max", "hy_ytd_mean", "hy_ytd_max", "hy_ytd_mean_anom", "hy_ytd_max_anom"]
MIN_NORMAL_YEARS = 2
COVER_DAYS = 31  # 평년 계산 연도는 그해 1/1 + 31일 안에 측정이 시작돼 있어야 한다

FEATURE_SETS: dict[str, list[str]] = {
    "A1": ["st_regime"],
    "H1": ["hy_prev_max"],
    "H2": ["hy_ytd_mean", "hy_ytd_max", "hy_ytd_mean_anom", "hy_ytd_max_anom"],
    "H3": list(HIST_COLS),
}

# ---------------------------------------------------------------- 선택 규칙
RMSE_SLACK = 0.01
LEAD_MIN = 18.0
MIN_GAIN = 0.01
SALT_GATE, SALT_EXPERT = 1, 2  # 무작위 국면 표지 생성기 구분


# ================================================================ 원자료
def load_algae() -> pd.DataFrame:
    """조류경보 원자료 5지점(station_id·obs_date·cells·wtemp). 2025-12-31 이후 측정은 읽은 즉시 버린다."""
    return R2.load_algae()


def _site_frames(algae: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        str(s): g[["obs_date", "cells"]].reset_index(drop=True)
        for s, g in algae.groupby("station_id", observed=True)
    }


def _log_series(d: pd.DataFrame) -> pd.Series:
    """(이미 as_of 로 자른) 측정 → 유효 세포수의 log10(세포수+1) 시계열(날짜 오름차순, 같은 날은 마지막)."""
    d = d[d["cells"].notna()]
    if d.empty:
        return pd.Series(dtype=float)
    vals = np.log10(np.clip(d["cells"].to_numpy(dtype=float), 0.0, None) + 1.0)
    s = pd.Series(vals, index=pd.DatetimeIndex(pd.to_datetime(d["obs_date"])).normalize())
    return s.sort_index(kind="stable").groupby(level=0).last()


# ================================================================ A. 국면(순수 함수)
def regime_code(l0: float, l1: float) -> int:
    """규칙 기반 국면: 0 평온, 1 증가, 2 정점(고수준 정체), 3 감소."""
    if not np.isfinite(l0):
        return 0
    if not np.isfinite(l1):
        l1 = l0
    d = l0 - l1
    if d >= DELTA and l0 >= RISE_FLOOR:
        return 1
    if d <= -DELTA and l1 >= HIGH:
        return 3
    if abs(d) < DELTA and l0 >= HIGH:
        return 2
    return 0


def state_features(algae_site: pd.DataFrame, as_of: date) -> dict[str, float]:
    """한 지점 측정 원자료(obs_date·cells) → as_of 기준 최근 3회 궤적·4주 최고·국면 코드."""
    d = cut_as_of(algae_site, as_of)
    s = _log_series(d)
    out: dict[str, float] = dict.fromkeys(STATE_COLS, math.nan)
    if s.empty:
        out["st_regime"] = 0.0
        return out
    v = s.to_numpy(dtype=float)
    l0 = float(v[-1])
    l1 = float(v[-2]) if len(v) > 1 else math.nan
    l2 = float(v[-3]) if len(v) > 2 else math.nan
    w = s[s.index > pd.Timestamp(as_of) - pd.Timedelta(days=28)]
    out.update(
        {
            "st_L0": l0,
            "st_L1": l1,
            "st_L2": l2,
            "st_d01": l0 - l1 if np.isfinite(l1) else math.nan,
            "st_max4w": float(w.max()) if len(w) else math.nan,
            "st_regime": float(regime_code(l0, l1)),
        }
    )
    return out


# ================================================================ C. 전년도·평년(순수 함수)
def _window_stats(daily: pd.Series, lo: pd.Timestamp, hi: pd.Timestamp) -> tuple[float, float]:
    w = daily.loc[lo:hi].dropna()
    if w.empty:
        return math.nan, math.nan
    return float(w.mean()), float(w.max())


def history_features(algae_site: pd.DataFrame, as_of: date) -> dict[str, float]:
    """한 지점 측정 원자료 → 전년도 최고·올해 누적 강도·같은 날짜까지의 평년 대비.

    일 단위 이월(ffill) log10 세포수로 올해 1/1(또는 첫 측정)~as_of 평균·최고를 구한다. 평년은 as_of 연도보다 앞선
    연도(그해 1/1 + 31일 안에 측정이 시작된 해)의 같은 날짜까지 값의 평균이고, 2년 이상일 때만 편차를 낸다.
    """
    d = cut_as_of(algae_site, as_of)
    s = _log_series(d)
    out: dict[str, float] = dict.fromkeys(HIST_COLS, math.nan)
    if s.empty:
        return out
    t = pd.Timestamp(as_of).normalize()
    yr = t.year
    prev = s[s.index.year == yr - 1]
    if len(prev):
        out["hy_prev_max"] = float(prev.max())
    first = s.index[0]
    daily = s.reindex(pd.date_range(first, t, freq="D")).ffill()
    jan1 = pd.Timestamp(yr, 1, 1)
    m, x = _window_stats(daily, max(jan1, first), t)
    out["hy_ytd_mean"], out["hy_ytd_max"] = m, x
    offset = t - jan1
    nm: list[float] = []
    nx: list[float] = []
    for y in range(first.year, yr):
        start = pd.Timestamp(y, 1, 1)
        if first > start + pd.Timedelta(days=COVER_DAYS):
            continue
        end = min(start + offset, pd.Timestamp(y, 12, 31))
        a, b = _window_stats(daily, max(start, first), end)
        if np.isfinite(a):
            nm.append(a)
            nx.append(b)
    if len(nm) >= MIN_NORMAL_YEARS and np.isfinite(m):
        out["hy_ytd_mean_anom"] = m - float(np.mean(nm))
        out["hy_ytd_max_anom"] = x - float(np.mean(nx))
    return out


# ================================================================ 표 단위 생성
def _rows(df: pd.DataFrame) -> list[tuple[str, date]]:
    return list(zip(df["station_id"].astype(str), pd.to_datetime(df["base_date"]).dt.date, strict=True))


def build_state(df: pd.DataFrame, algae: pd.DataFrame | None = None) -> pd.DataFrame:
    """df 각 행의 state_features(같은 인덱스)."""
    sites = _site_frames(load_algae() if algae is None else algae)
    empty = pd.DataFrame({"obs_date": pd.to_datetime([]), "cells": []})
    recs = [state_features(sites.get(s, empty), bd) for s, bd in _rows(df)]
    return pd.DataFrame(recs, index=df.index, columns=STATE_COLS)


def build_history(df: pd.DataFrame, algae: pd.DataFrame | None = None) -> pd.DataFrame:
    """df 각 행의 history_features(같은 인덱스)."""
    sites = _site_frames(load_algae() if algae is None else algae)
    empty = pd.DataFrame({"obs_date": pd.to_datetime([]), "cells": []})
    recs = [history_features(sites.get(s, empty), bd) for s, bd in _rows(df)]
    return pd.DataFrame(recs, index=df.index, columns=HIST_COLS)


def build_all_features(df: pd.DataFrame, algae: pd.DataFrame | None = None) -> pd.DataFrame:
    """P5 새 열 전체(국면 상태 + 전년도·평년). df = harness.load_base() 형식."""
    H.guard_no_2026(df)
    algae = load_algae() if algae is None else algae
    return pd.concat([build_state(df, algae), build_history(df, algae)], axis=1)


def load_p5_features(df: pd.DataFrame) -> pd.DataFrame:
    """저장한 P5 새 열(키 대조 후). 없거나 키가 다르면 새로 만들어 저장한다."""
    if FEATURES_PATH.exists():
        f = pd.read_parquet(FEATURES_PATH)
        same = (
            len(f) == len(df)
            and (f["station_id"].astype(str).to_numpy() == df["station_id"].astype(str).to_numpy()).all()
            and (f["base_date"].astype(str).to_numpy() == df["base_date"].astype(str).to_numpy()).all()
        )
        if same:
            return f[STATE_COLS + HIST_COLS].set_axis(df.index)
    feats = build_all_features(df)
    FEATURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    keyed = pd.concat([df[["station_id", "base_date"]].astype(str), feats], axis=1)
    keyed.to_parquet(FEATURES_PATH, index=False)
    return feats


# ================================================================ B. 아날로그 kNN
@dataclass(frozen=True)
class KnnCfg:
    k: int = 10
    pool: str = "site"
    agg: str = "log"

    @property
    def name(self) -> str:
        return f"k{self.k}-{self.pool}-{self.agg}"


def knn_inputs(df: pd.DataFrame, state: pd.DataFrame) -> np.ndarray:
    """거리 계산용 원값(n, 7): L0·L1·L2·계절 sin·cos·수온·log1p 체류시간."""
    doy = pd.to_datetime(df["base_date"]).dt.dayofyear.to_numpy(dtype=float)
    ang = 2 * np.pi * doy / 365.25
    res = np.log1p(np.clip(df["weir_residence_proxy"].to_numpy(dtype=float), 0.0, None))
    return np.column_stack(
        [
            state["st_L0"].to_numpy(dtype=float),
            state["st_L1"].to_numpy(dtype=float),
            state["st_L2"].to_numpy(dtype=float),
            np.sin(ang),
            np.cos(ang),
            df["wtemp_t0"].to_numpy(dtype=float),
            res,
        ]
    )


def _sd(x: np.ndarray) -> float:
    s = float(np.nanstd(x)) if np.isfinite(x).any() else math.nan
    return s if np.isfinite(s) and s > 1e-9 else 1.0


def _standardize(X: np.ndarray, cand: np.ndarray, sites: np.ndarray) -> np.ndarray:
    """후보 행(학습 폴드) 통계로만 표준화. 궤적 3열은 공통 척도, 체류시간은 지점별."""
    Z = np.full_like(X, np.nan)
    lv = X[cand][:, 0:3]
    mu, sd = float(np.nanmean(lv)), _sd(lv)
    Z[:, 0:3] = (X[:, 0:3] - mu) / sd
    for j in (3, 4, 5):
        Z[:, j] = (X[:, j] - float(np.nanmean(X[cand, j]))) / _sd(X[cand, j])
    g_mu, g_sd = float(np.nanmean(X[cand, 6])), _sd(X[cand, 6])
    for s in np.unique(sites):
        m = sites == s
        cm = cand & m
        mu_s, sd_s = (float(np.nanmean(X[cm, 6])), _sd(X[cm, 6])) if cm.sum() >= 10 else (g_mu, g_sd)
        Z[m, 6] = (X[m, 6] - mu_s) / sd_s
    return Z


def _dist2(Q: np.ndarray, C: np.ndarray, w: np.ndarray = KNN_W) -> np.ndarray:
    """결측 인지 가중 제곱거리(있는 차원만 평균 후 전체 가중 합으로 환산)."""
    diff = Q[:, None, :] - C[None, :, :]
    ok = np.isfinite(diff)
    num = (np.where(ok, diff**2, 0.0) * w).sum(-1)
    den = (ok * w).sum(-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den * w.sum(), np.inf)


def knn_member(
    df: pd.DataFrame, state: pd.DataFrame, cfg: KnnCfg, *, random_seed: int | None = None
) -> np.ndarray:
    """아날로그 kNN 원단위 예측(2020~2025 행만 값). 연도 Y 행의 이웃 후보는 기준일 연도 < Y 인 행(그 폴드의 학습 행)뿐.

    random_seed 가 있으면 대조군: 같은 풀에서 무작위 k 이웃(pool=site 는 같은 지점 우선).
    """
    H.guard_no_2026(df)
    X = knn_inputs(df, state)
    obs = df["target_cells"].to_numpy(dtype=float)
    tlog = np.log10(np.clip(obs, 0.0, None) + 1.0)
    years = H.years_of(df)
    sites = df["station_id"].astype(str).to_numpy()
    out = np.full(len(df), np.nan)
    rng = np.random.default_rng([RC.CTRL_SALT, int(random_seed), cfg.k]) if random_seed is not None else None
    for yv in (*H.CV_YEARS, H.FINAL_YEAR):
        cand = (years < yv) & np.isfinite(tlog)
        if not cand.any():
            continue
        Z = _standardize(X, cand, sites)
        ci = np.where(cand)[0]
        for s in sorted(set(sites[years == yv])):
            qi = np.where((years == yv) & (sites == s))[0]
            other = sites[ci] != s
            if cfg.pool == "site":
                pen = np.where(other, OTHER_SITE_FAR, 0.0)
            elif cfg.pool == "all":
                pen = np.where(other, SITE_PENALTY, 0.0)
            else:
                raise ValueError(cfg.pool)
            if rng is None:
                d2 = _dist2(Z[qi], Z[ci]) + pen[None, :]
            else:
                rand_pen = np.where(other, OTHER_SITE_FAR, 0.0) if cfg.pool == "site" else 0.0
                d2 = rng.random((len(qi), len(ci))) + rand_pen
            kk = min(cfg.k, len(ci))
            nb = np.argsort(d2, axis=1, kind="stable")[:, :kk]
            nbi = ci[nb]
            if cfg.agg == "log":
                p = 10 ** tlog[nbi].mean(axis=1) - 1
            elif cfg.agg == "raw":
                p = obs[nbi].mean(axis=1)
            elif cfg.agg == "delta":
                l0q = X[qi, 0]
                l0n = X[nbi, 0]
                dlt = np.nanmean(np.where(np.isfinite(l0n), tlog[nbi] - l0n, np.nan), axis=1)
                lg = np.where(np.isfinite(l0q) & np.isfinite(dlt), l0q + dlt, tlog[nbi].mean(axis=1))
                p = 10**lg - 1
            else:
                raise ValueError(cfg.agg)
            out[qi] = np.clip(p, 0.0, None)
    return out


# ================================================================ A. 국면 게이트·전문가
def expert_groups(state: pd.DataFrame, kind: str) -> np.ndarray:
    """E4 = 국면 4개, E2 = 평온(0) / 활성(1~3)."""
    r = state["st_regime"].fillna(0).to_numpy(dtype=int)
    if kind == "E4":
        return r
    if kind == "E2":
        return (r > 0).astype(int)
    raise ValueError(kind)


def random_groups(groups: np.ndarray, seed: int, salt: int) -> np.ndarray:
    """대조군: 같은 비율의 무작위 국면 표지(전체 행 순열). 생성기 (CTRL_SALT, seed, 그룹 수, salt)."""
    k = len(np.unique(groups))
    rng = np.random.default_rng([RC.CTRL_SALT, int(seed), k, salt])
    return rng.permutation(groups)


def gated_ensemble(
    df: pd.DataFrame,
    members: dict[str, np.ndarray],
    groups: np.ndarray,
    names: tuple[str, ...] = H2.C_NAMES,
    min_rows: int = MIN_GATE_ROWS,
) -> tuple[np.ndarray, dict[str, dict[str, float]]]:
    """국면별 연도 확장 NNLS(합=1, log 공간). 연도 Y·국면 g 의 가중치는 Y 이전 CV OOF 중 국면 g 행으로 적합.

    적합 행이 min_rows 미만이면 그 연도 전체 가중치(harness.ensemble_expanding 과 같은 규칙)를 쓴다.
    """
    years = H.years_of(df)
    cv_mask, _ = H.masks(df)
    obs = df["target_cells"].to_numpy(dtype=float)
    sub = {k: np.asarray(members[k], dtype=float) for k in names}
    pred = np.full(len(df), np.nan)
    weights: dict[str, dict[str, float]] = {}
    for yv in (*H.CV_YEARS, H.FINAL_YEAR):
        fit_m = cv_mask & (years < yv)
        if fit_m.sum() < 50:
            w_all = {k: 1.0 / len(sub) for k in sub}
        else:
            w_all = nnls_weights({k: v[fit_m] for k, v in sub.items()}, obs[fit_m])
        for g in np.unique(groups[years == yv]):
            fm = fit_m & (groups == g)
            wg = nnls_weights({k: v[fm] for k, v in sub.items()}, obs[fm]) if fm.sum() >= min_rows else w_all
            am = (years == yv) & (groups == g)
            pred[am] = combine({k: v[am] for k, v in sub.items()}, wg)
            weights[f"{yv}_{int(g)}"] = wg
    return pred, weights


FitFn = Callable[[pd.DataFrame, pd.DataFrame, list[str], int], np.ndarray]


@lru_cache(maxsize=1)
def _c1_spec() -> object:
    return H.v1_specs()["c1"]


def c1_fit(tr: pd.DataFrame, va: pd.DataFrame, cols: list[str], seed: int) -> np.ndarray:
    """C1(v1 log_w 설정, smearing) 한 번 적합 → va 원단위 예측(run_cv 의 smearing 경로와 같은 식)."""
    from algaecast.models.train import fit_predict

    f = fit_predict(tr, va, cols, _c1_spec(), seed=seed)  # type: ignore[arg-type]
    return np.clip(np.nan_to_num(f.raw * f.smear, nan=0.0), 0.0, None)


def expert_member(
    df: pd.DataFrame,
    cols: list[str],
    groups: np.ndarray,
    seed: int,
    fallback: np.ndarray,
    *,
    fit: FitFn = c1_fit,
    min_train: int = MIN_EXPERT_ROWS,
) -> np.ndarray:
    """국면별 전문가 OOF: 폴드(기준일 연도 < Y 학습 → Y)마다 국면 g 의 학습 행만으로 적합해 국면 g 검증 행을 예측.

    학습 행이 min_train 미만인 국면은 fallback(C 의 c1 OOF)을 쓴다.
    """
    from algaecast.models.cv import year_folds

    H.guard_no_2026(df)
    out = np.full(len(df), np.nan)
    for fo in year_folds(df, include_final=True):
        gv = groups[fo.valid_idx]
        for g in np.unique(gv):
            va = fo.valid_idx[gv == g]
            tr = fo.train_idx[groups[fo.train_idx] == g]
            if len(tr) < min_train:
                out[va] = fallback[va]
            else:
                out[va] = fit(df.iloc[tr], df.iloc[va], cols, seed)
    return out


# ================================================================ 구성(설정)·Builder
@dataclass(frozen=True)
class P5Config:
    """C 위에 얹는 P5 요소. ctrl=True 면 모든 요소를 같은 구조의 대조군으로 바꾼다."""

    feats: tuple[str, ...] = ()  # FEATURE_SETS 키(A1·H1·H2·H3)
    knn: KnnCfg | None = None
    experts: str = ""  # "" | "E2" | "E4"
    gate: bool = False
    ctrl: bool = False

    @property
    def parts(self) -> list[str]:
        p = list(self.feats)
        if self.knn is not None:
            p.append("knn-" + self.knn.name)
        if self.experts:
            p.append(self.experts)
        if self.gate:
            p.append("gate")
        return p

    @property
    def name(self) -> str:
        return "P5_" + "+".join(self.parts or ["C"]) + ("_ctrl" if self.ctrl else "")

    @property
    def names(self) -> tuple[str, ...]:
        return H2.C_NAMES + (("knn",) if self.knn is not None else ()) + (("moe",) if self.experts else ())

    def control(self) -> P5Config:
        return P5Config(self.feats, self.knn, self.experts, self.gate, True)


@dataclass
class Ctx:
    """P5 실행 문맥: 새 열·상류 F2·kNN 구성원 캐시."""

    feats: pd.DataFrame
    f2: pd.DataFrame
    knn_cache: dict[tuple[str, int | None], np.ndarray] = field(default_factory=dict)

    def feature_frame(self, sets: tuple[str, ...]) -> pd.DataFrame:
        cols = [c for s in sets for c in FEATURE_SETS[s]]
        return self.feats[cols]

    @property
    def state(self) -> pd.DataFrame:
        return self.feats[STATE_COLS]

    def knn(self, df: pd.DataFrame, cfg: KnnCfg, random_seed: int | None) -> np.ndarray:
        key = (cfg.name, random_seed)
        if key not in self.knn_cache:
            self.knn_cache[key] = knn_member(df, self.state, cfg, random_seed=random_seed)
        return self.knn_cache[key]


_CTX: dict[str, Ctx] = {}


def make_ctx(df: pd.DataFrame) -> Ctx:
    """df 의 (지점, 기준일) 키로 문맥을 하나만 만든다(같은 프로세스 재사용)."""
    key = f"{len(df)}_{df['station_id'].astype(str).str.cat()[:64]}_{df['base_date'].astype(str).iloc[-1]}"
    if key not in _CTX:
        _CTX[key] = Ctx(feats=load_p5_features(df), f2=H2.f2_frame(df))
    return _CTX[key]


def config_members(
    df: pd.DataFrame, cfg: P5Config, seed: int, ctx: Ctx | None = None
) -> dict[str, np.ndarray]:
    """설정 하나의 시드 OOF 구성원(c1·c3·c2·cg + knn/moe)."""
    H.guard_no_2026(df)
    ctx = ctx or make_ctx(df)
    extra: pd.DataFrame | None = None
    if cfg.feats:
        frame = ctx.feature_frame(cfg.feats)
        extra = H2.noise_like(frame, seed) if cfg.ctrl else frame
        mem = CF.config_members(df, pd.concat([ctx.f2, extra], axis=1), seed, genus=True)
    else:
        c = H2.run_cached(df, "C", seed, H2.c_pred)
        mem = {k: c[f"m_{k}"] for k in H2.C_NAMES}
    if cfg.knn is not None:
        mem["knn"] = ctx.knn(df, cfg.knn, seed if cfg.ctrl else None)
    if cfg.experts:
        groups = expert_groups(ctx.state, cfg.experts)
        if cfg.ctrl:
            groups = random_groups(groups, seed, SALT_EXPERT)
        ex = ctx.f2 if extra is None else pd.concat([ctx.f2, extra], axis=1)
        dfx = pd.concat([df, ex], axis=1)
        H.guard_no_2026(dfx)
        mem["moe"] = expert_member(dfx, H.base_columns() + list(ex.columns), groups, seed, mem["c1"])
    return mem


def config_pred(
    df: pd.DataFrame, cfg: P5Config, mem: dict[str, np.ndarray], seed: int, ctx: Ctx | None = None
) -> np.ndarray:
    """구성원 → 점예측: 연도 확장 NNLS(gate 면 국면별 NNLS)."""
    if cfg.gate:
        ctx = ctx or make_ctx(df)
        groups = expert_groups(ctx.state, "E4")
        if cfg.ctrl:
            groups = random_groups(groups, seed, SALT_GATE)
        return gated_ensemble(df, mem, groups, cfg.names)[0]
    return H.ensemble_expanding(df, mem, names=cfg.names)[0]


def make_builder(cfg: P5Config, ctx: Ctx | None = None) -> H2.Builder:
    """harness2.Builder: (df, seed) → {"pred", "q90": None(v1 동결), "m_*"}."""

    def build(df: pd.DataFrame, seed: int) -> dict[str, np.ndarray]:
        c = ctx or make_ctx(df)
        mem = config_members(df, cfg, seed, c)
        pred = config_pred(df, cfg, mem, seed, c)
        return {"pred": pred, "q90": None, **{f"m_{k}": mem[k] for k in cfg.names}}  # type: ignore[dict-item]

    return build


# 선택 설정(2026-10-22 main() 의 CV 규칙 결과로 고정 — 다르면 main 이 경고). 종합 단계 재사용 기본값.
# A2 국면별 NNLS 게이트: 시드 평균 ΔC CV r2_raw +0.009(부트스트랩 95% 가 0 포함), 2025 확인은 C 보다 낮다(README 참고).
CHOSEN = P5Config(gate=True)


def regime_groups(df: pd.DataFrame, algae: pd.DataFrame | None = None) -> np.ndarray:
    """df 각 행의 국면 코드(0 평온·1 증가·2 정점·3 감소, as_of 규칙). gated_ensemble 의 groups 로 쓴다."""
    return build_state(df, algae)["st_regime"].fillna(0).to_numpy(dtype=int)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """선택 설정의 새 피처 열(같은 인덱스). 선택 설정에 피처가 없으면 열 0개 DataFrame."""
    H.guard_no_2026(df)
    if not CHOSEN.feats:
        return pd.DataFrame(index=df.index)
    feats = build_all_features(df)
    return feats[[c for s in CHOSEN.feats for c in FEATURE_SETS[s]]]


def members(df: pd.DataFrame, seed: int) -> dict[str, np.ndarray]:
    """선택 설정의 OOF 구성원(c1·c3·c2·cg + 선택한 knn/moe)."""
    return config_members(df, CHOSEN, seed)


def builder(df: pd.DataFrame, seed: int) -> dict[str, np.ndarray]:
    """선택 설정의 harness2.Builder."""
    return make_builder(CHOSEN)(df, seed)


# ================================================================ 실험 실행
A_VARIANTS: dict[str, tuple[str, P5Config]] = {
    "A1": ("A1 국면 코드 피처", P5Config(feats=("A1",))),
    "A2": ("A2 국면별 NNLS 게이트", P5Config(gate=True)),
    "A3": ("A3 국면 전문가 4개(E4)", P5Config(experts="E4")),
    "A4": ("A4 평온·활성 전문가 2개(E2)", P5Config(experts="E2")),
}
H_VARIANTS: dict[str, tuple[str, P5Config]] = {
    "H1": ("H1 전년도 최고 1열", P5Config(feats=("H1",))),
    "H2": ("H2 올해 누적·평년 대비 4열", P5Config(feats=("H2",))),
    "H3": ("H3 전년도+올해 누적 5열", P5Config(feats=("H3",))),
}
THEME = {"A": "국면·MoE", "B": "아날로그 kNN", "H": "전년도·평년 피처", "X": "결합"}


@dataclass
class Res:
    """변형 하나의 시드별·평균 지표와 대조군."""

    key: str
    label: str
    theme: str
    cfg: P5Config
    rows: list[dict]
    mean: dict
    ctrl_rows: list[dict] | None = None
    ctrl_mean: dict | None = None


def _budget() -> H.Budget:
    b = H.Budget(BUDGET_HOURS, PX)
    b.t0 = datetime.strptime(TASK_START, "%Y-%m-%d %H:%M:%S").timestamp()
    return b


def _evaluate(df: pd.DataFrame, cfg: P5Config, label: str, ctx: Ctx) -> tuple[list[dict], dict]:
    t0 = time.time()
    rows, mean = H2.evaluate(df, cfg.name, make_builder(cfg, ctx))
    mean["구성"] = label
    log.info("%s(%s): CV r2_raw %.4f (%.0fs)", label, cfg.name, mean["cv_r2_raw"], time.time() - t0)
    return rows, mean


def run_pair(df: pd.DataFrame, key: str, label: str, theme: str, cfg: P5Config, ctx: Ctx) -> Res:
    """변형과 그 대조군(같은 구조의 난수·무작위 표지·무작위 이웃)을 시드 5개로 평가."""
    rows, mean = _evaluate(df, cfg, label, ctx)
    crows, cmean = _evaluate(df, cfg.control(), f"{label} 대조군", ctx)
    return Res(key, label, theme, cfg, rows, mean, crows, cmean)


def summarize(res: Res, base_rows: list[dict]) -> dict:
    """C 대비 시드 짝 차이·대조군·선택 조건·탐색 판정."""
    d = H2.paired_delta(res.rows, base_rows, "cv_r2_raw")
    drm = H2.paired_delta(res.rows, base_rows, "cv_rmse_log")
    dc = H2.paired_delta(res.ctrl_rows, base_rows, "cv_r2_raw") if res.ctrl_rows else math.nan
    uniq = d - dc if res.ctrl_rows else math.nan
    lead = float(res.mean["lead_q90"])
    cond = {
        "rmse_ok": bool(drm <= RMSE_SLACK),
        "lead_ok": bool(lead >= LEAD_MIN),
        "unique_ok": bool(res.ctrl_rows is not None and uniq > 0),
    }
    return {
        "key": res.key,
        "label": res.label,
        "theme": res.theme,
        "name": res.cfg.name,
        "cv_r2_raw": float(res.mean["cv_r2_raw"]),
        "d_cv_r2_raw": d,
        "d_cv_rmse_log": drm,
        "d_ctrl_cv_r2_raw": dc,
        "unique": uniq,
        "lead_q90": lead,
        **cond,
        "eligible": bool(all(cond.values())),
        "d_y25_r2_raw": H2.paired_delta(res.rows, base_rows, "y25_r2_raw"),
        "d_y25_rmse_log": H2.paired_delta(res.rows, base_rows, "y25_rmse_log"),
        "d_y25b_rmse_log": H2.paired_delta(res.rows, base_rows, "y25b_rmse_log"),
        "explore_check": H2.explore_check(res.mean, res.rows, base_rows, res.ctrl_rows),
    }


def merge(a: P5Config, b: P5Config) -> P5Config:
    return P5Config(
        feats=tuple(dict.fromkeys(a.feats + b.feats)),
        knn=a.knn or b.knn,
        experts=a.experts or b.experts,
        gate=a.gate or b.gate,
    )


def new_member_weight(df: pd.DataFrame, cfg: P5Config, seeds: tuple[int, ...] = H2.EXPLORE_SEEDS) -> dict:
    """새 NNLS 구성원(knn·moe)의 연도별 가중치(시드 평균). gate 설정은 국면별이라 생략."""
    new = [k for k in cfg.names if k not in H2.C_NAMES]
    if not new or cfg.gate:
        return {}
    acc: dict[int, list[float]] = {}
    for s in seeds:
        out = H2.run_cached(df, cfg.name, s, make_builder(cfg))
        mem = {k: out[f"m_{k}"] for k in cfg.names}
        _, w = H.ensemble_expanding(df, mem, names=cfg.names)
        for y, wy in w.items():
            acc.setdefault(int(y), []).append(float(sum(wy[k] for k in new)))
    return {y: float(np.mean(v)) for y, v in acc.items()}


def knn_grid(df: pd.DataFrame, ctx: Ctx, budget: H.Budget) -> dict[str, dict]:
    """kNN 격자(k × 지점 × 집계): 구성원 단독 CV 지표 + C + kNN NNLS 의 시드 평균 지표."""
    from algaecast.eval.metrics import compute_all

    cv, _ = H.masks(df)
    obs = df["target_cells"].to_numpy(dtype=float)
    out: dict[str, dict] = {}
    for k in KNN_KS:
        for pool in KNN_POOLS:
            for agg in KNN_AGGS:
                kc = KnnCfg(k, pool, agg)
                cfg = P5Config(knn=kc)
                rows, mean = _evaluate(df, cfg, f"B kNN {kc.name}", ctx)
                m = ctx.knn(df, kc, None)
                ok = cv & np.isfinite(m)
                alone = compute_all(obs[ok], m[ok])
                out[kc.name] = {
                    "cfg": kc,
                    "rows": rows,
                    "mean": mean,
                    "alone_cv_r2_raw": float(alone["r2_raw"]),
                    "alone_cv_rmse_log": float(alone["rmse_log"]),
                    "alone_cv_r2_log": float(alone["r2_log"]),
                }
                budget.check()
    return out


def regime_breakdown(
    df: pd.DataFrame, groups: np.ndarray, preds: dict[str, list[np.ndarray]]
) -> pd.DataFrame:
    """CV 행의 국면별 기여: n·관측≥10k·SST 비중, 구성별 SSE 비중(시드 평균)·rmse_log(시드 평균)."""
    cv, _ = H.masks(df)
    obs = df["target_cells"].to_numpy(dtype=float)
    mu = obs[cv].mean()
    sst = float(((obs[cv] - mu) ** 2).sum())
    recs = []
    for g, nm in REGIMES.items():
        m = cv & (groups == g)
        r: dict[str, object] = {
            "국면": nm,
            "n": int(m.sum()),
            "관측≥10k": int((obs[m] >= H.T10K).sum()),
            "SST 비중": float(((obs[m] - mu) ** 2).sum() / sst),
        }
        for name, plist in preds.items():
            r[f"{name} SSE/SST"] = float(np.mean([((obs[m] - p[m]) ** 2).sum() / sst for p in plist]))
            r[f"{name} rmse_log"] = float(
                np.mean([np.sqrt(np.mean((np.log10(obs[m] + 1) - np.log10(p[m] + 1)) ** 2)) for p in plist])
            )
        recs.append(r)
    return pd.DataFrame(recs)


def b0_builder(ctx: Ctx | None = None) -> H2.Builder:
    """진단(선택 대상 아님): C + 지속성 구성원 b0 = 10^L0 − 1 을 NNLS 에 추가.

    kNN 'delta' 집계의 무작위 이웃 대조군은 'L0 + 같은 지점 평균 변화량' 이라 지속성에 가깝다 — 그 효과의 크기를 따로 잰다.
    """

    def build(df: pd.DataFrame, seed: int) -> dict[str, np.ndarray]:
        c = ctx or make_ctx(df)
        out = H2.run_cached(df, "C", seed, H2.c_pred)
        mem = {k: out[f"m_{k}"] for k in H2.C_NAMES}
        mem["b0"] = np.clip(10 ** c.state["st_L0"].to_numpy(dtype=float) - 1, 0.0, None)
        pred, _ = H.ensemble_expanding(df, mem, names=(*H2.C_NAMES, "b0"))
        return {"pred": pred, "q90": None, "m_b0": mem["b0"]}

    return build


def gate_weights(df: pd.DataFrame, ctx: Ctx, year: int = H.FINAL_YEAR) -> pd.DataFrame:
    """A2 게이트의 국면별 NNLS 가중치(year 적용분, 시드 평균)와 전체(국면 무시) 가중치."""
    groups = expert_groups(ctx.state, "E4")
    acc: dict[str, list[dict[str, float]]] = {}
    for s in H2.EXPLORE_SEEDS:
        out = H2.run_cached(df, "C", s, H2.c_pred)
        mem = {k: out[f"m_{k}"] for k in H2.C_NAMES}
        _, w = gated_ensemble(df, mem, groups)
        _, wa = H.ensemble_expanding(df, mem, names=H2.C_NAMES)
        acc.setdefault("전체(C)", []).append(wa[year])
        for g, nm in REGIMES.items():
            if f"{year}_{g}" in w:
                acc.setdefault(nm, []).append(w[f"{year}_{g}"])
    return pd.DataFrame(
        [{"국면": nm, **{k: float(np.mean([x[k] for x in v])) for k in H2.C_NAMES}} for nm, v in acc.items()]
    )


def expert_alone(df: pd.DataFrame, ctx: Ctx) -> pd.DataFrame:
    """국면 전문가 구성원 moe 단독 vs 단일 C1(c1) 의 CV 지표(시드 평균) — 국면별 회귀 자체가 나은지."""
    from algaecast.eval.metrics import compute_all

    cv, _ = H.masks(df)
    obs = df["target_cells"].to_numpy(dtype=float)
    groups = expert_groups(ctx.state, "E4")
    recs = []
    for label, cfg in A_VARIANTS.values():
        if not cfg.experts:
            continue
        for ctrl in (False, True):
            c = cfg.control() if ctrl else cfg
            acc: dict[str, list[float]] = {}
            for s in H2.EXPLORE_SEEDS:
                out = H2.run_cached(df, c.name, s, make_builder(c, ctx))
                for nm, p in (("moe", out["m_moe"]), ("c1", out["m_c1"])):
                    m = compute_all(obs[cv], p[cv])
                    acc.setdefault(f"{nm} r2_raw", []).append(float(m["r2_raw"]))
                    acc.setdefault(f"{nm} rmse_log", []).append(float(m["rmse_log"]))
                    pk = cv & (groups == 2)
                    acc.setdefault(f"{nm} 정점 rmse_log", []).append(
                        float(np.sqrt(np.mean((np.log10(obs[pk] + 1) - np.log10(p[pk] + 1)) ** 2)))
                    )
            recs.append(
                {
                    "구성원": f"{label}" + (" 대조군(무작위 표지)" if ctrl else ""),
                    **{k: float(np.mean(v)) for k, v in acc.items()},
                }
            )
    return pd.DataFrame(recs)


def diagnostics(df: pd.DataFrame, ctx: Ctx, base_rows: list[dict]) -> tuple[str, dict]:
    """선택에 쓰지 않는 진단: (1) C + 지속성 구성원 b0, (2) 게이트 국면별 가중치, (3) 전문가 단독 성능."""
    rows, mean = H2.evaluate(df, "P5_diag_C+b0", b0_builder(ctx))
    mean["구성"] = "진단: C + 지속성 b0 구성원"
    d = {
        k: H2.paired_delta(rows, base_rows, k)
        for k in ("cv_r2_raw", "cv_rmse_log", "y25_r2_raw", "y25_rmse_log", "y25b_rmse_log")
    }
    w = new_member_weight_b0(df, ctx)
    gw = gate_weights(df, ctx)
    ea = expert_alone(df, ctx)
    md = "\n## 9. 진단(선택 대상 아님)\n\n" "### 9.1 C + 지속성 구성원 b0(= 10^L0 − 1) NNLS\n\n" + H2.table2(
        [(H2.mean_rows(base_rows, "C(기준 모델)"), base_rows), (mean, rows)], base_rows
    ) + "\nb0 의 NNLS 가중치(시드 평균): " + ", ".join(
        f"{y} {v:.3f}" for y, v in w.items()
    ) + "\n\n### 9.2 A2 게이트의 2025 적용 국면별 NNLS 가중치(시드 평균)\n\n" + _md(
        gw, 3
    ) + "\n### 9.3 국면 전문가 구성원(moe) 단독 vs 단일 C1(c1), CV 시드 평균(c1 은 같은 시드의 C 구성원)\n\n" + _md(
        ea, 3
    )
    return md, {
        "b0_seed_rows": rows,
        "b0_mean": mean,
        "b0_d_vs_c": d,
        "b0_weight": w,
        "gate_weights_2025": gw.to_dict(orient="records"),
        "expert_alone": ea.to_dict(orient="records"),
    }


def new_member_weight_b0(df: pd.DataFrame, ctx: Ctx) -> dict[int, float]:
    acc: dict[int, list[float]] = {}
    for s in H2.EXPLORE_SEEDS:
        out = H2.run_cached(df, "P5_diag_C+b0", s, b0_builder(ctx))
        c = H2.run_cached(df, "C", s, H2.c_pred)
        mem = {**{k: c[f"m_{k}"] for k in H2.C_NAMES}, "b0": out["m_b0"]}
        _, w = H.ensemble_expanding(df, mem, names=(*H2.C_NAMES, "b0"))
        for y, wy in w.items():
            acc.setdefault(int(y), []).append(float(wy["b0"]))
    return {y: float(np.mean(v)) for y, v in acc.items()}


def _md(t: pd.DataFrame, nd: int = 3) -> str:
    cols = list(t.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in t.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, bool | np.bool_):
                cells.append("예" if v else "아니오")
            elif isinstance(v, float | np.floating):
                cells.append("–" if not np.isfinite(v) else f"{v:.{nd}f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _sum_table(sums: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "변형": s["label"],
                "갈래": THEME[s["theme"]],
                "시드평균 CV r2_raw": s["cv_r2_raw"],
                "ΔC r2_raw": s["d_cv_r2_raw"],
                "Δ대조군": s["d_ctrl_cv_r2_raw"],
                "고유 효과": s["unique"],
                "ΔC rmse_log": s["d_cv_rmse_log"],
                "리드": s["lead_q90"],
                "선택 적격": s["eligible"],
                "ΔC 2025 r2_raw": s["d_y25_r2_raw"],
                "ΔC 2025 9~10월 rmse_log": s["d_y25b_rmse_log"],
                "탐색 판정": s["explore_check"]["meets_explore"],
            }
            for s in sums
        ]
    )


def main() -> int:  # noqa: C901
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    budget = _budget()
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.mkdir(parents=True, exist_ok=True)
    df = H.load_base()
    H.guard_no_2026(df)
    ctx = make_ctx(df)
    base_rows = H2.baseline_c(df)
    base_mean = H2.mean_rows(base_rows, "C(기준 모델)")
    results: dict[str, Res] = {}
    grid: dict[str, dict] = {}
    status, note = "completed", ""
    chosen_key: str | None = None
    combo_log: list[dict] = []
    try:
        # ---- A. 국면·MoE
        for key, (label, cfg) in A_VARIANTS.items():
            results[key] = run_pair(df, key, label, "A", cfg, ctx)
            budget.check()
        # ---- B. kNN 격자 → CV 최고 → 대조군
        grid = knn_grid(df, ctx, budget)
        best_b = max(grid, key=lambda n: grid[n]["mean"]["cv_r2_raw"])
        bcfg = P5Config(knn=grid[best_b]["cfg"])
        results["B"] = run_pair(df, "B", f"B kNN {best_b}(격자 CV 최고)", "B", bcfg, ctx)
        budget.check()
        # ---- C. 전년도·평년 피처
        for key, (label, cfg) in H_VARIANTS.items():
            results[key] = run_pair(df, key, label, "H", cfg, ctx)
            budget.check()
        # ---- 선택(CV 만) + 갈래 결합
        sums = {k: summarize(r, base_rows) for k, r in results.items()}
        elig = {k: s for k, s in sums.items() if s["eligible"]}
        if elig:
            chosen_key = max(elig, key=lambda k: elig[k]["d_cv_r2_raw"])
            best_by_theme = {}
            for k, s in sorted(elig.items(), key=lambda kv: -kv[1]["d_cv_r2_raw"]):
                best_by_theme.setdefault(s["theme"], k)
            remaining = [k for t, k in best_by_theme.items() if t != results[chosen_key].theme]
            step = 0
            while remaining:
                step += 1
                cur = results[chosen_key]
                trials = []
                for k in remaining:
                    cfg = merge(cur.cfg, results[k].cfg)
                    key = f"X{step}_{k}"
                    lab = f"결합{step}: " + " + ".join(cfg.parts)
                    r = run_pair(df, key, lab, "X", cfg, ctx)
                    results[key] = r
                    s = summarize(r, base_rows)
                    sums[key] = s
                    gain = H2.paired_delta(r.rows, cur.rows, "cv_r2_raw")
                    ok = s["eligible"] and gain >= MIN_GAIN
                    trials.append((key, k, gain, ok))
                    combo_log.append(
                        {
                            "step": step,
                            "from": chosen_key,
                            "add": k,
                            "key": key,
                            "gain": gain,
                            "accepted": False,
                            "eligible": s["eligible"],
                        }
                    )
                    budget.check()
                good = [t for t in trials if t[3]]
                if not good:
                    break
                key, k, gain, _ = max(good, key=lambda t: t[2])
                for c in combo_log:
                    if c["key"] == key:
                        c["accepted"] = True
                chosen_key = key
                remaining = [x for x in remaining if x != k]
    except H.BudgetExceeded as e:
        status, note = "time_cap", f"시간 상한 초과로 중단: {e}"
        log.warning(note)
    sums = {k: summarize(r, base_rows) for k, r in results.items()}
    chosen_cfg = results[chosen_key].cfg if chosen_key else P5Config()
    if chosen_cfg != CHOSEN:
        log.warning("CHOSEN 상수(%s)와 이번 선택(%s)이 다르다 — 상수를 고칠 것", CHOSEN.name, chosen_cfg.name)
    _write_outputs(
        df, ctx, base_rows, base_mean, results, sums, grid, chosen_key, combo_log, status, note, budget
    )
    return 0


def _write_outputs(
    df: pd.DataFrame,
    ctx: Ctx,
    base_rows: list[dict],
    base_mean: dict,
    results: dict[str, Res],
    sums: dict[str, dict],
    grid: dict[str, dict],
    chosen_key: str | None,
    combo_log: list[dict],
    status: str,
    note: str,
    budget: H.Budget,
) -> None:
    order = [k for k in results]
    entries: list[tuple[dict, list[dict]]] = [(base_mean, base_rows)]
    for k in order:
        r = results[k]
        entries.append((r.mean, r.rows))
        if r.ctrl_rows is not None and r.ctrl_mean is not None:
            entries.append((r.ctrl_mean, r.ctrl_rows))
    txt = [f"# P5 자동 생성 표(손으로 고치지 않음)\n\n상태: {status} {note}\n"]
    txt.append("## 1. 표준 표(탐색 시드 11·22·33·44·55 평균, ΔC = 같은 시드 C 대비 짝 차이)\n\n")
    txt.append(H2.table2(entries, base_rows))
    txt.append(
        "\n## 2. 변형 요약(선택은 CV 만: ΔC rmse_log ≤ +0.01, 리드 ≥ 18, 고유 효과 > 0 중 ΔC r2_raw 최대)\n\n"
    )
    txt.append(_md(_sum_table([sums[k] for k in order]), 3))
    if grid:
        g = pd.DataFrame(
            [
                {
                    "kNN": n,
                    "C+kNN 시드평균 CV r2_raw": v["mean"]["cv_r2_raw"],
                    "ΔC r2_raw": H2.paired_delta(v["rows"], base_rows, "cv_r2_raw"),
                    "ΔC rmse_log": H2.paired_delta(v["rows"], base_rows, "cv_rmse_log"),
                    "단독 CV r2_raw": v["alone_cv_r2_raw"],
                    "단독 CV rmse_log": v["alone_cv_rmse_log"],
                    "단독 CV r2_log": v["alone_cv_r2_log"],
                    "ΔC 2025 r2_raw": H2.paired_delta(v["rows"], base_rows, "y25_r2_raw"),
                }
                for n, v in grid.items()
            ]
        )
        txt.append("\n## 3. kNN 격자(k × 지점 × 집계, 선택은 C+kNN 시드평균 CV r2_raw)\n\n")
        txt.append(_md(g, 3))
    # 새 구성원 가중치
    wrows = []
    for k in order:
        w = new_member_weight(df, results[k].cfg)
        if w:
            wrows.append({"변형": results[k].label, **{str(y): v for y, v in w.items()}})
    if wrows:
        txt.append("\n## 4. 새 NNLS 구성원(knn·moe) 가중치 합(시드 평균, 연도 확장 적합)\n\n")
        txt.append(_md(pd.DataFrame(wrows), 3))
    # 국면별 기여
    groups = expert_groups(ctx.state, "E4")
    preds = {"C": [H2.run_cached(df, "C", s, H2.c_pred)["pred"] for s in H2.EXPLORE_SEEDS]}
    if chosen_key:
        rc = results[chosen_key]
        preds["선택"] = [
            H2.run_cached(df, rc.cfg.name, s, make_builder(rc.cfg, ctx))["pred"] for s in H2.EXPLORE_SEEDS
        ]
    for k in ("A2", "A3", "B", "H3"):
        if k in results and k != chosen_key:
            preds[k] = [
                H2.run_cached(df, results[k].cfg.name, s, make_builder(results[k].cfg, ctx))["pred"]
                for s in H2.EXPLORE_SEEDS
            ]
    rb = regime_breakdown(df, groups, preds)
    txt.append("\n## 5. CV 국면별 기여(SST 비중 = 원단위 R² 분모 중 그 국면 몫, SSE/SST = R² 손실 몫)\n\n")
    txt.append(_md(rb, 3))
    years = H.years_of(df)
    dist = pd.crosstab(years, pd.Series(groups).map(REGIMES)).reset_index().rename(columns={"row_0": "연도"})
    txt.append("\n## 6. 연도별 국면 분포(기준일 기준)\n\n")
    txt.append(_md(dist, 0))
    if combo_log:
        txt.append("\n## 7. 갈래 결합 경로\n\n")
        txt.append(_md(pd.DataFrame(combo_log), 3))
    # 선택 설정: 시드 짝 차이·부트스트랩·OOF 저장
    chosen: dict = {"key": chosen_key, "name": None, "cfg": None}
    if chosen_key:
        rc = results[chosen_key]
        sel = [H2.run_cached(df, rc.cfg.name, s, make_builder(rc.cfg, ctx))["pred"] for s in H2.EXPLORE_SEEDS]
        lo, hi, med = CF.bootstrap_ci(df, sel, preds["C"])
        chosen = {
            "key": chosen_key,
            "label": rc.label,
            "name": rc.cfg.name,
            "cfg": {
                "feats": list(rc.cfg.feats),
                "knn": rc.cfg.knn.name if rc.cfg.knn else None,
                "experts": rc.cfg.experts,
                "gate": rc.cfg.gate,
            },
            "seed_mean": rc.mean,
            "d_vs_c": {
                k: H2.paired_delta(rc.rows, base_rows, k)
                for k in (
                    "cv_r2_raw",
                    "cv_rmse_log",
                    "y25_r2_raw",
                    "y25_rmse_log",
                    "y25a_rmse_log",
                    "y25b_rmse_log",
                    "y25_f1_10k",
                )
            },
            "boot_ci_cv_r2_raw": {"lo": lo, "hi": hi, "median": med},
            "summary": sums[chosen_key],
        }
        oof = {f"pred_s{s}": p for s, p in zip(H2.EXPLORE_SEEDS, sel, strict=True)}
        oof.update({f"C_s{s}": p for s, p in zip(H2.EXPLORE_SEEDS, preds["C"], strict=True)})
        H.save_oof(df, oof, OUT_DATA / "chosen_oof.parquet")
        txt.append(
            f"\n## 8. 선택 설정\n\n{rc.label}(`{rc.cfg.name}`). 시드 짝 차이 ΔC CV r2_raw {chosen['d_vs_c']['cv_r2_raw']:+.4f}, "
            f"(연도·지점) 블록 부트스트랩 95% [{lo:+.4f}, {hi:+.4f}].\n"
        )
    else:
        txt.append("\n## 8. 선택 설정\n\n적격 변형 없음 → C 유지.\n")
    # kNN 구성원 저장(시드 무관)
    if ctx.knn_cache:
        H.save_oof(
            df,
            {
                f"knn_{n}" + ("" if s is None else f"_rand{s}"): v
                for (n, s), v in ctx.knn_cache.items()
                if s is None
            },
            OUT_DATA / "knn_members.parquet",
        )
    diag_md, diag = diagnostics(df, ctx, base_rows)
    txt.append(diag_md)
    elapsed = budget.elapsed_h
    txt.append(f"\n소요 {elapsed:.2f}시간(착수 {TASK_START} 기준, 상한 {BUDGET_HOURS}시간).\n")
    (OUT_REPORT / "tables.md").write_text("".join(txt), encoding="utf-8")
    H2.write_json(
        OUT_REPORT / "metrics.json",
        {
            "status": status,
            "note": note,
            "elapsed_h": elapsed,
            "base_c": {"seed_rows": base_rows, "mean": base_mean},
            "variants": {
                k: {
                    "label": r.label,
                    "theme": r.theme,
                    "name": r.cfg.name,
                    "seed_rows": r.rows,
                    "mean": r.mean,
                    "ctrl_seed_rows": r.ctrl_rows,
                    "ctrl_mean": r.ctrl_mean,
                    "summary": sums[k],
                }
                for k, r in results.items()
            },
            "knn_grid": {
                n: {
                    "seed_rows": v["rows"],
                    "mean": v["mean"],
                    "alone_cv_r2_raw": v["alone_cv_r2_raw"],
                    "alone_cv_rmse_log": v["alone_cv_rmse_log"],
                    "alone_cv_r2_log": v["alone_cv_r2_log"],
                }
                for n, v in grid.items()
            },
            "combo_log": combo_log,
            "chosen": chosen,
            "regime_breakdown": rb.to_dict(orient="records"),
            "diagnostics": diag,
        },
    )
    print("".join(txt))


if __name__ == "__main__":
    raise SystemExit(main())
