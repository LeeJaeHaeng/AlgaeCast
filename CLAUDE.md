# CLAUDE.md — AlgaeCast-7 프로젝트 작업 규칙

이 저장소는 **2026 DATA·AI 분석 경진대회(KISTI) 문제해결 부문** 제출작
"수질·수문·기상 융합 기반 댐·하천 유해남조류(녹조) 7일 예측 AI 모델 + 취수원 운영 의사결정 대시보드"의 코드와 문서를 담는다.

## 반드시 먼저 읽을 것
1. `docs/00_README.md` — 문서 지도와 작업 순서
2. `docs/09_DEV_GUIDE_CLAUDE_CODE.md` — 태스크 단위 개발 지시서 (이 파일의 태스크 번호 순서로 작업)
3. 작업 중인 영역의 명세서 (데이터면 02, 피처면 03, 모델이면 04, DB면 05, 웹이면 06·07)

## 절대 규칙 (위반 시 대회 실격)
- 기준일(`base_date`) **이후** 시점의 관측값을 피처로 사용하지 않는다. 피처 생성 함수는 항상 `as_of=base_date` 인자를 받고, 그 이후 행을 필터링한 뒤 계산한다.
- 예측값 하드코딩, 실측치 룩업테이블 금지. 모델 파일 + 피처 파이프라인만으로 `submission.csv`가 재생성되어야 한다.
- `sample_submission.csv`의 `(지점, base_date, target_date)` 조합을 그대로 사용한다. target_date를 임의로 바꾸지 않는다.
- 분할: 학습 ≤2024 / 검증 2025 / 평가 2026. 랜덤 KFold 금지, 연도 단위 expanding-window만 허용.
- 모든 난수 시드는 `config/seed.yaml`의 값(기본 42)을 사용한다.
- 외부 데이터는 `docs/02_DATA_SPEC.md`에 등재된 공공 데이터(공공누리/이용제한 없음)만 사용한다. 출처 URL과 수집 일시를 `data/raw/MANIFEST.md`에 기록한다.

## 기술 스택
- ML: Python 3.11, pandas, numpy, scikit-learn, lightgbm, catboost, optuna, shap, statsmodels
- 파이프라인: `make` 타깃 + GitHub Actions (일일 수집·추론)
- 웹: Next.js 15 (App Router, TypeScript), Tailwind, shadcn/ui, Recharts, Mapbox GL 또는 Leaflet
- DB/백엔드: Supabase (PostgreSQL, Row Level Security, Edge Functions)
- 배포: Vercel (web), Supabase (db), GitHub Actions (batch)

## 디렉터리 구조 (목표)
```
algaecast/
  CLAUDE.md
  docs/                 # 이 문서 세트
  config/               # seed.yaml, sites.yaml, features.yaml, model.yaml
  data/
    raw/                # 원본 (git ignore, MANIFEST.md만 커밋)
    interim/            # 정렬·병합 중간물
    processed/          # features.parquet, splits
  src/algaecast/
    collect/            # 수집기 (모듈 목록은 docs/08 4절: competition, nier_algae, nier_wq, nier_forecast, kwater_dam, wamis, dataon_level, kma_asos, kma_basin, kma_forecast, aida_grid, run, base)
    align/              # 주기 정렬·결측 처리
    features/           # 피처 생성 (as_of 규칙 강제)
    models/             # train.py, tune.py, predict.py, ensemble.py
    eval/               # metrics.py, stats_tests.py, report.py
    db/                 # supabase 업로드
  notebooks/            # EDA 소스 (출력은 nbstripout 으로 커밋 전 제거 — 대회 데이터 노출 방지; 그림·표는 reports/eda/ 로 export 해 인용)
  tests/                # test_no_leakage.py 등
  web/                  # Next.js 앱
  supabase/             # migrations/, functions/
  reports/              # 방법 설명서, 정책 브리프, 그림
  submission/           # submission.csv, 재현 스크립트
  scripts/              # 운영 보조 스크립트 (check_api_keys.py 등)
  docs/reference/       # 공공 API 기술문서 사본
  Makefile
  pyproject.toml        # 패키지 메타 + ruff/black/pytest 설정
  requirements.txt      # 느슨한 상한/하한
  requirements.lock.txt # make lock 결과 (설치 버전 고정, 재현용)
```

## 코드 스타일
- Python: ruff + black, 타입 힌트 필수, docstring은 한국어 가능
- 함수 하나에 역할 하나. 피처 함수는 순수 함수(입력 DataFrame → 출력 DataFrame).
- 로그는 `logging` 모듈, 수집기는 재시도(3회, 지수 백오프)와 캐시(요청 URL 해시 → `data/raw/cache/`).
- 테스트: 피처 함수마다 누수 테스트 1개 이상 (`tests/test_no_leakage.py`).

## 작업 완료 기준
각 태스크는 `docs/09_DEV_GUIDE_CLAUDE_CODE.md`의 "완료 기준(DoD)"을 모두 만족해야 완료로 표시한다. 완료 시 `docs/PROGRESS.md`에 날짜·태스크·결과 수치를 한 줄 추가한다.

## 커밋 규칙
- Conventional Commits: `feat(collect): ...`, `fix(features): ...`, `docs: ...`, `exp(model): ...`
- 실험 결과는 `reports/experiments/EXP-###.md`에 기록하고 커밋 메시지에 번호를 남긴다.

## 로컬 환경 메모 (2026-10-20, T0-a)
- OS: Windows 11. Python 3.11.9 는 `winget install Python.Python.3.11` 로 사용자 설치 → `py -3.11`. GNU make 4.4.1 은 `winget install ezwinports.make` (설치 후 새 터미널 필요).
- Windows 에서는 Makefile 이 `SHELL := cmd.exe` 로 실행된다(PowerShell·Git Bash 공통). 레시피에 sh 전용 문법(`$$(...)`, `/dev/null`, 작은따옴표 인용)을 쓰지 말고, 복잡한 로직은 `python -c` 나 `scripts/` 로 뺀다.
- `make setup` 이 `.venv` 를 만들고 `requirements.txt` + 패키지 editable 설치 + `pre-commit install` 까지 수행한다. Makefile 은 `OS=Windows_NT` 여부로 `.venv/Scripts` 와 `.venv/bin` 을 자동 선택한다.
- data.go.kr 인증키는 `.env` 의 `DATA_GO_KR_KEY`(Decoding) / `DATA_GO_KR_KEY_ENC`(Encoding) 에만 둔다. 점검: `python scripts/check_api_keys.py` (다목적댐 API 는 일 100건 제한).
- 다목적댐 운영 정보 API 는 `vdate`·`tdate`·`ldate`·`vtime` 4개가 모두 있어야 응답한다(없으면 totalCount 0). 댐코드가 없고 댐명(`damnm`)으로 식별한다.
- Git Bash 에서 winget `--override "/quiet ..."` 는 MSYS 경로 변환으로 깨진다. winget 은 PowerShell 에서 실행할 것.
