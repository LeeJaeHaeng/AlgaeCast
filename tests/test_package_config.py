"""제출 패키지에 설정 파일이 빠지지 않는다 — config/ 의 모든 파일이 빌더 CONFIG_FILES 에 있어야 한다.

2026-10-23 FIX-v2.1 에서 새 설정 파일(derived_constants.json)을 빌더 목록에 넣지 않아 패키지 노트북의 피처 생성이
FileNotFoundError 로 멈춘 일이 있었다(녹화 중 발견). 새 설정 파일을 만들면 이 테스트가 빌더 목록 갱신을 강제한다.
"""

from __future__ import annotations

import importlib.util

from algaecast.config import ROOT


def _builder():  # noqa: ANN202 — 스크립트 모듈을 파일 경로로 불러온다
    spec = importlib.util.spec_from_file_location(
        "build_pkg", ROOT / "scripts" / "build_submission_package.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_all_config_files_are_packaged() -> None:
    files = sorted(p.name for p in (ROOT / "config").iterdir() if p.is_file())
    missing = [f for f in files if f not in _builder().CONFIG_FILES]
    assert not missing, f"빌더 CONFIG_FILES 에 없는 설정 파일: {missing}"


def test_posthoc_modules_are_not_packaged() -> None:
    skip = _builder().SRC_SKIP_FILES
    posthoc = sorted(p.name for p in (ROOT / "src" / "algaecast" / "eval").glob("posthoc*.py"))
    assert posthoc and all(f in skip for f in posthoc), f"사후 계산 모듈은 패키지에서 빼야 한다: {posthoc}"
