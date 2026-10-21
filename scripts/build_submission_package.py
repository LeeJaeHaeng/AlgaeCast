# ruff: noqa: E501  (README·안내 문구의 긴 한국어 줄)
"""공식 제출 패키지 생성 (T9-b): submission_package/ 트리 → 민감정보 검사 → zip.

구조: README.md, requirements.txt, data/, model/, src/, notebooks/, scripts/, demo/, figures/, config/, submission/
- data/: 대회 번들 + 외부 수집 원천 parquet + MANIFEST.md (git 미포함, 패키지 전용)
- model/: 동결 레지스트리 3종 + registry.json + FROZEN.md
- src/, scripts/: 재현에 필요한 코드만(수집기는 스냅샷 로더용으로 포함, 대시보드·DB 업로드 코드는 제외)
사용: python scripts/build_submission_package.py [--out submission_package] [--zip]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

from algaecast.config import ROOT

ZIP_NAME = "AlgaeCast_녹조7일예측_이재행.zip"
RAW_FILES = [
    "nier_algae/nier_algae_2012_2026.parquet",
    "kma_asos/kma_asos_daily_2012_2026.parquet",
    "hydro/hydro_daily_long.parquet",
    "kwater_sluice/kwater_sluice_daily.parquet",
    "wamis_dam/wamis_dam_daily.parquet",
    "kwater_damapi/kwater_damapi_recent.parquet",
    "dataon/level_continuous_long.parquet",
    "MANIFEST.md",
]
SRC_SKIP = {"db", "predict"}  # 대시보드 업로드·일일 운영 코드는 재현에 불필요
SRC_SKIP_FILES = {"live.py"}  # test 타깃 로더(사후 검증 전용) — 패키지에서 제외
SCRIPTS = ["verify_frozen.py", "leakage_audit.py"]
SECRET_PATTERNS = [
    r"serviceKey" "=",
    r"eyJ[A-Za-z0-9_-]{30,}",
    r"[A-Za-z0-9+/%]{80,}={0,2}",
    r"SUPABASE_[A-Z_]*KEY=\S",
    r"VERCEL_TOKEN=\S",
    r"PASSWORD=\S",
    r"sbp_[A-Za-z0-9]{20,}",
]


def copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(
            src,
            dst,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".ipynb_checkpoints"),
        )
    else:
        shutil.copy2(src, dst)


def pip_freeze() -> str:
    r = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True)
    lines = [
        ln
        for ln in r.stdout.splitlines()
        if ln and not ln.startswith("-e ") and "algaecast" not in ln.lower()
    ]
    return "\n".join(lines) + "\n"


def env_info() -> dict:
    import lightgbm
    import numpy
    import pandas
    import sklearn

    return {
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "python": platform.python_version(),
        "lightgbm": lightgbm.__version__,
        "scikit-learn": sklearn.__version__,
        "pandas": pandas.__version__,
        "numpy": numpy.__version__,
        "gpu": "미사용 (CPU 전용)",
    }


def readme(info: dict, frozen_commit: str, sizes: dict[str, str]) -> str:
    return f"""# AlgaeCast-7 — 수질·수문·기상 융합 기반 댐·하천 유해남조류 7일 예측 (제출 패키지)

2026 DATA·AI 분석 경진대회(KISTI) 문제해결 부문 · 참가자 이재행 · 생성일 {date.today()}

## 1. 구성
| 폴더 | 내용 | 크기 |
|---|---|---|
| `data/` | 대회 번들(`data/raw/competition/`) + 외부 공공 데이터 스냅샷(parquet) + `data/raw/MANIFEST.md`(출처·수집일시·라이선스) | {sizes.get('data', '-')} |
| `model/` | 동결 모델 3종(회귀 앙상블·경보 분류기·분위 회귀) + `registry.json` + `FROZEN.md`(sha256, 동결 커밋 `{frozen_commit}`) | {sizes.get('model', '-')} |
| `src/` | 파이썬 패키지 `algaecast`(정렬·피처·모델·평가) — 재현에 필요한 코드만 | {sizes.get('src', '-')} |
| `notebooks/01_train_eval.ipynb` | 데이터 로드·전처리 → 피처 → 학습(동결 파라미터) → 2025 검증 지표 → `submission.csv` 생성 → 그림. 실행 결과 포함 | |
| `scripts/` | `verify_frozen.py`(해시 검증), `leakage_audit.py`(누수 감사) | |
| `config/` | 지점·피처·모델·시드 설정 (`seed.yaml`=42) | |
| `submission/submission.csv` | 제출본 (124행, `station_id,base_date,target_date,pred_cells`) | |
| `figures/` | 방법설명서·발표용 핵심 그림 | |
| `demo/` | 데모 영상 자리(README_DEMO.md) — UI 개편 후 추가 | |
| `docs/` | 방법설명서·설계 문서 | |

## 2. 데이터·모델 요약
- 타깃: 조류경보제 5지점(해평·강정고령·칠서·물금매리·회남) 유해남조류 세포수(cells/mL), 기준일(base_date)+7일(±3일 매칭) 예측.
- 입력: 조류경보제 측정(국립환경과학원), 댐·보 운영(K-water delist·WAMIS), 댐유역 하천 일평균수위(**DataON** 국가참조표준 DOI 10.20925/KSRD.74670854.v5 — 원 배포처 약관상 파일은 미포함, 집계 산출물만 포함), ASOS 기상(기상청), 단기·중기예보(2026-10-21 이후 누적).
- 모델: LightGBM 변형 3종(log 가중 회귀 C1 · hurdle C3 · tweedie C2)의 NNLS 앙상블(제출용 세포수) + 경계(+4~+10일 ≥10,000) 분류기(경보 확률) + 분위 회귀 q10/50/90(CQR 보정, 감시 규칙). 피처 30개(VIF·Boruta·보 ablation 선별).
- 검증: 연도 expanding-window CV(2020~2024) → 2025 홀드아웃 → **모델 동결** → 2026 사후 검증(모델 선택·튜닝에 미사용). 누수 감사: 전 샘플 재계산 불일치 0.
- 핵심 결과: 2025 log R² 0.78, 경계 F1 0.68(지속성 0.73과 동률 수준), 원단위 R² 0.17(봉우리 1건이 분산 43%); 공식 경계 발령 2020~2026 28건 중 25건을 첫 초과 측정 기준 중앙 14~21일 앞서 감시 단계로 포착(지속성 3건).

## 3. 실행 환경
- OS {info['os']}, Python {info['python']}, lightgbm {info['lightgbm']}, scikit-learn {info['scikit-learn']}, pandas {info['pandas']}, numpy {info['numpy']}. **GPU 미사용(CPU 전용)**.
- 정확한 라이브러리 버전: `requirements.txt`(pip freeze).

## 4. 설치·실행 (3줄)
```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt   # Linux/mac: .venv/bin/python
.venv/Scripts/python -m pip install -e . --no-deps
.venv/Scripts/python -m jupytext --to notebook --execute notebooks/01_train_eval.py   # → submission/submission.csv, figures/
```
- 재현 소요 시간: 약 20분(피처 생성 15분 포함, 8코어 노트북 기준). 결과 `submission/submission.csv` 는 제출본과 바이트 동일(`scripts/verify_package.py` 로 확인).
- **외부 API는 재현에 필요 없다.** `data/` 스냅샷만 사용한다. 공공 API 키(.env)는 대시보드 일일 운영(GitHub Actions)에만 쓰이며 패키지에 포함되지 않는다.
- 대시보드(운영 데모): https://algaecast-7.vercel.app · 저장소: https://github.com/LeeJaeHaeng/AlgaeCast (private)

## 5. AI 활용범위 및 주요 검토 과정 [검토 필요 — 참가자 직접 검토·수정 예정]
- **활용 도구**: 기획·검토 — Claude 채팅(claude.ai, Claude Opus 4.1/Sonnet 4.5 [검토 필요: 실제 사용 모델 확인]); 구현 — Claude Code(CLI, 모델 Claude Fable 5.1). 코드 생성·실험 실행·문서 초안에 사용.
- **활용 단계**: 데이터 조사·수집기 구현(T1), 통계분석 노트북(T2), 피처·누수 테스트(T3), 모델 튜닝·실험 러너(T4), 평가 보고서(T5), DB·대시보드·자동화(T6~T8), 문서 초안(T9).
- **주요 활용 내용**: 공공 API 수집기와 캐시·재시도 구조, 피처 함수와 누수 감사 스크립트, Optuna 튜닝 파이프라인, 통계 검정·그림 코드, Next.js 대시보드, GitHub Actions 워크플로.
- **참가자 주요 기여·검증** [검토 필요]: 문제 정의와 데이터 선정(DataON 수위 자료·보 운영자료 1차화 결정), 2단계 경보 체계(감시=CQR q90, 경보=분류기 운영점 r=3)와 헤드라인 정의, 모델 동결·2026 사후 검증 원칙(결과를 보고 규칙을 바꾸지 않음), 원단위 R² 한계의 서술 방향, 우선순위 규칙(가중치 미사용)·취수용량 출처 등급 판단, 모든 태스크 결과 수치 검토·승인.
- **검토한 대안·실패 사례**: 원단위 R²·NSE 개선을 위한 6개 변형×3개 보정(smearing·isotonic·CQR) 실험 — 어떤 조합도 0.2를 넘지 못함(isotonic 은 악화); 경보 분류기·스태킹·q90 규칙 — 2025 전체 F1 에서 지속성(0.727)을 넘지 못함(진입 구간 Recall·PR-AUC·리드타임에서만 우위); hurdle·tweedie 단일 모델 — CV 에서 C1 과 차이 미미; 물모아 공식 예측 벤치마크 — 단계만 제공돼 분류 비교로 전환(누적 중); CCTV·위성 영상 피처 [검토 필요: 검토 사실 확인] — 데이터 접근·정렬 비용으로 미채택; 외부 유역강수 CSV(MT-02/03) — 미수령으로 보류.
- **최종 선택 이유**: CV 복합점수 기준 채택 절차를 고정해 홀드아웃 과적합을 막았고, 운영 목적(발령 선행 판단)에 맞는 지표(log R²·경보 F1·리드타임)로 평가했으며, 재현 가능한 동결 모델과 공개 데이터 스냅샷으로 전 과정을 패키지화했다.

## 6. 라이선스·출처
`data/raw/MANIFEST.md` 참조. DataON 자료(CC BY-NC-SA, 제3자 제공 금지)는 원 파일 대신 집계 산출물(연속 수위 편차)만 포함했으며 다운로드 안내를 MANIFEST 에 적었다.
"""


def scan_secrets(root: Path) -> list[str]:
    hits = []
    for p in root.rglob("*"):
        if (
            not p.is_file()
            or p.suffix in {".parquet", ".pkl", ".png", ".zip", ".ipynb"}
            and p.suffix != ".ipynb"
        ):
            continue
        if p.suffix in {".parquet", ".pkl", ".png", ".zip"}:
            continue
        if p.name == ".env" or p.name.startswith(".env."):
            hits.append(f"{p}: .env 파일 포함")
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in SECRET_PATTERNS:
            for m in re.finditer(pat, text):
                ctx = text[max(0, m.start() - 20) : m.start() + 20].replace("\n", " ")
                if "integrity" in ctx or "sha512-" in ctx or "sha256" in ctx.lower():
                    continue
                hits.append(f"{p.relative_to(root)}: /{pat}/ … {ctx[:12]}…")
                break
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "submission_package")
    ap.add_argument("--zip", action="store_true")
    args = ap.parse_args(argv)
    out = args.out
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    # data
    copy(ROOT / "data" / "raw" / "competition", out / "data" / "raw" / "competition")
    for f in RAW_FILES:
        src = ROOT / "data" / "raw" / f
        if src.exists():
            copy(src, out / "data" / "raw" / f)
    for sub in ("interim", "processed"):
        (out / "data" / sub).mkdir(parents=True, exist_ok=True)
        (out / "data" / sub / ".gitkeep").write_text("", encoding="utf-8")
    copy(ROOT / "data" / "raw" / "kma_forecast", out / "data" / "raw" / "kma_forecast")
    # model
    reg = json.loads((ROOT / "models" / "registry.json").read_text(encoding="utf-8"))
    for name, ver in reg["current"].items():
        copy(ROOT / "models" / name / ver, out / "models" / name / ver)
    copy(ROOT / "models" / "registry.json", out / "models" / "registry.json")
    copy(ROOT / "models" / "FROZEN.md", out / "models" / "FROZEN.md")
    (out / "model").mkdir(exist_ok=True)
    (out / "model" / "README.md").write_text(
        "동결 모델 파일은 `../models/`(코드가 참조하는 경로)에 있다. 이 폴더는 공지 구조(model/)를 맞추기 위한 안내이며 `models/FROZEN.md` 의 sha256 으로 검증한다.\n",
        encoding="utf-8",
    )
    # src (필요 모듈만)
    pkg = ROOT / "src" / "algaecast"
    for p in pkg.rglob("*.py"):
        rel = p.relative_to(pkg)
        if rel.parts and rel.parts[0] in SRC_SKIP:
            continue
        if p.name in SRC_SKIP_FILES:
            continue
        copy(p, out / "src" / "algaecast" / rel)
    # predict_registry 는 db/upload 에 있음 → 재현용 경량 사본
    copy(pkg / "db" / "upload.py", out / "src" / "algaecast" / "db" / "upload.py")
    (out / "src" / "algaecast" / "db" / "__init__.py").write_text(
        '"""DB 업로드 코드 — 재현에서는 predict_registry() 만 사용(Supabase 미사용)."""\n', encoding="utf-8"
    )
    for f in (
        "pyproject.toml",
        "Makefile",
        "config/sites.yaml",
        "config/features.yaml",
        "config/model.yaml",
        "config/seed.yaml",
        "config/dam_codes.json",
        "config/level_cont_stats.json",
    ):
        if (ROOT / f).exists():
            copy(ROOT / f, out / f)
    for s in SCRIPTS:
        copy(ROOT / "scripts" / s, out / "scripts" / s)
    (
        copy(ROOT / "scripts" / "verify_package.py", out / "scripts" / "verify_package.py")
        if (ROOT / "scripts" / "verify_package.py").exists()
        else None
    )
    # notebooks (실행 결과 포함 ipynb + py)
    for f in ("01_train_eval.ipynb", "01_train_eval.py"):
        if (ROOT / "notebooks" / f).exists():
            copy(ROOT / "notebooks" / f, out / "notebooks" / f)
    # submission, figures, docs, demo
    copy(ROOT / "submission" / "submission.csv", out / "submission" / "submission.csv")
    (out / "figures").mkdir(exist_ok=True)
    for f in [
        "fig_site_response.png",
        "fig_lag_corr.png",
        "fig_onset_trend.png",
        "fig_shap_global.png",
        "fig_shap_cases.png",
        "fig_residuals.png",
    ]:
        for d in ("reports/eval", "reports/eda"):
            if (ROOT / d / f).exists():
                copy(ROOT / d / f, out / "figures" / f)
                break
    for f in (ROOT / "figures").glob("*.png") if (ROOT / "figures").exists() else []:
        copy(f, out / "figures" / f.name)
    for f in (ROOT / "reports" / "screenshots").glob("*.png"):
        copy(f, out / "figures" / f"dashboard_{f.name}")
    copy(ROOT / "docs", out / "docs")
    copy(ROOT / "reports" / "eval", out / "reports" / "eval")
    copy(ROOT / "reports" / "eda", out / "reports" / "eda")
    (out / "demo").mkdir(exist_ok=True)
    (out / "demo" / "README_DEMO.md").write_text(
        "# 데모 영상 (자리표시)\n\n대시보드 UI 개편(T7-R) 후 90~120초 영상을 추가한다. 현재는 운영 중인 대시보드 https://algaecast-7.vercel.app 와 `figures/dashboard_*.png` 스크린샷으로 대체.\n",
        encoding="utf-8",
    )
    # requirements / README
    (out / "requirements.txt").write_text(pip_freeze(), encoding="utf-8")
    frozen = re.search(
        r"동결 커밋: `([0-9a-f]+)`", (ROOT / "models" / "FROZEN.md").read_text(encoding="utf-8")
    )
    sizes = {
        k: f"{sum(p.stat().st_size for p in (out / k).rglob('*') if p.is_file()) / 1e6:.1f} MB"
        for k in ("data", "models", "src")
        if (out / k).exists()
    }
    sizes["model"] = sizes.pop("models", "-")
    (out / "README.md").write_text(
        readme(env_info(), frozen.group(1)[:7] if frozen else "?", sizes), encoding="utf-8"
    )
    # 민감정보 검사
    hits = scan_secrets(out)
    (out / "SECURITY_SCAN.txt").write_text(
        ("민감정보 검사 결과: 0건\n" if not hits else "\n".join(hits) + "\n"), encoding="utf-8"
    )
    print("민감정보 검사:", "0건" if not hits else f"{len(hits)}건\n" + "\n".join(hits[:10]))
    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"패키지 {out} 총 {total / 1e6:.1f} MB")
    if args.zip:
        zpath = ROOT / "dist" / ZIP_NAME
        zpath.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for p in sorted(out.rglob("*")):
                if p.is_file():
                    z.write(p, Path("AlgaeCast_녹조7일예측_이재행") / p.relative_to(out))
        print(
            f"zip {zpath} {zpath.stat().st_size / 1e6:.1f} MB sha256 {hashlib.sha256(zpath.read_bytes()).hexdigest()[:16]}"
        )
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
