# ruff: noqa: E501  (README·안내 문구의 긴 한국어 줄)
"""공식 제출 패키지 생성 (T9-b, 2026-10-21 공지 #564 구조로 정리).

패키지 루트(공지 #564): README.md, data/, model/, src/, notebooks/, scripts/, demo/, figures/
  + 루트 파일: submission.csv(제출 파일), 방법설명서.pdf, requirements.txt(pip freeze), pyproject.toml(설치용)
- data/   : 대회 번들 + 외부 수집 원천 parquet + MANIFEST.md (git 미포함, 패키지 전용)
- model/  : 재현에 불러오는 동결 모델 폴더만(PACKAGE_MODEL_DIRS = registry current v2.1 회귀·분류기·분위)
            + registry.json(current 그대로, 패키지에 없는 이력 항목에 "package" 표시) + 동결 문서 3종(sha256)
            + HISTORY.md(뺀 이력 모델 폴더의 파일별 sha256·동결 커밋·재학습 명령·제공 방법)
- src/    : 파이썬 패키지 algaecast(재현에 필요한 코드만) + src/config/(설정) + src/docs/(설계 문서)
- scripts/: verify_frozen.py, leakage_audit.py, verify_package.py
- demo/   : 저장소 루트 demo/ 에서 복사(AlgaeCast_demo.mp4·.srt·script.md·README_DEMO.md·captures/). raw/·tools/·.gitignore·*.webm 제외.
            루트 demo/ 에 mp4 가 없으면 빌드를 중단한다(자리표시로 대체하지 않음).
- figures/: 핵심 그림 + 대시보드 스크린샷 + figures/reports/(eval·eda·features·experiments 표 — 방법설명서 각주의 원천)

사용(3단계):
  1) python scripts/build_submission_package.py             # 패키지 생성(+민감정보 검사)
  2) python scripts/verify_package.py --update-package      # 새 venv 재현(diff 0·노트북 오류 0·데모 sha256) → 실행본 ipynb 를 패키지에 반영
  3) python scripts/build_submission_package.py --zip-only  # README 체크리스트를 검증 결과로 갱신 → 민감정보 재검사 → 모델자료 zip 2개 → 문서자료 zip 2개(A안·B안)
     (모델자료 = 영상 포함·영상 제외, 둘 다 DataON 원값 포함 — 운영사무국 답변 2026-10-28 '결과물 data/ 에 포함 가능')
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
# 제출란 두 칸(공지 2026-10-27): ① 문서자료(필수) ② 모델자료. 둘 다 최상위 폴더 하나인 zip.
ZIP_NAME = "AlgaeCast_모델자료_이재행.zip"  # 모델자료 기본(영상 포함) — 2026-10-27 전 이름 AlgaeCast_녹조7일예측_이재행.zip
ZIP_NOVIDEO = "AlgaeCast_모델자료_영상제외_이재행.zip"  # 모델자료 업로드가 용량 때문에 실패할 때
# 2026-10-28 전에는 DataON 원값을 기본 zip 에서 빼고 대체 zip AlgaeCast_녹조7일예측_이재행_with_dataon.zip 에만 넣었다.
# 운영사무국 답변(2026-10-28, '결과물 data/ 폴더에 원자료 포함 가능')으로 모델자료 zip 2종 모두에 넣고 대체 zip 은 없앴다.
DATAON_ANSWER = (
    "운영사무국 답변(2026-10-28): DataON 원자료(일평균수위 원값)를 결과물 data/ 폴더에 포함해 제출 가능"
)
DOC_PKG = "AlgaeCast_문서자료_이재행"  # 문서자료 zip 의 최상위 폴더(A안·B안 같음)
ZIP_DOC = f"{DOC_PKG}.zip"  # 문서자료 A안: 방법설명서.pdf + 읽어보기.txt — 모델자료(영상 포함)와 짝
ZIP_DOC_VIDEO = (
    "AlgaeCast_문서자료_영상포함_이재행.zip"  # B안: A안 + demo/ 영상·README_DEMO — 모델자료 영상제외와 짝
)
DASHBOARD_URL = "https://algaecast-7.vercel.app"
# 다시 보기 장면 3개(web/src/lib/replay.ts SCENES, 방법설명서 8.4절)
REPLAY_SCENES = (
    ("2026-07-27", "강정·고령 경계 진입 7일 전(그날 경보 단계)"),
    ("2026-08-03", "같은 사건의 첫 초과일"),
    ("2026-07-06", "회남 경계 사건 7일 전(그날 안전 — 미리 알리지 못한 사례)"),
)
# DataON 원값(CC BY-NC-SA)이 든 연속 수위 시계열(DataON ≤2024 + 같은 관측소 WAMIS 일수위 2025~, 기준면 오프셋 보정)
# — 패키지에 넣고 노트북은 이 원자료로 수위 피처를 계산한다(level_cont_mode = raw)
DATAON_RAW_FILE = "dataon/level_continuous_long.parquet"
# DataON 가공 수위 피처(level_cont_t0·level_cont_diff7) — 원자료로 계산한 값과 같은지 대조용으로 함께 둔다
LEVEL_FEATURE_FILE = "level_cont_features_S1.parquet"
# WAMIS 원값 — 기본 패키지에서 뺀다(회원약관 제15조④ 적용 여부가 분명하지 않아 원값 재배포 안 함).
# wamis_dam/ 는 통째로, hydro_daily_long 은 WAMIS 출처 행만 뺀 사본을 넣고 가공 수문 피처 파일로 재현한다.
WAMIS_SOURCES = ("wamis_mn_dtdata", "wamis_wl_dtdata")
WAMIS_FEATURE_FILE = "wamis_hydro_features_S1.parquet"
DEMO_SHA_PREFIX = "0907b110"  # 2026-10-23 v6(성능 페이지 3장면 재녹화). 이전: v1 6a0d78e3·v2a 43761cbc·v3 5363e22a·v4 0a1fb2f4·v5 87b6d928 → dist/backup_demo_2026102*
# DataON 유래 파일이 있는(또는 노트북 실행으로 생기는) 폴더 — LICENSE_DataON.txt 를 붙인다
DATAON_DIRS = ("data/raw/dataon", "data/interim", "data/processed", "src/config")
DEMO_FILES = ["AlgaeCast_demo.mp4", "AlgaeCast_demo.srt", "script.md", "README_DEMO.md"]
# 공공 API 조류 스냅샷(nier_algae/)은 넣지 않는다 — 패키지 재현은 예측 대상 5지점 조류를 대회 번들 algae_measure.csv 에서
# 읽고(collect/algae_source.py, features.yaml algae_source: auto), 상류 피처의 바로 위 지점(HP·GJGR·CS)도 모두 이 5지점 안이라
# API 파일에서 5지점 행을 빼면 남는 행이 없다.
API_ALGAE_DIR = "nier_algae"
MANIFEST_PACKAGE_NOTE = (
    "> 제출 패키지 사본 주(빌더가 붙임): 아래 WQ-01·WQ-01b(공공데이터포털 조류경보 API 스냅샷 `data/raw/nier_algae/`·"
    "`nier_algae_all/`) 파일은 이 패키지에 없다. 패키지 재현은 예측 대상 5지점 조류(상류 피처의 바로 위 지점도 이 5지점 안)를 "
    "대회 번들 `data/raw/competition/` 의 `algae_measure.csv` 에서 읽는다. API 조류는 대시보드 일일 운영에만 쓴다. "
    "WAMIS 원값(`wamis_dam/`·`hydro_daily_long` 의 WAMIS 행)은 패키지에 없고, DataON 연속 수위 원값은 "
    "`data/raw/dataon/` 에 있다(README §1·§2·§6).\n"
)


def package_manifest_text(text: str) -> str:
    """패키지에 넣는 MANIFEST 사본: 첫 제목 줄 바로 아래에 패키지 사본 주를 붙인다(저장소 MANIFEST 는 그대로)."""
    head, sep, rest = text.partition("\n")
    if head.startswith("#"):
        return f"{head}\n\n{MANIFEST_PACKAGE_NOTE}{sep}{rest}"
    return f"{MANIFEST_PACKAGE_NOTE}\n{text}"


RAW_FILES = [
    "kma_asos/kma_asos_daily_2012_2026.parquet",
    "kwater_sluice/kwater_sluice_daily.parquet",
    "kwater_damapi/kwater_damapi_recent.parquet",
    "MANIFEST.md",
]
CONFIG_FILES = [
    "sites.yaml",
    "features.yaml",
    "model.yaml",
    "seed.yaml",
    "dam_codes.json",
    "level_cont_stats.json",
    "derived_constants.json",  # 데이터 유래 상수(연도별 수온 임계·선택 결정) — 계산 자료 메타데이터 포함
]
SRC_SKIP = {"db", "predict"}  # 대시보드 업로드·일일 운영 코드는 재현에 불필요
SRC_SKIP_FILES = {
    "live.py",
    "posthoc.py",
    "posthoc_v2.py",
    "posthoc_v21.py",
    "posthoc_v21_detail.py",
    "posthoc_metrics_by_definition.py",  # 회귀 지표 정의별 표(2026 사후 예측 재집계)
    "posthoc_answer_source.py",  # 2026 사후 분석 정답 출처 점검(번들 끝 이후 측정 의존 여부)
    "posthoc_t24.py",  # 비상안 T24 모델 2026 사후(동결 뒤 1회)
}  # test 타깃 로더·사후 검증(전용) — 패키지에서 제외
SCRIPTS = ["verify_frozen.py", "leakage_audit.py", "verify_package.py"]
# 패키지 model/ 에 넣는 모델 폴더 — 재현에 실제로 불러오는 것만(2026-10-23 추적: make_submission·노트북 모두
# registry current 3개 폴더의 model.pkl 만 모델로 불러오고, 나머지 동결 폴더는 verify_frozen 의 sha256 읽기뿐).
# scripts/verify_package.py 의 PACKAGE_MODEL_DIRS 와 같아야 한다(tests/test_package_config.py).
PACKAGE_MODEL_DIRS = (
    "regression/20261023_120818",  # v2.1 회귀(제출·운영)
    "classifier/20261023_120255",  # v2.1 경보 분류기 b
    "quantile/20261023_120257",  # v2.1 분위 회귀
)
FROZEN_DOCS = ("FROZEN.md", "FROZEN_v2.md", "FROZEN_v2.1.md")
FROZEN_ROW = re.compile(r"\| (\w+) \| (\d+_\d+) \| `([0-9a-f]{64})` \|")
HISTORY_DOC = "HISTORY.md"  # 뺀 이력 모델 목록(models/HISTORY.md → model/HISTORY.md)
HISTORY_FILE_ROW = re.compile(r"\| `(\w+/\d+_\d+/[\w.]+)` \| `([0-9a-f]{64})` \|")
HISTORY_MARK = "미포함(이력) — model/HISTORY.md"
# 실험 중간 산출물(재현·근거에 쓰지 않음): 칼만 모수 추적, API 탐침, 설정 조각, 재실행 로그·설정 사본·원자료 표
EXP_INTERMEDIATE = (
    "params_*.csv",
    "probe.json",
    "sites_snippet.yaml",
    "*.log",
    "model_yaml_*.yaml",
    "*_v21.csv",
)
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
RAW_NOTE = "원본 녹화(노트북 전체 실행 약 20분·운영 화면 장면별)는 용량 때문에 제출 패키지에서는 제외했으며, 요청 시 제공한다."


def copy(src: Path, dst: Path, extra_ignore: tuple[str, ...] = ()) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(
            src,
            dst,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".ipynb_checkpoints", *extra_ignore),
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
            f"새 venv 재실행 오류 {v.get('notebook_errors', '미실행')}건, submission.csv 가 패키지 제출 파일과 바이트 동일={v.get('submission_identical', '미실행')}, 소요 {v.get('minutes', '-')}분 ({v.get('when', '-')})",
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
            "5절 (활용 도구·참가자 기여·검토 과정, 참가자 최종 검토)",
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


def readme(info: dict, frozen: dict[str, str], sizes: dict[str, str], check_md: str) -> str:
    """제출 패키지 README. frozen = 동결 커밋 앞 7자 {"v1": FROZEN.md, "v2": FROZEN_v2.md, "v2.1": FROZEN_v2.1.md}."""
    return f"""# AlgaeCast-7 — 수질·수문·기상 융합 기반 댐·하천 유해남조류 7일 예측 (제출 패키지)

2026 DATA·AI 분석 경진대회(KISTI) 문제해결 부문 · 참가자 이재행 · 생성일 {date.today()}

## 0. 심사위원용 1쪽 요약

**7일 앞 녹조 위험을 감시·경보 두 단계로 알려 주는 운영 시스템**

**핵심 수치**
- **2026년 경계 사건 8건 중 7건을 중앙 21일 앞서 감시 단계로 포착**(지속성 2건)
- **2020~2026년 경계 사건 28건 중 24건(86%) 포착**(중앙 14일, 지속성 3건)
- 2025 홀드아웃(252행): 로그 R² 0.78 · 로그 RMSE 0.71
- 2026(124조합): 로그 RMSE 0.72(지속성 0.90)
- 2025년까지 자료로만 학습했다. 2026년 값은 동결 뒤 1회 계산한 사후 결과다(블라인드 아님).

> **목표 R² 0.6에 대해**
> 1. 원단위 R²는 2025년 0.175, 2026년 0.001로 목표에 못 미쳤다.
> 2. 봉우리 1건이 2025년 원단위 분산의 43%를 차지하고, 측정 잡음만으로도 원단위 R² 기대 상한(중앙값)이 0.36~0.47이다.
> 3. 그래서 로그 오차·경계 사건 선행 포착·리드타임 같은 운영 지표로 가치를 입증했다.

**차별점**
1. 매일 05시(KST) 예약 실행으로 자동 갱신되는 관제 상황판 — https://algaecast-7.vercel.app. ‘다시 보기’로 2026년 8월 급증기 화면 확인 가능(사후 재현)
2. 감시(CQR 보정 q90 ≥ 1만 cells/mL)·경보(분류기 확률 ≥ 0.46) 두 단계 알림
3. 당일 측정의 가치(방법설명서 6.12절): 기준일 측정을 쓰면 2025 경계 F1 0.53→0.70. 당일 발령 확대(2026 녹조계절관리제)는 예측의 가치도 높이며, 이 시스템은 녹조 대응 체계의 예측·조기경보 기능 원형이다(방법설명서 7.7절).

**데이터·재현** 제출 재현 경로의 조류 자료는 대회 번들만 사용(외부 조류 자료 없음). 재현은 4절의 3줄이며, 설치 후 인터넷 없이 재현되고 `submission.csv` sha256 `4741a3d3…` 가 같다. 제출 모델 v2.1(동결 커밋 `{frozen['v2.1']}`, 회귀 model.pkl sha256 `d95e7a4e…`).

**버전 이력**: 방법설명서 부록 B 참조.

## 1. 구성 (공지 #564 구조)
제출은 두 칸으로 나뉜다. 문서자료(방법설명서 PDF·읽어보기)와 모델자료(이 패키지)다. 기본 조합은 문서자료 `{ZIP_DOC}` + 모델자료 `{ZIP_NAME}`이다. 모델자료 업로드가 용량 때문에 안 되면 문서자료 `{ZIP_DOC_VIDEO}`(데모 영상 포함) + 모델자료 `{ZIP_NOVIDEO}`(영상제외판)로 낸다.

| 위치 | 내용 | 크기 |
|---|---|---|
| `README.md` | 이 문서(구성·데이터·모델·실행환경·설치·실행·AI 활용·제출 전 확인사항) | |
| `submission.csv` | 제출 파일 = 제출·운영 모델 v2.1 예측(124행, `station_id,base_date,target_date,pred_cells`, UTF-8 BOM, 예시와 같은 행 순서). 이전 제출 후보(submission.csv)는 저장소에 보존(v1 태그 `v1-submission`, v2 동결 커밋 `{frozen['v2']}`) | |
| `방법설명서.pdf` | 방법 설명서(문서자료와 같은 PDF — 1쪽 요약, 제출 양식 항목 대응표, 배경·데이터·통계분석·피처·모델·평가·설명가능성·시스템·재현·한계·기대효과 11장, 부록 A~C) | {sizes.get('pdf', '-')} |
| `requirements.txt` · `pyproject.toml` | 라이브러리 정확한 버전(pip freeze) · 패키지 설치 정보 | |
| `data/` | 대회 번들(`data/raw/competition/`, 심사용 — 공개 시 제외·대회 종료 후 폐기, `README_심사용_공개시제외.txt`) + 외부 공공 데이터 스냅샷(parquet; 조류경보 API 스냅샷은 미포함 — 조류는 대회 번들 사용; WAMIS 원값 제외 — `data/raw/hydro/hydro_daily_long.parquet` 는 WAMIS 출처 행을 뺀 사본) + DataON 연속 수위 원값(`data/raw/dataon/level_continuous_long.parquet` — DataON 2010~2024 + 같은 관측소 WAMIS 일수위 2025~, 운영사무국 답변 2026-10-28 '포함 가능', 노트북이 이 원자료로 수위 피처 계산)과 대조용 가공 수위 피처(`data/processed/level_cont_features_S1.parquet`) + WAMIS 가공 수문 피처(`data/processed/wamis_hydro_features_S1.parquet`, 33열; WAMIS 원값은 미포함, 받는 법 `data/raw/hydro/README_GET_WAMIS.md`) + `data/raw/MANIFEST.md`(출처·수집일시·라이선스) | {sizes.get('data', '-')} |
| `model/` | 동결 모델: **v2.1**(제출·운영, 데이터 유래 상수 누수 수정판 — 회귀·경보 분류기·분위 회귀 {' · '.join(f'`{d}`' for d in PACKAGE_MODEL_DIRS)}, 재현에 불러오는 모델은 이 3개뿐) + `registry.json`(current = v2.1) + `FROZEN_v2.1.md`(v2.1 sha256, 동결 커밋 `{frozen['v2.1']}`). 이력 모델 파일(수정 전 v1 회귀·분류기·분위, v2 회귀, 민감도용 v1-fix 회귀 — 5개 폴더)은 재현에 쓰지 않아 넣지 않았다: 폴더별 sha256·동결 커밋·재학습 명령·제공 방법(요청 시 제공)은 `HISTORY.md`. 동결 문서 `FROZEN.md`(v1, 동결 커밋 `{frozen['v1']}`)·`FROZEN_v2.md`(v2, 동결 커밋 `{frozen['v2']}`)는 기록으로 남김 | {sizes.get('model', '-')} |
| `src/` | 파이썬 패키지 `algaecast`(정렬·피처·모델·평가, 재현에 필요한 코드만) + `src/config/`(지점·피처·모델·시드 설정, `seed.yaml`=42, `derived_constants.json` — 데이터 유래 상수와 계산 자료 메타데이터) + `src/docs/`(설계 문서) | {sizes.get('src', '-')} |
| `notebooks/01_train_eval.ipynb` | 동결 모델 검증(`FROZEN.md`·`FROZEN_v2.md`·`FROZEN_v2.1.md` — 제출 모델은 파일 해시, 패키지에 없는 이력 모델은 `model/HISTORY.md` 해시 대조) → 데이터 로드·전처리 → 피처(+ 상류 피처) → 학습(동결 파라미터, v2.1·비교용 v1-fix) → 2025 검증 지표(v2.1·v1-fix 나란히) → `submission.csv`(v2.1) 생성 → 그림. 실행 결과(출력) 포함 | |
| `scripts/` | `verify_frozen.py`(세 동결 문서 해시 검증 — 제출 모델 3개는 파일이 있어야 하고, 이력 모델은 '패키지 미포함(이력, model/HISTORY.md)'으로 표시), `leakage_audit.py`(누수 감사, 원자료부터 재계산 포함), `verify_package.py`(새 venv 재현 검증, `model/` 허용 폴더 점검), `security_scan.txt` | |
| `demo/` | 데모 영상 `AlgaeCast_demo.mp4`(2분 28초, 1080p H.264, 한국어 자막) · `AlgaeCast_demo.srt` · `script.md`(콘티) · `README_DEMO.md`(구성·편집 내역) · `captures/`(장면 캡처 6장). {RAW_NOTE} | {sizes.get('demo', '-')} |
| `figures/` | 방법설명서·발표용 핵심 그림, 대시보드 스크린샷(`dashboard_*.png`), `figures/reports/`(평가·통계 표 원본 — 방법설명서 각주의 출처) | {sizes.get('figures', '-')} |

## 2. 데이터·모델 요약
- 타깃: 조류경보제 5지점(해평·강정고령·칠서·물금매리·회남) 유해남조류 세포수(cells/mL), 기준일(base_date)+7일(±3일 매칭) 예측.
- 조류 원천: 예측 대상 지점 조류 = 대회 번들(`algae_measure.csv`). 상류 지점 조류도 대회 번들이다(상류 피처의 바로 위 지점 해평·강정고령·칠서가 모두 예측 대상 5지점 안이라 같은 파일, 기준일 이전 값만). 공공데이터포털 조류경보 API 는 대시보드 일일 운영에만 쓰고 패키지에 넣지 않았다(겹치는 기간 값은 번들과 같음, 방법설명서 2장·9.1절).
- 입력: 조류경보제 측정(국립환경과학원), 댐·보 운영(K-water delist·WAMIS — WAMIS 원값은 기본 패키지에 넣지 않고 수문 피처 33열 가공 파일만 포함, 받는 법 `data/raw/hydro/README_GET_WAMIS.md`), 댐유역 하천 일평균수위(**DataON** 국가참조표준 DOI 10.20925/KSRD.74670854.v5, CC BY-NC-SA — 운영사무국 답변(2026-10-28)에 따라 연속 수위 원값을 `data/raw/dataon/` 에 포함, `LICENSE_DataON.txt` 첨부), ASOS 기상(기상청), 단기·중기예보(2026-10-21 이후 누적). AIDA 정규격자 자료는 계획했으나 미사용(기상 입력은 ASOS 관측소로 대체).
- 모델: **제출·운영 모델 v2.1**(2026-10-23 동결, 커밋 `{frozen['v2.1']}`, 데이터 유래 상수 누수 수정판) = LightGBM 변형 3종(log 가중 회귀 C1 · hurdle C3 · tweedie C2, v1 하이퍼파라미터)에 속별 구성원 cg(Microcystis + 나머지 3속)를 더한 log10 공간 NNLS 앙상블(제출용 세포수, 가중치 c1 0.055 · c3 0.280 · c2 0.267 · cg 0.398) + 경계(+4~+10일 ≥10,000) 분류기(경보 확률, 운영점 p ≥ 0.46 = 놓침:헛경보 비용비 r=3) + 분위 회귀 q10/50/90(CQR 보정 q̂ 0.165, 감시 규칙 q90 ≥ 10,000). 회귀 피처 35개 = 선별 30개(VIF·Boruta) + 상류 지점 피처 5열(바로 위 지점의 최근 측정, 해평·회남 결측). 분류기·분위·CQR·운영점도 수정 피처로 다시 적합했다. 데이터로 계산한 상수는 기준일까지(as-of) 또는 학습기간 자료로만 쓴다: 수위 편차 = 관측소별 직전 365일 평균 대비, 지점별 수온 임계 = 학습기간 측정만(폴드마다, 최종 ≤2025, `src/config/derived_constants.json`). 이력(수정 전): v1(2026-10-21 봉인, 커밋 `{frozen['v1']}`, 같은 3종 NNLS 앙상블·피처 30개), v2(2026-10-22 동결, 커밋 `{frozen['v2']}`, v2.1 과 같은 구성), v1-fix(v1 구성 + 수정 피처, 민감도용) — 이력 모델 파일은 재현에 쓰지 않아 패키지에 넣지 않았다(`model/HISTORY.md`: sha256·재학습 명령, 요청 시 제공).
- 검증: 연도 expanding-window CV(2020~2024) → 2025 홀드아웃(목표일 ≤2025-12-31 인 252행) → v1 동결(2026-10-21) → v2 사전등록 확인 실험(EXP-confirm)으로 채택·동결(2026-10-22) → 2026-10-23 데이터 유래 상수 전수 점검에서 누수 발견 → 사전등록(FIX-v2.1) 규칙대로 고친 v2.1 을 결과와 무관하게 채택·동결 → 2026 사후 계산(v2.1 동결 뒤 1회. 모델 선택·수정 규칙에 2026 미사용, 단 팀은 v1·v2 의 2026 결과를 이미 봤으므로 블라인드 아님). 누수 감사: 기준일까지 잘라낸 달력 재계산 표본 300·원자료부터 재계산 표본 60 불일치 0, 예전 방식 음성 대조 5/5 검출, 데이터 유래 상수 테스트 15개.
- 핵심 결과: 2025 홀드아웃(같은 252행) v2.1 rmse_log 0.712 · log R² 0.778 · 원단위 R² 0.175 · 경계 F1 0.705(지속성 F1 0.727, 봉우리 1건이 분산의 43%). **2025년까지 자료로만 만든 모델(v2.1)로 2026년 경계 사건 8건 중 7건을 중앙 21일 앞서 감시 단계로 포착(지속성 2건)**, **2020~2026년 합계 28건 중 24건(86%)을 첫 경계 초과 측정 기준 중앙 14일 앞서 포착(지속성 3건)**. 2026 test 124조합: v2.1 log R² 0.520 · 원단위 R² 0.001 · F1@10k 0.826(지속성 F1 0.841). 누수 수정: 이전 모델 v1·v2 가 일부 데이터 유래 상수(수위 편차 관측소 평균·지점별 수온 임계·ASOS 관측소 선정)를 2026 자료까지 포함해 계산했음을 2026-10-23 사후 발견해 사전등록 규칙대로 고쳤다(경위와 수정 전후 비교는 방법설명서 5.11절). v1 봉인본의 2026 7/8 은 이력으로만 남긴다. 2026 사후 성능 저하와 한계는 방법설명서 5.11절·6.11절·10장.

- 회귀 지표 정의별(방법설명서 표 6-1c, 지점 평균 = 5지점 단순 평균):

  | 지표 | 집계 | 2025 v2.1 | 2025 지속성 | 2026 v2.1 | 2026 지속성 |
  |---|---|---|---|---|---|
  | 원단위 결정계수(=NSE) | 통합 / 지점 평균 | 0.175 / 0.099 | −0.283 / −0.378 | 0.001 / −0.033 | −0.302 / −0.529 |
  | 원단위 상관계수 제곱 | 통합 / 지점 평균 | 0.204 / 0.292 | 0.148 / 0.162 | 0.100 / 0.201 | 0.120 / 0.090 |
  | 로그 RMSE | 통합 / 지점 평균 | 0.712 / 0.707 | 0.896 / 0.891 | 0.718 / 0.702 | 0.902 / 0.879 |
  | 로그 MAE | 통합 / 지점 평균 | 0.537 / 0.534 | 0.591 / 0.587 | 0.549 / 0.549 | 0.633 / 0.634 |

  원단위 설명력은 정의·집계·해에 따라 −0.03~0.29로 흔들리고 모두 0.6 아래(2026 통합 r²는 지속성이 더 높음)지만, 로그 RMSE는 두 해 모두 지속성보다 약 20% 작다.

> **DataON 활용과 기여** — 국가참조표준 「댐유역 하천 일평균수위」(K-water, DOI 10.20925/KSRD.74670854.v5, CC BY-NC-SA)로 5지점 상류 관측소 23곳의 연속 수위 피처 2개(`level_cont_t0` 기준일 수위 편차, `level_cont_diff7` 7일 변화, 직전 365일 평균 대비)를 만들어 회귀·분류기·분위에 넣었다. DataON 범위(≤2024) 뒤는 같은 관측소의 WAMIS 일수위를 2020~2024 겹침 구간 중앙값 오프셋으로 이어 붙였고(2026 기준일은 365일 창이 모두 WAMIS 라 제출 124행 값은 DataON 원값과 무관), 일일 운영도 같은 정의로 계산한다. 원 배포처 약관에 사전 허가 없는 배포 제한 문구가 있어 운영사무국에 문의했고, '결과물 data/ 폴더에 원자료 포함 가능'이라는 답변(2026-10-28)에 따라 연속 수위 원값(`data/raw/dataon/level_continuous_long.parquet`)을 넣었다. 노트북은 이 원자료로 두 피처를 계산하고, 결과는 가공 파일(`data/processed/level_cont_features_S1.parquet`)과 같다(바이트 동일 재현). 원 배포 xlsx 부터 다시 만드는 경로는 `data/raw/dataon/README_GET_DATAON.md`. 기여: 문제 설명서가 제안한 '하천 구간 수위 보강으로 체류시간 대리변수의 설명력 제고' 가설을 동결 파이프라인으로 검증했다. 두 피처를 뺀 비교(2026 미계산)에서 CV rmse_log 0.7917→0.7919, 2025 rmse_log 0.7120→0.7100, 감시 포착 17→18/20 으로 차이가 부트스트랩 95% 구간 안이라 정확도 기여는 확인되지 않았다. DataON 은 학습기간 상류 23개 관측소의 연속 수위를 제공해, 운영(WAMIS)과 같은 정의의 피처로 학습할 수 있게 했다(방법설명서 2.4절 상자).

## 3. 실행 환경
- OS {info['os']}, Python {info['python']}, lightgbm {info['lightgbm']}, scikit-learn {info['scikit-learn']}, pandas {info['pandas']}, numpy {info['numpy']}, jupyterlab {info['jupyterlab']}. **GPU 미사용(CPU 전용)**.
- 정확한 라이브러리 버전: `requirements.txt`(pip freeze, jupyterlab·ipykernel 포함).
- **오프라인 재현**: 패키지 설치 후 인터넷 없이 재현 가능, 결과 sha256 동일(2026-10-26 확인 — 새 venv 설치 뒤 네트워크를 막은 상태에서 노트북 전체 실행, `submission.csv` sha256 `4741a3d3…`, 외부 접속 시도 0건).

## 4. 설치·실행
```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt   # Linux/mac: .venv/bin/python
.venv/Scripts/python -m pip install -e . --no-deps
.venv/Scripts/python -m jupytext --to notebook --execute notebooks/01_train_eval.py   # → submission.csv, figures/
```
- 화면에서 셀 단위로 실행해 보려면: `.venv/Scripts/jupyter lab notebooks/01_train_eval.ipynb` (위 2줄 설치 후).
- 재현 소요 시간: 약 20분(대부분 피처 생성, 8코어 CPU 기준). 다시 만든 `submission.csv` 는 패키지 루트 제출 파일과 바이트 동일(`scripts/verify_package.py` 로 새 가상환경에서 확인).
- **DataON 수위는 원자료로 계산한다.** 노트북은 `data/raw/dataon/level_continuous_long.parquet`(DataON 원값 포함 연속 시계열)로 수위 피처 2열(`level_cont_t0`·`level_cont_diff7`)을 만든다. 가공 파일 `data/processed/level_cont_features_S1.parquet` 는 대조용이며, 원자료 파일을 치우면 노트북이 이 파일로 두 열을 채워 같은 `submission.csv` 를 만든다. 원 배포 xlsx 부터 다시 만드는 경로는 `data/raw/dataon/README_GET_DATAON.md`.
- **WAMIS 원자료도 재현에 필요 없다.** 수문 피처 33열은 `data/processed/wamis_hydro_features_S1.parquet` 에서 채운다. `data/raw/hydro/hydro_daily_long.parquet` 는 WAMIS 출처 행을 뺀 사본(K-water delist·다목적댐·대회 번들 행)이다. 원자료부터 다시 만드는 경로와 같은 값을 받는 공식 경로(공공데이터포털 #3068550·#3040409)는 `data/raw/hydro/README_GET_WAMIS.md`.
- **외부 API는 재현에 필요 없다.** `data/` 스냅샷만 사용한다. 공공 API 키(.env)는 대시보드 일일 운영(GitHub Actions)에만 쓰이며 패키지에 포함되지 않는다.
- 대시보드(운영 데모): https://algaecast-7.vercel.app · 코드 저장소: 비공개 저장소 — 요청 시 열람 권한 제공

## 5. AI 활용범위 및 주요 검토 과정
- **활용 도구**
  - 기획·설계 검토와 웹 자료 조사 — Claude(claude.ai). 2026-10-20~10-21 오전은 Claude Fable 5.1, 2026-10-21 T4-c(경보 분류) 검토부터 Claude Opus 5.5.
  - 구현·실험·문서 작성 — Claude Code(CLI). 2026-10-20~10-21 13시는 Claude Fable 5.1(수집·통계분석·피처·튜닝·평가 등), 2026-10-21 16시부터 Claude Opus 5.5(대시보드·일일 운영·동결 뒤 실험·v2 이식·데이터 유래 상수 누수 점검과 수정(FIX-v2.1)·패키징·데모 영상). 구분은 커밋의 공동 작성자 표기 기준이다.
- **참가자 기여**: 문제 정의와 평가 원칙(연도 단위 검증, 2026 정답 격리, 원단위 지표를 숨기지 않기), 입력 데이터 선택, 아래 표의 모든 채택·기각 결정, 사전등록 조건 검토·승인과 판정 승인, 대시보드 표현 원칙(공식 발령과 AI 예상 병기, 예상값 하나), 데이터 유래 상수 전수 점검 지시 → 누수 발견 → 사전등록 수정(v2.1).
- **참가자 검증**
  - 배포 대시보드를 직접 확인해 구버전 화면과 빌드 실패를 발견, 수정 지시
  - 원단위 R² 목표(0.6) 미달을 문제 제기하고 외부 자료·문헌 기반 개선 실험 지시
  - 비전문가 관점에서 대시보드 문구가 어렵다고 판단해 쉬운 말 개편 지시
  - CCTV 연계를 제안하고 타당성 검토 결과를 보고 미채택 결정
  - DataON 원자료 재배포 가능 여부를 운영사무국에 직접 문의
  - 최종 수치·README·방법설명서 검토
- **활용 단계**: 수집기(T1), 통계분석(T2), 피처·누수 테스트(T3), 튜닝·실험 러너(T4), 평가 보고서(T5), DB·대시보드·자동화(T6~T8), 패키지·방법설명서 초안·데모 영상(T9).
- **주요 활용 내용**: 공공 API 수집기, 피처 함수·누수 감사, Optuna 튜닝, 통계 검정·그림, Next.js 관제 대시보드, GitHub Actions 일일 자동화, 데모 영상 스크립트, 방법설명서 초안(수치는 `figures/reports/` 표에서 인용).

**주요 검토 과정 — AI 제안 → 참가자 선택**

| 쟁점 | AI 제안 | 참가자 선택(결정) |
|---|---|---|
| 입력 데이터 | 대회 번들에 공공 API 다수 추가(AIDA 격자 포함) | DataON 국가참조표준 수위와 보 운영자료를 1차 입력으로 확정, AIDA 격자 미사용(ASOS 대체) |
| 원단위 R²·NSE 미달 | 6개 변형 × 3개 보정 실험, 결과가 좋은 조합 채택 | 채택 절차(CV 기준)를 고정하고 2025 결과로 규칙을 바꾸지 않음. 원단위 지표를 그대로 보고(봉우리 1건 = 분산 43% 병기) |
| 경보 체계 | 분류기(a)·(b)·스태킹·q90 규칙 비교 | 2단계: 감시 = CQR 보정 q90 ≥ 10,000, 경보 = 분류기(b) p ≥ 운영점 0.46(놓침:헛경보 비용비 r=3 규칙) |
| 2026 평가 | 평가 타깃 격리 로더·사후 검증 스크립트 | 각 모델 동결 뒤 1회만 사후 계산, 저하도 그대로 기록. v1 의 2026 결과는 봉인 당시 상수에 2026 자료가 섞여 이력으로만, v2·v2.1 은 '블라인드 아님' 명기 |
| 성과 표현 | 2020~2025 경계 사건만으로 리드타임 표현 | 2026 포함 합계와 2026년을 함께 쓰고 지속성(3건) 병기: 2026년 8건 중 7건·중앙 21일, 2020~2026년 28건 중 24건(86%)·중앙 14일 |
| 우선순위·대시보드 | 취수용량 가중 우선순위, 위험 단계 3색 표시 | 공식 출처 없는 가중치는 쓰지 않음(단계 → 경계 확률 순). 공식 발령 × AI 예상 조합 5단계 라벨, 쉽게 보기 기본 |

**사전등록 판정 절차(제출 후보 v1 → v2 → v2.1) — AI 제안 → 참가자 검토·승인**

| 단계 | AI 제안 | 참가자 결정 |
|---|---|---|
| 판정 방식 | 선택지 A(v1 유지)·B(통합 학습 + C1 단독)·C(v1 + 상류 피처 + 속별 구성원) 제시, C 는 확인 실험 필요 의견 | B 기각, A 기본, C 는 실행 전 조건을 등록한 확인 실험 1회로만 판정 |
| 사전등록(EXP-confirm) | 운영 정의(새 시드 101~505, 난수 대조군, 블록 부트스트랩 2,000회)와 채택 조건 수치 초안: (a) CV r2_raw 시드 평균 Δ ≥ +0.08·부트스트랩 하한 > 0·대조군 대비 ≥ +0.04 (b) 2025 비열등(r2_raw −0.02·rmse_log +0.01·F1 −0.02 이내, 리드타임 포착 수 감소 없음) (c) 누수 테스트 통과 | 검토·승인. 하나라도 미달이면 v1 유지, 2026 은 판정 커밋 뒤 채택 모델만 1회 계산, 판정 번복 금지 |
| 판정 | 실행·독립 검증 → 조건 충족(2026-10-22, v2 피처) | C 를 v2 로 채택. v2.1 채택은 FIX-v2.1 사전등록(결과와 무관하게 채택)에 따르며, v2.1 피처 재계산(2026-10-23)은 참고용: CV Δ +0.102·대조군 대비 +0.076·2025 비열등, (b4) 리드타임은 원문 문턱 18/20 미충족(17/20). 같은 누수를 고친 v1-fix 도 17/20 |
| 2차 고도화(EXP-005)·P3 | 6개 계열·종합 기준 사전등록, 최선 후보 C + 칼만 판정, 마지막으로 P3(단기예보 격자) 1회 | 기준 미충족·P3 미통과 → C 를 v2 로 동결(커밋 {frozen['v2']}), 제출 후보(submission.csv)를 v2 로 교체, v1 제출 후보(submission.csv)는 태그 `v1-submission` 에 보존 |
| 누수 수정(FIX-v2.1) | 참가자 지시로 데이터 유래 상수 15개 항목 점검(수위 평균·수온 임계·ASOS 선정·보현산댐 문제 발견), 수정 규칙 ①~⑦ 초안을 결과 계산 전에 커밋(같은 252행·CV 에서 영향 비교) | 검토·승인. 기준일 이후 자료(2026년 측정값)가 섞여 계산된 상수를 공식 제출 전 개발 단계에서 찾아 사전등록 규칙대로 고친 것이므로 v2.1 을 결과와 무관하게 채택·동결(커밋 {frozen['v2.1']}), 제출 후보(submission.csv)를 v2.1 로 교체. 2026 은 동결 뒤 1회만 계산하고, 수정본은 블라인드라 부르지 않음 |

**검토한 대안·실패 사례** (세부 수치는 방법설명서 5.11절·10장)

| 대안 | 결과 | 판단 |
|---|---|---|
| 원단위 R² 개선 6개 변형 × 3개 보정 | 원단위 R² 0.2 미만(v2.1 재계산 최대 0.189), isotonic 은 악화 | 채택 절차 고정, 지표 그대로 보고 |
| 경보 분류기·스태킹 단독 | 2025 전체 F1 이 지속성(0.727) 미달, 진입 재현율·리드타임 우위 | 감시·경보 2단계로 사용 |
| 동결 뒤 원단위 고도화 7종(EXP-004~010) | CV 기준을 넘은 3종도 2025 에서 원단위 R² 개선 없음 | 기각(이력으로 보관) |
| 통합 학습 + C1 단독(후보 B) | 2025 에서 크게 나빠짐 | 기각 |
| 견고성 대안 C(상류 피처 + 속별 구성원) | v2 채택 → 누수 수정 뒤 v2.1. 재계산(참고) (b4) 원문 문턱 18/20 미충족(17/20)·v1-fix 도 17/20 | v2.1 로 제출·운영 |
| 2차 고도화(EXP-005 6개 계열·P3 단기예보) | 사전등록 기준을 넘은 구성 없음 | 기각, C 유지 |
| 수정 피처로 다시 돌린 선별 | 목록 변경(`ss_sum7`·`residence_proxy_ma14` 추가, `outflow_t0`·`ws_mean7` 제외) | 사전등록대로 채택하지 않음 |
| 물모아 벤치마크·외부 유역강수·Sentinel-2 | 단계만 제공·자료 미수령·비용 과다 | 분류 비교로 누적, 나머지 보류 |

- **CCTV·위성 영상(미채택)**: 수면이 보이는 공개 CCTV는 5지점 중 3곳뿐이고 영상 직접 연동은 약관·기술상 불가해, 정지영상 '녹조 색 지수'만 설계하고 예측 입력에는 쓰지 않는다.
  Sentinel-2 NDCI 는 해상도 20 m·구축 비용으로 보류(상세: `src/docs/13_CCTV_FEASIBILITY.md`·방법설명서 10장).
- **최종 선택 이유**: CV 기준 채택 절차를 고정해 홀드아웃 과적합을 막았고, 제출 후보 교체(v1 → v2)도 실행 전에 등록한 조건으로만 판정했다. 기준일 이후 자료(2026년 측정값)가 섞여 계산된 상수는 공식 제출 전 개발 단계에서 찾아 사전등록 규칙대로 고쳤고, 고친 v2.1 을 결과와 무관하게 제출·운영 모델로 정했다. 평가는 운영 지표(log R²·경보 F1·리드타임)로 했다.

본 절은 참가자가 최종 검토함

## 6. 라이선스·출처
`data/raw/MANIFEST.md` 참조(첫 표 라이선스 칸과 '라이선스 확인' 절 — 2026-10-22~23 각 출처 페이지에서 다시 확인). 외부 데이터는 출처별 라이선스를 MANIFEST 에 기록하고 그 조건을 지킨다. 공공데이터포털 자료는 공공누리 제1유형(출처표시) 또는 이용허락범위 제한 없음이다. WAMIS 자료는 개방 API 의 인증키 없는 엔드포인트로 수집했고(회원가입 안 함, 저장소의 `WAMIS_KEY` 는 실제로는 한강홍수통제소 OpenAPI 키이며 수집에 쓰지 않음), 같은 값이 공공데이터포털 #3068550(한강홍수통제소_수자원 정보)·#3040409(한강홍수통제소_표준수문DB)에 이용허락범위 제한 없음으로 등록돼 있다. DataON 수위 자료는 CC BY-NC-SA(저작자표시-비영리-동일조건변경허락)다. 라이선스를 확인하지 못한 물환경정보시스템 수질자동측정소 목록·좌표는 실험(EXP-009) 전용이며 제출 모델에 쓰지 않았고 이 패키지에 넣지 않았다.

- **WAMIS 원값은 이 패키지에 넣지 않았다.** WAMIS OPEN API 회원약관 제15조④(회원은 서비스를 이용해 얻은 정보를 사전 승낙 없이 복제·제공할 수 없음)가 회원이 아닌 이용자에게도 적용되는지 약관만으로 분명하지 않기 때문이다. 빠진 파일은 `data/raw/wamis_dam/` 과 `data/raw/hydro/hydro_daily_long.parquet` 의 WAMIS 출처 행이다. 대신 가공 수문 피처 `data/processed/wamis_hydro_features_S1.parquet`(33열)를 넣었고, 원값을 받는 공식 경로·라이선스·재생성 명령은 `data/raw/hydro/README_GET_WAMIS.md` 에 적었다. 출처 표시: 한강홍수통제소 국가수자원관리종합정보시스템(WAMIS). 예외: DataON 연속 수위 시계열(`data/raw/dataon/level_continuous_long.parquet`)의 2025년 이후 구간은 같은 관측소의 WAMIS 일수위를 기준면 오프셋으로 이어 붙인 값이다. 이 값은 공공데이터포털 #3068550·#3040409(이용허락범위 제한 없음)에서도 받을 수 있다.
- **대회 제공 데이터**(`data/raw/competition/`): 참가신청서 경진대회 규정 3항(승인 목적 외 이용 금지, 제3자 열람·제공·대여·판매 금지, 대회 완료 후 폐기, 성과물 발생 시 출처 명시)에 따라 **심사용으로만** 넣었다. 운영사무국은 심사 재현을 위해 결과물 data/ 폴더에 포함해도 된다고 답했다(2026-10-28, '별도의 컴퓨터에서 재현이 원활하도록 구성'). 공개할 때는 이 폴더를 빼고, 대회가 끝나면 폐기한다(`README_심사용_공개시제외.txt`).
- **DataON 유래 데이터와 그 가공물은 CC BY-NC-SA 로만 재배포할 수 있다.** 원 자료: 「댐유역 하천 일평균수위」(국가참조표준), 생산 한국수자원공사 오재우·이영창·이재용, 발행 국가참조표준센터, DOI 10.20925/KSRD.74670854.v5, 제·개정 2025-12-16.
- 이 패키지의 DataON 유래 파일: `data/raw/dataon/level_continuous_long.parquet`(연속 수위 원값 — DataON 2010~2024 + WAMIS 2025~), `data/processed/level_cont_features_S1.parquet`(수위 피처 2열 가공값, 2,979행, 대조용), `src/config/level_cont_stats.json`(기준면 오프셋·관측소 목록, 일일 운영용), 노트북 실행으로 생기는 `data/processed/features_*.parquet` 의 `level_cont_*` 열. 해당 폴더마다 `LICENSE_DataON.txt` 를 붙였다. 원값은 원 배포처 약관의 배포 제한 문구 때문에 운영사무국에 문의한 뒤 넣었다({DATAON_ANSWER}). 원 배포 xlsx 는 넣지 않았다(받는 법: `data/raw/dataon/README_GET_DATAON.md`).

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


def env_secret_prefixes() -> dict[str, str]:
    """로컬 .env 의 키·토큰 값 앞 8자(값 일부라도 패키지에 들어갔는지 검사용). 값은 출력하지 않는다."""
    env = ROOT / ".env"
    out: dict[str, str] = {}
    if not env.exists():
        return out
    for ln in env.read_text(encoding="utf-8").splitlines():
        if "=" not in ln or ln.lstrip().startswith("#"):
            continue
        k, v = ln.split("=", 1)
        v = v.strip().strip("'\"")
        if len(v) >= 12 and re.search(r"KEY|TOKEN|SECRET|PASS", k) and not v.startswith("eyJ"):
            out[k.strip()] = v[:8]
    return out


def scan_secrets(root: Path) -> list[str]:
    hits = []
    prefixes = env_secret_prefixes()
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
        for name, pre in prefixes.items():
            if pre in text:
                hits.append(f"{p.relative_to(root)}: .env {name} 값의 앞부분 포함")
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


def frozen_commits(model_dir: Path) -> dict[str, str]:
    """동결 문서(v1 FROZEN.md, v2 FROZEN_v2.md, v2.1 FROZEN_v2.1.md)의 동결 커밋 앞 7자. 문서가 없거나 형식이 다르면 '?'."""
    out = {}
    for key, doc in (("v1", "FROZEN.md"), ("v2", "FROZEN_v2.md"), ("v2.1", "FROZEN_v2.1.md")):
        p = model_dir / doc
        m = re.search(r"동결 커밋: `([0-9a-f]+)`", p.read_text(encoding="utf-8")) if p.exists() else None
        out[key] = m.group(1)[:7] if m else "?"
    return out


def write_readme(out: Path) -> None:
    frozen = frozen_commits(out / "model")
    sizes = {k: dir_size(out / k) for k in ("data", "model", "src", "demo", "figures")}
    pdf = out / "방법설명서.pdf"
    sizes["pdf"] = f"{pdf.stat().st_size / 1e6:.1f} MB" if pdf.exists() else "-"
    vj = ROOT / "reports" / "eval" / "package_verify.json"
    verify = json.loads(vj.read_text(encoding="utf-8")) if vj.exists() else None
    # 1차 작성(체크리스트 계산에 README 존재 여부가 필요) → 체크리스트 반영해 다시 작성
    (out / "README.md").write_text(readme(env_info(), frozen, sizes, "(작성 중)"), encoding="utf-8")
    (out / "README.md").write_text(
        readme(env_info(), frozen, sizes, checklist(out, verify)),
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


def level_feature_file() -> Path:
    """가공 수위 피처 파일이 지금 features_S1 의 두 열과 같은지 확인하고 경로를 돌려준다."""
    import pandas as pd

    from algaecast.features import run as feat_run

    lvl = ROOT / "data" / "processed" / LEVEL_FEATURE_FILE
    if not lvl.exists():
        raise SystemExit(
            f"빌드 중단: {lvl} 가 없다(원자료 환경에서 python -m algaecast.features.run --strategy S1 --export-level-cont)."
        )
    f = ROOT / "data" / "processed" / "features_S1.parquet"
    if f.exists():
        feats = pd.read_parquet(f)
        blank = feats.copy()
        blank[list(feat_run.LEVEL_FEATURES)] = float("nan")
        filled = feat_run.apply_level_cont_derived(blank, "S1")
        pd.testing.assert_frame_equal(filled, feats, check_exact=True)
    return lvl


def model_dir_problems(models_dir: Path | None = None) -> list[str]:
    """패키지 model/ 구성 점검(빈 목록 = 통과).

    - PACKAGE_MODEL_DIRS = registry current(제출·운영 v2.1 3개 폴더)이고, 그 폴더에 model.pkl·meta.json 이 있어야 한다.
    - 동결 문서 표에 있으나 패키지에서 빼는 폴더(이력)는 HISTORY.md 에 model.pkl sha256(동결 문서와 같은 값)과
      저장소 폴더의 파일별 sha256 이 모두 적혀 있어야 한다.
    """
    md = models_dir or ROOT / "models"
    problems: list[str] = []
    reg = json.loads((md / "registry.json").read_text(encoding="utf-8"))
    cur = {f"{n}/{v}" for n, v in reg["current"].items()}
    keep = set(PACKAGE_MODEL_DIRS)
    if cur != keep:
        problems.append(f"registry current {sorted(cur)} 가 PACKAGE_MODEL_DIRS {sorted(keep)} 와 다르다")
    for d in PACKAGE_MODEL_DIRS:
        for f in ("model.pkl", "meta.json"):
            if not (md / d / f).exists():
                problems.append(f"models/{d}/{f} 없음")
    rows: dict[str, str] = {}
    for doc in FROZEN_DOCS:
        if (md / doc).exists():
            rows |= {f"{n}/{v}": h for n, v, h in FROZEN_ROW.findall((md / doc).read_text(encoding="utf-8"))}
    hist = md / HISTORY_DOC
    listed = dict(HISTORY_FILE_ROW.findall(hist.read_text(encoding="utf-8"))) if hist.exists() else {}
    for d in sorted(set(rows) - keep):
        if listed.get(f"{d}/model.pkl") != rows[d]:
            problems.append(f"{HISTORY_DOC}: {d}/model.pkl sha256 이 없거나 동결 문서와 다르다")
        if (md / d).is_dir():
            for f in sorted(p for p in (md / d).iterdir() if p.is_file()):
                if listed.get(f"{d}/{f.name}") != sha256(f):
                    problems.append(f"{HISTORY_DOC}: {d}/{f.name} sha256 이 없거나 저장소 파일과 다르다")
    return problems


def package_registry(reg: dict) -> dict:
    """패키지용 registry.json — current·항목은 그대로 두고, 패키지에 없는 이력 항목에만 "package" 표시를 더한다."""
    out = json.loads(json.dumps(reg))
    keep = set(PACKAGE_MODEL_DIRS)
    for e in out["versions"]:
        if f"{e['name']}/{e['version']}" not in keep:
            e["package"] = HISTORY_MARK
    if out["current"] != reg["current"] or len(out["versions"]) != len(reg["versions"]):
        raise SystemExit("빌드 중단: 패키지 registry.json 의 current·항목 수가 저장소와 다르다")
    return out


def build(out: Path) -> int:
    demo_src = demo_sources()  # 먼저 확인 — 영상이 없으면 아무것도 지우지 않고 중단
    problems = model_dir_problems()  # 모델 폴더 허용 목록·HISTORY.md 도 지우기 전에 확인
    if problems:
        raise SystemExit("빌드 중단: model/ 구성 문제\n" + "\n".join(problems))
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
    man = out / "data" / "raw" / "MANIFEST.md"
    if man.exists():
        man.write_text(package_manifest_text(man.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    copy(ROOT / "data" / "raw" / "kma_forecast", out / "data" / "raw" / "kma_forecast")
    # 대회 자료: 참가신청서 규정 3항 — 심사용, 공개 시 제외, 대회 종료 후 폐기
    copy(
        ROOT / "docs" / "reference" / "README_COMPETITION_DATA.txt",
        out / "data" / "raw" / "competition" / "README_심사용_공개시제외.txt",
    )
    # DataON: 연속 수위 원값(운영사무국 답변 2026-10-28 '포함 가능') + 대조용 가공 수위 피처 2열 + 받는 법 안내
    dataon_raw = ROOT / "data" / "raw" / DATAON_RAW_FILE
    if not dataon_raw.exists():
        raise SystemExit(f"빌드 중단: DataON 연속 수위 원값 {dataon_raw} 가 없다.")
    copy(dataon_raw, out / "data" / "raw" / DATAON_RAW_FILE)
    copy(level_feature_file(), out / "data" / "processed" / LEVEL_FEATURE_FILE)
    # WAMIS: 원값(wamis_dam/·hydro 의 WAMIS 행)은 빼고 가공 수문 피처 + 받는 법 안내
    import pandas as pd

    hy = pd.read_parquet(ROOT / "data" / "raw" / "hydro" / "hydro_daily_long.parquet")
    hy = hy[~hy["source"].isin(WAMIS_SOURCES)]
    (out / "data" / "raw" / "hydro").mkdir(parents=True, exist_ok=True)
    hy.to_parquet(out / "data" / "raw" / "hydro" / "hydro_daily_long.parquet", index=False)
    copy(ROOT / "data" / "processed" / WAMIS_FEATURE_FILE, out / "data" / "processed" / WAMIS_FEATURE_FILE)
    copy(
        ROOT / "docs" / "reference" / "README_GET_WAMIS.md",
        out / "data" / "raw" / "hydro" / "README_GET_WAMIS.md",
    )
    copy(
        ROOT / "docs" / "reference" / "README_GET_DATAON.md",
        out / "data" / "raw" / "dataon" / "README_GET_DATAON.md",
    )
    for sub in ("interim", "processed"):
        (out / "data" / sub).mkdir(parents=True, exist_ok=True)
        (out / "data" / sub / ".gitkeep").write_text("", encoding="utf-8")
    # model/ (동결 모델 — 코드가 model/ 을 읽도록 algaecast.config 가 패키지 구조를 감지)
    # 재현에 불러오는 폴더(PACKAGE_MODEL_DIRS)만 넣는다. 이력 모델은 HISTORY.md(sha256·재학습 명령)로 대신하고,
    # verify_frozen 은 패키지에 없는 이력 행을 HISTORY.md 해시로 대조한다. 동결 문서 3종은 기록으로 남긴다.
    for doc in FROZEN_DOCS:
        if (ROOT / "models" / doc).exists():
            copy(ROOT / "models" / doc, out / "model" / doc)
    for d in PACKAGE_MODEL_DIRS:
        copy(ROOT / "models" / d, out / "model" / d)
    copy(ROOT / "models" / HISTORY_DOC, out / "model" / HISTORY_DOC)
    reg = json.loads((ROOT / "models" / "registry.json").read_text(encoding="utf-8"))
    (out / "model" / "registry.json").write_text(
        json.dumps(package_registry(reg), ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
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
    # DataON 유래 파일(원값·가공물)이 있는 폴더마다 라이선스 안내(CC BY-NC-SA·저작자·DOI)를 붙인다
    lic = ROOT / "docs" / "reference" / "LICENSE_DataON.txt"
    for d in DATAON_DIRS:
        (out / d).mkdir(parents=True, exist_ok=True)
        shutil.copy2(lic, out / d / "LICENSE_DataON.txt")
    # docs/handoff/(작업 보고서·화면 캡처, 내부 전달용)는 재현·설계와 무관해 넣지 않는다
    copy(ROOT / "docs", out / "src" / "docs", extra_ignore=("handoff",))
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
        copy(
            ROOT / "reports" / d,
            out / "figures" / "reports" / d,
            EXP_INTERMEDIATE if d == "experiments" else (),
        )
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
    if sha256(out / "data" / "raw" / DATAON_RAW_FILE) != sha256(ROOT / "data" / "raw" / DATAON_RAW_FILE):
        raise SystemExit("빌드 중단: 패키지 DataON 연속 수위 원값이 저장소 파일과 다르다")
    if (out / "data" / "raw" / "wamis_dam").exists():
        raise SystemExit("빌드 중단: 기본 패키지에 WAMIS 원값 폴더(wamis_dam/)가 있다")
    if (out / "data" / "raw" / API_ALGAE_DIR).exists():
        raise SystemExit(
            f"빌드 중단: 패키지에 공공 API 조류 폴더({API_ALGAE_DIR}/)가 있다(조류 원천은 대회 번들)"
        )
    print(f"패키지 {out} 총 {dir_size(out)}")
    print("루트:", sorted(p.name for p in out.iterdir()))
    return 1 if hits else 0


def make_zips(out: Path) -> int:
    mp4 = out / "demo" / "AlgaeCast_demo.mp4"
    if not mp4.exists() or not sha256(mp4).startswith(DEMO_SHA_PREFIX):
        raise SystemExit("zip 중단: 패키지 데모 영상이 없거나 sha256 이 승인본과 다르다.")
    # 문서자료·모델자료가 같은 최신 PDF 를 담도록: 9절 검증 시각을 고쳐 다시 렌더링했으면 패키지에 복사한 뒤 zip 한다
    src_pdf = ROOT / "reports" / "방법설명서.pdf"
    if sha256(out / "방법설명서.pdf") != sha256(src_pdf):
        raise SystemExit(
            "zip 중단: 패키지 방법설명서.pdf 가 reports/방법설명서.pdf 와 다르다 — PDF 를 패키지에 복사한 뒤 다시 실행한다."
        )
    write_readme(out)  # 체크리스트에 최신 검증 결과 반영
    security(out)
    write_readme(out)
    if security(out):
        return 1
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    files = sorted(p for p in out.rglob("*") if p.is_file())
    if not (out / "data" / "raw" / DATAON_RAW_FILE).exists():
        raise SystemExit("zip 중단: 패키지에 DataON 연속 수위 원값이 없다(1단계 빌드를 다시 한다).")
    for name, keep in (
        (ZIP_NAME, lambda p: True),
        (ZIP_NOVIDEO, lambda p: p != mp4),
    ):
        zpath = dist / name
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for p in files:
                if keep(p):
                    z.write(p, Path(PKG_NAME) / p.relative_to(out))
            if name == ZIP_NOVIDEO:
                z.writestr(
                    f"{PKG_NAME}/demo/영상_별도_안내.txt",
                    f"데모 영상 AlgaeCast_demo.mp4(2분 28초, {mp4.stat().st_size / 1e6:.1f} MB, sha256 {sha256(mp4)})는 "
                    f"용량 제한에 대비해 이 zip 에서 제외했다. 영상 포함본: {ZIP_NAME}, "
                    f"또는 문서자료 {ZIP_DOC_VIDEO} 의 demo/ 폴더\n",
                )
        print(f"zip {zpath.name} {zpath.stat().st_size / 1e6:.1f} MB sha256 {sha256(zpath)}")
    make_doc_zips(out, dist)
    return 0


def doc_readme(pdf: Path, pair_zip: str, pair_sha: str, mp4: Path | None) -> str:
    """문서자료 zip 의 읽어보기.txt — 대시보드·다시 보기 주소, 짝이 되는 모델자료 zip 이름·sha256, 재현 안내."""
    lines = [
        "AlgaeCast-7 — 수질·수문·기상 융합 기반 댐·하천 유해남조류(녹조) 7일 예측",
        "2026 DATA·AI 분석 경진대회(KISTI) 문제해결 부문 · 참가자 이재행",
        "",
        "[이 zip — 문서자료]",
        f"- 방법설명서.pdf : 문제해결 방법 설명 문서. 1쪽 요약, 2쪽 제출 양식 항목 대응표(개요·활용 데이터·모델 개발 방법·"
        f"실험 및 평가·기대효과 → 해당 절), 부록 C AI 활용범위 및 주요 검토 과정. sha256 {sha256(pdf)}",
        "- 읽어보기.txt : 이 파일",
    ]
    if mp4 is not None:
        lines += [
            f"- demo/AlgaeCast_demo.mp4 : 데모 영상(2분 28초, 추론 과정과 운영 대시보드), sha256 {sha256(mp4)}",
            "- demo/README_DEMO.md : 영상 구성·편집 내역(여기서 말하는 자막 .srt·콘티 script.md·캡처 captures/ 는 "
            "모델자료 zip 의 demo/ 에 있다)",
        ]
    lines += [
        "",
        "[대시보드]",
        f"- {DASHBOARD_URL} (매일 05시 KST 자동 갱신)",
        "- 다시 보기: 2026년 사건을 그날까지의 자료로 다시 그린 사후 재현 화면이다(당시 실시간 운영 화면이 아님).",
    ]
    for i, (asof, label) in enumerate(REPLAY_SCENES, 1):
        lines.append(f"  {i}) {DASHBOARD_URL}/?asof={asof}  {label}")
    lines += [
        "",
        "[짝이 되는 모델자료]",
        f"- {pair_zip}",
        f"  sha256 {pair_sha}",
        f"- 모델자료 zip 의 폴더 {PKG_NAME}/ 에 코드·데이터·동결 모델(v2.1)·submission.csv·실행 결과를 담은 노트북이 있다.",
        "- data/ 에는 대회 제공 데이터(심사용)와 DataON 연속 수위 원값이 들어 있다"
        "(운영사무국 답변 2026-10-28: 둘 다 결과물 data/ 폴더에 포함 가능).",
    ]
    if mp4 is not None:
        lines.append("- 이 모델자료는 영상제외판이다. 데모 영상은 이 문서자료 zip 의 demo/ 에 있다.")
    else:
        lines.append(
            f"- 데모 영상(2분 28초)은 이 모델자료 zip 의 {PKG_NAME}/demo/AlgaeCast_demo.mp4 에 있다."
        )
    lines += [
        "",
        "[재현]",
        "- 모델자료 README.md 의 '4. 설치·실행' 절을 따른다(Python 3.11, CPU 전용, 설치 후 인터넷 없이 재현).",
        "- 다시 만든 submission.csv 는 제출본과 바이트가 같다(sha256 4741a3d37ef3ae9f71b381e083028d93e83ec378ae5d5a65beba2ed48545a8e7).",
        "",
    ]
    return "\r\n".join(lines)


def make_doc_zips(out: Path, dist: Path) -> None:
    """문서자료 zip 2종(최상위 폴더 DOC_PKG 하나). A안 = PDF + 읽어보기(모델자료 영상 포함과 짝),
    B안 = A안 + demo/ 영상·README_DEMO(모델자료 영상제외와 짝). 모델자료 zip 을 만든 뒤에 부른다(짝 sha256)."""
    pdf = out / "방법설명서.pdf"
    mp4 = out / "demo" / "AlgaeCast_demo.mp4"
    readme_demo = out / "demo" / "README_DEMO.md"
    for name, pair, video in ((ZIP_DOC, ZIP_NAME, False), (ZIP_DOC_VIDEO, ZIP_NOVIDEO, True)):
        pair_path = dist / pair
        if not pair_path.exists():
            raise SystemExit(f"zip 중단: 짝이 되는 모델자료 {pair} 가 없다.")
        zpath = dist / name
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.write(pdf, f"{DOC_PKG}/방법설명서.pdf")
            text = doc_readme(pdf, pair, sha256(pair_path), mp4 if video else None)
            z.writestr(f"{DOC_PKG}/읽어보기.txt", text.encode("utf-8-sig"))  # 메모장에서 바로 열리게 BOM·CRLF
            if video:
                z.write(mp4, f"{DOC_PKG}/demo/AlgaeCast_demo.mp4")
                z.write(readme_demo, f"{DOC_PKG}/demo/README_DEMO.md")
        print(f"zip {zpath.name} {zpath.stat().st_size / 1e6:.1f} MB sha256 {sha256(zpath)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "submission_package")
    ap.add_argument(
        "--zip-only",
        action="store_true",
        help="기존 패키지에서 README 갱신·민감정보 재검사·모델자료 zip 3개·문서자료 zip 2개만",
    )
    args = ap.parse_args(argv)
    if args.zip_only:
        return make_zips(args.out)
    return build(args.out)


if __name__ == "__main__":
    raise SystemExit(main())
