# ruff: noqa: E501  (한국어 표·보고서 문자열)
"""EXP-005(2차) P4 — 일 단위 칼만 필터(로컬 레벨 + 수온 성장항)와 측정 잡음 상한.

모형(지점별, 상태 x = log10(세포수 + 1), 일 단위 격자, 측정 결측 허용)
- 상태 전이(하루):  x_{d+1} = x_d + b0 + b1·(T_d − TC) + η_d,   η ~ N(0, q)        ("lltemp", 본 모형)
- 측정:            y_d = x_d + ε_d,   ε ~ N(0, r)  (조류경보 채수일에만 관측)
- T_d = d 이전(포함) 마지막 실측 수온(전진 채움, 미래 값 없음). 수온 실측이 하나도 없던 기간은 T = TC(성장항 0).
- 측정일 사이에는 T 가 일정하므로 k 일 전이를 닫힌 식(평균 k·g(T), 분산 k·q)으로 한 번에 계산한다.
  이는 일 단위 격자에서 측정 없는 날을 결측으로 두고 하루씩 돌린 필터와 수치상 같다(tests 에서 대조).
- 확장·민감도 모형: "ll"(성장항 없음), "lltemp_r2"(측정 잡음을 5~10월/11~4월 둘로),
  "damped"(Gompertz형 밀도 의존 성장: x_{d+1} = x_d + (1−φ)·(a0 + a1·(T_d − TC) − x_d) + η_d,
  즉 수온이 정하는 평형으로 되돌아가는 AR(1)), "damped_r2"(감쇠 + 계절 측정 잡음).

매개변수 추정(as_of 규칙)
- 기준일 as_of 가 Y 년이면 매개변수는 obs_date ≤ (Y−1)-12-31 측정으로 최대우도 추정한다(= 검증 연도 Y 폴드의 학습 구간).
  2025 행은 ≤2024, CV 연도 Y 행은 ≤Y−1. 학습 행(Y < 검증 연도)도 같은 규칙이라 모든 피처가 as_of 이전 자료만의 함수다.
- 지점 자료가 MIN_OBS 개 미만이면 같은 기간 모든 지점을 묶은 공통 매개변수, 그것도 모자라면 NaN.
- 필터는 obs_date ≤ as_of 측정만으로 as_of 까지 돌린다(필터링만, 평활화 없음). 7일 앞 = 상태 전이 7회(수온은 as_of 값 유지).

산출
- 피처(build_features): kf_level(필터 상태), kf_sd(상태 표준편차), kf_pred7(7회 전이 예측), kf_innov(마지막 표준화 혁신),
  kf_drift(하루 성장률). 묶음 BUNDLES.
- 구성원(kf_member): 목표일까지 h = horizon_days 회 전이한 예측의 원단위 10^m − 1(중앙값) 또는 로그정규 평균.
- 잡음 상한(ceiling_*): 측정 잡음 분산 σ_ε² 로 log R² 상한 = 1 − Σσ_ε²/SST_log(구간별), 원단위 상한은 로그정규 잡음 모의.

공개 함수(종합 단계 재사용)
- build_features(df, bundle=CHOSEN["bundle"]) -> DataFrame : df = harness.load_base() 형식, 같은 인덱스.
- kf_member(df, variant="median") -> np.ndarray : 칼만 예측 원단위(2012~2025 행, 매개변수 없는 행 NaN).
- members(df, seed) -> dict : 선택 설정의 OOF 구성원(c1·c3·c2·cg + kf).
- builder(df, seed) -> {"pred", "q90": None, "m_*"} : harness2.Builder 형식(선택 설정).
- make_kf_features(algae, as_of, station_id, horizon, model) -> dict : 순수 함수(행 하나).

실행: python -m algaecast.exp.r2nd_p4_kalman  → reports/experiments/EXP-005/P4/, data/processed/exp/EXP-005b/P4/
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import math
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from algaecast.exp import harness as H
from algaecast.exp import harness2 as H2
from algaecast.features.base import cut_as_of

log = logging.getLogger(__name__)

PX = "P4"
OUT_DATA = H2.EXP_DIR / PX
OUT_REPORT = H2.REPORT_DIR / PX
BUDGET_HOURS = 8.0
TASK_START = "2026-10-22 12:11:59"  # 작업 착수(KST) — 시간 상한 기준

TC = 15.0  # 수온 중심(℃)
WT_RANGE = (-1.0, 40.0)  # 물리적으로 불가능한 수온은 결측
MIN_OBS = 80  # 지점별 매개변수 추정 최소 측정 수(약 1.5년), 미만이면 공통 매개변수
LN10 = math.log(10.0)
MODELS: tuple[str, ...] = ("lltemp", "ll", "lltemp_r2", "lltemp_lv", "damped", "damped_r2", "damped_lv")
ROW_MODELS: tuple[str, ...] = ("lltemp", "damped", "lltemp_lv", "damped_lv")  # 행 단위 필터를 만드는 모형
LV_REF = 2.0  # 수준 의존 잡음 모형의 기준 수준(log10 세포수)
MAIN_MODEL = "lltemp"
WARM_MONTHS = (5, 6, 7, 8, 9, 10)
MODEL_LABEL: dict[str, str] = {
    "lltemp": "로컬 레벨+수온",
    "ll": "로컬 레벨",
    "lltemp_r2": "로컬 레벨+수온·계절 잡음",
    "damped": "Gompertz(감쇠)+수온",
    "damped_r2": "Gompertz(감쇠)+수온·계절 잡음",
    "lltemp_lv": "로컬 레벨+수온·수준 의존 잡음",
    "damped_lv": "Gompertz(감쇠)+수온·수준 의존 잡음",
}
PREFIX: dict[str, str] = {"lltemp": "kf_", "damped": "kfd_"}

FEATURE_COLS: tuple[str, ...] = ("kf_level", "kf_sd", "kf_pred7", "kf_innov", "kf_drift")
_C3 = ("kf_level", "kf_pred7", "kf_sd")
_C5 = ("kf_level", "kf_pred7", "kf_sd", "kf_innov", "kf_drift")
# 묶음 이름 → (모형, 열). 열 이름은 build_features 에서 모형 접두어(kf_/kfd_)로 바뀐다.
BUNDLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "kf3": ("lltemp", _C3),
    "kf5": ("lltemp", _C5),
    "kfd3": ("damped", _C3),
    "kfd5": ("damped", _C5),
}
# main() 의 CV 규칙 결과로 고정(builder·members·build_features 기본값). 다르면 main 이 경고한다.
CHOSEN: dict[str, str] = {"variant": "P4_kf_member", "bundle": ""}


# ================================================================ 1. 원자료
def load_algae(last: pd.Timestamp = H.LAST_DATE) -> pd.DataFrame:
    """조류경보 원자료(5지점) → station_id·obs_date·cells·wtemp. 2025-12-31 이후 측정은 읽은 즉시 버린다."""
    a = pd.read_parquet(
        H.ALGAE_PARQUET, columns=["station_id", "obs_date", "iem_bgalage_cell_co", "iem_wtrtp"]
    )
    a["obs_date"] = pd.to_datetime(a["obs_date"]).dt.normalize()
    a = a[a["obs_date"] <= last].copy()
    a = a.rename(columns={"iem_bgalage_cell_co": "cells", "iem_wtrtp": "wtemp"})
    a["station_id"] = a["station_id"].astype(str)
    a["cells"] = a["cells"].astype(float)
    a["wtemp"] = a["wtemp"].astype(float)
    return a.sort_values(["station_id", "obs_date"]).reset_index(drop=True)


@dataclass(frozen=True)
class Series:
    """한 지점의 측정 사건열(일 번호·log 세포수·전진 채움 수온·측정 월)."""

    days: np.ndarray  # int, 1970-01-01 기준 일 번호(오름차순, 중복 없음)
    y: np.ndarray  # log10(cells + 1), 결측 NaN
    T: np.ndarray  # 그 날까지의 마지막 실측 수온(없으면 TC)
    month: np.ndarray  # 측정 월
    has_T: np.ndarray  # 그 날까지 실측 수온이 있었는지


def make_series(a_site: pd.DataFrame) -> Series:
    """한 지점 원자료 → Series. 같은 날 중복은 평균(원자료에는 없음)."""
    d = a_site[["obs_date", "cells", "wtemp"]].copy()
    d["obs_date"] = pd.to_datetime(d["obs_date"]).dt.normalize()
    wt = d["wtemp"].astype(float)
    d["wtemp"] = wt.where((wt >= WT_RANGE[0]) & (wt <= WT_RANGE[1]))
    d = d.groupby("obs_date", as_index=False).mean(numeric_only=True).sort_values("obs_date")
    days = (d["obs_date"].to_numpy().astype("datetime64[D]").astype(np.int64)).astype(np.int64)
    cells = d["cells"].to_numpy(dtype=float)
    y = np.log10(np.clip(cells, 0.0, None) + 1.0)
    tf = pd.Series(d["wtemp"].to_numpy(dtype=float)).ffill().to_numpy()
    has_t = np.isfinite(tf)
    return Series(
        days=days,
        y=y,
        T=np.where(has_t, tf, TC),
        month=pd.to_datetime(d["obs_date"]).dt.month.to_numpy(),
        has_T=has_t,
    )


def day_number(x: date | pd.Timestamp) -> int:
    return int(np.datetime64(pd.Timestamp(x).normalize().date(), "D").astype(np.int64))


# ================================================================ 2. 모형·필터
@dataclass(frozen=True)
class Params:
    model: str
    q: float
    r: float
    b0: float = 0.0
    b1: float = 0.0
    r_cold: float = math.nan  # lltemp_r2: 11~4월 측정 잡음(r 은 5~10월)
    phi: float = math.nan  # damped: 하루 자기회귀 계수
    a0: float = math.nan  # damped: T = TC 에서의 평형 log 세포수
    a1: float = math.nan  # damped: 평형의 수온 기울기
    rho1: float = 0.0  # *_lv: ln r = ln r(LV_REF) + rho1·(수준 − LV_REF), 수준 = 갱신 직전 예측 평균


def r_of(p: Params, month: np.ndarray) -> np.ndarray:
    """측정별 측정 잡음 분산."""
    if p.model in ("lltemp_r2", "damped_r2"):
        return np.where(np.isin(month, WARM_MONTHS), p.r, p.r_cold)
    return np.full(len(month), p.r)


def r_level(p: Params, level: float) -> float:
    """수준 의존 측정 잡음 분산(*_lv 모형): r·exp(rho1·(수준 − LV_REF)), [1e-4, 5] 로 자른다."""
    return float(min(max(p.r * math.exp(p.rho1 * (level - LV_REF)), 1e-4), 5.0))


def transition(p: Params, k: np.ndarray | float, T: np.ndarray | float) -> tuple:
    """k 일 동안 수온 T 로 전이: x' = a·x + c, 분산 += Q. (a, c, Q)"""
    k = np.asarray(k, dtype=float)
    T = np.asarray(T, dtype=float)
    if p.model in ("ll", "lltemp", "lltemp_r2", "lltemp_lv"):
        g = p.b0 + p.b1 * (T - TC)
        return np.ones_like(k), k * g, k * p.q
    if p.model in ("damped", "damped_r2", "damped_lv"):
        phik = p.phi**k
        mu = p.a0 + p.a1 * (T - TC)
        return phik, (1.0 - phik) * mu, p.q * (1.0 - phik**2) / (1.0 - p.phi**2)
    raise ValueError(p.model)


@dataclass
class FilterOut:
    m: np.ndarray  # 사건 후 필터 평균(시작 전 NaN)
    P: np.ndarray  # 사건 후 필터 분산
    v: np.ndarray  # 혁신(관측일만)
    S: np.ndarray  # 혁신 분산(관측일만)
    ll: float
    n_ll: int


def kf_filter(s: Series, p: Params) -> FilterOut:
    """사건열 칼만 필터(필터링만). 첫 유효 관측에서 산만(diffuse) 시작: m = y, P = r(우도에서 제외)."""
    n = len(s.days)
    a, c, Q = transition(p, np.diff(s.days).astype(float), s.T[:-1]) if n > 1 else ([], [], [])
    a, c, Q = list(np.asarray(a, float)), list(np.asarray(c, float)), list(np.asarray(Q, float))
    rr = list(r_of(p, s.month).astype(float))
    ys = list(s.y.astype(float))
    lv = p.model.endswith("_lv")
    m_out, P_out = [math.nan] * n, [math.nan] * n
    v_out, S_out = [math.nan] * n, [math.nan] * n
    started = False
    m = P = 0.0
    ll, n_ll = 0.0, 0
    log2pi = math.log(2.0 * math.pi)
    for i in range(n):
        if started:
            ai = a[i - 1]
            m = ai * m + c[i - 1]
            P = ai * ai * P + Q[i - 1]
        yi = ys[i]
        if yi == yi:  # 유효 관측
            if not started:
                r0 = rr[i] if not lv else r_level(p, yi)
                m, P, started = yi, r0, True
            else:
                S = P + (rr[i] if not lv else r_level(p, m))
                v = yi - m
                ll -= 0.5 * (log2pi + math.log(S) + v * v / S)
                n_ll += 1
                K = P / S
                m += K * v
                P = (1.0 - K) * P
                v_out[i], S_out[i] = v, S
        if started:
            m_out[i], P_out[i] = m, P
    return FilterOut(np.array(m_out), np.array(P_out), np.array(v_out), np.array(S_out), ll, n_ll)


# ---------------------------------------------------------------- 최대우도
def _theta_to_params(model: str, th: np.ndarray, fix_b1: bool) -> Params:
    q, r = math.exp(th[0]), math.exp(th[1])
    if model == "ll":
        return Params(model, q, r)
    if model == "lltemp":
        return Params(model, q, r, b0=th[2] / 100.0, b1=0.0 if fix_b1 else th[3] / 100.0)
    if model == "lltemp_r2":
        return Params(
            model, q, r, b0=th[3] / 100.0, b1=0.0 if fix_b1 else th[4] / 100.0, r_cold=math.exp(th[2])
        )
    if model == "damped":
        return Params(model, q, r, phi=1.0 - math.exp(th[2]), a0=th[3], a1=0.0 if fix_b1 else th[4] / 10.0)
    if model == "damped_r2":
        return Params(
            model,
            q,
            r,
            r_cold=math.exp(th[2]),
            phi=1.0 - math.exp(th[3]),
            a0=th[4],
            a1=0.0 if fix_b1 else th[5] / 10.0,
        )
    if model == "lltemp_lv":
        return Params(model, q, r, b0=th[2] / 100.0, b1=0.0 if fix_b1 else th[3] / 100.0, rho1=th[4])
    if model == "damped_lv":
        return Params(
            model,
            q,
            r,
            phi=1.0 - math.exp(th[2]),
            a0=th[3],
            a1=0.0 if fix_b1 else th[4] / 10.0,
            rho1=th[5],
        )
    raise ValueError(model)


def _starts(model: str) -> list[np.ndarray]:
    lq = [math.log(0.02), math.log(0.005), math.log(0.08)]
    lr = [math.log(0.10), math.log(0.30), math.log(0.03)]
    out = []
    for a, b in zip(lq, lr, strict=True):
        if model == "ll":
            out.append(np.array([a, b]))
        elif model == "lltemp":
            out.append(np.array([a, b, 0.0, 0.5]))
        elif model == "lltemp_r2":
            out.append(np.array([a, b, b, 0.0, 0.5]))
        elif model == "damped_r2":
            out.append(np.array([a, b, b, math.log(0.05), 2.0, 1.0]))
        elif model == "lltemp_lv":
            out.append(np.array([a, b, 0.0, 0.5, -0.2]))
        elif model == "damped_lv":
            out.append(np.array([a, b, math.log(0.05), 2.0, 1.0, -0.2]))
        else:
            out.append(np.array([a, b, math.log(0.05), 2.0, 1.0]))
    return out


def _bounds(model: str) -> list[tuple[float, float]]:
    vq, vr = (math.log(1e-6), math.log(2.0)), (math.log(1e-4), math.log(5.0))
    if model == "ll":
        return [vq, vr]
    if model == "lltemp":
        return [vq, vr, (-20.0, 20.0), (-5.0, 5.0)]
    if model == "lltemp_r2":
        return [vq, vr, vr, (-20.0, 20.0), (-5.0, 5.0)]
    if model == "damped_r2":
        return [vq, vr, vr, (math.log(1e-4), math.log(0.5)), (-2.0, 8.0), (-5.0, 5.0)]
    if model == "lltemp_lv":
        return [vq, vr, (-20.0, 20.0), (-5.0, 5.0), (-2.0, 2.0)]
    if model == "damped_lv":
        return [vq, vr, (math.log(1e-4), math.log(0.5)), (-2.0, 8.0), (-5.0, 5.0), (-2.0, 2.0)]
    return [vq, vr, (math.log(1e-4), math.log(0.5)), (-2.0, 8.0), (-5.0, 5.0)]


def neg_loglik(th: np.ndarray, model: str, series: list[Series], fix_b1: bool) -> float:
    p = _theta_to_params(model, th, fix_b1)
    tot = 0.0
    for s in series:
        tot += kf_filter(s, p).ll
    return -tot if np.isfinite(tot) else 1e12


@dataclass
class Fit:
    params: Params
    nll: float
    n_obs: int
    source: str  # own / pooled
    theta: np.ndarray
    fix_b1: bool


def fit_mle(series: list[Series], model: str) -> tuple[Params, float, np.ndarray, bool]:
    """여러 시작점 L-BFGS-B. 수온 실측이 30개 미만이면 수온 기울기를 0 으로 고정."""
    n_t = int(sum(int(np.sum(s.has_T & np.isfinite(s.y))) for s in series))
    fix_b1 = n_t < 30
    best = None
    for th0 in _starts(model):
        res = minimize(
            neg_loglik, th0, args=(model, series, fix_b1), method="L-BFGS-B", bounds=_bounds(model)
        )
        if best is None or res.fun < best.fun:
            best = res
    assert best is not None
    return _theta_to_params(model, best.x, fix_b1), float(best.fun), np.asarray(best.x), fix_b1


def _fingerprint(a: pd.DataFrame) -> str:
    h = hashlib.sha1()
    h.update(a["station_id"].astype(str).str.cat(sep=",").encode())
    h.update(pd.to_datetime(a["obs_date"]).to_numpy().astype("datetime64[D]").astype(np.int64).tobytes())
    h.update(np.nan_to_num(a["cells"].to_numpy(dtype=float), nan=-7.0).tobytes())
    h.update(np.nan_to_num(a["wtemp"].to_numpy(dtype=float), nan=-7.0).tobytes())
    return h.hexdigest()


_FIT_CACHE: dict[tuple, Fit | None] = {}


def params_for_year(algae: pd.DataFrame, station_id: str, year: int, model: str = MAIN_MODEL) -> Fit | None:
    """기준일 연도 year 행에 쓸 매개변수: obs_date ≤ (year−1)-12-31 측정만으로 최대우도.

    지점 유효 측정이 MIN_OBS 미만이면 같은 기간 모든 지점 공통 매개변수(지점별 우도 합), 그래도 모자라면 None.
    결과는 (모형, 지점, 연도, 입력 지문)으로 기억한다(입력이 같으면 같은 결과 — 순수 함수 성질 유지).
    """
    cut = cut_as_of(algae, date(year - 1, 12, 31))
    own = cut[cut["station_id"].astype(str) == station_id]
    n_own = int(own["cells"].notna().sum())
    if n_own >= MIN_OBS:
        key = (model, station_id, year, "own", _fingerprint(own))
        if key not in _FIT_CACHE:
            p, nll, th, fx = fit_mle([make_series(own)], model)
            _FIT_CACHE[key] = Fit(p, nll, n_own, "own", th, fx)
        return _FIT_CACHE[key]
    n_all = int(cut["cells"].notna().sum())
    if n_all < MIN_OBS:
        return None
    key = (model, "*", year, "pooled", _fingerprint(cut))
    if key not in _FIT_CACHE:
        ser = [make_series(g) for _, g in cut.groupby("station_id") if g["cells"].notna().sum() >= 2]
        p, nll, th, fx = fit_mle(ser, model)
        _FIT_CACHE[key] = Fit(p, nll, n_all, "pooled", th, fx)
    return _FIT_CACHE[key]


# ================================================================ 3. 순수 피처 함수(행 하나)
NAN_FEATS: dict[str, float] = {
    **{c: math.nan for c in FEATURE_COLS},
    "kf_predh": math.nan,
    "kf_varh": math.nan,
    "kf_obsvarh": math.nan,
}


def state_at(s: Series, p: Params, as_of_day: int, fo: FilterOut | None = None) -> dict[str, float]:
    """사건열 s(이미 as_of 이전으로 잘림)의 필터를 as_of 까지 전이 → 상태·혁신·수온."""
    fo = fo or kf_filter(s, p)
    ok = np.where(np.isfinite(fo.m) & (s.days <= as_of_day))[0]
    if not len(ok):
        return {}
    i = int(ok[-1])
    a, c, Q = transition(p, float(as_of_day - s.days[i]), float(s.T[i]))
    m = float(a * fo.m[i] + c)
    P = float(a * a * fo.P[i] + Q)
    vi = np.where(np.isfinite(fo.v[: i + 1]))[0]
    innov = float(fo.v[vi[-1]] / math.sqrt(fo.S[vi[-1]])) if len(vi) else math.nan
    return {"m": m, "P": P, "T": float(s.T[i]), "innov": innov}


def forecast(p: Params, m: float, P: float, T: float, h: float) -> tuple[float, float]:
    """h 일 앞(전이 h 회, 수온 T 유지) 상태 평균·분산."""
    a, c, Q = transition(p, float(h), float(T))
    return float(a * m + c), float(a * a * P + Q)


def make_kf_features(
    algae: pd.DataFrame, as_of: date, station_id: str, horizon: float = 7.0, model: str = MAIN_MODEL
) -> dict[str, float]:
    """(원자료, as_of, 지점) → 칼만 필터 피처 dict. as_of 이후 측정은 진입 직후 버린다.

    매개변수는 (as_of 연도 − 1)-12-31 까지의 측정으로 추정(params_for_year), 필터는 as_of 까지의 측정으로만 돈다.
    kf_predh·kf_varh·kf_obsvarh 는 목표일(h = horizon 회 전이) 예측 평균·상태 분산·관측 분산(구성원용).
    """
    a = cut_as_of(algae, as_of)
    a = a[pd.to_datetime(a["obs_date"]) <= H.LAST_DATE]
    fit = params_for_year(a, station_id, pd.Timestamp(as_of).year, model)
    own = a[a["station_id"].astype(str) == station_id]
    if fit is None or own["cells"].notna().sum() == 0:
        return dict(NAN_FEATS)
    p = fit.params
    st = state_at(make_series(own), p, day_number(as_of))
    if not st:
        return dict(NAN_FEATS)
    m7, _ = forecast(p, st["m"], st["P"], st["T"], 7.0)
    mh, vh = forecast(p, st["m"], st["P"], st["T"], float(horizon))
    if p.model.endswith("_lv"):
        r_h = r_level(p, mh)
    else:
        r_h = float(r_of(p, np.array([(pd.Timestamp(as_of) + pd.Timedelta(days=float(horizon))).month]))[0])
    return {
        "kf_level": st["m"],
        "kf_sd": math.sqrt(max(st["P"], 0.0)),
        "kf_pred7": m7,
        "kf_innov": st["innov"],
        "kf_drift": (m7 - st["m"]) / 7.0,
        "kf_predh": mh,
        "kf_varh": vh,
        "kf_obsvarh": vh + r_h,
    }


# ================================================================ 4. 표본 단위 생성(같은 인덱스)
def all_kf(df: pd.DataFrame, model: str = MAIN_MODEL, algae: pd.DataFrame | None = None) -> pd.DataFrame:
    """표본 행마다 make_kf_features(as_of = base_date, horizon = horizon_days). 같은 인덱스."""
    H.guard_no_2026(df)
    algae = load_algae() if algae is None else algae
    rows = []
    for sid, bd, hz in zip(
        df["station_id"].astype(str),
        pd.to_datetime(df["base_date"]),
        df["horizon_days"].astype(float),
        strict=True,
    ):
        rows.append(make_kf_features(algae, bd.date(), sid, hz, model))
    return pd.DataFrame(rows, index=df.index)


def _kf_cache_path(model: str) -> Path:
    return OUT_DATA / f"kf_rows_{model}.parquet"


def load_kf(df: pd.DataFrame, model: str = MAIN_MODEL) -> pd.DataFrame:
    """all_kf 결과를 행 단위 파일로 기억(키 대조). 없거나 다르면 새로 만든다."""
    p = _kf_cache_path(model)
    if p.exists():
        o = pd.read_parquet(p)
        same = len(o) == len(df) and (
            (o["station_id"].astype(str).to_numpy() == df["station_id"].astype(str).to_numpy()).all()
            and (o["base_date"].astype(str).to_numpy() == df["base_date"].astype(str).to_numpy()).all()
        )
        if same:
            return o.drop(columns=["station_id", "base_date"]).set_axis(df.index)
    k = all_kf(df, model)
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    out = k.copy()
    out.insert(0, "base_date", df["base_date"].astype(str).to_numpy())
    out.insert(0, "station_id", df["station_id"].astype(str).to_numpy())
    out.to_parquet(p, index=False)
    return k


def build_features(df: pd.DataFrame, bundle: str | None = None) -> pd.DataFrame:
    """칼만 피처 묶음 열(같은 인덱스). 열 이름은 모형 접두어(kf_ = lltemp, kfd_ = damped).

    bundle 기본값은 CHOSEN['bundle'](비어 있으면 kfd3).
    """
    b = bundle or CHOSEN.get("bundle") or "kfd3"
    model, cols = BUNDLES[b]
    k = load_kf(df, model)[list(cols)]
    return k.rename(columns={c: PREFIX[model] + c[3:] for c in cols})


def kf_member(df: pd.DataFrame, variant: str = "median", model: str = MAIN_MODEL) -> np.ndarray:
    """칼만 예측 구성원(원단위). median = 10^m − 1, mean = 로그정규 평균 10^(m + ½·ln10·관측분산) − 1."""
    k = load_kf(df, model)
    m = k["kf_predh"].to_numpy(dtype=float)
    if variant == "median":
        z = m
    elif variant == "mean":
        z = m + 0.5 * LN10 * k["kf_obsvarh"].to_numpy(dtype=float)
    else:
        raise ValueError(variant)
    return np.clip(10.0**z - 1.0, 0.0, None)


def b0_member(df: pd.DataFrame) -> np.ndarray:
    """참고 구성원: 지속성(기준일 측정 그대로) 10^cell_log_t0 − 1."""
    return np.clip(10.0 ** df["cell_log_t0"].to_numpy(dtype=float) - 1.0, 0.0, None)


# ================================================================ 5. 구성원·빌더
# 구성원 이름 → (모형, 원단위 변환). b0 는 지속성 참고 구성원.
MEMBER_KINDS: dict[str, tuple[str, str]] = {
    "kf_member": ("lltemp", "median"),
    "kf_member_mean": ("lltemp", "mean"),
    "kfd_member": ("damped", "median"),
    "kfd_member_mean": ("damped", "mean"),
    "kflv_member": ("lltemp_lv", "median"),
    "kfdlv_member": ("damped_lv", "median"),
    "b0_member": ("", "b0"),
}
MEMBER_NAME: dict[str, str] = {
    "kf_member": "kf",
    "kf_member_mean": "kf",
    "kfd_member": "kfd",
    "kfd_member_mean": "kfd",
    "kflv_member": "kflv",
    "kfdlv_member": "kfdlv",
    "b0_member": "b0",
}


def member_values(df: pd.DataFrame, kind: str) -> np.ndarray:
    model, how = MEMBER_KINDS[kind]
    return b0_member(df) if how == "b0" else kf_member(df, how, model)


def _with_member(df: pd.DataFrame, mem: dict[str, np.ndarray], name: str, values: np.ndarray) -> dict:
    """C 구성원 + 추가 구성원 하나 → 연도 확장 NNLS. 추가 구성원이 NaN 인 행은 c1 로 채운다(2020~2025 에는 없음)."""
    v = np.asarray(values, dtype=float).copy()
    bad = ~np.isfinite(v)
    v[bad] = np.asarray(mem["c1"], dtype=float)[bad]
    full = {**mem, name: v}
    names = (*H2.C_NAMES, name)
    pred, w = H.ensemble_expanding(df, full, names=names)
    out = {"pred": pred, "q90": None, **{f"m_{k}": full[k] for k in names}}
    for y, wy in w.items():
        out[f"w{y}_{name}"] = np.full(len(df), wy[name])
    return out


def _feature_members(df: pd.DataFrame, seed: int, feat: str) -> dict[str, np.ndarray]:
    """피처 변형(또는 그 대조군) 이름 feat 의 회귀 구성원(캐시). 'C' 면 기준 모델."""
    if feat == "C":
        o = H2.run_cached(df, "C", seed, H2.c_pred)
    else:
        o = H2.run_cached(df, f"P4_{feat}", seed, variant_builder(feat))
    return {k: o[f"m_{k}"] for k in H2.C_NAMES}


def parse_variant(name: str) -> tuple[str, bool, str]:
    """'P4_' 를 뗀 이름 → (피처 묶음 또는 '', 대조군 여부, 구성원 또는 '').

    예: kfd3 · kfd3_ctrl · kfd_member · kfd3+kfd_member · kfd3_ctrl+kfd_member
    """
    n = name[3:] if name.startswith("P4_") else name
    feat, _, mem = n.partition("+")
    if feat in MEMBER_KINDS and not mem:
        return "", False, feat
    ctrl = feat.endswith("_ctrl")
    b = feat[: -len("_ctrl")] if ctrl else feat
    if b not in BUNDLES or (mem and mem not in MEMBER_KINDS):
        raise KeyError(name)
    return b, ctrl, mem


def variant_builder(name: str) -> H2.Builder:
    """변형 이름 → harness2.Builder. 피처는 C 에 열 추가(대조군은 같은 모양·결측 위치 난수), 구성원은 NNLS 5번째."""
    b, ctrl, mem = parse_variant(name)

    def build(df: pd.DataFrame, seed: int) -> dict[str, np.ndarray]:
        if b and not mem:
            feat = build_features(df, b)
            return H2.c_pred(df, seed, H2.noise_like(feat, seed) if ctrl else feat)
        base = "C" if not b else (f"{b}_ctrl" if ctrl else b)
        return _with_member(df, _feature_members(df, seed, base), MEMBER_NAME[mem], member_values(df, mem))

    return build


def control_of(name: str) -> str | None:
    """피처가 들어간 변형의 대조군 이름(구성원은 그대로, 피처 열만 난수)."""
    b, ctrl, mem = parse_variant(name)
    if not b or ctrl:
        return None
    return f"P4_{b}_ctrl" + (f"+{mem}" if mem else "")


def label_of(name: str) -> str:
    b, ctrl, mem = parse_variant(name)
    parts = ["C"]
    if b:
        model, cols = BUNDLES[b]
        parts.append(
            f"난수 {len(cols)}열({b} 대조군)" if ctrl else f"{b}({MODEL_LABEL[model]} 피처 {len(cols)}열)"
        )
    if mem:
        model, how = MEMBER_KINDS[mem]
        parts.append(
            "지속성 구성원(참고)"
            if how == "b0"
            else f"{MODEL_LABEL[model]} 칼만 구성원({'중앙값' if how == 'median' else '로그정규 평균'})"
        )
    return " + ".join(parts)


def builder(df: pd.DataFrame, seed: int) -> dict[str, np.ndarray]:
    """harness2.Builder 형식: 선택 설정(CHOSEN['variant'])의 {'pred', 'q90': None, 'm_*'}(분위는 v1 동결)."""
    return H2.run_cached(df, CHOSEN["variant"], seed, variant_builder(CHOSEN["variant"]))


def members(df: pd.DataFrame, seed: int) -> dict[str, np.ndarray]:
    """선택 설정의 OOF 구성원(c1·c3·c2·cg + 칼만). 종합 단계 재사용용."""
    out = builder(df, seed)
    return {k[2:]: v for k, v in out.items() if k.startswith("m_")}


# ================================================================ 6. 측정 잡음 상한
def site_fits(algae: pd.DataFrame, year: int = 2025, models: tuple[str, ...] = MODELS) -> dict:
    """연도 year 행용(= ≤ year−1 측정) 지점별 모형 적합 결과."""
    out: dict = {}
    for m in models:
        for sid in sorted(algae["station_id"].unique()):
            f = params_for_year(algae, sid, year, m)
            out[(m, sid)] = f
    return out


def hessian_ci_r(fit: Fit, series: list[Series], model: str) -> tuple[float, float]:
    """log r 의 관측 정보(수치 2계 미분)로 r 의 95% 구간."""
    th = np.asarray(fit.theta, dtype=float)
    n = len(th)
    eps = 1e-3
    Hm = np.zeros((n, n))

    def f(t: np.ndarray) -> float:
        return neg_loglik(t, model, series, fit.fix_b1)

    f0 = f(th)
    for i in range(n):
        for j in range(i, n):
            ei, ej = np.eye(n)[i] * eps, np.eye(n)[j] * eps
            if i == j:
                Hm[i, i] = (f(th + ei) - 2 * f0 + f(th - ei)) / eps**2
            else:
                Hm[i, j] = Hm[j, i] = (
                    f(th + ei + ej) - f(th + ei - ej) - f(th - ei + ej) + f(th - ei - ej)
                ) / (4 * eps**2)
    try:
        cov = np.linalg.inv(Hm)
        se = math.sqrt(max(cov[1, 1], 0.0))
    except np.linalg.LinAlgError:
        se = math.nan
    lr = th[1]
    return math.exp(lr - 1.96 * se), math.exp(lr + 1.96 * se)


def variogram_nugget(
    algae: pd.DataFrame, last_year: int = 2024, months: tuple[int, ...] = (6, 7, 8, 9, 10)
) -> dict:
    """모형 없는 교차 점검: 같은 지점 측정 짝의 반변동 γ(h) = ½·평균(Δlog)², h ∈ {3~4, 7, 14} 일(목표 측정 월 기준).

    γ(h) ≈ σ_ε² + ½·q·h(랜덤 워크 + 백색 잡음) → h 에 대한 가중 직선의 절편 = 잡음 분산(nugget).
    """
    a = algae[pd.to_datetime(algae["obs_date"]).dt.year <= last_year]
    out = {}
    for sid, g in a.groupby("station_id"):
        g = g.dropna(subset=["cells"]).sort_values("obs_date")
        d = pd.to_datetime(g["obs_date"]).to_numpy().astype("datetime64[D]").astype(np.int64)
        y = np.log10(g["cells"].to_numpy(dtype=float) + 1)
        mo = pd.to_datetime(g["obs_date"]).dt.month.to_numpy()
        lags = {"3-4": (3, 4), "7": (7, 7), "14": (14, 14)}
        gam, cnt, hs = {}, {}, {}
        for nm, (lo, hi) in lags.items():
            diffs, hh = [], []
            for i in range(len(d)):
                j = np.where((d - d[i] >= lo) & (d - d[i] <= hi))[0]
                for jj in j:
                    if mo[jj] in months:
                        diffs.append(y[jj] - y[i])
                        hh.append(d[jj] - d[i])
            diffs = np.asarray(diffs)
            gam[nm] = float(0.5 * np.mean(diffs**2)) if len(diffs) else math.nan
            cnt[nm] = len(diffs)
            hs[nm] = float(np.mean(hh)) if len(hh) else math.nan
        ok = [k for k in lags if np.isfinite(gam[k]) and cnt[k] >= 10]
        if len(ok) >= 2:
            x = np.array([hs[k] for k in ok])
            yv = np.array([gam[k] for k in ok])
            w = np.array([cnt[k] for k in ok], dtype=float)
            A = np.column_stack([np.ones_like(x), x]) * np.sqrt(w)[:, None]
            coef, *_ = np.linalg.lstsq(A, yv * np.sqrt(w), rcond=None)
            nug = float(coef[0])
        else:
            nug = math.nan
        out[str(sid)] = {"gamma": gam, "n_pairs": cnt, "mean_lag": hs, "nugget": nug}
    return out


def _site_month_prior(algae: pd.DataFrame, last_year: int = 2024) -> pd.DataFrame:
    a = algae[pd.to_datetime(algae["obs_date"]).dt.year <= last_year].dropna(subset=["cells"]).copy()
    a["l"] = np.log10(a["cells"].astype(float) + 1)
    a["month"] = pd.to_datetime(a["obs_date"]).dt.month
    return a.groupby(["station_id", "month"])["l"].agg(["mean", "var", "size"]).reset_index()


def sigma2_rows(df: pd.DataFrame, fits: dict[str, Fit]) -> np.ndarray:
    """행별 측정 잡음 분산(목표일 월 기준 — 계절 모형이면 5~10월/11~4월 값).

    수준 의존 모형(*_lv)은 수준 대신 관측된 목표값 log10(y+1)을 넣는다(진짜 상태의 근사, 민감도용).
    """
    sid = df["station_id"].astype(str).to_numpy()
    mon = pd.to_datetime(df["target_date"]).dt.month.to_numpy()
    ell = np.log10(df["target_cells"].to_numpy(dtype=float) + 1)
    out = np.full(len(df), np.nan)
    for s, f in fits.items():
        m = sid == s
        if f.params.model.endswith("_lv"):
            out[m] = [r_level(f.params, v) for v in ell[m]]
        else:
            out[m] = r_of(f.params, mon[m])
    return out


def ceiling_sim(
    df: pd.DataFrame,
    mask: np.ndarray,
    s2_all: np.ndarray,
    prior: pd.DataFrame,
    n_sim: int = 4000,
    seed: int = 20261022,
) -> dict:
    """진짜 상태를 아는 완벽한 모형의 기대 R²(로그정규 측정 잡음 가정).

    가정: 관측 ℓ = log10(y+1) = x + ε, ε ~ N(0, σ_ε²(지점)), x 의 사전분포 = 지점·월 N(μ, V − σ_ε²)(≤2024 측정).
    - B(조건부, 주): 실제 관측 ℓ 이 주어졌을 때 x 를 사후분포 N(μ + k(ℓ−μ), kσ²) 에서 뽑고(k = τ²/(τ²+σ²)),
      완벽한 예측 = E[Y|x] = 10^x·exp(½(ln10·σ)²) − 1 로 실제 관측 Y 에 대해 R² 를 계산한다(같은 SST).
    - A(합성): 같은 x 에서 새 관측 Y* = 10^(x+ε*) − 1 을 만들어 R² 를 계산한다(분포 수준 기대값).
    - 로그 R²: 해석식 1 − Σσ²/SST_log 과 B 의 모의값.
    """
    rng = np.random.default_rng(seed)
    obs = df["target_cells"].to_numpy(dtype=float)[mask]
    ell = np.log10(obs + 1)
    sid = df["station_id"].astype(str).to_numpy()[mask]
    mon = pd.to_datetime(df["target_date"]).dt.month.to_numpy()[mask]
    pr = prior.set_index(["station_id", "month"])
    s2 = np.asarray(s2_all, dtype=float)[mask]
    mu = np.array(
        [pr.loc[(s, m), "mean"] if (s, m) in pr.index else np.nan for s, m in zip(sid, mon, strict=True)]
    )
    V = np.array(
        [pr.loc[(s, m), "var"] if (s, m) in pr.index else np.nan for s, m in zip(sid, mon, strict=True)]
    )
    mu = np.where(np.isfinite(mu), mu, ell.mean())
    V = np.where(np.isfinite(V), V, ell.var())
    tau2 = np.clip(V - s2, 0.0, None)
    k = tau2 / (tau2 + s2)
    post_m = mu + k * (ell - mu)
    post_sd = np.sqrt(k * s2)
    sst_log = float(np.sum((ell - ell.mean()) ** 2))
    sst_raw = float(np.sum((obs - obs.mean()) ** 2))
    corr = np.exp(0.5 * (LN10**2) * s2)
    r2b_mean, r2b_med, r2b_log, r2a_mean, r2a_log = [], [], [], [], []
    for _ in range(n_sim):
        x = post_m + post_sd * rng.standard_normal(len(ell))
        p_mean = 10**x * corr - 1
        p_med = 10**x - 1
        r2b_mean.append(1 - np.sum((obs - p_mean) ** 2) / sst_raw)
        r2b_med.append(1 - np.sum((obs - p_med) ** 2) / sst_raw)
        r2b_log.append(1 - np.sum((ell - x) ** 2) / sst_log)
        ys = 10 ** (x + np.sqrt(s2) * rng.standard_normal(len(ell))) - 1
        r2a_mean.append(1 - np.sum((ys - p_mean) ** 2) / np.sum((ys - ys.mean()) ** 2))
        ls = np.log10(ys + 1)
        r2a_log.append(1 - np.sum((ls - x) ** 2) / np.sum((ls - ls.mean()) ** 2))

    def q(v: list[float]) -> dict[str, float]:
        a = np.asarray(v)
        return {
            "mean": float(a.mean()),
            "median": float(np.median(a)),
            "p05": float(np.percentile(a, 5)),
            "p95": float(np.percentile(a, 95)),
        }

    return {
        "n": int(mask.sum()),
        "var_log": float(ell.var()),
        "mean_sigma2": float(s2.mean()),
        "log_analytic": float(1 - np.sum(s2) / sst_log),
        "B_raw_condmean": q(r2b_mean),
        "B_raw_median": q(r2b_med),
        "B_log": q(r2b_log),
        "A_raw_condmean": q(r2a_mean),
        "A_log": q(r2a_log),
        "top1_share_sst_raw": float(np.max((obs - obs.mean()) ** 2) / sst_raw),
    }


def obs_as_truth_raw(
    df: pd.DataFrame, mask: np.ndarray, s2_all: np.ndarray, n_sim: int = 4000, seed: int = 7
) -> dict:
    """낙관 민감도: 관측을 진짜 상태로 보고(x = ℓ) 새 잡음을 더한 Y* 를 E[Y|x] 로 맞힐 때의 R²."""
    rng = np.random.default_rng(seed)
    obs = df["target_cells"].to_numpy(dtype=float)[mask]
    x = np.log10(obs + 1)
    s2 = np.asarray(s2_all, dtype=float)[mask]
    p = 10**x * np.exp(0.5 * LN10**2 * s2) - 1
    v = []
    for _ in range(n_sim):
        ys = 10 ** (x + np.sqrt(s2) * rng.standard_normal(len(x))) - 1
        v.append(1 - np.sum((ys - p) ** 2) / np.sum((ys - ys.mean()) ** 2))
    a = np.asarray(v)
    return {
        "mean": float(a.mean()),
        "median": float(np.median(a)),
        "p05": float(np.percentile(a, 5)),
        "p95": float(np.percentile(a, 95)),
    }


def innovation_check(algae: pd.DataFrame, fits: dict[str, Fit]) -> pd.DataFrame:
    """표준화 혁신² 평균(모형이 맞으면 1). 2025-09~10(새 채수 위치) vs 2025-01~08 vs 2020~2024 9~10월(≤2024 매개변수)."""
    rows = []
    for sid, f in fits.items():
        g = algae[algae["station_id"] == sid]
        s = make_series(g)
        fo = kf_filter(s, f.params)
        dates = pd.to_datetime(s.days.astype("datetime64[D]"))
        z2 = (fo.v / np.sqrt(fo.S)) ** 2
        ok = np.isfinite(z2)
        for nm, m in (
            ("2020~2024 9~10월", (dates.year >= 2020) & (dates.year <= 2024) & np.isin(dates.month, (9, 10))),
            ("2025 1~8월", (dates.year == 2025) & (dates.month <= 8)),
            ("2025 9~10월", (dates.year == 2025) & np.isin(dates.month, (9, 10))),
        ):
            mm = ok & np.asarray(m)
            rows.append(
                {
                    "지점": sid,
                    "구간": nm,
                    "n": int(mm.sum()),
                    "z2_mean": float(z2[mm].mean()) if mm.any() else math.nan,
                }
            )
    return pd.DataFrame(rows)


# ================================================================ 7. 실행·표
def _elapsed_budget() -> H.Budget:
    b = H.Budget(BUDGET_HOURS, f"EXP-005 {PX}")
    b.t0 = datetime.strptime(TASK_START, "%Y-%m-%d %H:%M:%S").timestamp()
    return b


def run_variants(df: pd.DataFrame, names: list[str], budget: H.Budget) -> dict[str, tuple[list[dict], dict]]:
    out = {}
    for nm in names:
        budget.check()
        t0 = time.time()
        rows, mean = H2.evaluate(df, nm, variant_builder(nm))
        mean["구성"] = label_of(nm)
        out[nm] = (rows, mean)
        log.info("%s: CV r2_raw %.4f (%.0fs)", nm, mean["cv_r2_raw"], time.time() - t0)
    return out


def params_table(algae: pd.DataFrame, model: str = MAIN_MODEL) -> pd.DataFrame:
    """매개변수 연도(= 그 연도 기준일 행에 쓰는 값, ≤ 연도−1 측정으로 추정)별 지점 매개변수."""
    rows = []
    for year in range(2013, 2026):
        for sid in sorted(algae["station_id"].unique()):
            f = params_for_year(algae, sid, year, model)
            if f is None:
                continue
            rows.append(
                {
                    "param_year": year,
                    "station_id": sid,
                    "source": f.source,
                    "n_obs": f.n_obs,
                    **asdict(f.params),
                }
            )
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=("all", "features", "ceiling", "models"))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from algaecast.exp import r2nd_p4_report as RP

    budget = _elapsed_budget()
    df = H.load_base()
    algae = load_algae()
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.mkdir(parents=True, exist_ok=True)
    if args.stage in ("all", "features"):
        for m in ROW_MODELS:
            t0 = time.time()
            load_kf(df, m)
            log.info("칼만 행 단위(%s) %.0fs", m, time.time() - t0)
        for m in ROW_MODELS:
            params_table(algae, m).to_csv(OUT_REPORT / f"params_{m}.csv", index=False, encoding="utf-8")
    if args.stage in ("all", "ceiling"):
        budget.check()
        RP.ceiling_report(df, algae)
    if args.stage in ("all", "models"):
        budget.check()
        RP.models_report(df, budget)
    log.info("경과 %.2fh / %.0fh", budget.elapsed_h, BUDGET_HOURS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
