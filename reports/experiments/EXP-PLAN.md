# 원단위 R²·NSE 고도화 실험 계획 (EXP-004~)

2026-10-21 사용자 지시. v1 제출본(태그 `v1-submission`, 동결 모델 13ac483, submission.csv sha256 182f4cb8…)을 확보한 뒤 시작한다.
v2 채택·재동결·제출 교체는 사용자가 정한다. 이 실험은 `reports/experiments/EXP-summary.md` 작성 후 멈춘다.

## 1. 번호

| 항목 | 실험 번호 | 시간 상한 | 내용 |
|---|---|---|---|
| R1 | EXP-004 | 4시간(0.5일) | 분산 반영 원단위 복원(분위 기반 σ, 로그정규 평균), log 폭 보정 p' = m + s·(p − m) |
| R2 | EXP-005 | 4시간(0.5일) | 상류 지점 특징(해평 → 강정·고령 → 칠서 → 물금·매리) |
| R3 | EXP-006 | 8시간(1일) | 속별 모델(4속 또는 Microcystis vs 나머지) 합산 |
| R4 | EXP-007 | 8시간(1일) | 영양염(국립환경과학원 수질 DB, 수질측정망) |
| R5 | EXP-008 | 12시간(1.5일) | 전국 조류경보 지점 통합 학습 |
| R6 | EXP-009 | 8시간(1일) | 수질자동측정망 일 단위 추세 |
| R7 | EXP-010 | 4시간(0.5일) | 희소 사건(>10,000) 재표본·가중 |
| 종합 | EXP-011 | – | 효과 있는 구성 요소 누적 결합 → v2 후보(CV 선택) |
| R8 | 보류 | – | Sentinel-2 는 R1~R7 결과를 보고 사용자가 결정 |

1일 = 8시간으로 환산했다. 상한을 넘으면 그 실험을 중단하고 그때까지의 결과와 사유를 보고서에 적는다.

## 2. 원칙(위반 금지)

1. **선택은 2020~2024 expanding CV OOF 로만.** 피처 채택, 보정 계수, 하이퍼파라미터, 앙상블 가중치 모두 해당. 후처리 계수처럼 OOF 로 적합하는 값은 `harness.expanding_fit_apply`(연도 Y 는 Y 이전 CV OOF 로 적합, 2025 는 2020~2024 전체)로 만들어 CV 수치가 정직하게 나오게 한다.
2. **2025 는 확인용.** 변형 간 선택에 쓰지 않는다.
3. **2026 은 계산·열람 금지.** `harness.load_base()` 로만 데이터를 읽고(base_date ≤ 2025-12-31, test 분할 없음), 모델에 넣는 프레임은 `harness.guard_no_2026` 을 통과해야 한다. `data/processed/test_targets_DO_NOT_USE.parquet`·`posthoc_2026.parquet` 를 읽지 않고, test 행 예측을 만들지 않는다. 새로 수집하는 원자료에 2026년 기록이 들어오는 것은 괜찮지만 그 값으로 지표·그림을 만들지 않는다. 리드타임 사건은 `harness.leadtime`(2025-12-31 까지의 측정)으로만 센다.
4. **v1 동결 산출물은 읽기만.** `data/processed/features_S*.parquet`·`splits.json`·`oof_predictions.parquet`·`data/interim/*`·`models/`·`config/*`·`submission/` 을 쓰지 않는다. `features.run`·`align.run`·`make reproduce` 등 v1 산출물을 다시 쓰는 명령을 실행하지 않는다. 끝나면 `python scripts/exp_check_protected.py` 가 "변경 0개" 여야 한다.
5. **새 피처는 as_of(base_date) 규칙.** `(원자료, as_of, site) → dict` 형태의 순수 함수로 만들고 진입 직후 `features.base.cut_as_of` 로 as_of 이후 행을 버린다. 실험별 누수 테스트 `tests/test_exp_<rN>_*.py` 를 만든다(as_of 이후 행을 난수로 바꾸거나 지워도 결과가 같아야 함, `tests/test_no_leakage.py` 와 같은 방식). 테스트가 통과해야 결과를 보고한다.
6. **하이퍼파라미터는 v1 그대로**(`harness.v1_specs()`). 실험 주제가 아니면 바꾸지 않는다. 바꾼다면 CV 로만.
7. **공유 파일 수정 금지.** `harness.py`·기존 `src/` 모듈·`config/*`·`data/raw/MANIFEST.md`·`docs/*`·`Makefile`·`requirements*.txt`·`.pre-commit-config.yaml` 은 고치지 않는다. 새 파일만 추가한다: `src/algaecast/exp/<rN>_<이름>.py`, 새 수집기 `src/algaecast/collect/<이름>.py`, 테스트 `tests/test_exp_<rN>_*.py`. MANIFEST·데이터 명세·sites.yaml 에 넣을 내용은 실험 폴더의 조각 파일로 남기고 통합은 메인 세션이 한다. 새 pip 패키지를 설치하지 않는다. git 은 읽기 명령만 쓴다(add·commit·push·checkout·stash·reset 금지).
8. **비밀키.** `.env` 를 python-dotenv 로 읽는다. 키 값을 화면·로그·파일에 출력하지 않는다(확인은 앞 6자리 + 길이). 공공데이터포털 키: `DATA_GO_KR_KEY`(Decoding)·`DATA_GO_KR_KEY_ENC`. 수질 DB 주소 `API_NIER_WQDB`, 키 `NIER_WQDB_KEY`.
9. **수집기 규칙.** 재시도 3회·지수 백오프, 요청 URL 해시 캐시(`data/raw/cache/`), 원자료는 `data/raw/<출처>/` 에 저장, 수집 일시·건수·sha256 을 `manifest_snippet.md` 에 적는다.
10. **코드 스타일.** ruff·black 통과(줄 길이 110), 타입 힌트.

## 3. 기준선(v1, 하네스 재현)

`python -m algaecast.exp.harness` → `reports/experiments/EXP-baseline/`. v1 저장 OOF 와 log10 최대 절대차 0.

| 구성 | 구간 | n | r2_raw | r2_pearson_raw | nse_raw | rmse_log | r2_log | F1@10k | 리드타임 포착(q90≥10k) |
|---|---|---|---|---|---|---|---|---|---|
| v1 기준 | CV 2020~2024 | 1278 | 0.173 | 0.319 | 0.173 | 0.805 | 0.706 | 0.599 | 18/20 |
| v1 기준 | 2025 | 256 | 0.166 | 0.194 | 0.166 | 0.708 | 0.780 | 0.682 | 〃 |

## 4. 표준 표와 채택 기준

- 모든 실험 보고서는 `harness.standard_table(rows)` 표(구성마다 CV·2025 두 줄)와 `harness.detail_table(rows)` 보조 표를 쓴다. 첫 줄은 v1 기준.
- CV = 2020~2024 OOF 통합 지표. 보조로 CV 폴드 평균을 함께 남긴다.
- 리드타임 = 2020~2025 경계 사건 20건 중 '감시(q90≥10k)' 경보가 첫 초과 측정 전에 켜진 사건 수. 회귀 점예측만 바꾸는 실험(R1·R7 등)은 q90 이 그대로라 같은 값이 나온다. 보조로 '점예측≥10k' 포착 수도 남긴다.
- **채택 기준(종합)**: CV r2_raw +0.10 이상, CV rmse_log 악화 0.01 이내, 리드타임 포착 수 감소 없음(`harness.adoption`).
- 실험 안의 변형 선택도 같은 규칙: 기준을 만족하는 변형 중 CV r2_raw 최대. 만족하는 변형이 없으면 CV r2_raw 최대 변형을 '기준 미달'로 표시해 보고한다.

## 5. 하네스 API (`src/algaecast/exp/harness.py`)

| 함수 | 용도 |
|---|---|
| `load_base()` | v1 학습·검증 행(≤2025). 행 순서 = v1 OOF |
| `base_columns()` / `v1_specs()` | v1 피처 30개 / C1·C3·C2 설정 |
| `run_members(df, cols, specs=None)` | C1(smearing)·c1_none·c1_log·C3·C2·q10·q50·q90 OOF(2020~2025) |
| `ensemble_expanding(df, preds)` | 연도 확장 NNLS 앙상블 |
| `expanding_fit_apply(df, fit, apply)` | 후처리 계수의 연도 확장 적합·적용 |
| `metric_row(df, pred, q90, label)` / `evaluate_members(df, members, label)` | 표준 지표 한 줄(리드타임 포함) |
| `standard_table(rows)` / `detail_table(rows)` / `adoption(base, cand)` | 표·채택 판정 |
| `save_oof(df, preds, path)` | 행 단위 OOF 저장(`data/processed/exp/` 아래만 허용) |
| `load_baseline()` | 기준 OOF(df, {c1, c1_none, c1_log, c3, c2, q10, q50, q90, ens}) |
| `Budget(hours, name)` | 시간 상한 확인 |

## 6. 실험 명세(사용자 지시 원문 + 구현 메모)

**R1 분산 반영 원단위 복원.** 분위 예측(q10/q50/q90)으로 조건부 분산 σ(x)를 추정해 원단위 조건부 평균으로 변환(로그정규 가정, σ는 CV OOF로 보정). 추가로 log 예측의 폭 보정 p' = m + s·(p − m)(s는 CV 원단위 MSE 최소, 지점 공통/지점별). 기존 smearing 대비 비교.
- 메모: log10 공간에서 σ ≈ (log10(q90+1) − log10(q10+1)) / (2·1.2816), 평균 = 10^(μ + ½·ln10·(kσ)²) − 1. k·m·s 는 `expanding_fit_apply` 로 이전 연도 OOF 원단위 MSE 최소. 앙상블 log 예측(주)과 C1 에 모두 적용. 기준: v1 앙상블(smearing 포함 C1).

**R2 상류 지점 특징.** 낙동강 순서 해평 → 강정·고령 → 칠서 → 물금·매리. 각 지점에 바로 위(및 두 단계 위) 지점의 base_date 이전 최근 세포수(log)·최근 3회 기울기·수온·경과일을 붙인다. 이동시간은 보 방류량 기반 대략값과 고정 lag(0/3/7일) 중 CV로 선택. 회남은 해당 없음.
- 메모: 상류 측정 원자료는 `data/raw/nier_algae/nier_algae_2012_2026.parquet`(obs_date ≤ base_date − lag 만 사용). 보 방류량은 `data/interim/daily_<지점>_S1.parquet` 의 `fac_outflow`(읽기 전용). 회남은 NaN.

**R3 속별 모델.** 4속(Microcystis, Dolichospermum/Anabaena, Aphanizomenon, Oscillatoria) 세포수를 대회·API 자료에서 분리해 속별 log 회귀(또는 2그룹: Microcystis vs 나머지) 후 원단위 합산. 합계 모델과 CV 비교, 앙상블 후보.
- 메모: 조류 원자료 열 `iem_bgalage_microsts`(Microcystis)·`iem_bgalage_anba`(Anabaena=Dolichospermum)·`iem_bgalage_apzo`(Aphanizomenon)·`iem_bgalage_osrtria`(Oscillatoria). v1 표본의 target_date 와 같은 날 측정에서 속별 타깃을 붙인다(대회 `algae_measure.csv` 와 대조). 합계 일치(`cells_consistent`)를 점검. 앙상블 후보는 NNLS 4번째 구성원으로 확장 적합.

**R4 영양염.** 국립환경과학원 수질 DB API(WaterQualityService) "물환경 수질측정망 운영결과 DB"(`getWaterMeasuringList`)에서 5지점 최근접 측정소(수질측정망 정보 JSON 좌표 기준, sites.yaml에 기록)의 TN, TP, NO3-N, NH3-N, PO4-P, TDN, TDP, Chl-a, DO, EC, SS를 2012~현재 수집. 피처: base_date 이전 최근값·4주 평균·N/P비·경과일.
- 메모: 승인 확인됨(2026-10-21, 응답에 측정소 경위도 DMS 포함). 측정망 자료는 공개까지 지연이 있으므로 '공개 지연 30일' 민감도(obs_date ≤ base_date − 30)도 함께 보고한다. 측정소 매핑은 `sites_snippet.yaml` 로 남긴다. 2016~2025 월별 GeoJSON 사본: `data/raw/nier_wq/`.

**R5 전국 경보지점 통합 학습.** 조류경보제 API를 ptNoList 없이 조회해 전 지점 목록·이력 수집. 각 지점에 최근접 ASOS(일자료) 연결, 수문은 가용 지점만(나머지 결측+플래그). 지점 임베딩 포함 통합 LightGBM 학습 → 우리 5지점으로 CV·2025 평가. 학습 표본 수와 10,000 초과 표본 수 증가도 보고.
- 메모: 엔드포인트 `apis.data.go.kr/1480523/nieragainstalgae/algaePreMeasure`(수집기 `collect/nier_algae.py` 참고). 우리 5지점 행은 v1 `features_S1` 값을 그대로 쓰고, 다른 지점은 같은 피처 함수(`features/*`)로 만든다. 폴드는 기준일 연도로 같게 자르고(다른 지점도 valid 연도 미만만 학습), 평가는 우리 5지점 행만.

**R6 수질자동측정망.** 같은 API의 "수질자동측정망 운영결과 DB"(`getRealTimeWaterQualityList`)에서 5지점 최근접 측정소의 일 단위 수온·pH·DO·EC·TOC·TN·TP(·Chl-a 있으면)를 수집, base_date 이전 7일 추세 피처. 측정소·항목 가용성부터 보고.

**R7 희소 사건.** 10,000 초과 표본 대상 회귀용 재표본(SMOGN 또는 가중 복제)과 가중치 함수 비교.
- 메모: 새 패키지 설치 없이 구현(SMOTER 방식 보간 + 가우스 잡음). 재표본은 각 폴드의 학습 구간 안에서만.

## 7. 보고서 형식(실험마다)

`reports/experiments/EXP-0xx/README.md`
1. 목적·설정(데이터 출처, 변형 목록)
2. 표준 표(v1 기준 + 변형들) + 보조 표
3. 선택한 변형과 이유(CV 기준), 채택 기준 판정(`adoption`)
4. 누수·2026 점검 결과(테스트 이름·통과, 보호 파일 변경 0)
5. 소요 시간 / 상한, 한계, 다음 단계 제안
첨부: `metrics.json`(표준 지표 행 전체), 필요 시 `manifest_snippet.md`·`docs02_snippet.md`·`sites_snippet.yaml`, 그림(png, 관측 원값을 표로 노출하지 않는 집계 그림만).
행 단위 OOF·중간 피처: `data/processed/exp/EXP-0xx/`(git 제외).
