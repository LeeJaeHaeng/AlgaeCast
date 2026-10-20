"""연도 expanding-window 폴드 생성기 — 랜덤 KFold 금지 (04 문서 2절) (T4-a).

Fold k: train base_date 연도 ≤ Y_k−1 → valid 연도 Y_k, Y_k ∈ {2020,…,2024}. Final: ≤2024 → 2025.
샘플 단위 = (site, base_date); 같은 base_date 의 지점은 같은 폴드.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from algaecast.eval.metrics import compute_all

FOLD_YEARS = (2020, 2021, 2022, 2023, 2024)
FINAL_VALID_YEAR = 2025
REPORT_METRICS = ["rmse_log", "mae_log", "r2_log", "r2_raw", "r2_pearson_raw", "nse_raw", "f1_10k", "f1_1k"]
SMALL_SAMPLE_SITES = {"MGMR": "표본 부족(2020-05~)"}


@dataclass(frozen=True)
class Fold:
    name: str
    valid_year: int
    train_idx: np.ndarray
    valid_idx: np.ndarray


def year_of(df: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(df["base_date"]).dt.year


def year_folds(df: pd.DataFrame, *, include_final: bool = False) -> list[Fold]:
    y = year_of(df).to_numpy()
    folds = [
        Fold(f"F{i + 1}", vy, np.where(y < vy)[0], np.where(y == vy)[0]) for i, vy in enumerate(FOLD_YEARS)
    ]
    if include_final:
        folds.append(
            Fold(
                "Final",
                FINAL_VALID_YEAR,
                np.where(y <= FINAL_VALID_YEAR - 1)[0],
                np.where(y == FINAL_VALID_YEAR)[0],
            )
        )
    return [f for f in folds if len(f.valid_idx) and len(f.train_idx)]


FitPredict = Callable[[pd.DataFrame, pd.DataFrame], np.ndarray]
"""(train_df, valid_df) → valid 예측 (cells/mL 원단위, ≥0)."""


def cv_evaluate(df: pd.DataFrame, fit_predict: FitPredict, *, include_final: bool = True) -> dict:
    """폴드별·지점별 지표와 OOF 예측을 돌려준다."""
    folds = year_folds(df, include_final=include_final)
    oof = pd.Series(np.nan, index=df.index, dtype=float)
    rows, site_rows = [], []
    for fo in folds:
        tr, va = df.iloc[fo.train_idx], df.iloc[fo.valid_idx]
        pred = np.asarray(fit_predict(tr, va), dtype=float)
        pred = np.clip(np.nan_to_num(pred, nan=0.0), 0, None)
        oof.iloc[fo.valid_idx] = pred
        obs = va["target_cells"].to_numpy(dtype=float)
        m = compute_all(obs, pred)
        rows.append(
            {
                "fold": fo.name,
                "valid_year": fo.valid_year,
                "n_train": len(tr),
                **{k: m[k] for k in ["n", *REPORT_METRICS]},
            }
        )
        for sid, g in va.groupby("station_id", observed=True):
            if len(g) < 5:
                continue
            ms = compute_all(g["target_cells"].to_numpy(dtype=float), pred[va.index.get_indexer(g.index)])
            note = SMALL_SAMPLE_SITES.get(str(sid), "")
            if fo.name == "F1" and str(sid) == "MGMR":
                note = "표본 부족·train 0 (별도 행)"
            site_rows.append(
                {
                    "fold": fo.name,
                    "station_id": str(sid),
                    "비고": note,
                    **{k: ms[k] for k in ["n", *REPORT_METRICS]},
                }
            )
    return {"folds": pd.DataFrame(rows), "by_site": pd.DataFrame(site_rows), "oof": oof}


def summarize(folds: pd.DataFrame) -> dict[str, float]:
    """F1~F5 평균 + Final 행."""
    cv = folds[folds["fold"] != "Final"]
    out = {f"cv_{k}": float(cv[k].mean()) for k in REPORT_METRICS}
    fin = folds[folds["fold"] == "Final"]
    if len(fin):
        out.update({f"final_{k}": float(fin[k].iloc[0]) for k in REPORT_METRICS})
        out["final_n"] = int(fin["n"].iloc[0])
    out["cv_n"] = int(cv["n"].sum())
    return out
