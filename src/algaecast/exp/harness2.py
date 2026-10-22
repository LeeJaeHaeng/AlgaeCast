# ruff: noqa: E501  (한국어 표 머리글)
"""원단위 R² 고도화 2차(EXP-005 2차, P0~P6·종합) 공통 하네스. 1차 harness.py 위에 얹는다.

- 기준 모델 = C(EXP-confirm 채택): v1 로그 앙상블 + R2 상류 피처 5열 + R3 속별 구성원 cg, 분위는 v1 동결 OOF.
- 시드: 탐색 EXPLORE_SEEDS(실험표·선택), 판정 FINAL_SEEDS(최종 판정 전용) — reports/experiments/EXP-005/PREREG_FINAL.md.
- 표준 표: CV(2020~2024 OOF 통합)·2025 전체·2025 1~8월·2025 9~10월(목표일 기준) × r2_raw·r2_pearson_raw·nse_raw·
  rmse_log·r2_log·F1@10k, 리드타임(q90≥10k, 2020~2025 사건 20건), 시드 평균과 기준 모델 C 대비 차이.
- 행 단위 산출물은 data/processed/exp/EXP-005b/ 아래(git 제외), 보고서는 reports/experiments/EXP-005/<P?>/.
- 2026 은 계산·열람 금지(harness.guard_no_2026, 리드타임 사건은 2025-12-31 까지).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from algaecast.eval.metrics import compute_all
from algaecast.exp import confirm as CF
from algaecast.exp import harness as H
from algaecast.exp import r_combo as RC

log = logging.getLogger(__name__)

EXPLORE_SEEDS: tuple[int, ...] = (11, 22, 33, 44, 55)
FINAL_SEEDS: tuple[int, ...] = (1001, 2002, 3003, 4004, 5005)
EXP_DIR = H.EXP_DATA / "EXP-005b"
REPORT_DIR = H.EXP_REPORTS / "EXP-005"
C_NAMES: tuple[str, ...] = ("c1", "c3", "c2", "cg")
SCOPES: tuple[tuple[str, str], ...] = (
    ("cv", "CV 2020~2024"),
    ("y25", "2025 전체"),
    ("y25a", "2025 1~8월"),
    ("y25b", "2025 9~10월"),
)

# build(df, seed) -> {"pred": 원단위 점예측(2020~2025 행), "q90": 분위 q90 또는 None(→ v1 동결 q90)}
Builder = Callable[[pd.DataFrame, int], dict[str, np.ndarray]]


# ---------------------------------------------------------------- 구간 마스크
def scope_masks(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """CV(기준일 2020~2024)·2025(기준일 2025) 전체·목표일 1~8월·목표일 9~10월."""
    cv, fin = H.masks(df)
    tm = pd.to_datetime(df["target_date"]).dt.month.to_numpy()
    return {"cv": cv, "y25": fin, "y25a": fin & (tm <= 8), "y25b": fin & np.isin(tm, (9, 10))}


def v1_q90() -> np.ndarray:
    """v1 동결 분위 모델의 OOF q90(시드 42) — 분위를 바꾸지 않는 구성의 리드타임용."""
    _, base = H.load_baseline()
    return base["q90"]


# ---------------------------------------------------------------- 지표
def metric_row2(df: pd.DataFrame, pred: np.ndarray, q90: np.ndarray | None, label: str) -> dict:
    """표준 지표 한 묶음(구간 4개 + CV 폴드 평균 + 리드타임)."""
    H.guard_no_2026(df)
    pred = np.asarray(pred, dtype=float)
    obs = df["target_cells"].to_numpy(dtype=float)
    row: dict = {"구성": label}
    for key, m in scope_masks(df).items():
        ok = m & np.isfinite(pred)
        mm = compute_all(obs[ok], pred[ok])
        row[f"{key}_n"] = int(ok.sum())
        for k in H.STD_METRICS:
            row[f"{key}_{k}"] = float(mm[k])
    years = H.years_of(df)
    fold = [
        compute_all(obs[(years == y) & np.isfinite(pred)], pred[(years == y) & np.isfinite(pred)])
        for y in H.CV_YEARS
    ]
    row["cvfold_r2_raw"] = float(np.nanmean([f["r2_raw"] for f in fold]))
    q = v1_q90() if q90 is None else np.asarray(q90, dtype=float)
    lt = H.leadtime(df, (q >= H.T10K).astype(float))
    row.update({"lead_q90": lt["detected"], "lead_n": lt["n_events"]})
    return row


def mean_rows(rows: list[dict], label: str) -> dict:
    """시드별 행 → 수치 열의 시드 평균(+ 최소·최대: cv_r2_raw)."""
    t = pd.DataFrame(rows)
    out = {"구성": label, "n_seeds": len(rows)}
    for c in t.columns:
        if c in ("구성", "seed"):
            continue
        if pd.api.types.is_numeric_dtype(t[c]):
            out[c] = float(t[c].mean())
    out["cv_r2_raw_min"] = float(t["cv_r2_raw"].min())
    out["cv_r2_raw_max"] = float(t["cv_r2_raw"].max())
    return out


# ---------------------------------------------------------------- 기준 모델 C
def f2_frame(df: pd.DataFrame) -> pd.DataFrame:
    return CF.f2_frame(df)


def c_members(df: pd.DataFrame, seed: int, extra: pd.DataFrame | None = None) -> dict[str, np.ndarray]:
    """C(또는 C + 추가 피처 extra)의 회귀 구성원 c1·c3·c2·cg OOF. 속별 구성원도 같은 열로 학습한다."""
    f2 = f2_frame(df)
    ex = f2 if extra is None else pd.concat([f2, extra], axis=1)
    return CF.config_members(df, ex, seed, genus=True)


def c_pred(df: pd.DataFrame, seed: int, extra: pd.DataFrame | None = None) -> dict[str, np.ndarray]:
    """C(+extra) 점예측 = 연도 확장 NNLS(c1·c3·c2·cg). 분위는 v1 동결(q90=None)."""
    mem = c_members(df, seed, extra)
    pred, _ = H.ensemble_expanding(df, mem, names=C_NAMES)
    return {"pred": pred, "q90": None, **{f"m_{k}": mem[k] for k in C_NAMES}}


def cache_path(name: str, seed: int) -> Path:
    return EXP_DIR / "cache" / f"{name}_{seed}.parquet"


def run_cached(df: pd.DataFrame, name: str, seed: int, build: Builder) -> dict[str, np.ndarray]:
    """build 결과를 (구성 이름, 시드)로 캐시. 키 열을 대조해 행 순서를 확인한다."""
    p = cache_path(name, seed)
    if p.exists():
        o = pd.read_parquet(p)
        same = (
            len(o) == len(df)
            and (o["base_date"].astype(str).to_numpy() == df["base_date"].astype(str).to_numpy()).all()
        )
        if same:
            return {
                k: o[k].to_numpy(dtype=float)
                for k in o.columns
                if k not in ("station_id", "base_date", "target_date", "target_cells", "year")
            }
    out = build(df, seed)
    save = {
        k: (np.full(len(df), np.nan) if v is None else np.asarray(v, dtype=float)) for k, v in out.items()
    }
    H.save_oof(df, save, p)
    return {k: (None if (k == "q90" and out.get("q90") is None) else save[k]) for k in save}


def baseline_c(df: pd.DataFrame, seeds: tuple[int, ...] = EXPLORE_SEEDS) -> list[dict]:
    """기준 모델 C 의 시드별 표준 지표 행(캐시)."""
    rows = []
    for s in seeds:
        out = run_cached(df, "C", s, c_pred)
        r = metric_row2(df, out["pred"], out.get("q90"), f"C 시드 {s}")
        r["seed"] = s
        rows.append(r)
    return rows


# ---------------------------------------------------------------- 대조군
def noise_like(frame: pd.DataFrame, seed: int, salt: int = RC.CTRL_SALT) -> pd.DataFrame:
    """frame 과 같은 모양·결측 위치의 표준정규 난수(생성기 (salt, seed, 열 수)). 열 이름은 ctrl_rnd_*."""
    k = frame.shape[1]
    return RC.control_columns(frame.index, k, seed, mask=frame.notna().to_numpy(), salt=salt)


# ---------------------------------------------------------------- 실행·표
def evaluate(
    df: pd.DataFrame, name: str, build: Builder, seeds: tuple[int, ...] = EXPLORE_SEEDS
) -> tuple[list[dict], dict]:
    """구성 하나를 시드별로 평가 → (시드별 행, 시드 평균 행). build 결과는 캐시한다."""
    rows = []
    for s in seeds:
        out = run_cached(df, name, s, build)
        r = metric_row2(df, out["pred"], out.get("q90"), f"{name} 시드 {s}")
        r["seed"] = s
        rows.append(r)
    return rows, mean_rows(rows, name)


def paired_delta(rows: list[dict], base_rows: list[dict], key: str) -> float:
    """시드 짝 차이의 평균(같은 시드끼리)."""
    b = {r["seed"]: r[key] for r in base_rows}
    return float(np.mean([r[key] - b[r["seed"]] for r in rows if r["seed"] in b]))


def _f(v: object, nd: int = 3) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "–"
    return (
        f"{v:+.{nd}f}"
        if isinstance(v, float) and nd < 0
        else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))
    )


def table2(entries: list[tuple[dict, list[dict]]], base_rows: list[dict]) -> str:
    """표준 표(시드 평균): 구성마다 구간 4줄, 기준 모델 C 대비 시드 짝 차이(Δr2_raw·Δrmse_log) 포함.

    entries = [(시드 평균 행, 시드별 행), ...]. 첫 항목은 보통 C 자신.
    """
    head = (
        "| 구성 | 구간 | n | r2_raw | r2_pearson_raw | nse_raw | rmse_log | r2_log | F1@10k | ΔC r2_raw | ΔC rmse_log | 리드타임 |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    lines = []
    for mean, rows in entries:
        lead = f"{mean['lead_q90']:.1f}/{int(mean['lead_n'])}"
        for key, nm in SCOPES:
            vals = " | ".join(f"{mean[f'{key}_{k}']:.3f}" for k in H.STD_METRICS)
            dr = paired_delta(rows, base_rows, f"{key}_r2_raw")
            dm = paired_delta(rows, base_rows, f"{key}_rmse_log")
            lines.append(
                f"| {mean['구성']} | {nm} | {int(mean[f'{key}_n'])} | {vals} | {dr:+.3f} | {dm:+.4f} | {lead if key == 'cv' else '〃'} |"
            )
    return head + "\n".join(lines) + "\n"


def explore_check(
    mean: dict, rows: list[dict], base_rows: list[dict], ctrl_rows: list[dict] | None = None
) -> dict:
    """탐색용 판정(PREREG_FINAL 기준을 탐색 시드에 적용한 참고값 — 최종 판정이 아님)."""
    base = mean_rows(base_rows, "C")
    d = paired_delta(rows, base_rows, "cv_r2_raw")
    out = {
        "d_cv_r2_raw": d,
        "d_vs_ctrl": paired_delta(rows, ctrl_rows, "cv_r2_raw") if ctrl_rows else float("nan"),
        "y25_r2_raw_ok": bool(mean["y25_r2_raw"] >= base["y25_r2_raw"] - 0.02),
        "y25_rmse_ok": bool(mean["y25_rmse_log"] <= base["y25_rmse_log"] + 0.01),
        "y25_f1_ok": bool(mean["y25_f1_10k"] >= base["y25_f1_10k"] - 0.02),
        "lead_ok": bool(mean["lead_q90"] >= 18.0),
        "y25b_rmse_ok": bool(mean["y25b_rmse_log"] <= base["y25b_rmse_log"]),
    }
    out["meets_explore"] = bool(
        d >= 0.08
        and (not ctrl_rows or out["d_vs_ctrl"] >= 0.04)
        and all(out[k] for k in ("y25_r2_raw_ok", "y25_rmse_ok", "y25_f1_ok", "lead_ok", "y25b_rmse_ok"))
    )
    return out


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")


def main() -> int:
    """기준 모델 C 의 탐색 시드 결과를 만들어 캐시하고 표를 쓴다(reports/experiments/EXP-005/BASE_C.md)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    df = H.load_base()
    rows = baseline_c(df)
    mean = mean_rows(rows, "C(기준 모델)")
    _, v1base = H.load_baseline()
    v1row = metric_row2(df, v1base["ens"], v1base["q90"], "v1 동결(시드 42, 참고)")
    v1row["seed"] = -1
    txt = "# 2차 기준 모델 C — 탐색 시드 결과\n\n" f"시드 {list(EXPLORE_SEEDS)} 평균. 구간은 목표일 기준(2025 1~8월 = 옛 채수 위치, 9~10월 = 새 위치). 분위는 v1 동결 q90.\n\n" + table2(
        [(mean, rows)], rows
    ) + "\n참고 — v1 동결(시드 42):\n\n" + table2(
        [(mean_rows([v1row], "v1 동결(시드 42)"), [v1row])], [v1row]
    )
    (REPORT_DIR / "BASE_C.md").write_text(txt, encoding="utf-8")
    write_json(REPORT_DIR / "base_c_metrics.json", {"seed_rows": rows, "mean": mean, "v1_seed42": v1row})
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
