"""제출 패키지 구성 — 설정 파일 누락 방지, 사후 계산 모듈 제외, model/ 허용 모델 폴더.

2026-10-23 FIX-v2.1 에서 새 설정 파일(derived_constants.json)을 빌더 목록에 넣지 않아 패키지 노트북의 피처 생성이
FileNotFoundError 로 멈춘 일이 있었다(녹화 중 발견). 새 설정 파일을 만들면 이 테스트가 빌더 목록 갱신을 강제한다.

model/ 에는 재현에 실제로 불러오는 모델 폴더만 넣는다(2026-10-23 추적: registry current 3개). 빌더와 verify_package 의
허용 목록이 같아야 하고, 뺀 동결 폴더(이력)는 models/HISTORY.md 에 sha256 이 있어야 한다.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from algaecast.config import ROOT


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _builder() -> ModuleType:  # 스크립트 모듈을 파일 경로로 불러온다
    return _load("build_submission_package")


def test_all_config_files_are_packaged() -> None:
    files = sorted(p.name for p in (ROOT / "config").iterdir() if p.is_file())
    missing = [f for f in files if f not in _builder().CONFIG_FILES]
    assert not missing, f"빌더 CONFIG_FILES 에 없는 설정 파일: {missing}"


def test_posthoc_modules_are_not_packaged() -> None:
    skip = _builder().SRC_SKIP_FILES
    posthoc = sorted(p.name for p in (ROOT / "src" / "algaecast" / "eval").glob("posthoc*.py"))
    assert posthoc and all(f in skip for f in posthoc), f"사후 계산 모듈은 패키지에서 빼야 한다: {posthoc}"


def test_package_model_dirs_same_in_builder_and_verifier() -> None:
    b, v = _builder(), _load("verify_package")
    assert tuple(b.PACKAGE_MODEL_DIRS) == tuple(v.PACKAGE_MODEL_DIRS)
    reg = json.loads((ROOT / "models" / "registry.json").read_text(encoding="utf-8"))
    current = {f"{n}/{ver}" for n, ver in reg["current"].items()}
    assert current == set(b.PACKAGE_MODEL_DIRS), "허용 목록은 registry current(제출·운영 모델)와 같아야 한다"


def test_history_doc_covers_excluded_models() -> None:
    """빼는 동결 폴더마다 HISTORY.md 에 model.pkl(동결 문서 해시)·저장소 파일별 sha256 이 있다.

    CI 처럼 model.pkl 이 없는 체크아웃에서는 '…/model.pkl 없음' 만 무시한다(meta.json·동결 문서 해시 대조는 그대로).
    """
    problems = [p for p in _builder().model_dir_problems() if not p.endswith("/model.pkl 없음")]
    assert not problems, problems


def test_verify_package_model_dir_check(tmp_path: Path) -> None:
    v = _load("verify_package")
    md = tmp_path / "model"
    for d in v.PACKAGE_MODEL_DIRS:
        (md / d).mkdir(parents=True)
        for f in v.MODEL_FILES:
            (md / d / f).write_bytes(b"x")
    (md / "HISTORY.md").write_text("# 이력\n", encoding="utf-8")
    assert v.model_dir_problems(tmp_path) == []
    (md / "regression" / "20261021_091108").mkdir()  # 목록 밖 폴더(이력)
    (md / v.PACKAGE_MODEL_DIRS[1] / "meta.json").unlink()  # 필수 파일 누락
    problems = v.model_dir_problems(tmp_path)
    assert any("목록 밖 모델 폴더: model/regression/20261021_091108" in p for p in problems)
    assert any(f"model/{v.PACKAGE_MODEL_DIRS[1]}/meta.json" in p for p in problems)
    (md / "HISTORY.md").unlink()
    assert any("HISTORY.md" in p for p in v.model_dir_problems(tmp_path))
