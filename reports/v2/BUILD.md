# 운영 모델 v2 빌드 보고 — 최종 모델 C 운영 경로 이식 (2026-10-22)

상태: **운영 코드·동등성 검증·dry-run 완료, 실제 동결 전**. `models/`·`submission/`·`dist/` 는 바꾸지 않았다
(dry-run 산출물은 `data/processed/exp/v2_dryrun/`, git 제외). 근거: 사전등록 확인 실험 EXP-confirm 채택
(`reports/experiments/EXP-confirm/RESULT.md`), 계획 `reports/experiments/EXP-confirm/V2_PLAN.md`.

## 1. 요약

- 최종 모델 C(v1 로그 앙상블 + 상류 피처 5열 + 속별 구성원 cg)를 실험 코드와 분리된 운영 모듈 3개로 옮겼다:
  `features/upstream.py`, `models/genus.py`, `models/v2.py`.
- 동등성: 실험 경로와 비교한 네 항목이 모두 **차이 0.0** 이었다(허용 기준 < 1e-9). 네 항목은 상류 피처(학습 2,562행, test 124행, NaN 위치 포함), 폴드 모드 2025 예측, NNLS 가중치, 최종 모드 test 124행 예측이다.
- v1 구성을 같은 운영 경로로 돌린 결과(d):
  - 예측 경로: v1 동결 구성원으로 예측하면 v1 제출본 124/124행이 정수 반올림까지 같다.
  - 학습 경로: 같은 학습 행에서 실험 절차와 차이 0.0 이다.
  - 재학습 재현: 현재 학습 행(2,562)으로 다시 학습하면 v1 제출본과 1/124행만 같다. v1 동결 모델은 2026-10-22 격리 이전의 2,566행으로 학습했기 때문이다. 4행 차이는 2026 정답을 읽지 않고 트리 leaf_count 로 확인했다(3.4절).
- dry-run 결과:
  - v2 회귀 `model.pkl` sha256 `d696f693…`, submission_v2.csv sha256 `0c77ac8e…`. 두 번 실행해 두 해시가 모두 같았다(결정론적).
  - 2025 홀드아웃(학습 ≤2024): r2_raw 0.1755, rmse_log 0.7102, F1@10k 0.7045.
- 남은 단계: 실제 동결(`scripts/freeze_v2.py --freeze`), 동결 커밋과 Release(v2 tarball), daily.yml 태그 교체, 노트북 실행·패키지 재빌드(6절).

## 2. 설계

### 2.1 구성(V2Config `v2_C`)

| 항목 | 값 |
|---|---|
| 피처 | v1 선택 30개(config/features.yaml selected, perc75, 결측 S1) + 묶음 `upstream` 5열 = 35 |
| 상류 피처 | up1_cell_log·up1_slope3·up1_wtemp·up1_days·up1_diff. 바로 위 지점(HP→GJGR→CS→MGMR)의 기준일까지 최근 측정(lag 0). 해평·회남은 NaN |
| 구성원 | c1 = C1 log 가중 회귀(smearing)<br>c3 = C3 hurdle<br>c2 = C2 tweedie(v1 하이퍼파라미터, config/model.yaml)<br>cg = 속별 G2(Microcystis + 나머지 3속, 부분별 C1 설정 log 회귀·smearing, 원단위 합) |
| 결합 | log10(y+1) 공간 NNLS(합=1). 가중치는 2020~2024 연도 확장 CV OOF(시드 42)로 적합한다(`fit_weights` = `harness.ensemble_expanding` 의 2025 가중치) |
| 가중치(시드 42) | c1 0.000000 · c3 0.266051 · c2 0.373269 · cg 0.360680 |
| 최종 학습 | 기준일 ≤ 2025-12-31 이면서 목표일 ≤ 2025-12-31 인 학습·검증 행 전체(2,562행, 기준일 2012-04-02~2025-12-22, 목표일 ≤ 2025-12-29), 시드 42 |
| 분위·분류기(b)·CQR·운영점 | v1 동결본 그대로(classifier 20261021_091109, quantile 20261021_091110, config/model.yaml) |

새 피처 묶음(예: 예보 피처)은 `models/v2.py` 의 `FEATURE_GROUPS` 에 `(열 목록, 생성 함수(df, algae))` 로 등록하고,
`V2Config.feature_groups` 에 이름을 넣으면 학습·CV·예측·as-of 경로가 모두 그 열을 쓴다. v1 구성은 `config_v1()` 이다
(피처 30, 구성원 3, model.yaml 고정 가중치).

### 2.2 모듈

| 파일 | 역할 |
|---|---|
| `src/algaecast/features/upstream.py` | `make_upstream_features(algae, as_of, station_id, own_cell_log)`: 순수 함수, 진입 직후 `cut_as_of`<br>`build_upstream(df, algae=None)`: 행마다 그 행의 기준일을 as_of 로 계산한다. 학습 행·2026 test 행·일일 as-of 행에 같은 함수를 쓴다<br>`prepare_algae`: parquet 과 수집기 출력 형식을 모두 받는다 |
| `src/algaecast/models/genus.py` | 속별 타깃: 목표일 측정이며 원자료는 읽은 즉시 2025-12-31 이후를 버린다. 목표일 2026 행이 들어오면 중단한다<br>부분 모델 적합(`fit_genus`)·예측(`predict_genus`) |
| `src/algaecast/models/v2.py` | `V2Config`·`config_v2()`·`config_v1()`·`load_training_frame()`·`ensure_features()`·`cv_members(df, seed)`·`fit_weights(df, seed=42)`·`fit_final(train_df)`<br>`V2Model`: `predict` → 원단위, `to_registry`/`from_registry`<br>`from_v1_registry`: v1 동결 객체를 V2Model 로 감싼다(확인용) |
| `src/algaecast/models/registry.py` | `reg_dir` 인자 추가(기본 models/), `current_entry`·`current_kind`·`entry_for`·`copy_version`·`set_current`·`explain_member`·`file_sha256`. 기존 `register`·`load_current` 동작은 그대로다(v1 항목 유지) |
| `scripts/freeze_v2.py` | `--dry-run`(data/processed/exp/v2_dryrun/) 또는 `--freeze`(models/·submission/·dist/v1/) |
| `scripts/check_v2_equivalence.py` | 동등성 (u)(a)(b)(c)(d) 전체 계산 → `data/processed/exp/v2_dryrun/equivalence.json`(수치만) |

### 2.3 운영 경로 변경(v1 일 때 동작은 그대로)

- 레지스트리 회귀 항목 `kind="ensemble_v2"`:
  - pickle 은 dict 와 LightGBM 객체만 담는다. 키는 config, weights, members, cols, cats, categories, train_info, aux.
  - aux 는 분류기·분위 입력용 v1 30열·범주로, v1 회귀 객체에서 복사한다.
  - meta 에는 kind, config, weights, train, 분류기·분위 버전이 들어간다.
- `db/upload.py predict_registry(feat, *, reg_dir, algae)`:
  - 회귀가 ensemble_v2 이면 feat 에 상류 피처를 붙여 `V2Model.predict` 로 예측한다.
  - 분위·분류기는 v1 입력(aux)으로 예측한다.
  - `shap_and_reco_rows` 는 `explain_member` 로 C1 구성원(35열)을 설명한다.
- `models/predict.py make_submission(..., reg_dir, algae)`: 제출 형식·검증은 v1 과 같다. `write_submission` 은 UTF-8 BOM·LF 로 쓰고, CLI 에 `--registry` 를 추가했다.
- `predict/asof.py attach_model_features(feat, algae)` 와 `scripts/daily_run.py`:
  - current 가 ensemble_v2 이면 이번에 수집한 5지점 조류 자료로 상류 피처를 붙인다(추가 수집 없음).
  - FROZEN_TAG 는 환경변수로 받는다.
  - model_runs 의 hyperparams 에 regression_kind 를 기록한다.
- `scripts/verify_frozen.py`:
  - FROZEN.md(v1)와 FROZEN_v2.md(있으면)의 파일 해시를 모두 확인한다.
  - registry current 가 가장 최근 동결 문서의 버전과 같은지 확인한다.
  - `--models-dir` 로 다른 디렉터리도 검증할 수 있다.
- `.github/workflows/daily.yml`:
  - `FROZEN_TAG` 를 dispatch 입력 `frozen_tag` 로 덮어쓸 수 있게 했다. 기본값은 v1 `model-frozen-13ac483` 그대로이고, '동결 후 교체' 주석을 달았다.
  - Release 자산 `models-frozen-*.tar.gz` 는 여러 개여도 모두 푼다.
- `scripts/build_submission_package.py`: model/ 에 FROZEN_v2.md 와 두 동결 문서의 모든 버전(v1 회귀 포함)을 복사한다.
- 노트북 `notebooks/01_train_eval.py`(+ .ipynb, jupytext 동기):
  - 1절 동결 검증: FROZEN_v2.md 가 있으면 current 가 v2 인지 확인한다.
  - 3절: 상류 피처를 계산한다.
  - 4절: v2 를 동결 가중치(레지스트리 meta.weights; 동결 전이면 같은 규칙으로 재계산)로 ≤2024 학습한다.
  - 5절: 2025 표에 v1·v2 를 나란히 놓는다.
  - 6절: current 레지스트리로 submission.csv 를 만든다.
  - **실행하지 않았다**(동결 후 실행). 같은 코드를 정렬·피처 재생성과 파일 쓰기 경로만 바꿔 임시로 돌렸을 때 오류 없이 끝났다. v1 레지스트리로 만든 제출본은 기존 v1 submission.csv 와 바이트 단위로 같았다.

### 2.4 as_of·2026 규칙

- 상류 피처는 행마다 `cut_as_of(base_date)` 뒤에 계산한다. test 행(2026 기준일)도 기준일까지의 측정만 쓴다.
- 누수 테스트를 했다: as_of 이후 원자료를 난수로 바꾸고 절반을 지워도 결과가 같다. `build_upstream` 은 행별로 확인했다.
- 학습·가중치 프레임 가드: 기준일 또는 목표일이 2025-12-31 을 넘는 행이나 test 분할이 있으면 중단한다(`guard_train`, `genus.guard_targets`).
- 2026 정답·격리 파일은 운영 코드와 검증 스크립트 어디에서도 읽지 않는다. confirm_2026 은 `final_fit_predict` 만 import 했고, 판정 가드가 있는 `main` 은 실행하지 않았다.

## 3. 동등성 검증(전체 하이퍼파라미터, `scripts/check_v2_equivalence.py`)

실행: 2026-10-22, 약 1.2분. 결과: `data/processed/exp/v2_dryrun/equivalence.json`. 실험 경로 값은 캐시를 쓰지 않고 새로 계산했다.

| 항목 | 비교 | 결과 |
|---|---|---|
| (u) 상류 피처 — 학습 | `build_upstream` vs `r2_upstream.build_features`, load_base 2,562행 | 완전 일치, NaN 위치 동일, 최대 차 0.0 |
| (u) 상류 피처 — test | `build_upstream` vs confirm_2026 방식(`build_variant_features`, lag 0), 124행 | 완전 일치, 최대 차 0.0 |
| (a) 폴드 모드 | V2(학습 ≤2024, 2,310행 → 2025 252행) vs C 시드 42 OOF(`confirm.config_members(df, f2, 42, genus=True)` + `ensemble_expanding(c1,c3,c2,cg)`) | log10 최대 차 **0.0** |
| (a') 구성원 OOF | `V2.cv_members` vs `config_members`, 2020~2025, c1·c3·c2·cg 각각 | log10 최대 차 0.0 / 0.0 / 0.0 / 0.0 |
| (b) 가중치 | `fit_weights(df, 42)` vs `ensemble_expanding` 2025 가중치 | 최대 절대차 **0.0**, 순서 동일(c1 0.000·c3 0.266·c2 0.373·cg 0.361) |
| (c) 최종 모드 | `V2.fit_final(2,562행).predict(test 124)` vs `confirm_2026.final_fit_predict` + combine(같은 학습 행·가중치) | log10 최대 차 **0.0**, 원단위 최대 차 0.0, 구성원 4개 모두 0.0 |
| (c') 저장 형식 | `to_registry` → pickle 왕복 → `from_registry` 예측 | 최대 차 0.0 |
| (d1) v1 운영 예측 경로 | v1 동결 회귀 구성원을 `from_v1_registry` 로 감싸 `V2Model.predict` | v1 제출본과 정수 반올림 **124/124** 일치, v1 `predict_registry` 와 log10 차 0.0 |
| (d2) v1 운영 학습 경로 | `fit_final(config_v1, 2,562행)` vs `confirm_2026.final_fit_predict` 의 c1·c3·c2 + model.yaml 가중치 | log10 최대 차 0.0(구성원별 0.0) |
| (d3) v1 재학습 → v1 제출본 | (d2) 예측을 정수 반올림 | 1/124 일치, 최대 차 3,144 cells/mL, v1 동결 예측과 log10 최대 차 0.112 |

### 3.4 (d3) 불일치 원인 — 학습 행 4개 차이(2026 정답 미사용으로 확인)

- 학습 행 수:
  - 학습·검증 로더(`load_train_valid(drop_missing_target=False)`)는 **2,566행**이다.
  - 그중 목표일 2026-01-05 인 4행(HP·CS·MGMR·DCHN, 기준일 2025-12-29)은 2026-10-22 격리 확대(커밋 ee9a9b0)로 정답이 비어 있다. 그래서 현재 학습 프레임은 2,562행이다.
- v1 동결 모델(2026-10-21 09:11 학습)과 `submission_reproduced.csv`(10:41, v1 과 동일)는 격리 이전(features_S1 재생성 13:56) 프레임으로 만들었다.
- LightGBM 첫 트리의 leaf_count 합(배깅 후 학습 표본 수)을 비교했다. v1 동결 모델은 c1 2202 / c2 2145 / c3 분류기 1669 이고, 현재 2,562행으로 재학습하면 2198 / 2141 / 1666 이다. 동결 모델이 행 3~4개를 더 보았다.
- 배깅은 행 순서에 따라 표본을 뽑는다. 그래서 행 4개만 달라도 모든 트리가 달라지고, 정수 단위 재현은 깨진다.
- 정확한 재학습 재현에는 격리된 4행의 2026 정답이 필요하다. 2026 규칙상 이 정답은 읽지 않았다. 대신 운영 경로가 v1 과 같다는 점은 (d1) 예측 경로와 (d2) 학습 경로로 확인했다.
- 따라서 v2 최종 학습 행(2,562)은 v1 동결 학습 행(2,566)과 4행 다르다. 과제 지시(현재 load_base 2,562행)와 confirm_2026 판정 경로가 같은 2,562행을 쓴다.

## 4. dry-run 산출물(`python scripts/freeze_v2.py --dry-run`, 0.44분)

위치 `data/processed/exp/v2_dryrun/`(git 제외). `models/`·`submission/` 은 변경 없음(git status 로 확인했고, 테스트 `test_freeze_v2_dry_run_isolated` 도 해시로 확인한다).

| 파일 | sha256 | 비고 |
|---|---|---|
| models/regression/20261022_143905/model.pkl | `d696f6933eff04130f722a52cda614f1f0cf091a06cf518b67acd18b2b1f34e2` | 20,430,437 B, ensemble_v2, features_hash a3076b49cfc7. 두 번 실행해 같은 해시 |
| models/classifier/20261021_091109/model.pkl | `81e913ad85a2ec586738c33c1f2d24ecc45d92993e1f4f567d96b27ba46f5c63` | v1 동결본 사본(FROZEN.md 와 동일) |
| models/quantile/20261021_091110/model.pkl | `3b26c445d5b728233e94015d58b52ef32f7f8a811777f015d6f37cb013f48478` | v1 동결본 사본(FROZEN.md 와 동일) |
| models/registry.json | `ead70f38426dfda052939f6e2ec25b04660e57e33d974719d7e8e446f069db93` | 현재 registry 사본 + v2 회귀 항목, current.regression = 20261022_143905 |
| models/FROZEN_v2.md | `dbfce4c0320efbbdc526493b535aba00e48f467964001cf28f5b7e8666ebf4b0` | 초안. 동결 커밋은 '커밋 후 기입'. `verify_frozen.py --models-dir` 통과 |
| submission_v2.csv | `0c77ac8efd3142bbb386e791b3109ca3506eb7b99730490310ed5fe9d133c3b6` | 124행, sample 순서, NaN·음수 0, UTF-8 BOM, 정수(min 5, 중앙 10,723, max 44,218) |
| summary.json | `a1a6a3d7b0839f79291f085516fa6fecc9e48e93011f34210faa8e035d807b55` | 가중치·지표·해시·검증 요약 |
| equivalence.json | `c5b4beb5b0f81be3506dd770c2eca41b41a6663c7565b13f154a47abacd57bc8` | 3절 수치(최종 코드로 재실행, 1.25분) |

- submission_v2 와 v1 제출본의 예측 차(예측끼리만 비교, 정답 미사용): |Δlog10| 중앙 0.093, 최대 0.340.
- 레지스트리에서 다시 읽은 모델의 예측과 메모리 모델의 예측 차: 0.0.

2025 홀드아웃(학습 ≤2024 → 2025 252행). 노트북 4·5절과 같은 절차이며 가중치는 위와 같다.

| 모델 | r2_raw | r2_pearson_raw | nse_raw | rmse_log | mae_log | r2_log | F1@10k | F1@1k |
|---|---|---|---|---|---|---|---|---|
| v2 앙상블 | 0.176 | 0.211 | 0.176 | 0.710 | 0.533 | 0.779 | 0.705 | 0.871 |
| v1 앙상블(재학습) | 0.164 | 0.192 | 0.164 | 0.709 | 0.526 | 0.780 | 0.682 | 0.877 |
| v2 속별 cg 단독 | 0.163 | 0.225 | 0.163 | 0.741 | 0.555 | 0.760 | 0.697 | 0.865 |
| B0 지속성 | −0.283 | 0.148 | −0.283 | 0.896 | 0.591 | 0.649 | 0.727 | 0.852 |

감시(q90_cqr)·경보(p_alert)는 v1 동결 분위·분류기를 쓰므로 v1 과 같다. 테스트에서 v1 경로와 q10·q50·q90·CQR·p_alert 가 정확히 같음을 확인했다. 리드타임 18/20·7/8 도 변하지 않는다.

## 5. 테스트

| 파일 | 내용 |
|---|---|
| `tests/test_v2_upstream.py` | as_of 누수(난수 교체·절반 삭제, 5지점×3기준일), `build_upstream` 행별 누수, 정의(lag 0·diff·HP/DCHN NaN·입력 형식), R2 동등성(load_base 400행 표본), test 124행 confirm_2026 방식 동등성 |
| `tests/test_v2_equivalence.py` | (a)(b)(c) 축약판(같은 스펙, 트리 40개): 구성원 OOF·폴드 2025·가중치·최종 test 124행. 모두 차 < 1e-9(실제 0) |
| `tests/test_v2_registry.py` | 합성 데이터 V2 저장·로드·예측(pickle 왕복), 구성 왕복, 가중치 합 1, 2026 행 가드, verify_frozen(v1+v2 문서·current 불일치·변조)<br>실제 데이터: 임시 v2 레지스트리 make_submission 형식(124행·순서·정수·BOM·LF), 분위·분류기 v1 동일, attach_model_features(v2 부착·v1 미부착·빈 자료 NaN), freeze_v2 dry-run 격리 |

전체: ruff·black(줄 110) 통과, `pytest` 442 통과(실패 0), `tests/test_no_2026_targets_outside_live.py` 통과.

## 6. 남은 단계(사람이 실행)

1. (선택) 재확인: `python scripts/check_v2_equivalence.py`(약 1.2분, 종료 코드 0).
2. **실제 동결**: `python scripts/freeze_v2.py --freeze`. 다음을 만든다.
   - `models/regression/<버전>/model.pkl·meta.json`
   - `models/registry.json` current.regression 갱신
   - `models/FROZEN_v2.md`
   - `dist/v1/submission_v1.csv`(v1 보존 사본)
   - `submission/submission.csv`(v2)

   같은 라이브러리·데이터면 model.pkl sha256 이 dry-run 과 같아야 한다(`d696f693…`). 이어서 `python scripts/verify_frozen.py` 를 실행한다(v1·v2 문서 모두 OK, current OK).
3. **동결 커밋**: 커밋할 파일은 registry.json, FROZEN_v2.md, regression/<버전>/meta.json, submission/submission.csv 다. pkl 은 git 제외다. 커밋 뒤 FROZEN_v2.md 의 `커밋 후 기입` 자리에 동결 커밋 해시를 적는다(v1 FROZEN.md 와 같은 방식).
4. **Release**:
   - tarball 만들기(v1 과 같은 이름 규칙):
     `tar -czf dist/models-frozen-v2-<커밋7>.tar.gz models/registry.json models/FROZEN.md models/FROZEN_v2.md models/regression/20261021_091108 models/regression/<v2버전> models/classifier/20261021_091109 models/quantile/20261021_091110`
   - Release 만들기: `gh release create model-v2-<커밋7> dist/models-frozen-v2-<커밋7>.tar.gz`
   - 태그 이름은 docs/DEPLOY.md 4단계의 `model-v2-<commit>` 을 따랐다. V2_PLAN 의 git 태그 `v2-frozen-<sha>` 는 함께 달아도 된다.
5. **워크플로 태그 교체**: `daily.yml` 의 FROZEN_TAG 기본값 `model-frozen-13ac483` → `model-v2-<커밋7>` 로 바꾼다.
   - **동결 커밋과 같은 push 에 넣는다.** v1 tarball 을 풀면 registry.json 이 v1 current 로 덮인다. 그러면 git 의 FROZEN_v2.md 가 가리키는 v2 pkl 이 없어 verify_frozen 이 실패한다.
   - push 전에 `workflow_dispatch`(dry_run=true, frozen_tag=model-v2-<커밋7>)로 미리 확인할 수 있다.
6. **노트북 실행**: `notebooks/01_train_eval.ipynb` 를 실행한다. 1절 동결 검증은 FROZEN_v2.md 를 쓰고, 5절에 v1·v2 2025 표, 6절에서 v2 submission.csv 를 만든다.
7. **제출 패키지**: `python scripts/build_submission_package.py` → `verify_package.py`. 이어서 패키지 README 의 '동결 모델 3종'·동결 커밋 문구(빌더가 FROZEN.md 의 v1 커밋을 읽음)와 방법설명서를 v2 기준으로 갱신한다(V2_PLAN ③).
8. 대시보드: `db/upload.py predictions_rows` 의 2025 홀드아웃 행은 v1 OOF 캐시(`oof_predictions.parquet`)를 그대로 올린다. 또 web `numbers.ts`·`copy.ts` 성능 수치·모델 설명도 갱신해야 한다(V2_PLAN ④). `eval/report.py`(v1 보고서 생성기)는 바꾸지 않았다.
