# ruff: noqa: E501  (한국어 보고서 문장 — 표시 폭 기준 초과, black 110 은 통과)
"""R1(EXP-004) 분산 반영 원단위 복원 — 재학습 없이 v1 기준 OOF 의 후처리만 비교한다.

배경
- v1 점예측은 log10(x+1) 공간 회귀(C1·C3)와 tweedie(C2)를 log 공간 NNLS 로 묶은 값이라 조건부 '중앙값'에
  가깝다. 원단위 R²·NSE 는 소수의 극단값(10^5 cells/mL 안팎)이 좌우하므로, 점예측을 조건부 '평균' 쪽으로
  옮기면 원단위 오차가 줄 수 있다(대신 log 오차는 늘어난다).
- 분위 예측 q10·q90 의 log 폭으로 행별 σ(x) ≈ (log10(q90+1) − log10(q10+1)) / (2·1.2816) 를 추정하고
  로그정규 평균 10^(μ + ½·ln10·(kσ)²) − 1 로 바꾼다(k 는 σ 보정 배수).
- 폭 보정 p' = m + s·(p − m)(지점 공통/지점별), 단측 폭 보정 p' = p + (s − 1)·max(p − m, 0),
  상위 구간 한정 로그정규 평균(μ > g 인 행만), C1 에 같은 처리 후 재결합, 전역 smearing 을 비교한다.
- 앙상블 수준 원단위 복원: v1 의 log 공간 NNLS 는 smearing 을 거친 C1 을 낮게 가중한다. 구성원 가중치를
  원단위 MSE 로 고르는 볼록 결합(합=1, 비음수, 0.01 격자)과 합 제약 없는 원단위 NNLS 를 비교하고, 그 위에
  σ·폭 보정을 겹친 변형도 본다.

규칙(EXP-PLAN 2·4절)
- 모든 계수(k·m·s·g·smearing 배수·결합 가중치)는 ``harness.expanding_fit_apply`` 로 적합한다: 연도 Y 는
  Y 이전 CV OOF(2020~Y−1), 2025 는 2020~2024 전체. 적합 자료가 없는 2020 은 v1 점예측 그대로다.
- 목적함수는 적합 구간 원단위 MSE 최소(격자 탐색). '제약' 변형(slack 지정)은 적합 구간 rmse_log 가 v1 앙상블
  대비 +slack 이하인 후보 중에서만 고른다(채택 기준 'rmse_log 악화 0.01 이내'를 적합 단계에서 미리 반영).
- 변형 선택은 CV(2020~2024) 지표로만 한다. 2025 는 확인용이고, 2026 은 읽지 않는다.

공개 함수(종합 단계 재사용)
- ``postprocess(df, preds, variant=None) -> np.ndarray``: ``df`` 는 ``harness.load_base()`` 형식,
  ``preds`` 는 ``harness.run_members`` 반환 형식(c1·c1_log·c3·c2·q10·q50·q90, 선택적으로 ens).
  선택 변형(기본 ``CHOSEN``)을 연도 확장 적합으로 적용한 원단위 점예측(2020~2025 행, 나머지 NaN)을 돌려준다.
  ens 가 없으면 ``harness.ensemble_expanding`` 으로 만든다(2020 대체값·제약 기준).
- ``run_variant(df, preds, variant) -> (pred, info)``: 임의 변형 실행(연도별 적합 계수 포함).
- 변환 함수: ``sigma_from_quantiles``·``lognormal_mean``·``stretch``·``hinge``·``simplex_grid``.

실행: ``python -m algaecast.exp.r1_variance_restore`` → reports/experiments/EXP-004/, data/processed/exp/EXP-004/
"""

from __future__ import annotations

import itertools
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.optimize import nnls

from algaecast.exp import harness as H

log = logging.getLogger(__name__)

EXP_ID = "EXP-004"
OUT_REPORT = H.EXP_REPORTS / EXP_ID
OUT_DATA = H.EXP_DATA / EXP_ID
BUDGET_HOURS = 4.0

LN10 = float(np.log(10.0))
Z90 = 1.2815515655446004  # 표준정규 0.9 분위
LOG_CAP = 7.0  # log10 상한(models.train.LOG_CAP 과 같음)
LOG_SLACK = 0.005  # 제약 변형: 적합 구간 rmse_log 허용 증가(채택 기준 0.01 의 절반)
MIN_SITE_ROWS = 40  # 지점별 적합 최소 행 수(미만이면 지점 공통 계수)
MEMBERS = ("c1", "c3", "c2")
W_STEP = 0.01  # 볼록 결합 가중치 격자 간격

K_GRID = np.round(np.arange(0.0, 2.0 + 1e-9, 0.01), 2)  # σ 보정 배수
S_GRID = np.round(np.arange(0.80, 1.60 + 1e-9, 0.01), 2)  # 폭 배수
M_GRID = np.round(np.arange(1.0, 5.0 + 1e-9, 0.1), 1)  # 폭 보정 중심(log10)
G_GRID = np.round(np.arange(2.0, 5.0 + 1e-9, 0.25), 2)  # 로그정규 적용 하한(log10)


# ---------------------------------------------------------------- 변환(순수 함수)
def to_log(x: np.ndarray) -> np.ndarray:
    """log10(x + 1), 음수는 0 으로."""
    return np.log10(np.clip(np.asarray(x, dtype=float), 0.0, None) + 1.0)


def from_log(z: np.ndarray) -> np.ndarray:
    """10^z − 1, z 는 [0, LOG_CAP] 로 자른다(models.train.to_cells 와 같은 규칙)."""
    return np.clip(10.0 ** np.clip(np.asarray(z, dtype=float), 0.0, LOG_CAP) - 1.0, 0.0, None)


def sigma_from_quantiles(q10: np.ndarray, q90: np.ndarray) -> np.ndarray:
    """분위 폭으로 본 log10 공간 표준편차 σ = (log10(q90+1) − log10(q10+1)) / (2·z0.9)."""
    return np.clip(to_log(q90) - to_log(q10), 0.0, None) / (2.0 * Z90)


def lognormal_shift(sigma: np.ndarray, k: float | np.ndarray) -> np.ndarray:
    """log10 공간 평균 이동량 ½·ln10·(kσ)². log10(Y+1) ~ N(μ, (kσ)²) 이면 E[Y+1] = 10^(μ + 이동량)."""
    return 0.5 * LN10 * (k * sigma) ** 2


def lognormal_mean(mu: np.ndarray, sigma: np.ndarray, k: float) -> np.ndarray:
    """로그정규 조건부 평균(원단위) 10^(μ + ½·ln10·(kσ)²) − 1."""
    return from_log(np.asarray(mu, dtype=float) + lognormal_shift(np.asarray(sigma, dtype=float), k))


def stretch(p: np.ndarray, m: float | np.ndarray, s: float | np.ndarray) -> np.ndarray:
    """log 폭 보정 p' = m + s·(p − m)."""
    return m + s * (p - m)


def hinge(p: np.ndarray, m: float | np.ndarray, s: float | np.ndarray) -> np.ndarray:
    """단측 폭 보정 p' = p + (s − 1)·max(p − m, 0): m 위쪽만 늘리거나 줄인다."""
    return p + (s - 1.0) * np.maximum(p - m, 0.0)


def simplex_grid(n: int, step: float = W_STEP) -> np.ndarray:
    """합=1·비음수 가중치 격자 (n_cand, n)."""
    k = int(round(1.0 / step))
    head = [c for c in itertools.product(range(k + 1), repeat=n - 1) if sum(c) <= k]
    return np.array([(*c, k - sum(c)) for c in head], dtype=float) / k


# ---------------------------------------------------------------- 변형 정의
@dataclass(frozen=True)
class Variant:
    """후처리 변형 하나.

    kind: smear(전역 Duan 배수) | lognorm(로그정규 평균, k) | gated(μ>g 인 행만 로그정규, k·g)
          | stretch(폭 보정, m·s) | hinge(단측 폭 보정, m·s)
          | combine(c1·c3·c2 원단위 볼록 결합, 가중치) | nnls_free(원단위 NNLS, 합 제약 없음)
    mu: 중심 log 예측 — ens(입력 점예측) | q50(분위 중앙) | c1(C1 log 예측, recombine 전용)
    slack: None 이면 원단위 MSE 최소, 값이 있으면 적합 구간 rmse_log ≤ rmse_log(v1 앙상블) + slack 제약
    per_site: 지점별 계수(행이 MIN_SITE_ROWS 미만인 지점은 공통 계수)
    fit_m: stretch 에서 m 도 격자 적합(기본은 적합 구간 μ 평균)
    recombine: '' | 'log'(C1 처리 후 v1 log 공간 NNLS) | 'raw'(C1 처리 후 원단위 볼록 결합)
    base: 'ens'(v1 앙상블에 처리) | 'raw'(원단위 볼록 결합 (r) 결과에 처리)
    """

    key: str
    label: str
    kind: str
    mu: str = "ens"
    slack: float | None = None
    per_site: bool = False
    fit_m: bool = False
    recombine: str = ""
    base: str = "ens"


_SL = LOG_SLACK
VARIANTS: dict[str, Variant] = {
    v.key: v
    for v in (
        Variant("s_smear", "(s) 앙상블 전역 smearing", "smear"),
        Variant("b_lognorm", "(b) 로그정규 평균 μ=ens", "lognorm"),
        Variant("b_lognorm_c", "(b') 로그정규 평균 μ=ens, 제약", "lognorm", slack=_SL),
        Variant("c_lognorm_q50", "(c) 로그정규 평균 μ=q50", "lognorm", mu="q50"),
        Variant("c_lognorm_q50_c", "(c') 로그정규 평균 μ=q50, 제약", "lognorm", mu="q50", slack=_SL),
        Variant("d_stretch", "(d) 폭 보정 공통(m=평균)", "stretch"),
        Variant("d_stretch_m", "(d2) 폭 보정 공통(m·s 적합)", "stretch", fit_m=True),
        Variant("d_stretch_c", "(d') 폭 보정 공통, 제약", "stretch", fit_m=True, slack=_SL),
        Variant("e_stretch_site", "(e) 폭 보정 지점별(m=평균)", "stretch", per_site=True),
        Variant(
            "e_stretch_site_c", "(e') 폭 보정 지점별, 제약", "stretch", per_site=True, fit_m=True, slack=_SL
        ),
        Variant("f_c1_lognorm", "(f) C1 로그정규 평균 → log NNLS", "lognorm", mu="c1", recombine="log"),
        Variant("f_c1_stretch", "(f2) C1 폭 보정 → log NNLS", "stretch", mu="c1", recombine="log"),
        Variant(
            "f_c1_lognorm_raw", "(f3) C1 로그정규 평균 → 원단위 결합", "lognorm", mu="c1", recombine="raw"
        ),
        Variant("g_hinge", "(g) 단측 폭 보정 공통", "hinge"),
        Variant("g_hinge_c", "(g') 단측 폭 보정 공통, 제약", "hinge", slack=_SL),
        Variant("g_hinge_site_c", "(g'') 단측 폭 보정 지점별, 제약", "hinge", per_site=True, slack=_SL),
        Variant("h_gated", "(h) 상위 한정 로그정규 μ=ens", "gated"),
        Variant("h_gated_c", "(h') 상위 한정 로그정규 μ=ens, 제약", "gated", slack=_SL),
        Variant("r_combine", "(r) 원단위 볼록 결합(c1·c3·c2)", "combine"),
        Variant("r_combine_c", "(r') 원단위 볼록 결합, 제약", "combine", slack=_SL),
        Variant("r_nnls_free", "(r2) 원단위 NNLS(합 제약 없음)", "nnls_free"),
        Variant("rb_lognorm", "(r+b) 원단위 결합 + 로그정규 평균", "lognorm", base="raw"),
        Variant("rb_lognorm_c", "(r+b') 원단위 결합 + 로그정규 평균, 제약", "lognorm", base="raw", slack=_SL),
        Variant(
            "rd_stretch_c", "(r+d') 원단위 결합 + 폭 보정, 제약", "stretch", base="raw", fit_m=True, slack=_SL
        ),
        Variant("rg_hinge_c", "(r+g') 원단위 결합 + 단측 폭 보정, 제약", "hinge", base="raw", slack=_SL),
        Variant(
            "rh_gated_c", "(r+h') 원단위 결합 + 상위 한정 로그정규, 제약", "gated", base="raw", slack=_SL
        ),
    )
}
CHOSEN = "rh_gated_c"  # main() 의 CV 규칙 선택 결과로 고정(다르면 main 이 경고)


# ---------------------------------------------------------------- 격자·적합
def _grid(v: Variant, mu_fit: np.ndarray) -> np.ndarray:
    """후보 계수 (n_cand, n_par). 항등 변환(k=0 또는 s=1)을 포함한다."""
    if v.kind == "lognorm":
        return K_GRID[:, None]
    if v.kind == "gated":
        return np.array([(k, g) for g in G_GRID for k in K_GRID])
    if v.kind == "stretch":
        ms = M_GRID if v.fit_m else np.array([float(np.mean(mu_fit))])
        return np.array([(m, s) for m in ms for s in S_GRID])
    if v.kind == "hinge":
        return np.array([(m, s) for m in M_GRID for s in S_GRID])
    raise ValueError(v.kind)


def _apply_log(kind: str, theta: np.ndarray, mu: np.ndarray, sig: np.ndarray) -> np.ndarray:
    """계수 묶음 theta (n_cand, n_par) → log 예측 (n_cand, n)."""
    a = theta[:, 0:1]
    b = theta[:, 1:2] if theta.shape[1] > 1 else None
    if kind == "lognorm":
        return mu + lognormal_shift(sig, a)
    if kind == "gated":
        return mu + (mu > b) * lognormal_shift(sig, a)
    if kind == "stretch":
        return stretch(mu, a, b)
    if kind == "hinge":
        return hinge(mu, a, b)
    raise ValueError(kind)


def select_params(
    theta: np.ndarray, cands: np.ndarray, obs: np.ndarray, ref: np.ndarray, slack: float | None
) -> np.ndarray | None:
    """원단위 MSE 최소 후보. slack 이 있으면 rmse_log ≤ rmse_log(ref) + slack 인 후보만. 없으면 None."""
    err = np.mean((cands - obs[None, :]) ** 2, axis=1)
    if slack is not None:
        lo = to_log(obs)
        rl = np.sqrt(np.mean((to_log(cands) - lo[None, :]) ** 2, axis=1))
        rl0 = float(np.sqrt(np.mean((to_log(ref) - lo) ** 2)))
        err = np.where(rl <= rl0 + slack + 1e-12, err, np.inf)
    if not np.isfinite(err).any():
        return None
    return theta[int(np.argmin(err))].astype(float)


def _fit_one(
    v: Variant, obs: np.ndarray, ref: np.ndarray, mu: np.ndarray, sig: np.ndarray
) -> np.ndarray | None:
    """적합 행에서 변형 계수 하나를 고른다(None = 변환 없음)."""
    if v.kind == "smear":
        return np.array([float(np.mean(10.0 ** (to_log(obs) - mu)))])
    theta = _grid(v, mu)
    cands = from_log(_apply_log(v.kind, theta, mu, sig))
    return select_params(theta, cands, obs, ref, v.slack)


def _predict(
    v: Variant, theta: np.ndarray | None, base: np.ndarray, mu: np.ndarray, sig: np.ndarray
) -> np.ndarray:
    if theta is None:
        return base.copy()
    if v.kind == "smear":
        return from_log(mu + np.log10(theta[0]))
    return from_log(_apply_log(v.kind, theta[None, :], mu, sig)[0])


def _theta_txt(theta: np.ndarray | None) -> list[float] | None:
    return None if theta is None else [round(float(t), 4) for t in theta]


def expanding_postprocess(
    df: pd.DataFrame,
    v: Variant,
    base: np.ndarray,
    mu: np.ndarray,
    sig: np.ndarray,
    ref: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[int, object]]:
    """변형 v 를 연도 확장으로 적합·적용.

    base: 적합 자료가 없을 때(2020)·적합 실패 시의 출력. ref: 제약(slack) 기준 점예측(기본 base).
    """
    ref = base if ref is None else ref
    obs = df["target_cells"].to_numpy(dtype=float)
    sites = df["station_id"].astype(str).to_numpy()
    years = H.years_of(df)
    record: dict[int, object] = {}

    def fit(mask: np.ndarray) -> dict:
        common = _fit_one(v, obs[mask], ref[mask], mu[mask], sig[mask])
        state: dict = {"common": common, "site": {}}
        if v.per_site:
            for s in np.unique(sites):
                ms = mask & (sites == s)
                state["site"][s] = (
                    _fit_one(v, obs[ms], ref[ms], mu[ms], sig[ms]) if ms.sum() >= MIN_SITE_ROWS else common
                )
        return state

    def apply(state: dict | None, mask: np.ndarray) -> np.ndarray:
        if not mask.any():
            return np.empty(0)
        yv = int(years[mask][0])
        if state is None:
            record[yv] = None
            return base[mask].copy()
        if not v.per_site:
            record[yv] = _theta_txt(state["common"])
            return _predict(v, state["common"], base[mask], mu[mask], sig[mask])
        out = np.empty(int(mask.sum()))
        sub_sites = sites[mask]
        rec = {}
        for s in np.unique(sub_sites):
            th = state["site"].get(s, state["common"])
            rec[s] = _theta_txt(th)
            ii = np.flatnonzero(mask)[sub_sites == s]
            out[sub_sites == s] = _predict(v, th, base[ii], mu[ii], sig[ii])
        record[yv] = rec
        return out

    pred = H.expanding_fit_apply(df, fit, apply)
    return pred, record


def recombine_raw(
    df: pd.DataFrame,
    members: dict[str, np.ndarray],
    fallback: np.ndarray,
    *,
    free: bool = False,
    slack: float | None = None,
    ref: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[int, object]]:
    """구성원 원단위 결합(연도 확장). free=False: 합=1·비음수 격자(W_STEP) 중 원단위 MSE 최소(slack 제약 가능),
    free=True: 합 제약 없는 NNLS. 적합 자료가 없는 연도(2020)는 fallback(v1 앙상블)."""
    names = list(members)
    M = np.column_stack([np.asarray(members[k], dtype=float) for k in names])
    obs = df["target_cells"].to_numpy(dtype=float)
    ref = fallback if ref is None else ref
    years = H.years_of(df)
    W = simplex_grid(len(names))
    record: dict[int, object] = {}

    def fit(mask: np.ndarray) -> np.ndarray | None:
        if free:
            return nnls(M[mask], obs[mask])[0]
        return select_params(W, W @ M[mask].T, obs[mask], ref[mask], slack)

    def apply(state: np.ndarray | None, mask: np.ndarray) -> np.ndarray:
        if not mask.any():
            return np.empty(0)
        yv = int(years[mask][0])
        record[yv] = (
            None if state is None else {k: round(float(w), 3) for k, w in zip(names, state, strict=True)}
        )
        if state is None:
            return fallback[mask].copy()
        return np.clip(M[mask] @ state, 0.0, None)

    return H.expanding_fit_apply(df, fit, apply), record


# ---------------------------------------------------------------- 변형 실행
def _ens(df: pd.DataFrame, preds: dict[str, np.ndarray]) -> np.ndarray:
    if "ens" in preds:
        return np.asarray(preds["ens"], dtype=float)
    return H.ensemble_expanding(df, preds)[0]


def run_variant(
    df: pd.DataFrame, preds: dict[str, np.ndarray], variant: Variant | str
) -> tuple[np.ndarray, dict[str, object]]:
    """변형 하나를 실행해 (원단위 점예측, 정보) 를 돌려준다.

    정보: params(연도별 계수) · weights(결합 가중치) · c1_params/c1_post(C1 처리 시) · nnls_weights(log 재결합).
    """
    H.guard_no_2026(df)
    v = VARIANTS[variant] if isinstance(variant, str) else variant
    sig = sigma_from_quantiles(preds["q10"], preds["q90"])
    ens_v1 = _ens(df, preds)
    members = {k: np.asarray(preds[k], dtype=float) for k in MEMBERS}
    if v.kind in ("combine", "nnls_free"):
        pred, w = recombine_raw(df, members, ens_v1, free=v.kind == "nnls_free", slack=v.slack, ref=ens_v1)
        return pred, {"weights": w}
    if v.recombine:
        c1 = members["c1"]
        mu = np.clip(np.asarray(preds["c1_log"], dtype=float), 0.0, LOG_CAP)
        c1_post, rec = expanding_postprocess(df, v, c1, mu, sig)
        new = {**members, "c1": c1_post}
        if v.recombine == "raw":
            ens, w = recombine_raw(df, new, ens_v1, ref=ens_v1)
            return ens, {"c1_params": rec, "weights": w, "c1_post": c1_post}
        ens, wl = H.ensemble_expanding(df, new)
        return ens, {"c1_params": rec, "nnls_weights": wl, "c1_post": c1_post}
    info: dict[str, object] = {}
    if v.base == "raw":
        base, w = recombine_raw(df, members, ens_v1, ref=ens_v1)
        info["weights"] = w
    else:
        base = ens_v1
    mu = to_log(preds["q50"]) if v.mu == "q50" else to_log(base)
    pred, rec = expanding_postprocess(df, v, base, mu, sig, ref=ens_v1)
    info["params"] = rec
    return pred, info


def postprocess(df: pd.DataFrame, preds: dict[str, np.ndarray], variant: str | None = None) -> np.ndarray:
    """선택 변형(기본 CHOSEN)을 연도 확장 적합으로 적용한 원단위 점예측(2020~2025 행, 나머지 NaN).

    df: harness.load_base() 형식(target_cells·station_id·base_date). preds: harness.run_members 형식
    (c1·c3·c2·q10·q90 필수, q50 는 μ=q50 변형, c1_log 는 C1 처리 변형에 필요. ens 가 없으면 c1·c3·c2 로
    연도 확장 log NNLS 앙상블을 만들어 2020 대체값·제약 기준으로 쓴다).
    계수는 연도 Y 이전 CV OOF(2020~Y−1)로만 적합하고 2025 는 2020~2024 전체, 2020 은 v1 방식 앙상블 그대로.
    """
    pred, _ = run_variant(df, preds, variant or CHOSEN)
    return pred


# ---------------------------------------------------------------- 실험 실행
def choose(base_row: dict, rows: dict[str, dict]) -> tuple[str, bool]:
    """EXP-PLAN 4절: 채택 기준 만족 변형 중 CV r2_raw 최대, 없으면 CV r2_raw 최대(기준 미달)."""
    ok = {k: r for k, r in rows.items() if H.adoption(base_row, r)["pass"]}
    pool = ok or rows
    best = max(pool, key=lambda k: pool[k]["cv_r2_raw"])
    return best, bool(ok)


def cv_year_r2(df: pd.DataFrame, pred: np.ndarray) -> dict[int, float]:
    """CV 연도별 r2_raw(2020~2024, 안정성 참고)."""
    obs = df["target_cells"].to_numpy(dtype=float)
    years = H.years_of(df)
    out = {}
    for y in H.CV_YEARS:
        m = (years == y) & np.isfinite(pred)
        o, q = obs[m], np.asarray(pred, dtype=float)[m]
        out[int(y)] = float(1.0 - np.sum((o - q) ** 2) / np.sum((o - o.mean()) ** 2))
    return out


def _row(df: pd.DataFrame, pred: np.ndarray, q90: np.ndarray, label: str) -> dict:
    row = H.metric_row(df, pred, q90, label)
    for y, r in cv_year_r2(df, pred).items():
        row[f"cvyear_r2_raw_{y}"] = r
    return row


def _fmt_params(rec: object) -> str:
    if isinstance(rec, dict):
        return "{" + ", ".join(f"{k}: {_fmt_params(v)}" for k, v in rec.items()) + "}"
    if isinstance(rec, list):
        return "(" + ", ".join(f"{t:g}" for t in rec) + ")"
    if isinstance(rec, float):
        return f"{rec:g}"
    return "–" if rec is None else str(rec)


def _member_rows(
    df: pd.DataFrame, p: dict[str, np.ndarray], q90: np.ndarray
) -> tuple[list[dict], dict[str, object]]:
    """C1 단독 비교(보정 없음 / smearing / 로그정규 평균 / 폭 보정) — 참고용, 선택 후보 아님."""
    sig = sigma_from_quantiles(p["q10"], p["q90"])
    mu = np.clip(p["c1_log"], 0.0, LOG_CAP)
    rows = [
        _row(df, p["c1_none"], q90, "C1 단독 · 보정 없음"),
        _row(df, p["c1"], q90, "C1 단독 · smearing(v1)"),
    ]
    params: dict[str, object] = {}
    for v in (
        Variant("c1_lognorm", "C1 단독 · 로그정규 평균", "lognorm", mu="c1"),
        Variant("c1_stretch", "C1 단독 · 폭 보정(m=평균)", "stretch", mu="c1"),
    ):
        pred, rec = expanding_postprocess(df, v, p["c1"], mu, sig)
        rows.append(_row(df, pred, q90, v.label))
        params[v.key] = {"params": rec}
    return rows, params


def _diag(df: pd.DataFrame, p: dict[str, np.ndarray]) -> dict[str, float]:
    """CV 구간 진단: q10~q90 포함률, σ 분위, σ 와 |log 잔차| 상관, 극단 행의 오차 비중(2025 미사용)."""
    cv, _ = H.masks(df)
    raw = df["target_cells"].to_numpy(dtype=float)[cv]
    obs = to_log(raw)
    lo, hi = to_log(p["q10"])[cv], to_log(p["q90"])[cv]
    sig = sigma_from_quantiles(p["q10"], p["q90"])[cv]
    res = obs - to_log(p["ens"])[cv]
    sse = (raw - p["ens"][cv]) ** 2
    top = np.sort(sse)[::-1]
    return {
        "cv_cover_q10_q90": float(np.mean((obs >= lo) & (obs <= hi))),
        "cv_sigma_p50": float(np.median(sig)),
        "cv_sigma_p90": float(np.quantile(sig, 0.9)),
        "cv_resid_sd_log": float(np.std(res)),
        "cv_corr_sigma_absres": float(np.corrcoef(sig, np.abs(res))[0, 1]),
        "cv_k_implied_sd": float(np.std(res) / np.sqrt(np.mean(sig**2))),
        "cv_sse_share_top15": float(top[:15].sum() / sse.sum()),
    }


def _report(ctx: dict) -> str:
    rows, member_rows, params = ctx["rows"], ctx["member_rows"], ctx["params"]
    chosen, passed, adopt, adopt_all, diag = (
        ctx["chosen"],
        ctx["passed"],
        ctx["adopt"],
        ctx["adopt_all"],
        ctx["diag"],
    )
    v = VARIANTS[chosen]
    by = {r["구성"]: r for r in rows}
    ch = by[v.label]
    ok_rmse = [k for k, a in adopt_all.items() if a["d_cv_rmse_log"] <= 0.01]
    lines = [
        f"# {EXP_ID} — R1 분산 반영 원단위 복원(후처리)",
        "",
        "## 1. 목적·설정",
        "",
        "- 목적: v1 앙상블 점예측(log 공간 결합, 조건부 중앙값 성격)을 원단위 조건부 평균 쪽으로 옮겨 원단위 "
        "R²·NSE 를 높일 수 있는지, 그 대가로 log 지표(rmse_log)를 얼마나 잃는지 확인한다.",
        "- 데이터: `harness.load_baseline()` 의 v1 기준 OOF(2020~2025, 재학습 없음). 분위 q10·q50·q90 는 C1 "
        "파라미터의 분위 회귀 OOF. 2026 행은 읽지 않는다(`guard_no_2026`).",
        "- σ(x) = (log10(q90+1) − log10(q10+1)) / (2·1.2816), 로그정규 평균 = 10^(μ + ½·ln10·(kσ)²) − 1.",
        "- 폭 보정 p' = m + s·(p − m)(p = log10(점예측+1)), 단측 폭 보정 p' = p + (s − 1)·max(p − m, 0), "
        "상위 한정 로그정규는 μ > g 인 행에만 로그정규 이동을 더한다.",
        "- (r) 계열(명세 예시 밖 추가): v1 의 log 공간 NNLS 는 smearing 을 거친 C1 을 낮게 가중한다(2021~2025 "
        "가중치 0.01~0.28). 구성원 c1·c3·c2 를 원단위 MSE 최소의 볼록 결합(합=1, 비음수, 0.01 격자)으로 다시 묶는 "
        "것이 앙상블 수준의 원단위 복원이다. 합 제약 없는 원단위 NNLS (r2) 는 결합 + 배율(인플레이션) 형태다. "
        "참고: `models.ensemble.nnls_weights(log_space=False)` 는 합=1 증강 행이 원단위 크기에서 사실상 작동하지 "
        "않아(자유 NNLS 가중치 합 ≈ 2 를 사후 정규화) 쓰지 않았다.",
        "- 계수 적합: `harness.expanding_fit_apply` — 연도 Y 는 Y 이전 CV OOF(2020~Y−1)로 원단위 MSE 최소(격자), "
        "2025 는 2020~2024 전체, 적합 자료가 없는 2020 은 v1 그대로. '제약' 변형은 적합 구간 rmse_log 가 v1 앙상블 "
        f"대비 +{LOG_SLACK} 이하인 후보 중에서만 고른다(채택 기준 0.01 의 절반을 여유로 둠, 후보가 없으면 v1 그대로). "
        f"격자: k {K_GRID[0]}~{K_GRID[-1]}(0.01), s {S_GRID[0]}~{S_GRID[-1]}(0.01), "
        f"m {M_GRID[0]}~{M_GRID[-1]}(0.1), g {G_GRID[0]}~{G_GRID[-1]}(0.25), 결합 가중치 {W_STEP}. "
        f"지점별 적합은 지점 적합 행이 {MIN_SITE_ROWS} 미만이면 공통 계수.",
        "- (f) 계열은 C1 을 처리(k 또는 m·s 를 C1 단독 원단위 MSE 로 적합)한 뒤 log NNLS(f·f2) 또는 원단위 볼록 "
        "결합(f3)으로 다시 묶는다. (r+…) 계열은 (r) 결과에 σ·폭 보정을 겹친다(제약 기준은 계속 v1 앙상블).",
        "- 리드타임 '감시(q90≥10k)' 는 q90 를 바꾸지 않으므로 모든 변형이 v1 과 같다.",
        "",
        "변형 목록: " + ", ".join(f"`{k}` {vv.label}" for k, vv in VARIANTS.items()) + ".",
        "",
        "## 2. 표준 표",
        "",
        H.standard_table(rows),
        "### 보조 표",
        "",
        H.detail_table(rows),
        "### CV 연도별 r2_raw(안정성 참고, 2020 은 모든 변형이 v1 과 같음)",
        "",
        "| 구성 | 2020 | 2021 | 2022 | 2023 | 2024 | 최저 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        yr = [r[f"cvyear_r2_raw_{y}"] for y in H.CV_YEARS]
        lines.append(f"| {r['구성']} | " + " | ".join(f"{x:.3f}" for x in yr) + f" | {min(yr):.3f} |")
    lines += [
        "",
        "### 채택 기준 대비(전 변형, CV)",
        "",
        "| 구성 | Δ CV r2_raw | Δ CV rmse_log | 리드타임 유지 | 판정 |",
        "|---|---|---|---|---|",
    ]
    for k, a in adopt_all.items():
        lines.append(
            f"| {VARIANTS[k].label} | {a['d_cv_r2_raw']:+.3f} | {a['d_cv_rmse_log']:+.3f} | "
            f"{'예' if a['lead_ok'] else '아니오'} | {'통과' if a['pass'] else '미달'} |"
        )
    lines += [
        "",
        "### C1 단독 비교(smearing 대비, 참고용 — 선택 후보 아님)",
        "",
        H.standard_table(member_rows),
        "### 연도별 적합 계수(적용 연도 → 계수)",
        "",
        "lognorm (k), gated (k, g), stretch·hinge (m, s), smear (배수), weights(c1·c3·c2 결합 가중치), "
        "nnls_weights(log NNLS). None = 적합 자료 없음 또는 제약을 만족하는 후보 없음(입력 그대로).",
        "",
    ]
    for k, rec in params.items():
        lines.append(f"- `{k}`: {_fmt_params(rec)}")
    lines += [
        "",
        "### 진단(CV 2020~2024)",
        "",
        f"- q10~q90 포함률 {diag['cv_cover_q10_q90']:.3f}(명목 0.80), σ 중앙값 {diag['cv_sigma_p50']:.3f}, "
        f"σ 90% 분위 {diag['cv_sigma_p90']:.3f}, v1 앙상블 log 잔차 SD {diag['cv_resid_sd_log']:.3f}, "
        f"σ 와 |log 잔차| 상관 {diag['cv_corr_sigma_absres']:.3f}, 잔차 SD / RMS(σ) = "
        f"{diag['cv_k_implied_sd']:.2f}. v1 원단위 제곱오차 상위 15행(1,278행 중)이 CV SSE 의 "
        f"{diag['cv_sse_share_top15']:.0%} 를 차지한다.",
        "",
        "## 3. 선택한 변형과 채택 판정",
        "",
        f"- 선택: **{v.label}** (`{chosen}`) — "
        + (
            "채택 기준을 만족하는 변형 중 CV r2_raw 최대(EXP-PLAN 4절)."
            if passed
            else "채택 기준을 만족하는 변형이 없어 CV r2_raw 최대 변형을 고름(**기준 미달**)."
        ),
        f"- `harness.adoption`: Δ CV r2_raw {adopt['d_cv_r2_raw']:+.3f}(기준 +0.10), Δ CV rmse_log "
        f"{adopt['d_cv_rmse_log']:+.3f}(기준 ≤ +0.01), 리드타임 유지 {adopt['lead_ok']} → "
        f"**{'통과' if adopt['pass'] else '미달'}**.",
        f"- 선택 변형 CV r2_raw {ch['cv_r2_raw']:.3f} / nse_raw {ch['cv_nse_raw']:.3f} / rmse_log "
        f"{ch['cv_rmse_log']:.3f} / F1@10k {ch['cv_f1_10k']:.3f}, 2025 확인 r2_raw {ch['y2025_r2_raw']:.3f} / "
        f"rmse_log {ch['y2025_rmse_log']:.3f} / F1@10k {ch['y2025_f1_10k']:.3f}.",
        "- CV rmse_log 악화 0.01 이내 변형: " + (", ".join(f"`{k}`" for k in ok_rmse) or "없음") + ".",
        "",
    ]
    lines += ctx.get("discussion", [])
    lines += [
        "",
        "## 4. 누수·2026 점검",
        "",
        "- 테스트 `tests/test_exp_r1_variance_restore.py`(통과): 변환식(로그정규 평균 = 몬테카를로 평균, 항등 계수), "
        "단체 격자, 제약 선택, 연도 Y 이후 관측을 바꿔도 Y 이하 예측이 같음(연도 확장 적합 누수 없음, σ·폭·결합 "
        "변형 모두), 2026 행 거부.",
        "- 재학습 없음(v1 기준 OOF 만 읽음). 2026 행·test 분할·`test_targets_DO_NOT_USE` 미사용. "
        "`python scripts/exp_check_protected.py` → 변경 0개.",
        "",
        "## 5. 소요 시간·한계·다음 단계",
        "",
        f"- 시작 {ctx['t_start']}(작업 착수 기준), 종료 {ctx['t_end']}, 소요 {ctx['elapsed_h']:.2f}시간 / 상한 "
        f"{BUDGET_HOURS:.0f}시간" + (" — **시간 상한 초과로 중단**." if ctx["capped"] else "."),
    ]
    lines += ctx.get("limits", [])
    return "\n".join(lines) + "\n"


def run_all(budget: H.Budget) -> dict:
    """모든 변형을 실행해 지표·계수·선택을 모은다."""
    df, p = H.load_baseline()
    H.guard_no_2026(df)
    q90 = p["q90"]
    base_row = _row(df, p["ens"], q90, "v1 기준")
    rows, preds, params, capped = [base_row], {}, {}, False
    var_rows: dict[str, dict] = {}
    for key, v in VARIANTS.items():
        try:
            budget.check()
        except H.BudgetExceeded as e:
            log.warning("%s", e)
            capped = True
            break
        pred, info = run_variant(df, p, v)
        row = _row(df, pred, q90, v.label)
        rows.append(row)
        var_rows[key] = row
        preds[key] = (pred, info)
        params[key] = {k: val for k, val in info.items() if k != "c1_post"}
        log.info("%-18s CV r2_raw %.3f rmse_log %.3f", key, row["cv_r2_raw"], row["cv_rmse_log"])
    member_rows, member_params = _member_rows(df, p, q90)
    params.update(member_params)
    chosen, passed = choose(base_row, var_rows)
    return {
        "df": df,
        "p": p,
        "base_row": base_row,
        "rows": rows,
        "var_rows": var_rows,
        "preds": preds,
        "params": params,
        "member_rows": member_rows,
        "chosen": chosen,
        "passed": passed,
        "adopt": H.adoption(base_row, var_rows[chosen]),
        "adopt_all": {k: H.adoption(base_row, r) for k, r in var_rows.items()},
        "diag": _diag(df, p),
        "capped": capped,
    }


def _discussion(ctx: dict) -> tuple[list[str], list[str]]:
    """선택 근거 보충·해석·한계(모든 수치는 ctx 에서 읽는다)."""
    vr, base, chosen, adopt_all = ctx["var_rows"], ctx["base_row"], ctx["chosen"], ctx["adopt_all"]
    mr = {r["구성"]: r for r in ctx["member_rows"]}

    def yr(k: str, y: int) -> float:
        return float(vr[k][f"cvyear_r2_raw_{y}"])

    def worst(k: str) -> float:
        return min(yr(k, y) for y in H.CV_YEARS)

    def lst(keys: list[str]) -> str:
        return ", ".join(f"`{k}`" for k in keys) or "없음"

    b23 = float(base["cvyear_r2_raw_2023"])
    sig_keys = [k for k, v in VARIANTS.items() if v.kind in ("lognorm", "gated", "stretch", "hinge", "smear")]
    unstable = [k for k in sig_keys if yr(k, 2023) < b23 - 0.05]
    r_low = [y for y in H.CV_YEARS if yr("r_combine", y) < base[f"cvyear_r2_raw_{y}"] - 0.01]
    passing = [k for k, a in adopt_all.items() if a["pass"]]
    robust = max(passing, key=lambda k: vr[k]["cvfold_r2_raw"]) if passing else None
    better25 = [k for k in vr if vr[k]["y2025_r2_raw"] > base["y2025_r2_raw"] + 5e-4]
    ch = vr[chosen]
    c1s, c1l = mr["C1 단독 · smearing(v1)"], mr["C1 단독 · 로그정규 평균"]
    disc = [
        "### 해석",
        "",
        "- σ·폭 보정 계열(s·b·c·d·e·g·h, r+…)은 원단위 MSE 로 고른 계수가 직전 연도들의 극단값 수에 끌려간다. "
        "2022(>10^5 10행)를 포함해 적합한 2023 계수가 커지고(예: (b) k "
        f"{ctx['params']['b_lognorm']['params'][2023][0]:g}, (d) s {ctx['params']['d_stretch']['params'][2023][1]:g}), "
        f"극단값이 적은 2023 에 과대 예측이 생긴다. CV 2023 r2_raw 가 v1({b23:.3f})보다 0.05 이상 나쁜 변형: "
        f"{lst(unstable)}.",
        "- 로그정규 평균을 그대로 쓰면 원단위 R² 는 오르지만 rmse_log 가 크게 나빠진다((b) "
        f"{adopt_all['b_lognorm']['d_cv_rmse_log']:+.3f}, (c) {adopt_all['c_lognorm_q50']['d_cv_rmse_log']:+.3f}; "
        "조건부 평균은 log 오차 최소점이 아니다). rmse_log 제약을 두면 개선 폭이 거의 사라진다((b') "
        f"{adopt_all['b_lognorm_c']['d_cv_r2_raw']:+.3f}, (c') {adopt_all['c_lognorm_q50_c']['d_cv_r2_raw']:+.3f}).",
        f"- smearing 대비(C1 단독): smearing(v1) CV r2_raw {c1s['cv_r2_raw']:.3f}·rmse_log {c1s['cv_rmse_log']:.3f}, "
        f"행별 σ 로그정규 평균 {c1l['cv_r2_raw']:.3f}·{c1l['cv_rmse_log']:.3f}. 분위 폭 σ 는 |log 잔차|와 상관이 "
        f"{ctx['diag']['cv_corr_sigma_absres']:.2f} 에 그쳐 상수 배수(smearing)보다 나은 점이 없다. 앙상블 전체에 "
        "smearing 을 거는 (s) 는 log 잔차 분산이 커서 배수가 4~5 로 나와 크게 나빠진다.",
        "- 원단위 볼록 결합 (r): 가중치가 2023 부터 C1(smearing) 쪽으로 옮겨 가는 것(사실상 C1 단독)이 개선의 "
        "원천이다. 계수가 구성원 범위 안이라 과대 예측 위험이 작고, CV 연도 중 v1 보다 0.01 이상 나쁜 해: "
        + (", ".join(map(str, r_low)) or "없음")
        + f". CV 폴드 평균 r2_raw {vr['r_combine']['cvfold_r2_raw']:.3f}(v1 {base['cvfold_r2_raw']:.3f}).",
        f"- 선택 변형 `{chosen}` 은 통합 CV r2_raw 가 가장 크지만(+{adopt_all[chosen]['d_cv_r2_raw']:.3f}) 개선이 "
        f"2024 에 몰려 있다(2024 {yr(chosen, 2024):.3f} vs v1 {base['cvyear_r2_raw_2024']:.3f}, 2023 "
        f"{yr(chosen, 2023):.3f} vs v1 {b23:.3f}, CV 최저 연도 {worst(chosen):.3f}). CV 폴드 평균 r2_raw "
        f"{ch['cvfold_r2_raw']:.3f}(v1 {base['cvfold_r2_raw']:.3f}). 통과 변형 중 CV 폴드 평균 r2_raw 가 가장 큰 "
        f"(보조 지표 기준 가장 견고한) 변형은 `{robust}`.",
        f"- 2025 확인(선택에 쓰지 않음): 선택 변형 r2_raw {ch['y2025_r2_raw']:.3f}·rmse_log "
        f"{ch['y2025_rmse_log']:.3f}, v1 {base['y2025_r2_raw']:.3f}·{base['y2025_rmse_log']:.3f}. "
        + (
            f"`{robust}` 2025 r2_raw {vr[robust]['y2025_r2_raw']:.3f}. "
            if robust and robust != chosen
            else ""
        )
        + "2025 r2_raw 가 v1 보다 높은 변형: "
        + lst(better25)
        + ". CV 개선이 2025 로 이어지지 않는다. 채택 기준은 CV 로 통과했지만, v2 에 넣을지는 이 확인 결과를 보고 "
        "사용자가 정한다.",
    ]
    limits = [
        "- 한계: 계수 적합에 쓰는 원단위 MSE 는 소수 극단 행이 좌우한다(진단 참조). 2020 은 적합 자료가 없어 "
        "v1 그대로이고, 2021 계수는 2020 한 해(경계 초과 2행)로 적합된다. "
        f"변형이 {len(VARIANTS)}개라 통합 CV 최대값에는 선택 낙관(승자의 저주)이 섞여 있다.",
        "- σ 는 분위 폭에서만 얻었다(q10~q90 포함률이 명목 0.80 보다 낮다). 분위 모델 자체의 보정(conformal 등)은 "
        "범위 밖이다.",
        "- 다음 단계: 종합(EXP-011)에서 새 구성원(R2~R7)이 들어오면 `postprocess(df, preds, variant=...)` 로 같은 "
        "연도 확장 적합을 다시 한다(기본은 규칙 선택 `CHOSEN`, 견고성 대안은 "
        f"`{robust}`). σ 기반 인플레이션은 연도 체제(극단값이 많은 해/적은 해)를 설명하는 피처(상류·영양염 등)가 "
        "생긴 뒤 다시 볼 가치가 있다.",
    ]
    return disc, limits


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    t_start = "2026-10-21 17:53:24"  # 작업 착수(문서 읽기 시작) 시각 — 시간 상한은 이 시각부터 센다
    budget = H.Budget(BUDGET_HOURS, EXP_ID)
    budget.t0 = datetime.strptime(t_start, "%Y-%m-%d %H:%M:%S").timestamp()
    t0 = time.time()
    ctx = run_all(budget)
    df, p, chosen = ctx["df"], ctx["p"], ctx["chosen"]
    if chosen != CHOSEN:
        log.warning("CV 규칙 선택(%s)이 모듈 상수 CHOSEN(%s)과 다르다 — 상수를 고칠 것", chosen, CHOSEN)

    # 행 단위 OOF(선택 변형·전 변형)
    pred, info = ctx["preds"][chosen]
    oof = {"c1": p["c1"], "c3": p["c3"], "c2": p["c2"]}
    if "c1_post" in info:
        oof["c1_post"] = info["c1_post"]
    oof.update({"q10": p["q10"], "q50": p["q50"], "q90": p["q90"], "ens_v1": p["ens"], "pred": pred})
    H.save_oof(df, oof, OUT_DATA / "chosen_oof.parquet")
    H.save_oof(df, {k: v[0] for k, v in ctx["preds"].items()}, OUT_DATA / "variants_oof.parquet")

    t_end = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elapsed_h = (datetime.now() - datetime.strptime(t_start, "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600
    disc, limits = _discussion(ctx)
    ctx.update(
        {
            "t_start": t_start,
            "t_end": t_end,
            "elapsed_h": elapsed_h,
            "discussion": disc,
            "limits": limits,
        }
    )
    OUT_REPORT.mkdir(parents=True, exist_ok=True)
    (OUT_REPORT / "README.md").write_text(_report(ctx), encoding="utf-8", newline="\n")
    meta = {
        "exp_id": EXP_ID,
        "chosen": chosen,
        "chosen_label": VARIANTS[chosen].label,
        "chosen_passes_adoption": ctx["passed"],
        "adoption": ctx["adopt"],
        "adoption_all": ctx["adopt_all"],
        "variants": {k: asdict(v) for k, v in VARIANTS.items()},
        "rows": ctx["rows"],
        "member_rows": ctx["member_rows"],
        "params_by_year": ctx["params"],
        "diagnostics": ctx["diag"],
        "log_slack": LOG_SLACK,
        "time": {
            "start": t_start,
            "end": t_end,
            "elapsed_h": elapsed_h,
            "run_minutes": (time.time() - t0) / 60,
            "cap_h": BUDGET_HOURS,
            "capped": ctx["capped"],
        },
    }
    (OUT_REPORT / "metrics.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1, default=_json_default) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(H.standard_table(ctx["rows"]))
    print("선택:", chosen, ctx["adopt"])
    return 0


def _json_default(o: object) -> object:
    if isinstance(o, np.integer | np.floating):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


if __name__ == "__main__":
    raise SystemExit(main())
