"""피처 as_of 오프셋 — 비상용 S 모델(reports/experiments/PREREG_contingency.md 3절).

`config/features.yaml` 의 `as_of_offset_days`(기본 0)만큼 모든 자료의 as_of 를 기준일보다 앞당긴다.
0 이면 v2.1 과 같다(as_of = base_date). 1 이면 S 모델(as_of = base_date − 1일, 기준일 당일 측정 미사용).
달력·지점 상수 피처(월·연중일·지점 정보)는 자료가 아니므로 기준일 그대로 계산한다.
오프셋이 0 이 아니면 피처 파일 이름에 오프셋을 붙여 v2.1 캐시와 섞이지 않게 한다.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import yaml

from algaecast.config import CONFIG_DIR, DATA_DIR

PROCESSED = DATA_DIR / "processed"


@lru_cache(maxsize=1)
def as_of_offset_days() -> int:
    """config/features.yaml 의 as_of_offset_days(없으면 0)."""
    cfg = yaml.safe_load((CONFIG_DIR / "features.yaml").read_text(encoding="utf-8")) or {}
    off = int(cfg.get("as_of_offset_days", 0) or 0)
    if off < 0:
        raise ValueError("as_of_offset_days 는 0 이상이어야 한다")
    return off


def data_as_of(base: date) -> date:
    """자료의 as_of = 기준일 − 오프셋."""
    return base - timedelta(days=as_of_offset_days())


def file_suffix() -> str:
    off = as_of_offset_days()
    return "" if off == 0 else f"_asofm{off}"


def features_file(strategy: str, processed: Path = PROCESSED) -> Path:
    """data/processed/features_<전략>[_asofm<오프셋>].parquet"""
    return processed / f"features_{strategy}{file_suffix()}.parquet"


def require_zero(what: str) -> None:
    """오프셋 0 에서만 의미가 있는 작업(가공 피처 내보내기·원자료 없는 패키지 모드 등)을 막는다."""
    if as_of_offset_days() != 0:
        raise SystemExit(f"{what} 는 as_of_offset_days = 0 에서만 지원한다(현재 {as_of_offset_days()}).")
