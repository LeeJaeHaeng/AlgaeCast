"""pre-commit 훅 설치 (make setup 에서 호출).

PYTHONUTF8=1 을 강제해 훅 스크립트가 UTF-8 로 기록되게 한다. Windows 기본 인코딩(cp949)으로 쓰면
한글이 포함된 저장소 경로에서 sh 가 venv 인터프리터 경로를 해석하지 못해 커밋이 실패한다.
"""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.call([sys.executable, "-m", "pre_commit", "install"], env=env)


if __name__ == "__main__":
    sys.exit(main())
