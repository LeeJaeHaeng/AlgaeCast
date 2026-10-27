"""문서자료 zip(공지 2026-10-27 제출란 ① 문서자료) — 최상위 폴더 하나, 파일명 UTF-8 플래그, 짝 sha256.

A안 = 방법설명서.pdf + 읽어보기.txt(모델자료 영상 포함과 짝), B안 = A안 + demo/ 영상·README_DEMO(모델자료 영상제외와 짝).
가짜 패키지·가짜 모델자료 zip 으로 make_doc_zips 를 돌려 구성만 확인한다(실제 빌드는 build_submission_package.py).
"""

from __future__ import annotations

import hashlib
import importlib.util
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

from algaecast.config import ROOT


def _builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_submission_package", ROOT / "scripts" / "build_submission_package.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _fake(tmp: Path, b: ModuleType) -> tuple[Path, Path]:
    out = tmp / "pkg"
    (out / "demo").mkdir(parents=True)
    (out / "방법설명서.pdf").write_bytes(b"%PDF-1.4 fake")
    (out / "demo" / "AlgaeCast_demo.mp4").write_bytes(b"fake mp4")
    (out / "demo" / "README_DEMO.md").write_text("# demo", encoding="utf-8")
    dist = tmp / "dist"
    dist.mkdir()
    for name in (b.ZIP_NAME, b.ZIP_NOVIDEO):
        (dist / name).write_bytes(name.encode("utf-8"))
    return out, dist


def test_doc_zips_layout(tmp_path: Path) -> None:
    b = _builder()
    out, dist = _fake(tmp_path, b)
    b.make_doc_zips(out, dist)
    expect = {
        b.ZIP_DOC: ({"방법설명서.pdf", "읽어보기.txt"}, b.ZIP_NAME),
        b.ZIP_DOC_VIDEO: (
            {"방법설명서.pdf", "읽어보기.txt", "demo/AlgaeCast_demo.mp4", "demo/README_DEMO.md"},
            b.ZIP_NOVIDEO,
        ),
    }
    for name, (files, pair) in expect.items():
        with zipfile.ZipFile(dist / name) as z:
            infos = z.infolist()
            tops = {i.filename.split("/")[0] for i in infos}
            assert tops == {b.DOC_PKG}, f"{name}: 최상위 폴더가 하나가 아니다 {tops}"
            assert {i.filename.split("/", 1)[1] for i in infos} == files
            assert all(i.flag_bits & 0x800 for i in infos if not i.filename.isascii()), "UTF-8 플래그 없음"
            raw = z.read(f"{b.DOC_PKG}/읽어보기.txt")
            assert raw.startswith(b"\xef\xbb\xbf"), "읽어보기에 BOM 이 없다(메모장 호환)"
            assert b"\n" not in raw.replace(b"\r\n", b""), "읽어보기 줄바꿈이 CRLF 가 아니다"
            text = raw.decode("utf-8-sig")
            assert z.read(f"{b.DOC_PKG}/방법설명서.pdf") == (out / "방법설명서.pdf").read_bytes()
        pair_sha = hashlib.sha256((dist / pair).read_bytes()).hexdigest()
        assert pair in text and pair_sha in text, f"{name}: 짝 모델자료 이름·sha256 이 읽어보기에 없다"
        assert hashlib.sha256((out / "방법설명서.pdf").read_bytes()).hexdigest() in text
        assert "AlgaeCast_demo.mp4" in text, f"{name}: 데모 영상 위치 안내가 없다"
        assert b.DASHBOARD_URL in text
        assert all(f"?asof={asof}" in text for asof, _ in b.REPLAY_SCENES)


def test_doc_zips_need_pair(tmp_path: Path) -> None:
    """짝이 되는 모델자료 zip 이 없으면 문서자료 zip 을 만들지 않는다(읽어보기의 sha256 이 비게 되므로)."""
    b = _builder()
    out, dist = _fake(tmp_path, b)
    (dist / b.ZIP_NOVIDEO).unlink()
    with pytest.raises(SystemExit):
        b.make_doc_zips(out, dist)


def test_replay_scenes_match_web() -> None:
    """읽어보기의 다시 보기 날짜가 웹 장면 정의(web/src/lib/replay.ts SCENES)와 같아야 한다."""
    src = (ROOT / "web" / "src" / "lib" / "replay.ts").read_text(encoding="utf-8")
    for asof, _ in _builder().REPLAY_SCENES:
        assert f'asof: "{asof}"' in src, asof
