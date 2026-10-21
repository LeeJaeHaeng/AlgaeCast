"""레지스트리 current 모델 파일이 models/FROZEN.md 의 sha256 과 일치하는지 검증."""

from __future__ import annotations

import hashlib
import re
import sys

from algaecast.config import ROOT


def main() -> int:
    text = (ROOT / "models" / "FROZEN.md").read_text(encoding="utf-8")
    ok = True
    for name, ver, h in re.findall(r"\| (\w+) \| (\d+_\d+) \| `([0-9a-f]{64})` \|", text):
        p = ROOT / "models" / name / ver / "model.pkl"
        cur = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "(missing)"
        print(f"{name}/{ver}: {'OK' if cur == h else 'MISMATCH'}")
        ok &= cur == h
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
