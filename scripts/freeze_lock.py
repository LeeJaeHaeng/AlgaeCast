"""설치된 패키지 버전을 requirements.lock.txt 에 LF 줄바꿈으로 고정한다 (make lock).

cmd.exe 리다이렉트는 CRLF 를 쓰므로 Python 에서 직접 기록한다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "requirements.lock.txt"


def main() -> int:
    freeze = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--exclude-editable"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    lines = [ln.strip() for ln in freeze.splitlines() if ln.strip()]
    py = sys.version.split()[0]
    header = f"# pip freeze --exclude-editable (python {py}, make lock). 직접 수정 금지."
    OUT.write_text("\n".join([header, *lines]) + "\n", encoding="utf-8", newline="\n")
    print(f"{OUT.name}: {len(lines)} packages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
