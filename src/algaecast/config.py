"""프로젝트 공통 설정: 경로, 시드, 환경변수(.env) 로더."""

from __future__ import annotations

import os
import random
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml
from dotenv import load_dotenv

ROOT: Path = Path(__file__).resolve().parents[2]
# 제출 패키지(공지 #564 구조: README.md·data/·model/·src/·notebooks/·scripts/·demo/·figures/)에서는
# 설정 src/config/, 동결 모델 model/, 표·보고서 figures/reports/, 제출 파일 루트 submission.csv.
# 저장소에서는 기존 경로(config/, models/, reports/, submission/submission.csv)를 그대로 쓴다.
PACKAGE_LAYOUT: bool = (ROOT / "src" / "config").is_dir() and not (ROOT / "config").is_dir()
CONFIG_DIR: Path = ROOT / "src" / "config" if PACKAGE_LAYOUT else ROOT / "config"
MODELS_DIR: Path = ROOT / "model" if PACKAGE_LAYOUT else ROOT / "models"
REPORTS_DIR: Path = ROOT / "figures" / "reports" if PACKAGE_LAYOUT else ROOT / "reports"
SUBMISSION_PATH: Path = ROOT / "submission.csv" if PACKAGE_LAYOUT else ROOT / "submission" / "submission.csv"
DATA_DIR: Path = ROOT / "data"
RAW_DIR: Path = DATA_DIR / "raw"
INTERIM_DIR: Path = DATA_DIR / "interim"
PROCESSED_DIR: Path = DATA_DIR / "processed"


@lru_cache(maxsize=1)
def load_seed() -> int:
    """`config/seed.yaml`의 시드(기본 42)를 반환한다. 모든 난수는 이 값을 쓴다."""
    with (CONFIG_DIR / "seed.yaml").open(encoding="utf-8") as f:
        return int(yaml.safe_load(f)["seed"])


def set_global_seed(seed: int | None = None) -> int:
    """random / numpy 전역 시드를 고정하고 사용한 시드를 반환한다.

    PYTHONHASHSEED 는 인터프리터 시작 전에만 유효하므로 여기서 건드리지 않는다
    (필요 시 Makefile/CI 환경변수로 고정). lightgbm/catboost/optuna 는 각 호출부에서 이 값을 넘긴다.
    """
    s = load_seed() if seed is None else seed
    random.seed(s)
    np.random.seed(s)
    return s


def load_env() -> None:
    """저장소 루트의 `.env`를 읽는다(이미 설정된 OS 환경변수는 덮어쓰지 않음)."""
    load_dotenv(ROOT / ".env", override=False)


def get_env(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    """환경변수를 읽는다. `required=True`인데 없으면 RuntimeError."""
    load_env()
    value = os.getenv(name, default)
    if required and not value:
        msg = f"환경변수 {name} 이(가) 설정되지 않았습니다. .env.example 을 참고해 .env 를 작성하세요."
        raise RuntimeError(msg)
    return value
