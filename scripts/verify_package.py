# ruff: noqa: E501  (README·안내 문구의 긴 한국어 줄)
"""제출 패키지 재현 검증 (T9-b): zip 을 임시 폴더에 풀고 새 venv 에서 README 3줄대로 실행 → submission.csv 가 제출본과 diff 0 인지 확인.

사용: python scripts/verify_package.py [--zip dist/AlgaeCast_녹조7일예측_이재행.zip] [--keep]
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from algaecast.config import ROOT


def run(cmd: list[str], cwd: Path, log: Path) -> int:
    with log.open("a", encoding="utf-8") as f:
        f.write(f"\n$ {' '.join(cmd)}\n")
        f.flush()
        r = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=f,
            stderr=subprocess.STDOUT,
            text=True,
            env={**__import__("os").environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
    return r.returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip", type=Path, default=ROOT / "dist" / "AlgaeCast_녹조7일예측_이재행.zip")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)
    tmp = Path(tempfile.mkdtemp(prefix="algaecast_verify_"))
    log = ROOT / "reports" / "eval" / "package_verify.log"
    log.write_text(
        f"# 패키지 재현 검증 {time.strftime('%Y-%m-%d %H:%M')}\nzip: {args.zip}\n", encoding="utf-8"
    )
    t0 = time.time()
    with zipfile.ZipFile(args.zip) as z:
        z.extractall(tmp)
    pkg = next(p for p in tmp.iterdir() if p.is_dir())
    py = sys.executable  # 같은 인터프리터(3.11)로 새 venv
    steps = [
        [py, "-m", "venv", ".venv"],
        [
            str(pkg / ".venv" / "Scripts" / "python.exe"),
            "-m",
            "pip",
            "install",
            "-q",
            "-r",
            "requirements.txt",
        ],
        [str(pkg / ".venv" / "Scripts" / "python.exe"), "-m", "pip", "install", "-q", "-e", ".", "--no-deps"],
        [
            str(pkg / ".venv" / "Scripts" / "python.exe"),
            "-m",
            "jupytext",
            "--to",
            "notebook",
            "--execute",
            "notebooks/01_train_eval.py",
        ],
    ]
    for cmd in steps:
        rc = run(cmd, pkg, log)
        print(f"{'OK ' if rc == 0 else 'FAIL'} {' '.join(cmd[-3:])}")
        if rc != 0:
            print("로그:", log)
            return 1
    a = (pkg / "submission" / "submission.csv").read_bytes()
    b = (ROOT / "submission" / "submission.csv").read_bytes()
    same = a == b
    msg = f"submission.csv diff: {'0 (바이트 동일)' if same else '불일치'} — 패키지 sha256 {hashlib.sha256(a).hexdigest()[:16]} / 제출본 {hashlib.sha256(b).hexdigest()[:16]}; 소요 {(time.time() - t0) / 60:.1f} 분"
    print(msg)
    log.open("a", encoding="utf-8").write(msg + "\n")
    if not args.keep:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if same else 2


if __name__ == "__main__":
    raise SystemExit(main())
