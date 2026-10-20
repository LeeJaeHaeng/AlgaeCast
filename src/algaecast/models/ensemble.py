"""OOF 기반 NNLS 앙상블 (T4-c).

C1(smearing)·C3 hurdle·C2 tweedie 의 CV OOF(원단위, log 공간에서 적합)를 NNLS(합=1)로 결합.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import nnls


def nnls_weights(
    preds: dict[str, np.ndarray], obs: np.ndarray, *, log_space: bool = True
) -> dict[str, float]:
    """합=1 제약 NNLS: 증강 행(큰 가중치의 합 제약) 으로 근사."""
    names = list(preds)
    X = np.column_stack([preds[n] for n in names])
    y = obs.copy()
    ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
    X, y = X[ok], y[ok]
    if log_space:
        X, y = np.log10(X + 1), np.log10(y + 1)
    big = 1e3
    Xa = np.vstack([X, big * np.ones((1, X.shape[1]))])
    ya = np.append(y, big)
    w, _ = nnls(Xa, ya)
    w = w / w.sum() if w.sum() > 0 else np.ones(len(names)) / len(names)
    return dict(zip(names, map(float, w), strict=True))


def combine(preds: dict[str, np.ndarray], weights: dict[str, float], *, log_space: bool = True) -> np.ndarray:
    if log_space:
        z = sum(weights[n] * np.log10(preds[n] + 1) for n in weights)
        return np.clip(10**z - 1, 0, None)
    return np.clip(sum(weights[n] * preds[n] for n in weights), 0, None)
