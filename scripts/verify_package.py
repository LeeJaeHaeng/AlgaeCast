# ruff: noqa: E501  (README·안내 문구의 긴 한국어 줄)
"""제출 패키지 재현 검증 (T9-b): 패키지를 임시 폴더에 복사(또는 zip 을 풀고) 새 venv 에서 README 4절대로 실행.

확인 항목
1) submission.csv(패키지 루트)가 제출본(저장소 submission/submission.csv)과 바이트 동일(diff 0)
2) 노트북 재실행 오류 0 (실행본 ipynb 의 error 출력·Traceback 0)
3) 데모 영상 demo/AlgaeCast_demo.mp4 의 sha256 이 승인본(0a1fb2f4…, 2026-10-23 v4)으로 시작
4) DataON 원값 파일(data/raw/dataon/level_continuous_long.parquet) 유무를 기록(기본 패키지는 없음 → 가공 수위 피처로 재현)
결과: reports/eval/package_verify.log(실행 기록), reports/eval/package_verify.json(체크리스트용 요약)

사용: python scripts/verify_package.py [--dir submission_package | --zip dist/...zip] [--update-package] [--keep]
  --update-package : 새 venv 실행본 ipynb·그림을 submission_package/ 에 반영(서류평가용 '실행 결과 포함' 노트북)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO_SHA_PREFIX = "0a1fb2f4"  # 2026-10-23 v4(예상값 하나로 통일한 화면 재녹화). 이전: v1 6a0d78e3·v2a 43761cbc·v3 5363e22a → dist/backup_demo_2026102*


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
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
    return r.returncode


def notebook_errors(ipynb: Path) -> tuple[int, int]:
    """(error 출력 수, stderr 경고 줄 수) — INFO 로그는 제외."""
    nb = json.loads(ipynb.read_text(encoding="utf-8"))
    errors = warns = 0
    for c in nb.get("cells", []):
        for o in c.get("outputs", []):
            if o.get("output_type") == "error":
                errors += 1
            text = "".join(o.get("text", [])) if isinstance(o.get("text"), list) else str(o.get("text", ""))
            if "Traceback" in text:
                errors += 1
            if o.get("name") == "stderr":
                warns += sum(1 for ln in text.splitlines() if "Warning" in ln or "WARNING" in ln)
    return errors, warns


def abs_paths(ipynb: Path, pkg: Path) -> int:
    """실행본 출력에 남은 로컬 절대경로(임시 폴더·사용자 폴더) 수."""
    nb = json.loads(ipynb.read_text(encoding="utf-8"))
    marks = [str(pkg), str(pkg).replace("\\", "/"), "AppData", "C:\\Users", "C:/Users"]

    def strings(x: object) -> list[str]:
        if isinstance(x, str):
            return [x]
        if isinstance(x, list):
            return [t for v in x for t in strings(v)]
        if isinstance(x, dict):
            # 그림(base64) 출력은 제외 — 경로 문자열이 우연히 섞여 보이는 오탐 방지
            return [t for k, v in x.items() if not str(k).startswith("image/") for t in strings(v)]
        return []

    text = "".join(t for c in nb.get("cells", []) for o in c.get("outputs", []) for t in strings(o))
    return sum(text.count(m) for m in marks)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    # 저장소에서 실행하면 submission_package/, 패키지 안에서 실행하면 패키지 자신을 검증
    default_dir = ROOT / "submission_package" if (ROOT / "submission_package").is_dir() else ROOT
    ap.add_argument("--dir", type=Path, default=default_dir)
    ap.add_argument("--zip", type=Path, default=None)
    ap.add_argument("--update-package", action="store_true")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)
    tmp = Path(tempfile.mkdtemp(prefix="algaecast_verify_"))
    rep = ROOT / "reports" / "eval" if (ROOT / "reports").is_dir() else ROOT / "figures" / "reports" / "eval"
    rep.mkdir(parents=True, exist_ok=True)
    log = rep / "package_verify.log"
    src_desc = str(args.zip or args.dir)
    log.write_text(
        f"# 패키지 재현 검증 {time.strftime('%Y-%m-%d %H:%M')}\n원본: {src_desc}\n", encoding="utf-8"
    )
    t0 = time.time()
    if args.zip:
        with zipfile.ZipFile(args.zip) as z:
            z.extractall(tmp)
        pkg = next(p for p in tmp.iterdir() if p.is_dir())
    else:
        pkg = tmp / "pkg"
        shutil.copytree(args.dir, pkg)
    dataon_raw = (pkg / "data" / "raw" / "dataon" / "level_continuous_long.parquet").exists()
    level_file = (pkg / "data" / "processed" / "level_cont_features_S1.parquet").exists()
    wamis_raw = (pkg / "data" / "raw" / "wamis_dam" / "wamis_dam_daily.parquet").exists()
    wamis_file = (pkg / "data" / "processed" / "wamis_hydro_features_S1.parquet").exists()
    # 복사본의 제출 파일을 지워, 노트북이 실제로 다시 만든 파일만 비교한다.
    (pkg / "submission.csv").unlink(missing_ok=True)
    py = sys.executable  # 같은 인터프리터(3.11)로 새 venv
    vpy = str(pkg / ".venv" / "Scripts" / "python.exe")
    steps = [
        [py, "-m", "venv", ".venv"],
        [vpy, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
        [vpy, "-m", "pip", "install", "-q", "-e", ".", "--no-deps"],
        [vpy, "-m", "jupytext", "--to", "notebook", "--execute", "notebooks/01_train_eval.py"],
    ]
    rc = 0
    for cmd in steps:
        rc = run(cmd, pkg, log)
        print(f"{'OK ' if rc == 0 else 'FAIL'} {' '.join(cmd[-3:])}")
        if rc != 0:
            break
    res: dict = {
        "when": time.strftime("%Y-%m-%d %H:%M"),
        "returncode": rc,
        "source": src_desc,
        "dataon_raw_present": dataon_raw,
        "level_cont_mode": "raw" if dataon_raw else ("derived" if level_file else "missing"),
        "wamis_raw_present": wamis_raw,
        "wamis_mode": "raw" if wamis_raw else ("derived" if wamis_file else "missing"),
    }
    if rc == 0:
        out_csv = pkg / "submission.csv"
        a = out_csv.read_bytes() if out_csv.exists() else b""
        res["submission_regenerated"] = out_csv.exists()
        ref = ROOT / "submission" / "submission.csv"  # 저장소의 제출본
        if not ref.exists():
            ref = ROOT / "submission.csv"  # 패키지 안에서 실행할 때: 패키지에 든 제출본
        b = ref.read_bytes()
        res["submission_identical"] = a == b
        res["submission_sha256"] = hashlib.sha256(a).hexdigest()
        errs, warns = notebook_errors(pkg / "notebooks" / "01_train_eval.ipynb")
        res["notebook_errors"] = errs
        res["notebook_stderr_warnings"] = warns
        res["notebook_abs_paths"] = abs_paths(pkg / "notebooks" / "01_train_eval.ipynb", pkg)
    mp4 = pkg / "demo" / "AlgaeCast_demo.mp4"
    res["demo_sha256"] = hashlib.sha256(mp4.read_bytes()).hexdigest() if mp4.exists() else None
    res["demo_sha_ok"] = bool(res["demo_sha256"] and res["demo_sha256"].startswith(DEMO_SHA_PREFIX))
    res["minutes"] = round((time.time() - t0) / 60, 1)
    msg = (
        f"submission.csv diff: {'0 (바이트 동일)' if res.get('submission_identical') else '불일치/미실행'} · "
        f"노트북 오류 {res.get('notebook_errors', '미실행')}건(경고 줄 {res.get('notebook_stderr_warnings', '-')}, 절대경로 {res.get('notebook_abs_paths', '-')}) · "
        f"데모 sha256 {str(res['demo_sha256'])[:16]}… {'일치' if res['demo_sha_ok'] else '불일치'} · "
        f"DataON 원값 {'있음' if dataon_raw else '없음'}(수위 피처 {res['level_cont_mode']}) · "
        f"WAMIS 원값 {'있음' if wamis_raw else '없음'}(수문 피처 {res['wamis_mode']}) · 소요 {res['minutes']} 분"
    )
    print(msg)
    with log.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")
    (rep / "package_verify.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    good = (
        rc == 0
        and res.get("submission_identical")
        and res.get("notebook_errors") == 0
        and res.get("notebook_abs_paths") == 0
        and res["demo_sha_ok"]
    )
    if good and args.update_package and not args.zip:
        shutil.copy2(
            pkg / "notebooks" / "01_train_eval.ipynb", args.dir / "notebooks" / "01_train_eval.ipynb"
        )
        for f in ("fig_2025_pred_vs_obs.png", "fig_leadtime_summary.png"):
            if (pkg / "figures" / f).exists():
                shutil.copy2(pkg / "figures" / f, args.dir / "figures" / f)
        # 이 검증 기록도 패키지의 figures/reports/eval 에 넣는다(빌드 때 복사된 이전 기록을 덮어씀)
        for f in ("package_verify.log", "package_verify.json"):
            dst = args.dir / "figures" / "reports" / "eval" / f
            if dst.parent.is_dir():
                shutil.copy2(rep / f, dst)
        print("실행본 노트북·그림을 패키지에 반영:", args.dir / "notebooks" / "01_train_eval.ipynb")
    if not args.keep:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if good else 2


if __name__ == "__main__":
    raise SystemExit(main())
