"""고도화 실험 중 v1 동결 산출물이 바뀌지 않았는지 확인(data/processed/exp/protected_hashes.json 대조).

사용: python scripts/exp_check_protected.py  → 바뀐 파일이 있으면 목록을 출력하고 종료 코드 1.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ref = json.loads((ROOT / "data/processed/exp/protected_hashes.json").read_text(encoding="utf-8"))
    bad = []
    for rel, h in ref.items():
        p = ROOT / rel
        cur = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "(missing)"
        if cur != h:
            bad.append(rel)
    print(f"보호 파일 {len(ref)}개 중 변경 {len(bad)}개", *bad, sep="\n  ")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
