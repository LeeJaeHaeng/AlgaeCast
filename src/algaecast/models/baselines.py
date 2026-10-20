"""베이스라인 B0~B4 (04 문서 3절) (T4-a). B3 물모아는 2026 라이브 전용이라 제외.

사용: python -m algaecast.models.baselines [--strategy S1] → reports/eval/tbl_baseline.md
"""

from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from algaecast.config import ROOT
from algaecast.models import data as D
from algaecast.models.cv import REPORT_METRICS, cv_evaluate, summarize

log = logging.getLogger(__name__)
LOG_CAP = 7.0  # log10 상한(10^7 cells/mL)


def _to_cells(log_pred: np.ndarray) -> np.ndarray:
    return np.clip(10 ** np.clip(log_pred, 0, LOG_CAP) - 1, 0, None)


def b0_persistence(tr: pd.DataFrame, va: pd.DataFrame) -> np.ndarray:
    return _to_cells(va["cell_log_t0"].fillna(0).to_numpy(dtype=float))


def b1_site_month_median(tr: pd.DataFrame, va: pd.DataFrame) -> np.ndarray:
    m = pd.to_datetime(tr["base_date"]).dt.month
    med = tr.assign(month=m.to_numpy()).groupby(["station_id", "month"], observed=True)["target_log"].median()
    glob = tr.assign(month=m.to_numpy()).groupby("month")["target_log"].median()
    vm = pd.to_datetime(va["base_date"]).dt.month.to_numpy()
    out = []
    for sid, mo in zip(va["station_id"].astype(str), vm, strict=True):
        v = med.get((sid, mo), np.nan)
        if not np.isfinite(v):
            v = glob.get(mo, float(tr["target_log"].median()))
        out.append(v)
    return _to_cells(np.asarray(out, dtype=float))


def b2_trend(tr: pd.DataFrame, va: pd.DataFrame) -> np.ndarray:
    hi = float(tr["target_log"].max())
    base = va["cell_log_t0"].fillna(0).to_numpy(dtype=float)
    slope = va["cell_slope_3"].fillna(0).to_numpy(dtype=float)
    h = va["horizon_days"].fillna(7).to_numpy(dtype=float)
    return _to_cells(np.clip(base + slope * h, 0, hi))


def b4_elasticnet(tr: pd.DataFrame, va: pd.DataFrame, cols: list[str] | None = None) -> np.ndarray:
    cols = cols or D.feature_columns(tr, selected_only=True)
    nums, cats = D.numeric_and_categorical(cols)
    nums = [c for c in nums if tr[c].notna().any()]
    pre = ColumnTransformer(
        [
            ("num", Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())]), nums),
            ("cat", OneHotEncoder(handle_unknown="ignore"), cats),
        ]
    )
    model = Pipeline(
        [("pre", pre), ("en", ElasticNet(alpha=0.01, l1_ratio=0.5, max_iter=5000, random_state=42))]
    )
    X = tr[nums + cats].copy()
    for c in cats:
        X[c] = X[c].astype(str)
    model.fit(X, tr["target_log"].to_numpy(dtype=float))
    Xv = va[nums + cats].copy()
    for c in cats:
        Xv[c] = Xv[c].astype(str)
    hi = float(tr["target_log"].max())  # 선형 외삽 폭주 방지: 학습 타깃 최대(log) 로 클리핑
    return _to_cells(np.clip(model.predict(Xv), 0, hi))


BASELINES = {
    "B0 지속성": b0_persistence,
    "B1 지점×월 중앙값": b1_site_month_median,
    "B2 최근 3회 기울기 외삽": b2_trend,
    "B4 ElasticNet": b4_elasticnet,
}


def _md(t: pd.DataFrame, nd: int = 3) -> str:
    d = t.copy()
    for c in d.columns:
        if d[c].dtype.kind == "f":
            d[c] = d[c].round(nd)
    return (
        "| "
        + " | ".join(map(str, d.columns))
        + " |\n|"
        + "---|" * len(d.columns)
        + "\n"
        + "\n".join(
            "| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |"
            for r in d.itertuples(index=False)
        )
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strategy", default="S1")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    df = D.load_train_valid(args.strategy)
    summary, by_fold, by_site = [], [], []
    for name, fn in BASELINES.items():
        res = cv_evaluate(df, fn, include_final=True)
        s = summarize(res["folds"])
        summary.append(
            {
                "베이스라인": name,
                **{k: s[f"cv_{k}"] for k in REPORT_METRICS},
                "final_rmse_log": s.get("final_rmse_log"),
                "final_r2_log": s.get("final_r2_log"),
                "final_f1_10k": s.get("final_f1_10k"),
            }
        )
        by_fold.append(res["folds"].assign(베이스라인=name))
        by_site.append(res["by_site"].assign(베이스라인=name))
        log.info("%s: CV rmse_log %.3f, Final %.3f", name, s["cv_rmse_log"], s.get("final_rmse_log", np.nan))
    summary_df = pd.DataFrame(summary)
    fold_df = pd.concat(by_fold, ignore_index=True)
    site_df = pd.concat(by_site, ignore_index=True)
    site_final = site_df[site_df["fold"] == "Final"].drop(columns=["fold"])
    site_cv = (
        site_df[site_df["fold"] != "Final"]
        .groupby(["베이스라인", "station_id"], observed=True)[["n", *REPORT_METRICS]]
        .agg({"n": "sum", **{k: "mean" for k in REPORT_METRICS}})
        .reset_index()
    )
    out = ROOT / "reports" / "eval" / "tbl_baseline.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"# 베이스라인 (T4-a, 전략 {args.strategy})\n\n"
        f"- 샘플: train/valid {len(df):,} (splits.json), 폴드 F1~F5 = train ≤2019~2023 → valid 2020~2024, "
        "Final = ≤2024 → 2025. test(2026) 는 로더가 반환하지 않음.\n"
        "- B3 물모아 공식 예측은 2026 라이브 벤치마크 전용(reports/eval/live_benchmark.csv).\n\n"
        "## 요약 (F1~F5 평균, Final = 2025 홀드아웃)\n"
        + _md(summary_df)
        + "\n\n## 폴드별\n"
        + _md(fold_df[["베이스라인", "fold", "valid_year", "n_train", "n", *REPORT_METRICS]])
        + "\n\n"
        "## 지점별 — Final(2025)\n"
        + _md(site_final[["베이스라인", "station_id", "비고", "n", *REPORT_METRICS]])
        + "\n\n"
        "## 지점별 — CV 평균(F1~F5; 물금·매리 F1 은 train 0 이라 별도 행 참고)\n" + _md(site_cv) + "\n\n"
        "## 지점별 — 폴드 전체\n"
        + _md(site_df[["베이스라인", "fold", "station_id", "비고", "n", *REPORT_METRICS]])
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(summary_df.round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
