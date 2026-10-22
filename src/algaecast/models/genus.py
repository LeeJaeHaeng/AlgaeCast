"""속별 구성원 cg(운영 v2) — 유해남조류 합계를 Microcystis + 나머지 3속(G2)으로 나눠
부분별 log 회귀 후 원단위로 합산한다.

EXP-006(R3) 선택 설정(layout g2, 부분별 log, Duan smearing, 속별 자기회귀 피처 없음)을
운영용으로 옮긴 모듈이다.
- 부분 타깃: 표본의 목표일(target_date)과 같은 날 조류경보제 원자료의 속별 세포수
  (Microcystis = iem_bgalage_microsts, 나머지 = Anabaena + Aphanizomenon + Oscillatoria 합,
  하나라도 결측이면 제외).
  4속 합이 표본 타깃(target_cells)과 0.5 넘게 다르면 그 행의 속별 타깃을 비운다
  (R3.genus_targets 와 같은 규칙).
- 부분 모델: C1 설정(log10 타깃, 가중 w = 1 + α·log10(y+1), v1 하이퍼파라미터),
  역변환 10^ŷ−1 에 smearing 계수.
- 예측: 부분별 clip(10^ŷ−1, 0)·smear 를 원단위로 더한다.

2026 규칙: 속별 타깃은 목표일 ≤ 2025-12-31 측정만 쓴다. 원자료는 읽은 즉시 2025-12-31 이후 측정을 버리고,
목표일이 그 이후인 표본이 들어오면 중단한다.
2026 정답 격리 파일(data/processed 의 격리 parquet)은 읽지 않는다.
"""

from __future__ import annotations

from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from algaecast.config import RAW_DIR
from algaecast.models import data as D
from algaecast.models.train import SEED, VariantSpec, _lgb_params, _prep, to_cells

ALGAE_PARQUET: Path = RAW_DIR / "nier_algae" / "nier_algae_2012_2026.parquet"
TARGET_LAST = pd.Timestamp("2025-12-31")  # 속별 타깃(목표일 측정)의 마지막 허용일
TOTAL_COL = "iem_bgalage_cell_co"
GENUS: dict[str, str] = {
    "micro": "iem_bgalage_microsts",
    "anba": "iem_bgalage_anba",
    "apzo": "iem_bgalage_apzo",
    "osc": "iem_bgalage_osrtria",
}
PARTS: dict[str, tuple[str, ...]] = {"micro": ("micro",), "rest": ("anba", "apzo", "osc")}
LAYOUT: tuple[str, ...] = ("micro", "rest")  # G2
CONSISTENCY_TOL = 0.5


# ---------------------------------------------------------------- 타깃
def load_target_algae(path: Path = ALGAE_PARQUET, last: pd.Timestamp = TARGET_LAST) -> pd.DataFrame:
    """속별 타깃용 조류 원자료(총합·4속). last(2025-12-31) 이후 측정은 읽은 즉시 버린다."""
    a = pd.read_parquet(path, columns=["station_id", "obs_date", TOTAL_COL, *GENUS.values()])
    a["obs_date"] = pd.to_datetime(a["obs_date"])
    a = a[a["obs_date"] <= last]
    return a.sort_values(["station_id", "obs_date"]).reset_index(drop=True)


def guard_targets(df: pd.DataFrame, last: pd.Timestamp = TARGET_LAST) -> None:
    """목표일·기준일이 last 이후인 행(2026 정답에 해당)이나 test 분할이 섞이면 중단한다."""
    for col in ("base_date", "target_date"):
        d = pd.to_datetime(df[col])
        if (d > last).any():
            raise RuntimeError(f"{col} > {last.date()} 인 행 {int((d > last).sum())}개 — 속별 타깃 계산 금지")
    if "split" in df.columns and (df["split"] == "test").any():
        raise RuntimeError("test 분할 행이 속별 타깃 프레임에 섞임")


def genus_targets(df: pd.DataFrame, algae: pd.DataFrame | None = None) -> pd.DataFrame:
    """표본의 target_date 와 같은 날 측정에서 4속 타깃을 붙인다(같은 인덱스).

    열: y_<속>(원단위, 없으면 NaN), y_sum4, consistent(|y_sum4 − target_cells| ≤ 0.5; 4속 결측이면 NA).
    불일치 행의 속별 타깃은 NaN 으로 비운다.
    """
    guard_targets(df)
    algae = load_target_algae() if algae is None else algae
    if (pd.to_datetime(algae["obs_date"]) > TARGET_LAST).any():
        raise RuntimeError("속별 타깃 원자료에 2025-12-31 이후 측정이 있다 — load_target_algae 로 읽을 것")
    key = pd.DataFrame(
        {"station_id": df["station_id"].astype(str).to_numpy(), "obs_date": pd.to_datetime(df["target_date"])}
    )
    a = algae.drop_duplicates(["station_id", "obs_date"], keep="last")
    m = key.merge(a, on=["station_id", "obs_date"], how="left")
    out = pd.DataFrame(index=df.index)
    for g, col in GENUS.items():
        out[f"y_{g}"] = m[col].to_numpy(dtype=float)
    out["y_sum4"] = out[[f"y_{g}" for g in GENUS]].sum(axis=1, skipna=False)
    tgt = df["target_cells"].to_numpy(dtype=float)
    has = out["y_sum4"].notna().to_numpy()
    cons = pd.Series(pd.NA, index=df.index, dtype="boolean")
    cons[has] = np.abs(out["y_sum4"].to_numpy()[has] - tgt[has]) <= CONSISTENCY_TOL
    out["consistent"] = cons
    bad = cons.eq(False).to_numpy(dtype=bool, na_value=False)
    if bad.any():
        out.loc[bad, [f"y_{g}" for g in GENUS]] = np.nan
    return out


def part_target(tg: pd.DataFrame, part: str) -> np.ndarray:
    """부분(micro 또는 rest) 타깃 원단위. 구성 속 중 하나라도 결측이면 NaN."""
    return tg[[f"y_{g}" for g in PARTS[part]]].sum(axis=1, skipna=False).to_numpy(dtype=float)


def part_frame(df: pd.DataFrame, y: np.ndarray) -> pd.DataFrame:
    """부분 타깃이 있는 행만, target_cells·target_log 를 부분 타깃으로 바꾼 복사본(행 순서 유지)."""
    ok = np.isfinite(y)
    tr = df.iloc[np.where(ok)[0]].copy()
    tr["target_cells"] = y[ok]
    tr["target_log"] = np.log10(y[ok] + 1)
    return tr


# ---------------------------------------------------------------- 부분 모델
def fit_log_part(tr: pd.DataFrame, cols: list[str], spec: VariantSpec, seed: int = SEED) -> dict:
    """C1 설정 log 회귀 1개(train.fit_predict 의 log_w 분기와 같은 적합). 반환 {model, smear, categories}."""
    _, cats = D.numeric_and_categorical(cols)
    Xt = _prep(tr[cols], cats)
    ylog = tr["target_log"].to_numpy(dtype=float)
    m = lgb.LGBMRegressor(**_lgb_params(spec.params, seed, objective="regression"))
    m.fit(Xt, ylog, sample_weight=1.0 + spec.alpha * ylog, categorical_feature=cats or "auto")
    smear = float(np.mean(10 ** (ylog - m.predict(Xt))))
    return {
        "kind": "log_w",
        "model": m,
        "smear": smear,
        "cats": cats,
        "categories": {c: list(Xt[c].cat.categories) for c in cats},
    }


def fit_genus(
    train: pd.DataFrame,
    cols: list[str],
    spec: VariantSpec,
    seed: int = SEED,
    algae: pd.DataFrame | None = None,
) -> dict:
    """G2 부분 모델 2개를 train 행으로 적합. 반환 {"kind": "genus", "parts": {부분: log 회귀 dict}}."""
    tg = genus_targets(train, algae)
    parts = {p: fit_log_part(part_frame(train, part_target(tg, p)), cols, spec, seed) for p in LAYOUT}
    return {"kind": "genus", "layout": list(LAYOUT), "parts": parts}


def prep_x(feat: pd.DataFrame, cols: list[str], cats: list[str], categories: dict) -> pd.DataFrame:
    """예측 입력: cols 열만, 범주 열은 학습 때 범주 목록으로 고정(train._prep(ref=...) 과 같음)."""
    X = feat[cols].copy()
    for c in cats:
        X[c] = pd.Categorical(X[c].astype(str), categories=categories[c])
    return X


def predict_log_part(part: dict, feat: pd.DataFrame, cols: list[str]) -> np.ndarray:
    """부분 log 회귀의 원단위 예측(smearing 적용, NaN→0, 음수→0)."""
    X = prep_x(feat, cols, part["cats"], part["categories"])
    raw = to_cells(np.asarray(part["model"].predict(X), dtype=float)) * part["smear"]
    return np.clip(np.nan_to_num(raw, nan=0.0), 0, None)


def predict_genus(obj: dict, feat: pd.DataFrame, cols: list[str]) -> np.ndarray:
    """속별 합산 cg(원단위) = 부분 예측의 합."""
    return np.sum([predict_log_part(obj["parts"][p], feat, cols) for p in obj["layout"]], axis=0)
