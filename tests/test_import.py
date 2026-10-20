"""T0-a 스모크 테스트: 패키지 임포트·시드·디렉터리 골격."""

from pathlib import Path

import algaecast
from algaecast import config


def test_package_importable() -> None:
    assert algaecast.__version__


def test_seed_is_42() -> None:
    assert config.load_seed() == 42
    assert config.set_global_seed() == 42


def test_repo_skeleton_exists() -> None:
    root: Path = config.ROOT
    for rel in [
        "CLAUDE.md",
        "Makefile",
        "requirements.txt",
        ".env.example",
        ".gitignore",
        "config/seed.yaml",
    ]:
        assert (root / rel).exists(), rel
    for rel in ["data/raw", "data/interim", "data/processed"]:
        assert (root / rel / ".gitkeep").exists(), rel


PUBLIC_URL_VARS = {"SUPABASE_URL"}


def test_env_example_has_no_secret_values() -> None:
    """공개 엔드포인트(API_*, SUPABASE_URL)만 값을 가질 수 있고 나머지는 비어 있어야 한다."""
    text = (config.ROOT / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key.startswith("API_") or key in PUBLIC_URL_VARS:
            assert value == "" or value.startswith("https://"), f"{key}: 공개 URL 만 허용"
        else:
            assert value == "", f"{key} 에 값이 들어있음 — 예시 파일에는 비워둘 것"
