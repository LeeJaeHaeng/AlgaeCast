"""동결 모델 검증 — models/FROZEN.md(v1)·FROZEN_v2.md·FROZEN_v2.1.md(있으면)의 sha256 을 현재 파일과 대조한다.

- 각 동결 문서 표의 행 `| name | version | `sha256` | ...` 마다
  <models>/<name>/<version>/model.pkl 의 sha256 을 비교한다.
- 필수(제출·운영 모델) = 가장 최근 동결 문서(FROZEN_v2.1.md → FROZEN_v2.md → FROZEN.md 순으로 있는 것)의
  이름별 첫 행과 registry.json current. 파일이 있고 해시가 맞아야 한다.
- 이력 = 그 밖의 행(v1·v2·v1-fix). 저장소(models/)에서는 필수와 똑같이 파일이 있고 해시가 맞아야 한다.
  제출 패키지(model/)처럼 이력 모델 파일을 빼고 HISTORY.md 에 sha256 을 적어 둔 곳에서는, 파일이 없을 때
  HISTORY.md 의 model.pkl sha256 이 동결 문서와 같으면 '패키지 미포함(이력, model/HISTORY.md)'으로
  표시하고 통과한다(파일이 있으면 해시를 검증한다).
- registry.json 의 current 가 가장 최근 동결 문서의 버전(이름별 첫 행)과 같은지도
  확인한다(일일 예측·제출 파일이 동결 버전으로 만들어지는지).
- 하나라도 다르거나 필수 파일이 없으면 종료 코드 1.
사용: python scripts/verify_frozen.py [--models-dir DIR]   (DIR 기본: models/, 제출 패키지: model/)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from algaecast.config import MODELS_DIR, PACKAGE_LAYOUT

DOCS: tuple[str, ...] = ("FROZEN.md", "FROZEN_v2.md", "FROZEN_v2.1.md")  # 오래된 것 → 최근
ROW = re.compile(r"\| (\w+) \| (\d+_\d+) \| `([0-9a-f]{64})` \|")
HISTORY_DOC = "HISTORY.md"
# HISTORY.md 파일 표의 model.pkl 행: | `regression/20261021_091108/model.pkl` | `sha256` | bytes |
HISTORY_ROW = re.compile(r"\| `(\w+)/(\d+_\d+)/model\.pkl` \| `([0-9a-f]{64})` \|")
NOT_PACKAGED = "패키지 미포함(이력, model/HISTORY.md)"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def doc_rows(path: Path) -> list[tuple[str, str, str]]:
    """동결 문서의 (name, version, sha256) 행."""
    return ROW.findall(path.read_text(encoding="utf-8"))


def history_rows(models_dir: Path) -> dict[tuple[str, str], str]:
    """HISTORY.md 의 {(name, version): model.pkl sha256}. 문서가 없으면 빈 dict."""
    p = models_dir / HISTORY_DOC
    if not p.exists():
        return {}
    return {(n, v): h for n, v, h in HISTORY_ROW.findall(p.read_text(encoding="utf-8"))}


def required_versions(models_dir: Path, doc: str) -> set[tuple[str, str]]:
    """필수(제출·운영) 모델 = doc 의 이름별 첫 행 + registry current."""
    req: dict[str, str] = {}
    for name, ver, _ in doc_rows(models_dir / doc):
        req.setdefault(name, ver)
    out = set(req.items())
    reg_file = models_dir / "registry.json"
    if reg_file.exists():
        out |= set(json.loads(reg_file.read_text(encoding="utf-8")).get("current", {}).items())
    return out


def check_doc(
    models_dir: Path,
    doc: str,
    required: set[tuple[str, str]] | None = None,
    history: dict[tuple[str, str], str] | None = None,
    strict: bool = True,
) -> bool:
    """doc 표의 파일 해시 대조.

    strict 가 아니면 필수가 아닌 행(이력)의 파일이 없을 때 HISTORY.md 해시로 대신한다.
    """
    rows = doc_rows(models_dir / doc)
    print(f"[{doc}]")
    if not rows:
        print("  표 행 없음 — MISMATCH")
        return False
    required = required or set()
    history = history or {}
    ok = True
    for name, ver, h in rows:
        p = models_dir / name / ver / "model.pkl"
        if p.exists():
            same = sha256(p) == h
            print(f"{name}/{ver}: {'OK' if same else 'MISMATCH'}")
        elif not strict and (name, ver) not in required and history.get((name, ver)) == h:
            same = True
            print(f"{name}/{ver}: {NOT_PACKAGED}")
        else:
            same = False
            if strict:
                why = "저장소 models/ 는 모든 동결 파일이 있어야 함"
            elif (name, ver) in required:
                why = "필수(제출·운영) 모델"
            else:
                why = "이력 — HISTORY.md 에 같은 sha256 없음"
            print(f"{name}/{ver}: MISMATCH (파일 없음, {why})")
        ok &= same
    return ok


def check_current(models_dir: Path, doc: str) -> bool:
    """registry current 가 doc 의 버전과 같은지(registry.json 이 없으면 건너뜀)."""
    reg_file = models_dir / "registry.json"
    if not reg_file.exists():
        print("registry.json 없음 — current 확인 건너뜀")
        return True
    cur = json.loads(reg_file.read_text(encoding="utf-8")).get("current", {})
    ok = True
    seen: set[str] = set()
    for name, ver, _ in doc_rows(models_dir / doc):
        if name in seen:  # 이름별 첫 행만 current(뒤 행은 보존·참고용, 예: v1-fix)
            continue
        seen.add(name)
        same = cur.get(name) == ver
        print(f"current {name}: {cur.get(name)} ({'OK' if same else f'MISMATCH — {doc} 는 {ver}'})")
        ok &= same
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models-dir", type=Path, default=MODELS_DIR)
    args = ap.parse_args(argv)
    md: Path = args.models_dir
    docs = [d for d in DOCS if (md / d).exists()]
    if not docs:
        print(f"동결 문서 없음: {md}")
        return 1
    repo_models = not PACKAGE_LAYOUT and md.resolve() == MODELS_DIR.resolve()
    if "FROZEN.md" not in docs and repo_models:
        print("v1 동결 문서(FROZEN.md) 없음 — MISMATCH")
        return 1
    # 저장소 models/ 는 모든 파일이 있어야 한다(strict).
    # 그 밖(제출 패키지 model/ 등)은 이력 파일을 HISTORY.md 해시로 대신할 수 있다.
    strict = repo_models
    required = required_versions(md, docs[-1])
    history = {} if strict else history_rows(md)
    ok = all([check_doc(md, d, required, history, strict) for d in docs])
    ok &= check_current(md, docs[-1])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
