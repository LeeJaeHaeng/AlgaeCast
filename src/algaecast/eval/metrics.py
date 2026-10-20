"""평가 지표 (docs/04_MODELING_SPEC.md 6.1절) — T0-c.

| 지표 | 공간 | 정의 |
|---|---|---|
| rmse_log, mae_log | log10(x+1) | 대회 1차 지표 |
| r2_raw | 원단위 | sklearn r2_score (= 1 − SS_res/SS_tot, 검증 관측 평균 기준) |
| nse_raw | 원단위 | Nash–Sutcliffe = 1 − Σ(o−p)²/Σ(o−ō)². 수식상 r2_raw 와 동일하지만 보고 관례상 별도 제공 |
| r2_log, kge | log10(x+1) | 보완 (KGE: Gupta et al. 2009, r·α·β 분해) |
| f1_at(threshold) | 분류 | obs ≥ t vs pred ≥ t 의 precision/recall/f1 (경계 10,000·관심 1,000, 경계값 포함) |
| picp, mpiw | 구간 | 80% 예측구간(q10~q90) 포함률과 평균 폭(기본 log 공간). 교차 구간은 정렬 후 계산 |
| brier | 확률 | 경계 초과 확률의 Brier score |

모든 함수는 순수 함수이며 입력은 1차원 array-like(cells/mL 원단위). 음수·NaN·inf 는 ValueError —
결측 타깃은 호출 전에 제거하고, 모델의 음수 예측은 predict 단계에서 0 으로 클리핑한다.
상수 배열(관측 분산 0)에서 정의되지 않는 지표는 NaN 을 반환한다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike
from sklearn.metrics import precision_recall_fscore_support, r2_score

from algaecast.config import load_seed

LOG_OFFSET = 1.0
THRESHOLD_WARNING = 10_000  # 경계 (cells/mL, 상수원 구간). 데이터 컬럼 over_caution 이 가리키는 기준
THRESHOLD_CAUTION = 1_000  # 관심


# ---------------------------------------------------------------- 공통
def _as_array(x: ArrayLike, name: str, *, allow_prob: bool = False) -> np.ndarray:
    raw = np.asarray(x)
    if raw.dtype == object:  # pd.NA / None 섞인 object → NaN 으로 바꿔 아래 검사에 걸리게 한다
        raw = pd.to_numeric(pd.Series(raw.ravel()), errors="coerce").to_numpy()
    a = np.asarray(raw, dtype="float64").ravel()
    if a.size == 0:
        raise ValueError(f"{name}: 빈 배열")
    if not np.isfinite(a).all():
        n_bad = int((~np.isfinite(a)).sum())
        raise ValueError(f"{name}: NaN/inf {n_bad}개 포함. 결측은 호출 전에 제거할 것")
    if (a < 0).any():
        raise ValueError(
            f"{name}: 음수 {int((a < 0).sum())}개. 세포수/확률은 0 이상이어야 함 (예측은 0 클리핑)"
        )
    if allow_prob and (a > 1).any():
        raise ValueError(f"{name}: 확률은 0~1 이어야 함")
    return a


def _pair(
    a: ArrayLike, b: ArrayLike, names: tuple[str, str] = ("obs", "pred")
) -> tuple[np.ndarray, np.ndarray]:
    x, y = _as_array(a, names[0]), _as_array(b, names[1])
    if x.shape != y.shape:
        raise ValueError(f"길이 불일치: {names[0]} {x.shape[0]} vs {names[1]} {y.shape[0]}")
    return x, y


def _is_constant(x: np.ndarray) -> bool:
    """분산 0 판정. std()==0 은 부동소수 오차(1 ulp)로 놓칠 수 있어 범위(ptp)로 판정한다."""
    return x.size < 2 or float(np.ptp(x)) == 0.0


def log10p(x: ArrayLike) -> np.ndarray:
    """log10(x + 1). 대회 1차 지표 공간."""
    return np.log10(np.asarray(x, dtype="float64") + LOG_OFFSET)


# ---------------------------------------------------------------- 회귀 (log)
def rmse_log(obs: ArrayLike, pred: ArrayLike) -> float:
    o, p = _pair(obs, pred)
    return float(np.sqrt(np.mean((log10p(o) - log10p(p)) ** 2)))


def mae_log(obs: ArrayLike, pred: ArrayLike) -> float:
    o, p = _pair(obs, pred)
    return float(np.mean(np.abs(log10p(o) - log10p(p))))


def r2_log(obs: ArrayLike, pred: ArrayLike) -> float:
    o, p = _pair(obs, pred)
    return _r2(log10p(o), log10p(p))


# ---------------------------------------------------------------- 회귀 (원단위)
def _r2(o: np.ndarray, p: np.ndarray) -> float:
    if _is_constant(o):
        return float("nan")  # 관측 분산 0 → 정의 불가
    return float(r2_score(o, p))


def r2_raw(obs: ArrayLike, pred: ArrayLike) -> float:
    """sklearn r2_score (원단위). 관측이 상수이면 NaN."""
    o, p = _pair(obs, pred)
    return _r2(o, p)


def nse_raw(obs: ArrayLike, pred: ArrayLike) -> float:
    """Nash–Sutcliffe Efficiency = 1 − Σ(o−p)² / Σ(o−ō)², ō 는 검증 관측 평균. 관측이 상수이면 NaN."""
    o, p = _pair(obs, pred)
    if _is_constant(o):
        return float("nan")
    return float(1.0 - np.sum((o - p) ** 2) / np.sum((o - o.mean()) ** 2))


def kge(obs: ArrayLike, pred: ArrayLike, *, log: bool = True) -> float:
    """Kling–Gupta Efficiency = 1 − sqrt((r−1)² + (α−1)² + (β−1)²).

    r: Pearson 상관, α: σ_pred/σ_obs (ddof=0), β: μ_pred/μ_obs. 기본은 log10(x+1) 공간(04 문서 KGE_log).
    관측 또는 예측이 상수이거나 관측 평균이 0 이면 NaN.
    """
    o, p = _pair(obs, pred)
    if log:
        o, p = log10p(o), log10p(p)
    if _is_constant(o) or _is_constant(p) or o.mean() == 0.0:
        return float("nan")
    r = float(np.corrcoef(o, p)[0, 1])
    alpha = float(p.std(ddof=0) / o.std(ddof=0))
    beta = float(p.mean() / o.mean())
    return float(1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2))


# ---------------------------------------------------------------- 분류
def f1_at(obs: ArrayLike, pred: ArrayLike, threshold: float = THRESHOLD_WARNING) -> dict[str, float]:
    """obs ≥ threshold 를 양성으로 한 이진 분류 성능(경계값 포함, 경보 기준 '이상'). pred 는 세포수 점추정.

    Returns: {precision, recall, f1, n_pos_obs, n_pos_pred} (양성 없음 → 0, sklearn zero_division=0).
    """
    o, p = _pair(obs, pred)
    y_true, y_pred = (o >= threshold).astype(int), (p >= threshold).astype(int)
    prec, rec, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", pos_label=1, zero_division=0
    )
    return {
        "precision": float(prec),
        "recall": float(rec),
        "f1": float(f1),
        "n_pos_obs": int(y_true.sum()),
        "n_pos_pred": int(y_pred.sum()),
    }


# ---------------------------------------------------------------- 구간·확률
def _interval(q_low: ArrayLike, q_high: ArrayLike) -> tuple[np.ndarray, np.ndarray, int]:
    """교차한 구간(q_high < q_low)은 정렬해 쓰고 건수를 함께 돌려준다 (독립 분위 모델에서 흔함)."""
    lo, hi = _pair(q_low, q_high, ("q_low", "q_high"))
    n_crossed = int((hi < lo).sum())
    return np.minimum(lo, hi), np.maximum(lo, hi), n_crossed


def picp(obs: ArrayLike, q_low: ArrayLike, q_high: ArrayLike) -> float:
    """Prediction Interval Coverage Probability: q_low ≤ obs ≤ q_high 비율 (경계 포함)."""
    o = _as_array(obs, "obs")
    lo, hi, _ = _interval(q_low, q_high)
    if o.shape != lo.shape:
        raise ValueError(f"길이 불일치: obs {o.shape[0]} vs q {lo.shape[0]}")
    return float(np.mean((o >= lo) & (o <= hi)))


def mpiw(q_low: ArrayLike, q_high: ArrayLike, *, log: bool = True) -> float:
    """Mean Prediction Interval Width. 기본은 log10(x+1) 공간(원단위는 대발생 몇 건이 지배)."""
    lo, hi, _ = _interval(q_low, q_high)
    if log:
        lo, hi = log10p(lo), log10p(hi)
    return float(np.mean(hi - lo))


def brier(obs: ArrayLike, prob: ArrayLike, threshold: float = THRESHOLD_WARNING) -> float:
    """경계 초과 확률의 Brier score = mean((p − 1[obs ≥ threshold])²)."""
    o = _as_array(obs, "obs")
    p = _as_array(prob, "prob", allow_prob=True)
    if o.shape != p.shape:
        raise ValueError(f"길이 불일치: obs {o.shape[0]} vs prob {p.shape[0]}")
    return float(np.mean((p - (o >= threshold).astype(float)) ** 2))


# ---------------------------------------------------------------- 종합
def compute_all(
    obs: ArrayLike,
    pred: ArrayLike,
    q10: ArrayLike | None = None,
    q90: ArrayLike | None = None,
    p10k: ArrayLike | None = None,
) -> dict[str, float]:
    """04 문서 6.1절 지표를 한 번에 계산한다. 구간·확률 지표는 입력이 있을 때만 포함.

    키: n, rmse_log, mae_log, r2_raw, nse_raw, r2_log, kge_log, f1_10k/precision_10k/recall_10k/n_pos_obs_10k,
    같은 4개의 _1k, (q10·q90 시) picp80, mpiw80_log, mpiw80_raw, n_crossed_q, (p10k 시) brier_10k.
    """
    o, p = _pair(obs, pred)
    out: dict[str, float] = {
        "n": int(o.size),
        "rmse_log": rmse_log(o, p),
        "mae_log": mae_log(o, p),
        "r2_raw": r2_raw(o, p),
        "nse_raw": nse_raw(o, p),
        "r2_log": r2_log(o, p),
        "kge_log": kge(o, p, log=True),
    }
    for name, thr in (("10k", THRESHOLD_WARNING), ("1k", THRESHOLD_CAUTION)):
        cls = f1_at(o, p, thr)
        out[f"f1_{name}"] = cls["f1"]
        out[f"precision_{name}"] = cls["precision"]
        out[f"recall_{name}"] = cls["recall"]
        out[f"n_pos_obs_{name}"] = cls["n_pos_obs"]
    if (q10 is None) != (q90 is None):
        raise ValueError("q10 과 q90 은 함께 주어야 함")
    if q10 is not None and q90 is not None:
        lo, hi, n_crossed = _interval(q10, q90)
        out["picp80"] = picp(o, lo, hi)
        out["mpiw80_log"] = mpiw(lo, hi, log=True)
        out["mpiw80_raw"] = mpiw(lo, hi, log=False)
        out["n_crossed_q"] = n_crossed
    if p10k is not None:
        out["brier_10k"] = brier(o, p10k, THRESHOLD_WARNING)
    return out


def _group_ids(groups: Any, n: int) -> np.ndarray:
    """행별 군집 라벨 → 0..G-1 정수. (site, base_date) 튜플·2열 DataFrame/ndarray·MultiIndex 모두 허용."""
    if isinstance(groups, pd.MultiIndex):
        groups = groups.to_frame(index=False)
    if isinstance(groups, pd.DataFrame):
        keys = groups.to_numpy(dtype=object)
    elif isinstance(groups, (pd.Series, pd.Index, np.ndarray)):
        keys = np.asarray(groups, dtype=object)
    else:
        keys = np.asarray(list(groups), dtype=object)
    if keys.ndim > 1:  # 다열 키 → 행별 복합 문자열 키
        keys = np.array(["\x1f".join(map(str, row)) for row in keys], dtype=object)
    if keys.shape[0] != n:
        raise ValueError(f"groups 길이 {keys.shape[0]} 가 obs 길이 {n} 와 다름")
    return pd.factorize(keys)[0]


def bootstrap_ci(
    obs: ArrayLike,
    pred: ArrayLike,
    metric_fn: Callable[[np.ndarray, np.ndarray], float],
    n: int = 1000,
    seed: int | None = None,
    *,
    alpha: float = 0.05,
    groups: Sequence[Any] | None = None,
) -> dict[str, float]:
    """샘플을 복원추출해 지표의 백분위(percentile) 신뢰구간을 구한다 (04 문서 6.2절 3항).

    기본은 행(= (site, base_date) 샘플) 단위 재표본. ``groups`` 를 주면 군집 단위 cluster bootstrap
    (예: 같은 base_date 의 지점들을 함께 뽑기). 군집 키는 1차원 라벨, (site, base_date) 튜플 열,
    2열 DataFrame/ndarray, MultiIndex 모두 받는다.

    Args:
        metric_fn: (obs, pred) → float. 예: rmse_log, nse_raw, lambda o, p: f1_at(o, p)["f1"].
        n: 재표본 횟수(기본 1,000).
        seed: 난수 시드. None 이면 config/seed.yaml(42).
        alpha: 양측 유의수준(0.05 → 95% CI).

    Returns:
        {point, lo, hi, n_boot, n_failed, alpha, method}. NaN 재표본은 n_failed 로 세고 CI 에서 제외.
    """
    o, p = _pair(obs, pred)
    rng = np.random.default_rng(load_seed() if seed is None else seed)
    point = metric_fn(o, p)
    if isinstance(point, dict):
        raise TypeError("metric_fn 은 float 를 반환해야 함. 예: lambda o, p: f1_at(o, p)['f1']")
    point = float(point)
    members: list[np.ndarray] | None = None
    if groups is not None:
        ids = _group_ids(groups, o.shape[0])
        members = [np.flatnonzero(ids == k) for k in range(int(ids.max()) + 1)]
    stats = []
    for _ in range(n):
        if members is None:
            idx = rng.integers(0, o.size, size=o.size)
        else:
            picked = rng.integers(0, len(members), size=len(members))
            idx = np.concatenate([members[k] for k in picked])
        val = float(metric_fn(o[idx], p[idx]))
        if np.isfinite(val):
            stats.append(val)
    arr = np.asarray(stats, dtype="float64")
    if arr.size == 0:
        lo, hi = float("nan"), float("nan")
    else:
        lo, hi = (float(v) for v in np.percentile(arr, [100 * alpha / 2, 100 * (1 - alpha / 2)]))
    return {
        "point": point,
        "lo": lo,
        "hi": hi,
        "n_boot": int(arr.size),
        "n_failed": int(n - arr.size),
        "alpha": alpha,
        "method": "percentile",
    }
