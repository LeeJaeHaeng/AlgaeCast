"""통계 검정 (T5): Diebold-Mariano(HAC), Wilcoxon 부호순위, Ljung-Box."""

from __future__ import annotations

import numpy as np
from scipy import stats
from statsmodels.stats.diagnostic import acorr_ljungbox


def dm_test(
    e1: np.ndarray, e2: np.ndarray, *, loss: str = "squared", lag: int | None = None
) -> dict[str, float]:
    """Diebold-Mariano: 손실차 d = L(e1) − L(e2), HAC(Bartlett) 분산. 음수 통계량 = 모델1 이 더 좋음.

    e1, e2 는 같은 표본의 예측 오차(여기서는 log10 오차). lag 기본 floor(n^(1/3)).
    """
    e1, e2 = np.asarray(e1, float), np.asarray(e2, float)
    ok = np.isfinite(e1) & np.isfinite(e2)
    e1, e2 = e1[ok], e2[ok]
    d = (e1**2 - e2**2) if loss == "squared" else (np.abs(e1) - np.abs(e2))
    n = len(d)
    if n < 10:
        return {"n": n, "dm": float("nan"), "p": float("nan"), "mean_d": float("nan")}
    lag = int(np.floor(n ** (1 / 3))) if lag is None else lag
    dbar = d.mean()
    dc = d - dbar
    gamma0 = float(np.mean(dc * dc))
    var = gamma0
    for k in range(1, lag + 1):
        gk = float(np.mean(dc[k:] * dc[:-k]))
        var += 2 * (1 - k / (lag + 1)) * gk
    var = max(var, 1e-12) / n
    dm = dbar / np.sqrt(var)
    # Harvey-Leybourne-Newbold 소표본 보정 (h=1)
    hln = dm * np.sqrt((n + 1 - 2 * 1 + 1 * 0) / n)
    p = 2 * (1 - stats.t.cdf(abs(hln), df=n - 1))
    return {"n": n, "dm": float(hln), "p": float(p), "mean_d": float(dbar)}


def wilcoxon_abs_err(e1: np.ndarray, e2: np.ndarray) -> dict[str, float]:
    e1, e2 = np.asarray(e1, float), np.asarray(e2, float)
    ok = np.isfinite(e1) & np.isfinite(e2)
    a, b = np.abs(e1[ok]), np.abs(e2[ok])
    if len(a) < 10 or np.allclose(a, b):
        return {"n": int(ok.sum()), "stat": float("nan"), "p": float("nan"), "median_diff": float("nan")}
    r = stats.wilcoxon(a, b, zero_method="wilcox", alternative="two-sided")
    return {
        "n": int(ok.sum()),
        "stat": float(r.statistic),
        "p": float(r.pvalue),
        "median_diff": float(np.median(a - b)),
    }


def ljung_box(resid: np.ndarray, lags: int = 4) -> dict[str, float]:
    r = np.asarray(resid, float)
    r = r[np.isfinite(r)]
    if len(r) < lags + 5:
        return {"n": len(r), "lb_stat": float("nan"), "p": float("nan")}
    out = acorr_ljungbox(r, lags=[lags], return_df=True)
    return {"n": len(r), "lb_stat": float(out["lb_stat"].iloc[0]), "p": float(out["lb_pvalue"].iloc[0])}
