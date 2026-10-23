"""학습·튜닝·앙상블 공통 데이터 로더 — **train/valid 만** 반환하고 test 타깃은 절대 반환하지 않는다.

- 피처 파일 ``data/processed/features_<S>.parquet`` 의 test 행 타깃은 features/run 이 이미 NaN 으로 비웠고,
  원값은 별도 격리 파일에 있다(사후 검증은 eval 패키지의 명시적 로더만).
- ``load_train_valid``: splits.json 의 train/valid (site, base_date) 만 로드.
- ``load_test_features``: test 행의 **피처만** (타깃 컬럼 제거) — 제출 예측용.
- ``feature_columns``: config/features.yaml ``selected`` (T3-c 확정) 또는 전체 수치·범주 피처.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from algaecast.config import CONFIG_DIR, DATA_DIR

PROCESSED = DATA_DIR / "processed"
META_COLS = [
    "station_id", "site_code", "base_date", "target_date",
    "horizon_days", "target_cells", "target_log", "split",
]  # fmt: skip
TARGET_COLS = ("target_cells", "target_log")
CAT_COLS = ["dominant_genus", "site_code", "station_id", "basin", "facility_type"]
FORBIDDEN_SPLITS = ("test",)


def _features_path(strategy: str) -> Path:
    """features_<전략>.parquet — as_of 오프셋(S 모델)이 0 이 아니면 이름에 오프셋이 붙는다."""
    from algaecast.features.offset import features_file

    return features_file(strategy, PROCESSED)


def _split_key(strategy: str) -> str:
    from algaecast.features.offset import file_suffix

    return f"{strategy}{file_suffix()}"


def _read(strategy: str) -> pd.DataFrame:
    df = pd.read_parquet(_features_path(strategy))
    df["base_date"] = pd.to_datetime(df["base_date"]).dt.date
    df["target_date"] = pd.to_datetime(df["target_date"]).dt.date
    return df


def load_splits() -> dict:
    return json.loads((PROCESSED / "splits.json").read_text(encoding="utf-8"))


def load_train_valid(strategy: str = "S1", *, drop_missing_target: bool = True) -> pd.DataFrame:
    """train(≤2024)·valid(2025) 샘플만. test 행은 어떤 경우에도 포함하지 않는다."""
    df = _read(strategy)
    sp = load_splits().get(_split_key(strategy), {})
    keys = {(s, b) for part in ("train", "valid") for s, b, _ in sp.get(part, [])}
    key = list(zip(df["station_id"], df["base_date"].astype(str), strict=True))
    out = df[[k in keys for k in key] if keys else df["split"].isin(["train", "valid"])].copy()
    out = out[~out["split"].isin(FORBIDDEN_SPLITS)]
    if drop_missing_target:
        out = out[out["target_log"].notna()]
    assert not (out["split"] == "test").any(), "test 행이 학습 로더에 섞임"
    return out.reset_index(drop=True)


def load_test_features(strategy: str = "S1") -> pd.DataFrame:
    """제출용 test 행의 피처만 (타깃 컬럼은 아예 제거)."""
    df = _read(strategy)
    out = df[df["split"] == "test"].drop(columns=list(TARGET_COLS)).reset_index(drop=True)
    return out


def feature_columns(df: pd.DataFrame, *, selected_only: bool = True) -> list[str]:
    cfg = yaml.safe_load((CONFIG_DIR / "features.yaml").read_text(encoding="utf-8"))
    sel = cfg.get("selected")
    if selected_only and sel:
        return [c for c in sel if c in df.columns]
    return [c for c in df.columns if c not in META_COLS] + ["horizon_days"]


def numeric_and_categorical(cols: list[str]) -> tuple[list[str], list[str]]:
    cats = [c for c in cols if c in CAT_COLS]
    nums = [c for c in cols if c not in CAT_COLS]
    return nums, cats
