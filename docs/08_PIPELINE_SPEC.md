# 08. 파이프라인·자동화 명세

## 1. 전체 흐름
```
make collect  →  make align  →  make features  →  make train  →  make evaluate  →  make predict  →  make upload  →  make submission
   (T1)           (T3)            (T3)              (T4)            (T5)             (T8)             (T6/T8)          (T9)
```
각 타깃은 입력·출력 파일 해시를 `data/.manifest.json`에 기록해 멱등 실행.

## 2. Makefile 타깃
| 타깃 | 명령 | 입력 | 출력 |
|---|---|---|---|
| setup | pip install -r requirements.txt; pre-commit install | | |
| collect | `python -m algaecast.collect.run --start 2015-01-01 --end today` | `.env`, `config/sites.yaml` | `data/raw/<source>/*.parquet`, `MANIFEST.md` |
| align | `python -m algaecast.align.run --strategy S1,S2,S3` | raw | `data/interim/daily_<site>.parquet` |
| features | `python -m algaecast.features.run` | interim | `data/processed/features_S*.parquet`, `splits.json` |
| test | `pytest -q` | | 누수 테스트 통과 |
| eda | `jupyter nbconvert --execute notebooks/*.ipynb` | processed | `reports/eda/` |
| tune | `python -m algaecast.models.tune --model lgbm --trials 300` | features | `optuna.db`, `config/model.yaml` 갱신 |
| train | `python -m algaecast.models.train --config config/model.yaml` | features | `models/<name>_<ver>.pkl` |
| evaluate | `python -m algaecast.eval.report` | models, features | `reports/eval/*` |
| predict | `python -m algaecast.models.predict --as-of today` | models, 최신 raw | `data/predictions/<date>.parquet` |
| upload | `python -m algaecast.db.upload` | predictions, eval | Supabase |
| submission | `python -m algaecast.models.predict --sample data/raw/competition/sample_submission.csv` | models | `submission/submission.csv` |
| reproduce | `make features train submission && diff submission/submission.csv submission/submission_final.csv` | | diff 0 확인 |

## 3. 일일 자동화 (`.github/workflows/daily.yml`)
> **별도 워크플로**: `.github/workflows/mulmoa_snapshot.yml` (물모아 AI 녹조 예측 스냅샷, KST 06/09/18시, 봇 커밋, 실패해도 성공 처리)는 T8 의 `daily.yml` 과 분리해 유지한다 — 수집 주기·실패 정책이 다르고 벤치마크 원자료는 모델 파이프라인과 독립적으로 쌓여야 하기 때문. (2026-10-20)

```yaml
name: daily-forecast
on:
  schedule:
    - cron: "0 20 * * *"   # UTC 20:00 = KST 05:00
  workflow_dispatch:
jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 40
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11", cache: "pip" }
      - run: pip install -r requirements.txt
      - name: Collect (incremental, last 60 days)
        env:
          DATA_GO_KR_KEY: ${{ secrets.DATA_GO_KR_KEY }}
          KMA_APIHUB_KEY: ${{ secrets.KMA_APIHUB_KEY }}
        run: python -m algaecast.collect.run --start $(date -d '-60 days' +%F) --end $(date +%F)
      - name: Predict
        run: python -m algaecast.models.predict --as-of $(date +%F)
      - name: Upload
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
        run: python -m algaecast.db.upload
      - name: Revalidate web
        run: curl -fsS "https://<vercel-app>/api/revalidate?secret=${{ secrets.REVALIDATE_SECRET }}"
      - name: Backfill observed values
        run: python -m algaecast.db.backfill_obs
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: run-logs, path: logs/ }
```
- 모델 재학습은 수동(`workflow_dispatch` + `train` 입력). 재학습 후 `model_runs`에 새 run 등록.
- 실패 시 `model_runs.status='failed'` 행 삽입 → 대시보드 배너.

## 4. 수집기 상세 (`src/algaecast/collect/`)
| 모듈 | 소스 | 핵심 함수 | 비고 |
|---|---|---|---|
| `competition.py` | 대회 zip | `load()` | 컬럼 표준화 매핑 |
| `nier_algae.py` | 조류경보제 API(WQ-01) | `fetch(site, start, end)` | XML 파싱, 지점코드 매핑 |
| `nier_wq.py` | 수질측정망 엑셀(WQ-02) | `load_excel(path)` | 수동 다운로드 파일 파서 |
| `nier_forecast.py` | 조류예측정보(WQ-03/04) | `fetch()` | 벤치마크, HTML 테이블 파싱 |
| `kwater_dam.py` | HY-01/02/03 | `fetch_daily(dam_code, ...)` | API + CSV 폴백 |
| `wamis.py` | HY-06 | `fetch_weir(code, ...)` | |
| `dataon_level.py` | HY-05 | `load(path)` | DataON 다운로드 파일 파서 |
| `kma_asos.py` | MT-01 | `fetch(stn_id, ...)` | 페이지네이션 |
| `kma_basin.py` | MT-02/03 | `load_csv(path)` | |
| `kma_forecast.py` | MT-05/06 | `fetch_issued(date)` | 과거 발표분은 API허브 |
| `aida_grid.py` | AI-01~03 | `extract_bbox(nc_or_bin, bbox)` | 지점 주변만 추출 |
| `run.py` | 전체 | `main()` | 병렬 실행, MANIFEST 갱신 |

공통: `BaseCollector` (캐시, 재시도, 로그, 출력 스키마 검증 `pandera`).

## 5. 로컬 개발 환경
- Python 3.11 venv, `make setup`
- `.env.example` 제공, 실제 `.env`는 gitignore
- 노트북은 `jupytext`로 `.py` 페어링(diff 가능)
- pre-commit: ruff, black, nbstripout(출력은 reports에만)

## 6. 모델 레지스트리
- `models/registry.json`: `{name, version, created, features_hash, metrics_holdout, path}`
- `predict`는 registry의 `current`를 사용. 재현 시 `--model-version`으로 고정.

## 7. 로그·모니터링
- 수집 실패/건수, 예측 건수, 업로드 건수를 `logs/daily_<date>.log`
- 최근 7일 예측 vs 실측 MAE를 `model_metrics(split='live')`에 적재 → 성능 페이지 "실시간 성능" 섹션(Should)
