"""조류경보제 측정(예측 대상 5지점) 원천 선택 — 대회 번들 또는 공공 API 스냅샷.

- 저장소 구조: 공공데이터포털 조류경보 API 스냅샷 ``data/raw/nier_algae/nier_algae_2012_2026.parquet``
  (기존 동작 그대로).
- 제출 패키지 구조(``config.PACKAGE_LAYOUT``): 대회 번들 ``algae_measure.csv``(``competition.load_algae``)를
  API parquet 과 같은 열 이름·형식으로 바꿔 쓴다. 번들에 없는 수집기 파생열(cells_sum4·cells_consistent·
  alert_level_single·alert_level_2consec·alert_name_2consec)은 수집기(``collect/nier_algae.tidy``)와
  같은 규칙으로 계산한다.
  겹치는 측정의 값은 같고, API 에만 있는 2026-09-14 이후 측정은 학습·제출 피처에 들어가지 않는다
  (reports/experiments/PREREG_contingency.md 6.0~6.3절).
- ``config/features.yaml`` 의 ``algae_source``: auto(기본, 위 규칙) | bundle | api.
- 대시보드 일일 운영(GitHub Actions, 저장소 구조)은 지금처럼 API 를 쓴다: predict.asof 는 수집한 API 자료를
  직접 넘기고, 자료를 넘기지 않는 호출도 저장소 구조라 auto → api 다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

from algaecast.collect import competition as comp
from algaecast.collect import nier_algae as na
from algaecast.config import CONFIG_DIR, PACKAGE_LAYOUT, RAW_DIR

API_PARQUET: Path = RAW_DIR / "nier_algae" / "nier_algae_2012_2026.parquet"
SOURCES: tuple[str, ...] = ("auto", "bundle", "api")
SOURCE_PATHS: dict[str, str] = {  # 메타데이터 표기용(저장소 기준 상대 경로)
    "api": "data/raw/nier_algae/nier_algae_2012_2026.parquet",
    "bundle": "data/raw/competition/algae_contest_2026/algae_measure.csv",
}
DERIVED_COLS: list[str] = [
    "cells_sum4",
    "cells_consistent",
    "alert_level_single",
    "alert_level_2consec",
    "alert_name_2consec",
]
# API parquet(수집기 tidy 출력)의 열 순서
API_COLUMNS: list[str] = [
    *na.FIELDS.values(),
    "station_id",
    *(f"{c}_below_loq" for c in na.LOQ_COLS),
    *(f"{c}_pending" for c in na.PENDING_COLS),
    "cells_sum4",
    "cells_consistent",
    "dominant_genus",
    "alert_level_single",
    "alert_level_2consec",
    "alert_name_2consec",
    "source",
    "fetched_at",
]
CONSISTENCY_TOL = 0.5  # 4속 합과 총합의 허용 차(수집기 tidy 와 같음)


@lru_cache(maxsize=1)
def configured_source() -> str:
    """config/features.yaml 의 algae_source(없으면 auto)."""
    cfg = yaml.safe_load((CONFIG_DIR / "features.yaml").read_text(encoding="utf-8")) or {}
    return str(cfg.get("algae_source", "auto") or "auto")


def resolve_source(setting: str | None = None, *, package_layout: bool = PACKAGE_LAYOUT) -> str:
    """원천 설정 → 'bundle' | 'api'. auto 는 패키지 구조면 bundle, 저장소 구조면 api."""
    s = configured_source() if setting is None else setting
    if s not in SOURCES:
        raise ValueError(f"algae_source 는 {SOURCES} 중 하나여야 한다: {s!r}")
    if s == "auto":
        return "bundle" if package_layout else "api"
    return s


def add_collector_derived(df: pd.DataFrame) -> pd.DataFrame:
    """수집기 파생열 5개를 붙인 사본.

    행은 (site_code, obs_date) 정렬이어야 한다(2회 연속 규칙이 측정 순서에 의존).
    """
    d = df.copy()
    d["cells_sum4"] = d[list(na.GENUS)].sum(axis=1, min_count=1)
    both = d["iem_bgalage_cell_co"].notna() & d["cells_sum4"].notna()
    d["cells_consistent"] = pd.Series(pd.NA, index=d.index, dtype="boolean")
    diff = (d.loc[both, "iem_bgalage_cell_co"] - d.loc[both, "cells_sum4"]).abs()
    d.loc[both, "cells_consistent"] = diff <= CONSISTENCY_TOL
    d["alert_level_single"] = na.single_level(d["iem_bgalage_cell_co"])
    d["alert_level_2consec"] = (
        d.groupby("site_code", group_keys=False)["alert_level_single"]
        .apply(na.two_consecutive_levels)
        .astype("Int64")
    )
    d["alert_name_2consec"] = d["alert_level_2consec"].map(na.ALERT_NAMES)
    return d


def bundle_as_api() -> pd.DataFrame:
    """대회 번들 algae_measure.csv → API parquet 과 같은 열 이름·순서·형식(source = competition_bundle)."""
    b = comp.load_algae().sort_values(["site_code", "obs_date"], ignore_index=True)
    b = add_collector_derived(b)
    b["fetched_at"] = b["fetched_at"].astype("datetime64[ns, Asia/Seoul]")  # API parquet 과 같은 해상도
    return b[API_COLUMNS].reset_index(drop=True)


def load_algae_source(columns: list[str] | None = None, source: str | None = None) -> pd.DataFrame:
    """예측 대상 5지점 조류 측정(API parquet 형식). columns 가 있으면 그 열만 그 순서로 돌려준다."""
    src = resolve_source(source)
    if src == "api":
        return pd.read_parquet(API_PARQUET, columns=columns)
    df = bundle_as_api()
    return df if columns is None else df[list(columns)].copy()


def source_path(source: str | None = None) -> str:
    """현재 원천 파일의 상대 경로(메타데이터 표기용)."""
    return SOURCE_PATHS[resolve_source(source)]
