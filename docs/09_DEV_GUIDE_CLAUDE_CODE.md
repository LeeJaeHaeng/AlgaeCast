# 09. 개발 지시서 (Claude Code용)

## 사용법
- 각 태스크를 Claude Code에 **하나씩** 지시한다. 아래 "프롬프트" 블록을 그대로 붙여넣되 `<...>`만 채운다.
- 태스크 완료 조건(DoD)을 Claude Code가 스스로 확인하고 `docs/PROGRESS.md`에 한 줄 기록하도록 한다.
- 병렬 가능한 태스크(T1-a~e)는 git worktree로 동시에 돌려도 된다.
- 어떤 태스크든 **누수 규칙(CLAUDE.md)**을 먼저 읽게 한다.

---

## T0. 셋업 (10/20~21)

### T0-a 저장소·환경
입력: 없음 / 출력: 디렉터리 구조(CLAUDE.md), `requirements.txt`, `Makefile`, `.env.example`, `.gitignore`, `config/seed.yaml`
DoD: `make setup && make test` 통과(빈 테스트), `python -c "import algaecast"` 성공
```
CLAUDE.md와 docs/00_README.md, docs/08_PIPELINE_SPEC.md를 읽고 프로젝트 골격을 만들어줘.
- src/algaecast 패키지(빈 모듈 포함), tests/, config/, data/{raw,interim,processed}/.gitkeep
- requirements.txt: pandas numpy scikit-learn lightgbm catboost optuna shap statsmodels pandera pyarrow requests python-dotenv supabase jupytext pytest ruff black
- Makefile은 08 문서의 타깃 표대로, 아직 구현 없는 타깃은 echo "TODO"
- config/seed.yaml: {seed: 42}
완료 후 make setup, make test 실행 결과를 보여줘.
```

### T0-b 대회 데이터 분석·데이터 카드
입력: `data/raw/competition/datas_participants.zip`, `04_sample_data_public.xlsx` / 출력: `docs/DATA_CARD_COMPETITION.md`, `config/sites.yaml`, `src/algaecast/collect/competition.py`
DoD: 데이터 카드에 02 문서 2.1절 항목 전부 기재, sites.yaml에 5지점 코드·수계·연계 댐/보·ASOS 지점번호
```
data/raw/competition/에 있는 대회 데이터 zip을 풀고 모든 파일의 구조를 분석해 docs/DATA_CARD_COMPETITION.md를 작성해줘. docs/02_DATA_SPEC.md 2.1절 항목(행수, 컬럼, 자료형, 기간, 지점, 타깃 분포, sample_submission 구조, 주기)을 모두 포함.
그리고 collect/competition.py에 load() 함수를 만들어 각 파일을 표준 컬럼명(02 문서 9절 규약)으로 반환하게 해줘. 타깃 컬럼은 iem_bgalage_cell_co.
config/sites.yaml에 5개 지점(해평 2011G26, 강정고령 2011G56, 칠서 2020G33, 물금매리 2022G05, 대청호회남 3008G30)의 수계, 시설, 상류 댐, 가장 가까운 ASOS 지점번호, 취수 가중치를 02 문서 4.1절·04 문서 7절 기준으로 채워줘. 모르는 코드는 TODO로 표시.
```

### T0-c 평가 지표 모듈
출력: `src/algaecast/eval/metrics.py`, `tests/test_metrics.py`
DoD: 04 문서 6.1절 지표 전부 구현, 알려진 값으로 테스트(NSE=1 when pred==obs 등)
```
docs/04_MODELING_SPEC.md 6.1절의 지표를 eval/metrics.py에 구현해줘. 함수: rmse_log, mae_log, r2_raw, nse_raw, r2_log, kge, f1_at(threshold), picp(q_low,q_high), mpiw, brier. compute_all(obs, pred, q10=None, q90=None, p10k=None) -> dict. bootstrap_ci(obs, pred, metric_fn, n=1000, seed) 포함. 테스트 작성.
```

---

## T1. 수집 (10/21~24) — a~e 병렬 가능

공통 지시 접두:
```
docs/02_DATA_SPEC.md와 docs/08_PIPELINE_SPEC.md 4절을 읽고, collect/base.py의 BaseCollector(캐시·재시도·pandera 스키마 검증)를 먼저 만든 뒤(이미 있으면 재사용) 아래 수집기를 구현해줘. 출력은 02 문서 9절 규약(site_code, obs_date, 변수..., source, fetched_at), parquet+csv 저장, MANIFEST.md 행 추가.
```
| 태스크 | 모듈 | DoD |
|---|---|---|
| T1-a | `nier_algae.py` (WQ-01 API) | 5지점 가용 전 기간 수집(회남 2012-04~, 낙동강 4지점 2016-01~, 물금·매리 2020-05~), 대회 데이터와 겹치는 기간 세포수 일치율 ≥95% 검증 로그 |
| T1-b | `kwater_dam.py` (HY-01/02/03) | 매핑 댐 전체 일별, 결측률 보고 |
| T1-c | `kma_asos.py` (MT-01) + `kma_basin.py` (MT-02/03 CSV 파서) | 지점별 후보 관측소 2~3개 ASOS 2012~현재(가용 전 기간), 번들 일치율, 기온–수온 상관 기반 관측소 선정표, 결측률 표(관측소×변수×연도) |
| T1-d | `wamis.py` (HY-06) + `dataon_level.py` (HY-05 파서) | 낙동강 4보 수위·방류 |
| T1-e | `kma_forecast.py` (MT-05/06) + `nier_forecast.py` (WQ-03/04) | 발표일 기준 예보 테이블(issued_at, target_date, 값), 벤치마크 테이블 |
| T1-f (Should) | `aida_grid.py` (AI-01~03) | 지점 bbox 평균 시계열 |
| T1-g | `collect/run.py` | `make collect` 1회 실행으로 전부 갱신, 실패 소스는 건너뛰고 로그 |

---

## T2. EDA·통계분석 (10/23~25)
출력: `notebooks/01_eda.ipynb`, `02_stats.ipynb` (+ jupytext .py), `reports/eda/*`
DoD: 04 문서 1절 S1~S10 산출물 파일 전부 존재, 각 그림에 캡션 md
```
docs/04_MODELING_SPEC.md 1절(S1~S10)을 notebooks/02_stats.ipynb로 구현해 실행하고 산출물을 reports/eda/에 저장해줘. 선행연구 상관(수온 0.630, 월 0.374, 유입량 0.188, 방류량 0.187)과 비교한 표를 포함. 결측 MNAR 로지스틱 회귀는 statsmodels로 OR과 p값 보고. Mann-Kendall은 pymannkendall 사용. 결과 요약을 reports/eda/SUMMARY.md에 10줄로.
```

---

## T3. 정렬·결측·피처 (10/25~28)

### T3-a 정렬·결측
출력: `align/run.py`, `data/interim/daily_<site>.parquet` (S1/S2/S3)
DoD: 3전략 모두 생성, 결측 플래그 컬럼 유지, 03 문서 2·3절 준수
```
docs/03_FEATURE_ENGINEERING.md 2~3절대로 align/run.py를 구현해줘. 일 단위 기준 달력에 수문·기상 조인, 수질은 측정일만 값. 결측 전략 S1/S2/S3를 --strategy로 선택, 각 전략 출력 저장. 보간은 과거 값만 사용(미래 참조 금지).
```

### T3-b 피처 생성 + 누수 테스트
출력: `features/*.py`, `features/run.py`, `data/processed/features_S*.parquet`, `splits.json`, `tests/test_no_leakage.py`, `config/features.yaml`
DoD: 03 문서 4절 피처 전부 구현(예보 피처는 데이터 있을 때만), 누수 테스트 통과, `reports/features/feature_catalog.md`
```
docs/03_FEATURE_ENGINEERING.md 1절 시그니처와 4절 피처 정의서대로 features/ 모듈을 그룹별(ar.py, water.py, hydro.py, weather.py, forecast.py, time_site.py)로 구현해줘. 모든 함수는 as_of 이후 행을 진입 직후 drop. features/run.py는 (site, base_date) 샘플을 만들고 target_date 매칭(±3일) 규칙으로 타깃을 붙여 전략별 parquet 저장, splits.json(train≤2024/valid 2025/test=sample_submission) 생성.
tests/test_no_leakage.py: 각 피처 함수에 대해 as_of 이후 데이터를 무작위로 바꿔도 출력이 동일한지 검사. 피처 카탈로그(이름, 정의, 결측률, 타깃 Spearman) 생성.
```

### T3-c 피처 선별
출력: `reports/features/tbl_feature_select.md`, `config/features.yaml` 갱신
DoD: VIF>10 제거 목록, Boruta 결과, 최종 피처 수 ≤ 행수/20

---

## T4. 베이스라인·모델·튜닝 (10/28~31)

### T4-a 베이스라인·CV 프레임
출력: `models/baselines.py`, `models/cv.py`, `reports/eval/tbl_baseline.md`
DoD: B0~B4 CV 결과표, expanding-window 폴드 생성기 테스트
```
docs/04_MODELING_SPEC.md 2~3절대로 models/cv.py(연도 expanding-window 폴드, (site,base_date) 단위)와 models/baselines.py(B0~B4)를 구현하고 CV 결과표를 reports/eval/tbl_baseline.md로 저장해줘. B3(NIER 공식 예측)은 데이터 있는 조합만.
```

### T4-b LightGBM + Optuna
출력: `models/train.py`, `models/tune.py`, `optuna.db`, `config/model.yaml`, `reports/experiments/tune_lgbm.md`
DoD: 300 trial 또는 2시간, 상위 5 시드 재검증, 최적 파라미터 model.yaml 기록
```
docs/04_MODELING_SPEC.md 4.1·5절대로 LightGBM 학습(train.py)과 Optuna 튜닝(tune.py)을 구현해줘. 목적함수는 CV 평균 log-RMSE, TPE+MedianPruner, sqlite 저장. 완료 후 상위 10 trial 표와 파라미터 중요도 그림, 상위 5의 시드 3개 재검증 결과를 reports/experiments/tune_lgbm.md에 기록하고 최적 파라미터를 config/model.yaml에 써줘. 결측 전략 S1/S2/S3 각각에 대해 최적 파라미터로 CV 성능을 비교해 tbl_missing_strategy.md 생성.
```

### T4-c 분위 회귀·분류기·CatBoost·앙상블
출력: `models/quantile.py`, `models/classifier.py`, `models/ensemble.py`, `models/registry.json`
DoD: q10/q50/q90 모델, p_over_10k 두 방식 비교표, NNLS 앙상블 가중치, 최종 모델 등록
```
docs/04_MODELING_SPEC.md 4.2~4.5절을 구현해줘. 분위 회귀 3개(중앙값 파라미터 고정), 경계 초과 분류기(binary LightGBM), CatBoost(Optuna 150 trial), OOF 기반 NNLS 앙상블. 단일 vs 앙상블 CV 비교 후 더 좋은 쪽을 registry current로 등록.
```

---

## T5. 평가·검정·SHAP (10/31~11/2)
출력: `eval/report.py`, `eval/stats_tests.py`, `reports/eval/*` (04 문서 6.2절 1~11 전부)
DoD: 2025 holdout 표에 95% CI, DM 검정 p값, 지점·월 분해, ablation, NIER 벤치마크(04 문서 6.4절 단계 분류: 정확도·≥2단계 F1·혼동행렬, live_benchmark.csv 에 pred_level·p_over_10k 결합), 잔차 진단, SHAP 그림
```
docs/04_MODELING_SPEC.md 6절 표·그림 11개를 전부 생성하는 eval/report.py를 만들어 실행해줘. 부트스트랩 1000회 (site,base_date) 리샘플, Diebold-Mariano(vs B0, B3), Wilcoxon(모델 간), Ljung-Box 잔차. SHAP TreeExplainer 전역+사례 5건. 7절 규칙으로 담당자 문장(drivers)과 설비 배치 우선순위를 계산하는 eval/decision.py도 구현.
```

---

## T6. Supabase (10/30~11/1)
출력: `supabase/migrations/0001_init.sql`, `supabase/seed.sql`, `db/upload.py`, `db/backfill_obs.py`
DoD: 마이그레이션 적용, 시드 5지점, upload로 최근 2년 관측·수문·기상 + 최신 run 예측·SHAP·권고·metrics 적재, anon으로 SELECT 가능·INSERT 불가 확인
```
docs/05_ERD.md DDL을 supabase/migrations/0001_init.sql로 저장하고 supabase CLI로 적용해줘. db/upload.py는 service_role로 sites/observations/hydrology_daily/weather_daily(최근 730일)/model_runs/predictions/shap_contributions/recommendations/model_metrics를 upsert. RLS가 anon INSERT를 막는지 테스트 스크립트로 확인.
```

---

## T7. 대시보드 (11/1~4)

### T7-a 스캐폴드·데이터 레이어
출력: `web/` (Next.js 15, TS, Tailwind, shadcn, Recharts, Leaflet), `lib/queries.ts`, `types/`
DoD: `npm run build` 성공, `/api/sites`·`/api/overview`·`/api/sites/[id]/forecast` 응답 06 문서 JSON 형태
```
docs/06_API_SPEC.md와 07_DASHBOARD_SPEC.md를 읽고 web/에 Next.js 15 App Router 프로젝트를 만들어줘. Supabase SSR 클라이언트, lib/queries.ts 4함수, Route Handler 5개, 타입. 환경변수는 .env.local.example.
```

### T7-b 홈·지점 상세
DoD: 07 문서 3.1·3.2 와이어프레임 요소 전부, 모바일 레이아웃, Lighthouse ≥90
```
07 문서 3.1(홈)과 3.2(지점 상세)를 구현해줘. 디자인 토큰 4절 적용, 경보 단계는 색+텍스트 배지, 메인 차트는 Recharts ComposedChart(log y축, 예측 밴드 Area, 경보 ReferenceLine). base_date는 searchParams.
```

### T7-c 성능·인사이트·소개 + 배포
DoD: 3페이지 구현, Vercel 배포 URL, 환경변수 설정, `/api/revalidate` 동작
```
07 문서 3.3~3.5를 구현하고 Vercel에 배포해줘. 배포 URL과 revalidate 시크릿 설정 방법을 docs/DEPLOY.md에 기록.
```

---

## T8. 자동화 (11/3~4)
출력: `.github/workflows/daily.yml`, `models/predict.py --as-of`, `db/backfill_obs.py`
DoD: workflow_dispatch 수동 실행 성공, Supabase에 오늘 run 생성, 웹 갱신 확인
```
docs/08_PIPELINE_SPEC.md 3절 워크플로를 만들고, predict.py에 --as-of(오늘 기준 최신 관측으로 7일 예측) 모드를 추가해줘. Secrets 목록을 docs/DEPLOY.md에 추가. workflow_dispatch로 1회 실행해 성공 로그를 PROGRESS.md에 기록.
```

---

## T9. 문서·제출 (11/4~6)

### T9-a 방법 설명서
출력: `reports/방법설명서.md` → PDF
목차: 1 배경·목표 / 2 데이터(출처·라이선스·MANIFEST) / 3 통계분석 / 4 융합·결측·피처 / 5 모델·튜닝 / 6 평가(모든 표·CI·검정·벤치마크) / 7 설명가능성·의사결정 / 8 시스템(대시보드·자동화) / 9 재현 절차 / 10 한계·향후
```
docs/ 전체와 reports/eda, reports/eval, reports/experiments를 바탕으로 reports/방법설명서.md를 위 목차로 작성해줘. 모든 수치는 reports/ 파일에서 가져오고 출처 파일명을 각주로. 그림은 상대경로로 삽입. 20~30쪽.
```

### T9-b 재현 패키지·submission
DoD: `make reproduce` diff 0, README에 3줄 재현 명령, requirements 고정 버전, 모델 파일 포함, 데이터 다운로드 스크립트
```
submission/ 폴더에 submission.csv, README_REPRODUCE.md(환경, 데이터 받는 법, make 명령 3줄), 모델 파일, 고정 버전 requirements.txt를 넣고, 깨끗한 venv에서 make reproduce를 실행해 diff가 0인지 보여줘. 10_SUBMISSION_CHECKLIST.md 전 항목 체크.
```

### T9-c 정책 브리프·데모 영상 콘티
출력: `reports/정책브리프.md`(4쪽) → PDF, `reports/demo_script.md`
11 문서 참조.

---

## PROGRESS.md 양식
```
| 날짜 | 태스크 | 결과 | 비고 |
|---|---|---|---|
| 2026-10-21 | T0-b | 대회 데이터 3파일, 2018~2026, 샘플 1,842행 | sample_submission 110조합 |
```
