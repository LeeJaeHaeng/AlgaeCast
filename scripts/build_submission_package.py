# ruff: noqa: E501  (README·안내 문구의 긴 한국어 줄)
"""공식 제출 패키지 생성 (T9-b, 2026-10-21 공지 #564 구조로 정리).

패키지 루트(공지 #564): README.md, data/, model/, src/, notebooks/, scripts/, demo/, figures/
  + 루트 파일: submission.csv(제출본), 방법설명서.pdf, requirements.txt(pip freeze), pyproject.toml(설치용)
- data/   : 대회 번들 + 외부 수집 원천 parquet + MANIFEST.md (git 미포함, 패키지 전용)
- model/  : 동결 모델 3종 + registry.json + FROZEN.md(sha256)
- src/    : 파이썬 패키지 algaecast(재현에 필요한 코드만) + src/config/(설정) + src/docs/(설계 문서)
- scripts/: verify_frozen.py, leakage_audit.py, verify_package.py
- demo/   : 저장소 루트 demo/ 에서 복사(AlgaeCast_demo.mp4·.srt·script.md·README_DEMO.md·captures/). raw/·tools/·.gitignore·*.webm 제외.
            루트 demo/ 에 mp4 가 없으면 빌드를 중단한다(자리표시로 대체하지 않음).
- figures/: 핵심 그림 + 대시보드 스크린샷 + figures/reports/(eval·eda·features·experiments 표 — 방법설명서 각주의 원천)

사용(3단계):
  1) python scripts/build_submission_package.py             # 패키지 생성(+민감정보 검사)
  2) python scripts/verify_package.py --update-package      # 새 venv 재현(diff 0·노트북 오류 0·데모 sha256) → 실행본 ipynb 를 패키지에 반영
  3) python scripts/build_submission_package.py --zip-only  # README 체크리스트를 검증 결과로 갱신 → 민감정보 재검사 → zip 2개
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

PKG_NAME = "AlgaeCast_녹조7일예측_이재행"
ZIP_NAME = f"{PKG_NAME}.zip"
ZIP_NOVIDEO = f"{PKG_NAME}_영상제외.zip"
DEMO_SHA_PREFIX = "6a0d78e3"
DEMO_FILES = ["AlgaeCast_demo.mp4", "AlgaeCast_demo.srt", "script.md", "README_DEMO.md"]
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
CONFIG_FILES = [
    "sites.yaml",
    "features.yaml",
    "model.yaml",
    "seed.yaml",
    "dam_codes.json",
    "level_cont_stats.json",
]
SRC_SKIP = {"db", "predict"}  # 대시보드 업로드·일일 운영 코드는 재현에 불필요
SRC_SKIP_FILES = {"live.py", "posthoc.py"}  # test 타깃 로더·사후 검증(전용) — 패키지에서 제외
SCRIPTS = ["verify_frozen.py", "leakage_audit.py", "verify_package.py"]
SECRET_PATTERNS = [
    r"serviceKey" "=",
    r"eyJ[A-Za-z0-9_-]{30,}",
    r"[A-Za-z0-9+/%]{80,}={0,2}",
    r"SUPABASE_[A-Z_]*KEY=\S",
    r"VERCEL_TOKEN=\S",
    r"PASSWORD=\S",
    r"sbp_[A-Za-z0-9]{20,}",
]
# 민감정보 검사에서 제외하는 이진·영상·자막 파일(텍스트 전체는 검사)
SCAN_SKIP_SUFFIX = {
    ".parquet",
    ".pkl",
    ".png",
    ".zip",
    ".pdf",
    ".mp4",
    ".srt",
    ".webm",
    ".jpg",
    ".gif",
    ".xlsx",
}
RAW_NOTE = "원본 녹화(노트북 전체 실행 17분·운영 화면 장면별)는 용량 때문에 제출 패키지에서는 제외했으며, 요청 시 제공한다."


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


def os_name() -> str:
    """Windows 11 도 platform.release() 가 '10' 을 돌려주므로 빌드 번호(22000 이상 = 11)로 판별한다."""
    if platform.system() == "Windows":
        build = int(platform.version().split(".")[-1])
        return f"Windows {'11' if build >= 22000 else '10'} (빌드 {build}, {platform.machine()})"
    return f"{platform.system()} {platform.release()} ({platform.machine()})"


def env_info() -> dict:
    import jupyterlab
    import lightgbm
    import numpy
    import pandas
    import sklearn

    return {
        "os": os_name(),
        "python": platform.python_version(),
        "lightgbm": lightgbm.__version__,
        "scikit-learn": sklearn.__version__,
        "pandas": pandas.__version__,
        "numpy": numpy.__version__,
        "jupyterlab": jupyterlab.__version__,
        "gpu": "미사용 (CPU 전용)",
    }


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def dir_size(p: Path) -> str:
    if not p.exists():
        return "-"
    n = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return f"{n / 1e6:.1f} MB"


def demo_sources() -> Path:
    src = ROOT / "demo"
    mp4 = src / "AlgaeCast_demo.mp4"
    if not mp4.exists():
        raise SystemExit(f"빌드 중단: 저장소 루트 {mp4} 가 없다(자리표시로 대체하지 않음).")
    for f in DEMO_FILES:
        if not (src / f).exists():
            raise SystemExit(f"빌드 중단: demo/{f} 가 없다.")
    if not (src / "captures").is_dir():
        raise SystemExit("빌드 중단: demo/captures/ 가 없다.")
    h = sha256(mp4)
    if not h.startswith(DEMO_SHA_PREFIX):
        raise SystemExit(f"빌드 중단: 데모 영상 sha256 {h[:16]} 가 승인본({DEMO_SHA_PREFIX}…)과 다르다.")
    return src


def checklist(out: Path, verify: dict | None) -> str:
    """공지 #564 '제출 전 확인사항' 7개 점검. 검증 결과(verify_package.json)가 있으면 반영."""
    ok = "✅"
    no = "❌"
    sub = out / "submission.csv"
    folders = ["data", "model", "src", "notebooks", "scripts", "demo", "figures"]
    struct_ok = (out / "README.md").exists() and all((out / d).is_dir() for d in folders)
    import pandas as pd

    sample = ROOT / "data" / "raw" / "competition" / "algae_contest_2026" / "sample_submission.csv"
    s = pd.read_csv(sub, encoding="utf-8-sig", dtype={"station_id": str}) if sub.exists() else None
    e = pd.read_csv(sample, encoding="utf-8-sig", dtype={"station_id": str}) if sample.exists() else None
    sub_ok = (
        s is not None
        and e is not None
        and list(s.columns) == list(e.columns)
        and len(s) == len(e) == 124
        and (
            s[["station_id", "base_date", "target_date"]].values
            == e[["station_id", "base_date", "target_date"]].values
        ).all()
        and int(s["pred_cells"].isna().sum()) == 0
        and int((s["pred_cells"] < 0).sum()) == 0
        and sub.read_bytes().startswith(b"\xef\xbb\xbf")
    )
    req = (
        (out / "requirements.txt").read_text(encoding="utf-8") if (out / "requirements.txt").exists() else ""
    )
    req_ok = all(
        re.search(rf"^{k}==", req, re.M | re.I) for k in ("lightgbm", "pandas", "jupyterlab", "ipykernel")
    )
    mp4 = out / "demo" / "AlgaeCast_demo.mp4"
    demo_ok = mp4.exists() and sha256(mp4).startswith(DEMO_SHA_PREFIX)
    nb_ok = verify is not None and verify.get("returncode") == 0 and verify.get("notebook_errors") == 0
    repro_ok = verify is not None and verify.get("submission_identical") is True
    readme_txt = (out / "README.md").read_text(encoding="utf-8") if (out / "README.md").exists() else ""
    ai_ok = "AI 활용범위 및 주요 검토 과정" in readme_txt
    v = verify or {}
    rows = [
        (
            "1. 폴더 구조",
            "README.md, data/, model/, src/, notebooks/, scripts/, demo/, figures/",
            struct_ok,
            "루트 파일: submission.csv·방법설명서.pdf·requirements.txt·pyproject.toml. 설정은 src/config/.",
        ),
        (
            "2. 노트북 실행",
            "깨끗한 환경에서 위→아래 한 번에 실행, 실행 결과(출력) 포함 저장",
            nb_ok and repro_ok,
            f"새 venv 재실행 오류 {v.get('notebook_errors', '미실행')}건, submission.csv 제출본과 바이트 동일={v.get('submission_identical', '미실행')}, 소요 {v.get('minutes', '-')}분 ({v.get('when', '-')})",
        ),
        (
            "3. submission.csv",
            "예시 서식(컬럼명·순서·행 순서·UTF-8) 그대로, 124행, NaN·음수 없음",
            sub_ok,
            f"sha256 {sha256(sub)[:16] if sub.exists() else '-'}…",
        ),
        (
            "4. README 기재사항",
            "구성, 데이터·모델 설명, 실행환경(OS·Python·라이브러리 버전·GPU 미사용), 설치·실행, 재현 소요 시간, 외부 API 불필요",
            bool(readme_txt),
            "1~4절",
        ),
        (
            "5. 라이브러리 버전",
            "requirements.txt 정확한 버전(pip freeze)",
            req_ok,
            "jupyterlab·ipykernel 포함",
        ),
        (
            "6. 데모영상",
            "테스트 또는 추론 과정을 확인할 수 있는 데모영상",
            demo_ok,
            f"demo/AlgaeCast_demo.mp4 2:28, sha256 {sha256(mp4)[:16] if mp4.exists() else '-'}… (패키지 재현 검증에서도 일치={v.get('demo_sha_ok', '미실행')})",
        ),
        (
            "7. AI 활용범위",
            "AI 활용범위 및 주요 검토 과정 기재",
            ai_ok,
            "5절 (참가자 최종 검토 표시 [검토 필요] 포함)",
        ),
    ]
    lines = [
        "| # | 확인사항 | 결과 | 근거 |",
        "|---|---|---|---|",
    ]
    for name, what, good, note in rows:
        lines.append(f"| {name} | {what} | {ok if good else no} | {note} |")
    sec = (
        (out / "scripts" / "security_scan.txt").read_text(encoding="utf-8").strip()
        if (out / "scripts" / "security_scan.txt").exists()
        else "미실행"
    )
    lines += [
        "",
        f"- 자체 점검(추가): {sec} (텍스트 파일 전체 대상, 영상·자막·이진 파일 제외, `scripts/security_scan.txt`).",
        "- 주의 [검토 필요]: 공지 #564 원문의 7개 항목 문구를 이 패키지 작성 환경에서 다시 열람하지 못해, 참가자 정리 문서('제출요건_공지정리')에서 옮긴 요건으로 점검했다. 제출 전 공지 원문과 항목 문구를 대조할 것.",
    ]
    return "\n".join(lines)


def readme(info: dict, frozen_commit: str, sizes: dict[str, str], check_md: str) -> str:
    return f"""# AlgaeCast-7 — 수질·수문·기상 융합 기반 댐·하천 유해남조류 7일 예측 (제출 패키지)

2026 DATA·AI 분석 경진대회(KISTI) 문제해결 부문 · 참가자 이재행 · 생성일 {date.today()}

## 1. 구성 (공지 #564 구조)
| 위치 | 내용 | 크기 |
|---|---|---|
| `README.md` | 이 문서(구성·데이터·모델·실행환경·설치·실행·AI 활용·제출 전 확인사항) | |
| `submission.csv` | 제출본(124행, `station_id,base_date,target_date,pred_cells`, UTF-8 BOM, 예시와 같은 행 순서) | |
| `방법설명서.pdf` | 방법 설명서(배경·데이터·통계분석·피처·모델·평가·설명가능성·시스템·재현·한계, 10장) | {sizes.get('pdf', '-')} |
| `requirements.txt` · `pyproject.toml` | 라이브러리 정확한 버전(pip freeze) · 패키지 설치 정보 | |
| `data/` | 대회 번들(`data/raw/competition/`) + 외부 공공 데이터 스냅샷(parquet) + `data/raw/MANIFEST.md`(출처·수집일시·라이선스) | {sizes.get('data', '-')} |
| `model/` | 동결 모델 3종(회귀 앙상블·경보 분류기·분위 회귀) + `registry.json` + `FROZEN.md`(sha256, 동결 커밋 `{frozen_commit}`) | {sizes.get('model', '-')} |
| `src/` | 파이썬 패키지 `algaecast`(정렬·피처·모델·평가, 재현에 필요한 코드만) + `src/config/`(지점·피처·모델·시드 설정, `seed.yaml`=42) + `src/docs/`(설계 문서) | {sizes.get('src', '-')} |
| `notebooks/01_train_eval.ipynb` | 데이터 로드·전처리 → 피처 → 학습(동결 파라미터) → 2025 검증 지표 → `submission.csv` 생성 → 그림. 실행 결과(출력) 포함 | |
| `scripts/` | `verify_frozen.py`(동결 모델 해시 검증), `leakage_audit.py`(누수 감사), `verify_package.py`(새 venv 재현 검증), `security_scan.txt` | |
| `demo/` | 데모 영상 `AlgaeCast_demo.mp4`(2분 28초, 1080p H.264, 한국어 자막) · `AlgaeCast_demo.srt` · `script.md`(콘티) · `README_DEMO.md`(구성·편집 내역) · `captures/`(장면 캡처 6장). {RAW_NOTE} | {sizes.get('demo', '-')} |
| `figures/` | 방법설명서·발표용 핵심 그림, 대시보드 스크린샷(`dashboard_*.png`), `figures/reports/`(평가·통계 표 원본 — 방법설명서 각주의 출처) | {sizes.get('figures', '-')} |

## 2. 데이터·모델 요약
- 타깃: 조류경보제 5지점(해평·강정고령·칠서·물금매리·회남) 유해남조류 세포수(cells/mL), 기준일(base_date)+7일(±3일 매칭) 예측.
- 입력: 조류경보제 측정(국립환경과학원), 댐·보 운영(K-water delist·WAMIS), 댐유역 하천 일평균수위(**DataON** 국가참조표준 DOI 10.20925/KSRD.74670854.v5 — 원 배포 파일(연도별 xlsx)은 미포함, 피처 계산용 연속 수위 파일만 포함), ASOS 기상(기상청), 단기·중기예보(2026-10-21 이후 누적). AIDA 정규격자 자료는 계획했으나 미사용(기상 입력은 ASOS 관측소로 대체).
- 모델: LightGBM 변형 3종(log 가중 회귀 C1 · hurdle C3 · tweedie C2)의 NNLS 앙상블(제출용 세포수) + 경계(+4~+10일 ≥10,000) 분류기(경보 확률) + 분위 회귀 q10/50/90(CQR 보정, 감시 규칙). 피처 30개(VIF·Boruta 선별).
- 검증: 연도 expanding-window CV(2020~2024) → 2025 홀드아웃 → **모델 동결** → 2026 사후 검증(모델 선택·튜닝에 미사용). 누수 감사: 전 샘플 재계산 불일치 0.
- 핵심 결과: 2025 log R² 0.78, 경계 F1 0.68(지속성 0.73과 비슷한 수준), 원단위 R² 0.17(봉우리 1건이 분산의 43%). **2020~2026년 경계 사건 28건 중 25건(89%)을 첫 경계 초과 측정 기준 중앙 14일 앞서 감시 단계로 포착(지속성 3건)**, 모델 동결 후 처음 보는 **2026년 8건 중 7건을 중앙 21일 앞서** 포착(지속성 2건). 2026 사후 성능 저하(log R² 0.49 등)와 한계는 방법설명서 10장.

## 3. 실행 환경
- OS {info['os']}, Python {info['python']}, lightgbm {info['lightgbm']}, scikit-learn {info['scikit-learn']}, pandas {info['pandas']}, numpy {info['numpy']}, jupyterlab {info['jupyterlab']}. **GPU 미사용(CPU 전용)**.
- 정확한 라이브러리 버전: `requirements.txt`(pip freeze, jupyterlab·ipykernel 포함).

## 4. 설치·실행
```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt   # Linux/mac: .venv/bin/python
.venv/Scripts/python -m pip install -e . --no-deps
.venv/Scripts/python -m jupytext --to notebook --execute notebooks/01_train_eval.py   # → submission.csv, figures/
```
- 화면에서 셀 단위로 실행해 보려면: `.venv/Scripts/jupyter lab notebooks/01_train_eval.ipynb` (위 2줄 설치 후).
- 재현 소요 시간: 약 20분(대부분 피처 생성, 8코어 CPU 기준). 결과 `submission.csv` 는 제출본과 바이트 동일(`scripts/verify_package.py` 로 새 가상환경에서 확인).
- **외부 API는 재현에 필요 없다.** `data/` 스냅샷만 사용한다. 공공 API 키(.env)는 대시보드 일일 운영(GitHub Actions)에만 쓰이며 패키지에 포함되지 않는다.
- 대시보드(운영 데모): https://algaecast-7.vercel.app · 저장소: https://github.com/LeeJaeHaeng/AlgaeCast (private)

## 5. AI 활용범위 및 주요 검토 과정 [검토 필요 — 참가자 직접 검토·수정 예정]
- **활용 도구**: 기획·검토 — Claude 채팅(claude.ai) [검토 필요: 실제 사용 모델 확인]; 구현 — Claude Code(CLI). 구현 모델은 Claude Fable 5.1(수집·분석·모델·평가·DB·대시보드·데모 영상), 최종 패키징 일부는 Claude Opus 5.5.
- **활용 단계**: 데이터 조사·수집기(T1), 통계분석 노트북(T2), 피처·누수 테스트(T3), 모델 튜닝·실험 러너(T4), 평가 보고서(T5), DB·대시보드·자동화(T6~T8), 제출 패키지·방법설명서 초안·데모 영상(T9).
- **주요 활용 내용**: 공공 API 수집기(캐시·재시도), 피처 함수와 누수 감사, Optuna 튜닝 파이프라인, 통계 검정·그림, Next.js 관제 대시보드, GitHub Actions 일일 자동화, 데모 영상 녹화·편집 스크립트, 방법설명서 초안(모든 수치는 `figures/reports/` 표에서 인용).

**주요 검토 과정 — AI 제안 → 참가자 선택**

| 쟁점 | AI 제안 | 참가자 선택(결정) |
|---|---|---|
| 입력 데이터 | 대회 번들에 공공 API 다수 추가(AIDA 격자 포함) | DataON 국가참조표준 수위와 보 운영자료를 1차 입력으로 확정. AIDA 격자는 미사용(ASOS 대체) |
| 원단위 R²·NSE 미달 | 6개 변형 × 3개 보정(smearing·isotonic·CQR) 실험, 결과가 좋은 조합 채택 | 채택 절차(CV 기준)를 고정하고 2025 결과를 보고 규칙을 바꾸지 않음. 원단위 지표는 표 첫 줄에 그대로 보고하고 민감도(봉우리 1건 = 분산 43%) 병기 |
| 경보 체계 | 분류기(a)·(b)·스태킹·q90 규칙 비교 | 2단계로 확정: 감시 = CQR 보정 q90 ≥ 10,000, 경보 = 분류기(b) p ≥ 0.52(놓침:헛경보 비용비 r=3) |
| 2026 평가 | 평가 타깃 격리 로더·사후 검증 스크립트 | 모델 동결(커밋 13ac483) 후 사후 검증만 수행. 성능 저하도 그대로 기록 |
| 우선순위 | 취수용량 가중 우선순위 | 공식 출처가 없는 가중치는 쓰지 않음. 단계 → 경계 확률 순 |
| 성과 표현 | 2020~2025 경계 사건 20건 중 18건 | 2026 포함 28건 중 25건(89%)·중앙 14일, 2026년 8건 중 7건·중앙 21일로 통일하고 지속성(3건) 병기 |
| 대시보드 | 위험 단계 3색 표시 | 공식 발령 × AI 예상 조합 5단계 라벨(경계 진입 예상·지켜보기·경계 계속될 듯·나아질 가능성·안전), 쉽게 보기 기본 |
| 영상 자료 | CCTV·위성 지수 연계 조사 | 예측 입력에는 쓰지 않음(아래 요약). 향후 과제로 분리 |
| 원단위 고도화(동결 뒤) | 문헌 기반 7종(R1~R7) 실험과 누적 결합, 규칙상 후보 B(전국 통합 학습 + C1 단독 점예측) | B 기각(2025 원단위 R² 0.166 → −0.220). 견고성 대안 C 는 실행 전 등록한 확인 실험 1회로만 판정하도록 정함(조건 충족·채택, 제출 교체는 별도 결정) |

- **검토한 대안·실패 사례**: 원단위 R² 개선 6개 변형×3개 보정 — 어떤 조합도 0.2를 넘지 못함(isotonic 은 악화); 경보 분류기·스태킹·q90 규칙 — 2025 전체 F1 에서 지속성(0.727)을 넘지 못함(진입 구간 재현율·PR-AUC·리드타임에서만 우위); hurdle·tweedie 단일 모델 — CV 에서 C1 과 차이 미미; 물모아 공식 예측 벤치마크 — 단계만 제공돼 분류 비교로 전환(누적 중); 외부 유역강수 CSV — 미수령으로 보류. 동결 뒤 원단위 R² 고도화 7종(EXP-004~010: 분산 반영 원단위 복원, 상류 지점 피처, 속별 모델, 영양염, 전국 82개 경보지점 통합 학습, 수질자동측정망, 희소 사건 재표본·가중) — CV 채택 기준(r2_raw +0.10·rmse_log 악화 0.01 이내·리드 유지)을 넘은 3종도 2025 확인에서 원단위 R² 가 v1(0.166)보다 좋아지지 않음(−0.66~0.16); CV 원단위 R² 는 시드만 바꿔도 ±0.02~0.04, 난수 열을 더해도 +0.04 움직이는 잡음이 있음; 원단위 이득 대부분은 새 정보가 아니라 점예측 방식(로그 공간 앙상블 → 원단위 맞춤 단일 모델)에서 나오고 2025 에서 유지되지 않음; 누적 결합 후보 B(낙동강·금강 통합 학습 + C1 단독, CV +0.150)는 2025 −0.220 으로 기각; 새 정보 계열(영양염·자동측정망·전국 통합)은 2025 에서 효과 없음; 견고성 대안 C(v1 + 상류 피처 + 속별 구성원)는 사전등록 확인 실험에서 CV +0.116(대조군 대비 +0.084)·2025 비열등으로 채택 조건 충족(2025 원단위 R² 0.166 으로 v1 과 같음); Sentinel-2 위성 지표는 기대 이득 대비 비용이 커 보류(상세 reports/experiments/EXP-summary.md, 방법설명서 5.8절).
- **CCTV·위성 영상 연계 검토(미채택) 요약** (상세: `src/docs/13_CCTV_FEASIBILITY.md`, 방법설명서 10장):
  - 5지점 반경 5 km 안에서 수면이 보이는 공개 CCTV는 강정·고령(낙동강홍수통제소 사문진교 3.9 km), 칠서(계내리 1.5 km, 1080p), 물금·매리(월촌리 2.3 km) 3곳뿐이고, 해평(최근접 6.6 km)과 회남(10 km 안에 없음)은 불가로 판정했다.
  - 대시보드에 영상을 직접 붙이는 것은 불가하다. 낙동강 뷰어는 외부 iframe 을 막고(`X-Frame-Options: sameorigin`), 영상 페이지에 공공누리 표시가 없어 기관과 사전 협의가 필요하며, K-water CCTV 는 30초 재생 제한·공공누리 제4유형(변경 금지)이다.
  - 3지점에 한해 정지영상 주기 캡처로 "영상 녹조 색 지수"(녹색 색도·초과녹색·녹색 면적 비율, 야간·역광·강우·카메라 이동 제외 규칙)를 설계했으나, 이 지수는 **예측 모델 입력에 쓰지 않으며** 실측과의 상관은 한 시즌 이상 자료가 쌓인 뒤 평가한다.
  - 비교용 Sentinel-2 NDCI 는 B5(705 nm) 때문에 실효 해상도가 20 m 이며, 2017~2025년 5지점 구축에 약 7~9 반나절이 든다고 추정했다.
- **최종 선택 이유**: CV 복합점수 기준 채택 절차를 고정해 홀드아웃 과적합을 막았고, 운영 목적(발령 선행 판단)에 맞는 지표(log R²·경보 F1·리드타임)로 평가했으며, 재현 가능한 동결 모델과 공개 데이터 스냅샷으로 전 과정을 패키지화했다.

## 6. 라이선스·출처
`data/raw/MANIFEST.md` 참조. DataON 자료(CC BY-NC-SA, 원 배포처 약관상 제3자 제공 금지)는 원 배포 파일(연도별 xlsx)을 넣지 않았고, 원 자료의 DOI와 접속 주소를 MANIFEST(HY-05)에 적었다. 다만 노트북 재현에 필요한 연속 수위 파일 `data/raw/dataon/level_continuous_long.parquet`(24개 관측소, 144,068행)은 포함했다. 이 파일은 DataON 일평균수위(2010~2024) 128,279행에 WAMIS 일수위(2025년 이후, 기준면 오프셋 보정) 15,789행을 이어 붙인 것이다. **[검토 필요: 이 파일 포함이 원 배포처 약관과 충돌하지 않는지 제출 전 확인]** 대회 제공 데이터는 대회 규정에 따라 평가 목적으로만 포함했다.

## 7. 제출 전 확인사항 (공지 #564)
{check_md}
"""


def notebook_text(raw: str) -> str:
    """노트북은 코드·텍스트 출력만 검사한다. 그림 출력(image/*, base64)은 PNG 파일과 같이 이진 자료로 보고 뺀다."""
    try:
        nb = json.loads(raw)
    except ValueError:
        return raw

    def strings(x: object) -> list[str]:
        if isinstance(x, str):
            return [x]
        if isinstance(x, list):
            return [t for v in x for t in strings(v)]
        if isinstance(x, dict):
            return [t for k, v in x.items() if not str(k).startswith("image/") for t in strings(v)]
        return []

    return "\n".join(strings(nb.get("cells", [])))


def scan_secrets(root: Path) -> list[str]:
    hits = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() in SCAN_SKIP_SUFFIX:
            continue
        if p.name == ".env" or p.name.startswith(".env."):
            hits.append(f"{p}: .env 파일 포함")
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if p.suffix.lower() == ".ipynb":
            text = notebook_text(text)
        for pat in SECRET_PATTERNS:
            for m in re.finditer(pat, text):
                ctx = text[max(0, m.start() - 20) : m.start() + 20].replace("\n", " ")
                if (
                    "integrity" in ctx
                    or "sha512-" in ctx
                    or "sha256" in ctx.lower()
                    or "image/png;base64" in ctx
                ):
                    continue
                hits.append(f"{p.relative_to(root)}: /{pat}/ … {ctx[:12]}…")
                break
    return hits


def write_readme(out: Path) -> None:
    frozen = re.search(r"동결 커밋: `([0-9a-f]+)`", (out / "model" / "FROZEN.md").read_text(encoding="utf-8"))
    sizes = {k: dir_size(out / k) for k in ("data", "model", "src", "demo", "figures")}
    pdf = out / "방법설명서.pdf"
    sizes["pdf"] = f"{pdf.stat().st_size / 1e6:.1f} MB" if pdf.exists() else "-"
    vj = ROOT / "reports" / "eval" / "package_verify.json"
    verify = json.loads(vj.read_text(encoding="utf-8")) if vj.exists() else None
    # 1차 작성(체크리스트 계산에 README 존재 여부가 필요) → 체크리스트 반영해 다시 작성
    (out / "README.md").write_text(
        readme(env_info(), frozen.group(1)[:7] if frozen else "?", sizes, "(작성 중)"), encoding="utf-8"
    )
    (out / "README.md").write_text(
        readme(env_info(), frozen.group(1)[:7] if frozen else "?", sizes, checklist(out, verify)),
        encoding="utf-8",
    )


def security(out: Path) -> list[str]:
    hits = scan_secrets(out)
    (out / "scripts").mkdir(exist_ok=True)
    (out / "scripts" / "security_scan.txt").write_text(
        ("민감정보 검사 결과: 0건\n" if not hits else "\n".join(hits) + "\n"), encoding="utf-8"
    )
    print("민감정보 검사:", "0건" if not hits else f"{len(hits)}건\n" + "\n".join(hits[:10]))
    return hits


def build(out: Path) -> int:
    demo_src = demo_sources()  # 먼저 확인 — 영상이 없으면 아무것도 지우지 않고 중단
    pdf_src = ROOT / "reports" / "방법설명서.pdf"
    if not pdf_src.exists():
        raise SystemExit(f"빌드 중단: {pdf_src} 가 없다(방법설명서 PDF 를 먼저 만든다).")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    # data
    copy(ROOT / "data" / "raw" / "competition", out / "data" / "raw" / "competition")
    for f in RAW_FILES:
        src = ROOT / "data" / "raw" / f
        if src.exists():
            copy(src, out / "data" / "raw" / f)
    copy(ROOT / "data" / "raw" / "kma_forecast", out / "data" / "raw" / "kma_forecast")
    for sub in ("interim", "processed"):
        (out / "data" / sub).mkdir(parents=True, exist_ok=True)
        (out / "data" / sub / ".gitkeep").write_text("", encoding="utf-8")
    # model/ (동결 모델 — 코드가 model/ 을 읽도록 algaecast.config 가 패키지 구조를 감지)
    reg = json.loads((ROOT / "models" / "registry.json").read_text(encoding="utf-8"))
    for name, ver in reg["current"].items():
        copy(ROOT / "models" / name / ver, out / "model" / name / ver)
    copy(ROOT / "models" / "registry.json", out / "model" / "registry.json")
    copy(ROOT / "models" / "FROZEN.md", out / "model" / "FROZEN.md")
    # src/ (필요 모듈) + src/config/ + src/docs/
    pkg = ROOT / "src" / "algaecast"
    for p in pkg.rglob("*.py"):
        rel = p.relative_to(pkg)
        if rel.parts and rel.parts[0] in SRC_SKIP:
            continue
        if p.name in SRC_SKIP_FILES:
            continue
        copy(p, out / "src" / "algaecast" / rel)
    copy(
        pkg / "db" / "upload.py", out / "src" / "algaecast" / "db" / "upload.py"
    )  # predict_registry() 경량 사본
    (out / "src" / "algaecast" / "db" / "__init__.py").write_text(
        '"""DB 업로드 코드 — 재현에서는 predict_registry() 만 사용(Supabase 미사용)."""\n', encoding="utf-8"
    )
    for f in CONFIG_FILES:
        if (ROOT / "config" / f).exists():
            copy(ROOT / "config" / f, out / "src" / "config" / f)
    copy(ROOT / "docs", out / "src" / "docs")
    copy(ROOT / "pyproject.toml", out / "pyproject.toml")
    for s in SCRIPTS:
        copy(ROOT / "scripts" / s, out / "scripts" / s)
    # notebooks (실행본은 verify_package.py --update-package 가 새 venv 실행 결과로 덮어씀)
    for f in ("01_train_eval.ipynb", "01_train_eval.py"):
        copy(ROOT / "notebooks" / f, out / "notebooks" / f)
    # 루트 파일
    copy(ROOT / "submission" / "submission.csv", out / "submission.csv")
    copy(pdf_src, out / "방법설명서.pdf")
    # figures/
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
    for f in (ROOT / "figures").glob("*.png"):
        copy(f, out / "figures" / f.name)
    final = ROOT / "reports" / "screenshots" / "final"
    for f in sorted(final.glob("*.png")):
        copy(f, out / "figures" / f"dashboard_{f.name}")
    for d in ("eval", "eda", "features", "experiments"):
        copy(ROOT / "reports" / d, out / "figures" / "reports" / d)
    # demo/ — 루트 demo/ 에서 허용 목록만(raw/·tools/·.gitignore·*.webm 제외)
    for f in DEMO_FILES:
        copy(demo_src / f, out / "demo" / f)
    copy(demo_src / "captures", out / "demo" / "captures")
    # requirements / README / 민감정보
    (out / "requirements.txt").write_text(pip_freeze(), encoding="utf-8")
    write_readme(out)
    security(out)
    write_readme(out)  # 검사 결과를 README 에 반영한 뒤, README 를 포함해 다시 검사
    hits = security(out)
    print(f"패키지 {out} 총 {dir_size(out)}")
    print("루트:", sorted(p.name for p in out.iterdir()))
    return 1 if hits else 0


def make_zips(out: Path) -> int:
    mp4 = out / "demo" / "AlgaeCast_demo.mp4"
    if not mp4.exists() or not sha256(mp4).startswith(DEMO_SHA_PREFIX):
        raise SystemExit("zip 중단: 패키지 데모 영상이 없거나 sha256 이 승인본과 다르다.")
    write_readme(out)  # 체크리스트에 최신 검증 결과 반영
    security(out)
    write_readme(out)
    if security(out):
        return 1
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    files = sorted(p for p in out.rglob("*") if p.is_file())
    for name, keep in ((ZIP_NAME, lambda p: True), (ZIP_NOVIDEO, lambda p: p != mp4)):
        zpath = dist / name
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for p in files:
                if keep(p):
                    z.write(p, Path(PKG_NAME) / p.relative_to(out))
            if name == ZIP_NOVIDEO:
                z.writestr(
                    f"{PKG_NAME}/demo/영상_별도_안내.txt",
                    f"데모 영상 AlgaeCast_demo.mp4(2분 28초, {mp4.stat().st_size / 1e6:.1f} MB, sha256 {sha256(mp4)})는 "
                    f"용량 제한에 대비해 이 zip 에서 제외했다. 영상 포함본: {ZIP_NAME}\n",
                )
        print(f"zip {zpath.name} {zpath.stat().st_size / 1e6:.1f} MB sha256 {sha256(zpath)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "submission_package")
    ap.add_argument(
        "--zip-only", action="store_true", help="기존 패키지에서 README 갱신·민감정보 재검사·zip 2개만"
    )
    args = ap.parse_args(argv)
    if args.zip_only:
        return make_zips(args.out)
    return build(args.out)


if __name__ == "__main__":
    raise SystemExit(main())
