"""동결 모델 검증 — models/FROZEN.md(v1)와 models/FROZEN_v2.md(있으면)의 sha256 을 현재 파일과 대조한다.

- 각 동결 문서 표의 행 `| name | version | `sha256` | ...` 마다
  <models>/<name>/<version>/model.pkl 의 sha256 을 비교한다.
- registry.json 의 current 가 가장 최근 동결 문서(FROZEN_v2.md 가 있으면 그것,
  없으면 FROZEN.md)의 버전과 같은지도
  확인한다(일일 예측·제출 파일이 동결 버전으로 만들어지는지).
- 하나라도 다르거나 파일이 없으면 종료 코드 1.
사용: python scripts/verify_frozen.py [--models-dir DIR]   (DIR 기본: models/, 제출 패키지: model/)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from algaecast.config import MODELS_DIR

DOCS: tuple[str, ...] = ("FROZEN.md", "FROZEN_v2.md")  # 오래된 것 → 최근
ROW = re.compile(r"\| (\w+) \| (\d+_\d+) \| `([0-9a-f]{64})` \|")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def doc_rows(path: Path) -> list[tuple[str, str, str]]:
    """동결 문서의 (name, version, sha256) 행."""
    return ROW.findall(path.read_text(encoding="utf-8"))


def check_doc(models_dir: Path, doc: str) -> bool:
    rows = doc_rows(models_dir / doc)
    print(f"[{doc}]")
    if not rows:
        print("  표 행 없음 — MISMATCH")
        return False
    ok = True
    for name, ver, h in rows:
        p = models_dir / name / ver / "model.pkl"
        cur = sha256(p) if p.exists() else "(missing)"
        print(f"{name}/{ver}: {'OK' if cur == h else 'MISMATCH'}")
        ok &= cur == h
    return ok


def check_current(models_dir: Path, doc: str) -> bool:
    """registry current 가 doc 의 버전과 같은지(registry.json 이 없으면 건너뜀)."""
    reg_file = models_dir / "registry.json"
    if not reg_file.exists():
        print("registry.json 없음 — current 확인 건너뜀")
        return True
    cur = json.loads(reg_file.read_text(encoding="utf-8")).get("current", {})
    ok = True
    for name, ver, _ in doc_rows(models_dir / doc):
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
    if "FROZEN.md" not in docs and md.resolve() == MODELS_DIR.resolve():
        print("v1 동결 문서(FROZEN.md) 없음 — MISMATCH")
        return 1
    ok = all([check_doc(md, d) for d in docs])
    ok &= check_current(md, docs[-1])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
