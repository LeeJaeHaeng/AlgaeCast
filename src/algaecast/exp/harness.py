# ruff: noqa: E501  (한국어 표 머리글)
"""고도화 실험(EXP-004~) 공통 하네스 — 모든 실험이 같은 구조·지표·표로 비교되도록 한다.

원칙
- 선택(피처·보정 계수·하이퍼파라미터·가중치)은 2020~2024 expanding CV OOF 로만 한다. 2025 는 확인용.
- 2026 은 계산·열람 금지: base_date > 2025-12-31 행이 들어오면 즉시 중단(guard_no_2026), 리드타임 사건은
  2025-12-31 까지의 측정으로만 만든다(official_events_until).
- v1 동결 산출물(features_S*.parquet·models/·config/model.yaml·submission/)은 읽기만 한다.

구성(v1 과 동일)
- 회귀 C1(log 가중, smearing)·C3(hurdle)·C2(tweedie) → 연도 확장 NNLS 앙상블
  (연도 Y 의 가중치는 Y 이전 CV OOF 로 적합, 2020 은 균등, 2025 는 2020~2024 OOF 전체)
- 분위 q10/q50/q90(C1 파라미터, objective=quantile) → 리드타임 '감시(q90≥10k)' 포착 수

표준 지표(각 실험 표 공통)
- 구간: CV = 2020~2024 OOF 통합(1,278행 기준), 2025 = Final(≤2024 학습 → 2025)
- r2_raw, r2_pearson_raw, nse_raw, rmse_log, r2_log, F1@10k(점예측), 리드타임 포착(q90≥10k, 2020~2025 사건)
- 보조: CV 폴드 평균(cvfold_*), 점예측≥10k 리드타임 포착
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from algaecast.collect.nier_algae import two_consecutive_levels
from algaecast.collect.nier_forecast import level_from_cells
from algaecast.config import CONFIG_DIR, DATA_DIR, RAW_DIR, ROOT
from algaecast.eval.metrics import compute_all
from algaecast.models import data as D
from algaecast.models.ensemble import combine, nnls_weights
from algaecast.models.quantile import cv_quantiles
from algaecast.models.train import SEED, VariantSpec, feature_sets, run_cv
from algaecast.models.tune import OUT_DIR as OPTUNA_DIR
from algaecast.models.tune import spec_from_params

log = logging.getLogger(__name__)

T10K = 10_000.0
LAST_DATE = pd.Timestamp("2025-12-31")
CV_YEARS = (2020, 2021, 2022, 2023, 2024)
FINAL_YEAR = 2025
EXP_DATA = DATA_DIR / "processed" / "exp"
EXP_REPORTS = ROOT / "reports" / "experiments"
STD_METRICS = ("r2_raw", "r2_pearson_raw", "nse_raw", "rmse_log", "r2_log", "f1_10k")
MEMBERS = ("c1", "c3", "c2")
ALGAE_PARQUET = RAW_DIR / "nier_algae" / "nier_algae_2012_2026.parquet"


class BudgetExceeded(RuntimeError):
    """실험 시간 상한 초과."""


class Budget:
    """실험별 시간 상한(시간 단위). check() 가 상한을 넘으면 BudgetExceeded."""

    def __init__(self, hours: float, name: str) -> None:
        self.hours, self.name, self.t0 = hours, name, time.time()

    @property
    def elapsed_h(self) -> float:
        return (time.time() - self.t0) / 3600

    def check(self) -> None:
        if self.elapsed_h > self.hours:
            raise BudgetExceeded(f"{self.name}: 시간 상한 {self.hours}h 초과({self.elapsed_h:.2f}h)")


# ---------------------------------------------------------------- 데이터·가드
def guard_no_2026(df: pd.DataFrame, col: str = "base_date") -> None:
    """2026 행(또는 test 분할)이 섞이면 중단한다."""
    d = pd.to_datetime(df[col])
    if (d > LAST_DATE).any():
        raise RuntimeError(f"2026 행 {int((d > LAST_DATE).sum())}개가 실험 프레임에 섞임 — 계산 금지")
    if "split" in df.columns and (df["split"] == "test").any():
        raise RuntimeError("test 분할 행이 실험 프레임에 섞임")


def load_base(strategy: str = "S1") -> pd.DataFrame:
    """v1 학습·검증 행(≤2025, 타깃 있음)만. 행 순서는 v1 OOF 와 같다."""
    df = D.load_train_valid(strategy)
    guard_no_2026(df)
    return df


def years_of(df: pd.DataFrame) -> np.ndarray:
    return pd.to_datetime(df["base_date"]).dt.year.to_numpy()


def masks(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    y = years_of(df)
    return np.isin(y, CV_YEARS), y == FINAL_YEAR


def base_columns() -> list[str]:
    """v1 선택 피처 30개(perc75)."""
    return list(feature_sets()["perc75"])


def v1_specs() -> dict[str, VariantSpec]:
    cfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))

    def study(name: str) -> dict:
        return json.loads((OPTUNA_DIR / f"{name}.json").read_text(encoding="utf-8"))

    return {
        "c1": spec_from_params(cfg["selected"]["params"], "log_w"),
        "c3": spec_from_params(study("hurdle_rmse_log_perc75_S1")["best_params"], "hurdle"),
        "c2": spec_from_params(study("tweedie_rmse_log_perc75_S1")["best_params"], "tweedie"),
    }


# ---------------------------------------------------------------- 모델 OOF
def run_members(
    df: pd.DataFrame,
    cols: list[str],
    specs: dict[str, VariantSpec] | None = None,
    *,
    quantiles: bool = True,
    seeds: tuple[int, ...] = (SEED,),
) -> dict[str, np.ndarray]:
    """C1·C3·C2 회귀 OOF(원단위)와 분위 OOF. 2020~2025 행만 값, 나머지 NaN.

    반환 키: c1(smearing), c1_none, c1_log(log10 예측), c3, c2, q10, q50, q90
    """
    guard_no_2026(df)
    specs = specs or v1_specs()
    r1 = run_cv(df, cols, specs["c1"], seeds=seeds, bias_methods=("none", "smearing"))
    out = {"c1": r1.oof["smearing"], "c1_none": r1.oof["none"], "c1_log": r1.oof_log}
    out["c3"] = run_cv(df, cols, specs["c3"], seeds=seeds, bias_methods=("none",)).oof["none"]
    out["c2"] = run_cv(df, cols, specs["c2"], seeds=seeds, bias_methods=("none",)).oof["none"]
    if quantiles:
        out.update(cv_quantiles(df, cols, specs["c1"]))
    return out


def ensemble_expanding(
    df: pd.DataFrame, preds: dict[str, np.ndarray], names: tuple[str, ...] = MEMBERS
) -> tuple[np.ndarray, dict[int, dict[str, float]]]:
    """연도 확장 NNLS(합=1, log 공간). 연도 Y 는 Y 이전 CV OOF 로 적합, 2020 은 균등."""
    years = years_of(df)
    cv_mask, _ = masks(df)
    obs = df["target_cells"].to_numpy(dtype=float)
    ens = np.full(len(df), np.nan)
    weights: dict[int, dict[str, float]] = {}
    sub = {k: preds[k] for k in names}
    for yv in (*CV_YEARS, FINAL_YEAR):
        fit_m = cv_mask & (years < yv)
        app_m = years == yv
        if fit_m.sum() < 50:
            wy = {k: 1.0 / len(sub) for k in sub}
        else:
            wy = nnls_weights({k: v[fit_m] for k, v in sub.items()}, obs[fit_m])
        ens[app_m] = combine({k: v[app_m] for k, v in sub.items()}, wy)
        weights[int(yv)] = wy
    return ens, weights


def expanding_fit_apply(
    df: pd.DataFrame,
    fit: Callable[[np.ndarray], object],
    apply: Callable[[object, np.ndarray], np.ndarray],
    *,
    min_rows: int = 50,
) -> np.ndarray:
    """후처리 계수 등을 '연도 Y 이전 CV OOF 로 적합 → Y 에 적용' 하는 공통 틀(2025 는 2020~2024 전체).

    fit(mask) → 상태, apply(상태, mask) → 해당 행 예측. 적합 행이 min_rows 미만인 연도는 apply(None, mask).
    """
    years = years_of(df)
    cv_mask, _ = masks(df)
    out = np.full(len(df), np.nan)
    for yv in (*CV_YEARS, FINAL_YEAR):
        fit_m = cv_mask & (years < yv)
        app_m = years == yv
        state = fit(fit_m) if fit_m.sum() >= min_rows else None
        out[app_m] = apply(state, app_m)
    return out


# ---------------------------------------------------------------- 리드타임(2025 까지)
def official_events_until(
    last: pd.Timestamp = LAST_DATE, level: float = T10K, start_year: int = 2020
) -> pd.DataFrame:
    """transitions.official_events 와 같은 규칙(2회 연속 '경계' 진입)이되 last 이후 측정은 읽은 즉시 버린다."""
    a = pd.read_parquet(ALGAE_PARQUET, columns=["station_id", "obs_date", "iem_bgalage_cell_co"])
    a["obs_date"] = pd.to_datetime(a["obs_date"])
    a = a[(a["obs_date"] <= last) & (a["obs_date"].dt.year >= start_year - 1)]
    ev = []
    lvl_needed = 2 if level == T10K else 1
    for sid, g in a.sort_values("obs_date").groupby("station_id"):
        cells = g["iem_bgalage_cell_co"].astype(float)
        two = two_consecutive_levels(level_from_cells(cells)).astype(float).to_numpy()
        dates = g["obs_date"].to_numpy()
        cv = cells.to_numpy()
        for i in range(1, len(g)):
            if two[i] >= lvl_needed and two[i - 1] < lvl_needed:
                j = i
                while j - 1 >= 0 and np.isfinite(cv[j - 1]) and cv[j - 1] >= level:
                    j -= 1
                if pd.Timestamp(dates[i]).year >= start_year:
                    ev.append({"station_id": sid, "D": pd.Timestamp(dates[i]), "E": pd.Timestamp(dates[j])})
    return pd.DataFrame(ev)


def _measurements_until(last: pd.Timestamp = LAST_DATE) -> pd.DataFrame:
    m = pd.read_parquet(ALGAE_PARQUET, columns=["station_id", "obs_date", "iem_bgalage_cell_co"])
    m["obs_date"] = pd.to_datetime(m["obs_date"])
    m = m[m["obs_date"] <= last]
    m["cells"] = m["iem_bgalage_cell_co"].astype(float)
    return m


def leadtime(df: pd.DataFrame, alarm: np.ndarray, *, level: float = T10K, lookback_days: int = 28) -> dict:
    """2020~2025 경계 사건 중 첫 초과 측정(E) 이전 창에서 경보가 한 번이라도 켜진 사건 수(transitions 규칙)."""
    guard_no_2026(df)
    ev = official_events_until(level=level)
    meas = _measurements_until()
    o = pd.DataFrame(
        {
            "station_id": df["station_id"].astype(str).to_numpy(),
            "base_date": pd.to_datetime(df["base_date"]).to_numpy(),
            "year": years_of(df),
            "al": np.nan_to_num(np.asarray(alarm, dtype=float), nan=0.0),
        }
    )
    o = o[o["year"] >= 2020]
    detected, n_ev, leads = 0, 0, []
    for e in ev.itertuples():
        prev = meas[
            (meas["station_id"] == e.station_id) & (meas["obs_date"] < e.E) & (meas["cells"] >= level)
        ]["obs_date"]
        start = e.E - pd.Timedelta(days=lookback_days)
        if len(prev):
            start = max(start, prev.max() + pd.Timedelta(days=1))
        cand = o[(o["station_id"] == e.station_id) & (o["base_date"] < e.E) & (o["base_date"] >= start)]
        if cand.empty:
            continue
        n_ev += 1
        fired = cand[cand["al"] >= 1]
        if len(fired):
            detected += 1
            leads.append((e.E - fired["base_date"].min()).days)
    return {
        "detected": detected,
        "n_events": n_ev,
        "median_lead_E": float(np.median(leads)) if leads else np.nan,
    }


# ---------------------------------------------------------------- 지표·표
def metric_row(df: pd.DataFrame, pred: np.ndarray, q90: np.ndarray | None, label: str) -> dict:
    """표준 지표 한 묶음(CV 통합·2025·CV 폴드 평균·리드타임)."""
    guard_no_2026(df)
    pred = np.asarray(pred, dtype=float)
    obs = df["target_cells"].to_numpy(dtype=float)
    years = years_of(df)
    cv_mask, fin_mask = masks(df)
    row: dict = {"구성": label}
    for scope, m in (("cv", cv_mask), ("y2025", fin_mask)):
        ok = m & np.isfinite(pred)
        mm = compute_all(obs[ok], pred[ok])
        row[f"{scope}_n"] = int(ok.sum())
        for k in STD_METRICS:
            row[f"{scope}_{k}"] = float(mm[k])
    fold = [
        compute_all(obs[(years == y) & np.isfinite(pred)], pred[(years == y) & np.isfinite(pred)])
        for y in CV_YEARS
    ]
    for k in STD_METRICS:
        row[f"cvfold_{k}"] = float(np.nanmean([f[k] for f in fold]))
    if q90 is not None:
        lt = leadtime(df, (np.asarray(q90, dtype=float) >= T10K).astype(float))
        row.update(
            {"lead_q90": lt["detected"], "lead_n": lt["n_events"], "lead_q90_median": lt["median_lead_E"]}
        )
    lp = leadtime(df, (pred >= T10K).astype(float))
    row.update({"lead_point": lp["detected"], "lead_point_n": lp["n_events"]})
    return row


def evaluate_members(
    df: pd.DataFrame, members: dict[str, np.ndarray], label: str
) -> tuple[dict, np.ndarray, dict]:
    """회귀 3종 → 확장 NNLS 앙상블 → 표준 지표. (지표, 앙상블 OOF, 연도별 가중치)"""
    ens, w = ensemble_expanding(df, members)
    return metric_row(df, ens, members.get("q90"), label), ens, w


def _f(v: object, nd: int = 3) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "–"
    return f"{v:.{nd}f}" if isinstance(v, float) else str(v)


def standard_table(rows: list[dict]) -> str:
    """실험 공통 표: 구성마다 CV(2020~2024 OOF 통합)·2025 두 줄."""
    head = "| 구성 | 구간 | n | r2_raw | r2_pearson_raw | nse_raw | rmse_log | r2_log | F1@10k | 리드타임 포착(q90≥10k) |\n|---|---|---|---|---|---|---|---|---|---|\n"
    lines = []
    for r in rows:
        lead = f"{r['lead_q90']}/{r['lead_n']}" if "lead_q90" in r else "–"
        for scope, name in (("cv", "CV 2020~2024"), ("y2025", "2025")):
            vals = " | ".join(_f(r[f"{scope}_{k}"]) for k in STD_METRICS)
            lines.append(
                f"| {r['구성']} | {name} | {r[f'{scope}_n']} | {vals} | {lead if scope == 'cv' else '〃'} |"
            )
    return head + "\n".join(lines) + "\n"


def detail_table(rows: list[dict]) -> str:
    """보조 표: CV 폴드 평균·점예측 리드타임·q90 중앙 리드."""
    head = "| 구성 | CV 폴드평균 r2_raw | CV 폴드평균 nse_raw | CV 폴드평균 rmse_log | CV 폴드평균 F1@10k | 점예측≥10k 포착 | q90 중앙 리드(일) |\n|---|---|---|---|---|---|---|\n"
    return (
        head
        + "\n".join(
            f"| {r['구성']} | {_f(r['cvfold_r2_raw'])} | {_f(r['cvfold_nse_raw'])} | {_f(r['cvfold_rmse_log'])} | {_f(r['cvfold_f1_10k'])} | "
            f"{r['lead_point']}/{r['lead_point_n']} | {_f(r.get('lead_q90_median'), 1)} |"
            for r in rows
        )
        + "\n"
    )


def adoption(base: dict, cand: dict) -> dict:
    """채택 기준: CV r2_raw +0.10 이상, CV rmse_log 악화 0.01 이내, 리드타임 포착 수 감소 없음."""
    d_r2 = cand["cv_r2_raw"] - base["cv_r2_raw"]
    d_rmse = cand["cv_rmse_log"] - base["cv_rmse_log"]
    lead_ok = cand.get("lead_q90", base.get("lead_q90", 0)) >= base.get("lead_q90", 0)
    return {
        "d_cv_r2_raw": d_r2,
        "d_cv_rmse_log": d_rmse,
        "lead_ok": bool(lead_ok),
        "pass": bool(d_r2 >= 0.10 and d_rmse <= 0.01 and lead_ok),
    }


def save_oof(df: pd.DataFrame, preds: dict[str, np.ndarray], path: Path) -> Path:
    """행 단위 OOF(관측 포함) → data/processed/exp/ 아래(git 제외). reports/ 에 두지 않는다."""
    path = Path(path)
    if EXP_DATA not in path.parents:
        raise ValueError(f"행 단위 산출물은 {EXP_DATA} 아래에만 저장: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df[["station_id", "base_date", "target_date", "target_cells"]].copy()
    out["year"] = years_of(df)
    for k, v in preds.items():
        out[k] = np.asarray(v, dtype=float)
    out.to_parquet(path, index=False)
    return path


def load_baseline() -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    """하네스로 재현한 v1 기준 OOF(data/processed/exp/baseline/oof.parquet)를 읽는다."""
    df = load_base()
    o = pd.read_parquet(EXP_DATA / "baseline" / "oof.parquet")
    if (
        len(o) != len(df)
        or not (o["base_date"].astype(str).to_numpy() == df["base_date"].astype(str).to_numpy()).all()
    ):
        raise RuntimeError(
            "baseline OOF 행 순서가 load_base() 와 다르다 — python -m algaecast.exp.harness 재실행"
        )
    keys = [
        c for c in o.columns if c not in ("station_id", "base_date", "target_date", "target_cells", "year")
    ]
    return df, {k: o[k].to_numpy(dtype=float) for k in keys}


def main() -> int:
    """v1 기준선 재현: 하네스 OOF ↔ data/processed/oof_predictions.parquet 대조, 기준 OOF·표 저장."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    t0 = time.time()
    df = load_base()
    cols = base_columns()
    mem = run_members(df, cols)
    row, ens, w = evaluate_members(df, mem, "v1 기준(하네스 재현)")
    mem["ens"] = ens
    save_oof(df, mem, EXP_DATA / "baseline" / "oof.parquet")
    # v1 저장 OOF 와 대조(같은 (지점, base_date) 키)
    v1 = pd.read_parquet(DATA_DIR / "processed" / "oof_predictions.parquet")
    v1["base_date"] = pd.to_datetime(v1["base_date"]).dt.date.astype(str)
    key = df[["station_id", "base_date"]].astype(str)
    mrg = key.merge(v1, on=["station_id", "base_date"], how="left")
    diffs = {}
    for k_h, k_v in (("c1", "reg_c1"), ("c3", "reg_c3"), ("c2", "reg_c2"), ("ens", "ens"), ("q90", "q90")):
        a, b = np.log10(mem[k_h] + 1), np.log10(mrg[k_v].to_numpy(dtype=float) + 1)
        ok = np.isfinite(a) & np.isfinite(b)
        diffs[k_h] = float(np.max(np.abs(a[ok] - b[ok]))) if ok.any() else float("nan")
    w_txt = json.dumps(
        {y: {k: round(v, 3) for k, v in ww.items()} for y, ww in w.items()}, ensure_ascii=False
    )
    out = EXP_REPORTS / "EXP-baseline"
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text(
        "# v1 기준선(하네스 재현)\n\n"
        "고도화 실험(EXP-004~)의 비교 기준. 하네스(`src/algaecast/exp/harness.py`)로 v1 구성을 다시 돌린 OOF.\n\n"
        + standard_table([row])
        + "\n## 보조 지표\n\n"
        + detail_table([row])
        + f"\n## v1 저장 OOF 와의 차이(log10 최대 절대차)\n\n{json.dumps(diffs, ensure_ascii=False)}\n\n"
        f"## 연도별 NNLS 가중치\n\n{w_txt}\n\n소요 {(time.time() - t0) / 60:.1f}분.\n",
        encoding="utf-8",
    )
    (out / "baseline_metrics.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(standard_table([row]))
    print("v1 저장 OOF 와의 log10 최대 절대차:", diffs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
