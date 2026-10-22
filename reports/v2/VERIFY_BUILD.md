# v2 운영 구현 독립 검증 (VERIFY_BUILD) — 2026-10-22

대상: `reports/v2/BUILD.md` 의 v2 운영 구현(최종 모델 C). 검증자는 코드를 고치지 않았고, 저장소에는 이 문서만 새로 썼다.
2026 정답과 격리 파일은 읽지 않았다.

## 1. 결론

여섯 항목 모두 실행자 보고와 같은 결과가 나왔다. 동결을 막을 결함은 찾지 못했다. 다만 동결과 별개로 고칠 점 1건(major)과 문서·절차 주의점 5건(minor)이 있다(9절).

| 점검 | 판정 | 핵심 수치 |
|---|---|---|
| (1) 동등성 (a)~(d) | 통과 | (a)(b)(c) 차 0.0. (d) 운영 예측 경로 124/124 일치. (d) 재학습 불일치(1/124)의 원인인 '동결 v1 = 2,566행 학습'을 전 트리 배깅 표본 수로 확인 |
| (2) as_of·2026 누수 | 통과 | 미래 측정 교란 184/184행 불변. 과거 교란 감도 139/139행 반응. 2026 측정 교란 시 학습 2,562행·속별 타깃·cg 예측 불변. 가드 5종 모두 중단 |
| (3) predict·daily 경로 | 통과 | v1 CLI 제출본이 기존 파일과 바이트 동일. v1 `predict_registry` 가 변경 전(HEAD)과 444행 × 12열 모두 같음. v2 형식 검증 통과 |
| (4) dry-run 격리·동결 모드 | 통과 | 실행 전후 models/·submission/·dist/·config/ 등 39파일 해시 동일. 동결 모드를 임시 사본에서 실행해 FROZEN_v2 필수 항목 11/11 확인, verify_frozen 통과 |
| (5) 테스트 | 통과 | 전체 pytest 442 passed(종료 코드 0). `test_no_2026_targets_outside_live.py` 5 passed(종료 코드 0, dry-run 전후 2회). ruff·black(110) 통과 |
| (6) 노트북 2026 정답 미열람 | 통과 | 노트북 코드를 실행하며 열린 파일을 모두 기록했다. 정답류 경로 0건, `eval.live`·`eval.posthoc` 미적재, 저장소 파일 변경 0 |

## 2. 방법(독립성)

- 검증 코드는 모두 새로 썼고 `%TEMP%` 아래 세션 scratchpad 에 두었다(저장소 밖). 파일은 `vb_equiv.py`, `vb_leak.py`, `vb_predict.py`, `vb_v1_head.py`, `vb_freeze_sandbox.py`, `vb_notebook.py`, `vb_hash.py` 다.
- 실행자의 `scripts/check_v2_equivalence.py` 와 `tests/test_v2_*.py` 결과는 쓰지 않았다. 실행자 테스트는 (5)의 전체 pytest 에서만 함께 돌렸다.
- 비교 기준은 실험 코드다.
  - `exp.confirm.config_members` + `exp.harness.ensemble_expanding` (C 시드 42 OOF·2025 가중치)
  - `exp.confirm_2026.final_fit_predict` (최종 학습 경로)
  - `exp.r2_upstream.build_features`·`build_variant_features`
  - `exp.r3_genus.genus_targets`
- 운영 코드는 `models.v2`·`models.genus`·`features.upstream`·`db.upload.predict_registry`·`models.predict` CLI·`predict.asof`·`scripts/daily_run.py`·`scripts/freeze_v2.py` 를 썼다.
- 2026 규칙
  - `eval.live.load_test_targets` 를 호출하지 않았고 격리 파일을 열지 않았다.
  - 속별 타깃 교란에는 실제 2026 측정을 버리고 합성 2026 행을 넣었다(값 미열람).
  - 격리된 4행(목표일 2026-01-05)의 타깃은 0 자리표시로 채워 배깅 표본 수만 셌다. 표본 수는 타깃 값과 무관하다.

## 3. (1) 동등성

| 항목 | 비교 | 결과 |
|---|---|---|
| 학습 행 | `harness.load_base()` vs `V2.load_training_frame()` | 둘 다 2,562행이고 키·순서가 같다. 기준일 ≤ 2025-12-22, 목표일 ≤ 2025-12-29, 분할은 train·valid 뿐이다 |
| 하이퍼파라미터 | `V2.member_specs()`(config/model.yaml) vs `harness.v1_specs()`(optuna JSON) | c1·c3·c2 모두 같다(분류기 파라미터 포함) |
| 피처 열 | `config_v2().cols` vs `base_columns() + R2 5열` | 35열, 순서까지 같다 |
| (u) 상류 피처 — 학습 | `build_upstream` vs `R2.build_features` | 완전 일치, NaN 6,020칸 위치 동일 |
| (u) 상류 피처 — test | `build_upstream` vs `R2.build_variant_features(lag 0, 원자료 ≤2026-12-31)` | 완전 일치. 열마다 NaN 45개이고, 모두 HP·DCHN 행이다 |
| 속별 타깃 | `genus.genus_targets` vs `R3.genus_targets` | y_4속·y_sum4·consistent 모두 일치. 부분 타깃 행은 micro 2,457·rest 2,457 |
| (a') 구성원 OOF 2020~2025 | `V2.cv_members` vs `config_members` | log10 최대 차 c1 0.0 · c3 0.0 · c2 0.0 · cg 0.0 |
| (b) 가중치 | `V2.fit_weights(시드 42)` vs `ensemble_expanding` 2025 | 최대 절대차 0.0, 순서 동일, 합 1.0. c1 0.000000 · c3 0.266051 · c2 0.373269 · cg 0.360680 |
| (a) 폴드 모드 | `fit_final(≤2024, 2,310행).predict(2025, 252행)` vs C 시드 42 OOF | log10 최대 차 **0.0**(구성원별 0.0) |
| (c) 최종 모드 | `fit_final(2,562행)` 기본 경로(가중치 내부 계산).predict(test 124) vs `final_fit_predict` + combine | log10 최대 차 **0.0**, 원단위 0.0, 구성원 4개 0.0. 내부 가중치도 실험 값과 같다 |
| dry-run 산출물 | 실행자 dry-run 레지스트리(20261022_143905, pkl `d696f693…`)를 다시 읽어 예측 | 실험 C 예측과 log10 차 0.0. 가중치·열 동일. aux(분류기·분위 입력)는 v1 회귀의 열·범주와 같다. `submission_v2.csv` = round(C) 124/124. FROZEN_v2 표 해시 3/3 일치 |
| (d1) v1 운영 예측 | `predict_registry`(models/, v1) → 반올림 | v1 제출본 124/124(최대 차 0) |
| (d1') v1 감싼 예측 | `from_v1_registry` → `V2Model.predict` | 124/124, `predict_registry` 와 log10 차 0.0 |
| (d2) v1 운영 학습 | `fit_final(config_v1, 2,562행)` vs `final_fit_predict`(c1·c3·c2) + model.yaml 가중치 | log10 차 0.0(구성원별 0.0) |
| (d3) v1 재학습 → 제출본 | (d2) 예측 반올림 | 1/124 일치, 최대 차 3,144 cells/mL, 동결 v1 예측과 log10 차 0.1119 |
| (d4) 원인 확인 | 동결 v1 각 트리의 루트 표본 수(배깅 후) vs 2,566행 재적합(격리 4행 타깃 = 0 자리표시) vs 2,562행 재적합 | 동결 = 2,566행: c1 700/700 트리, c2 1,400/1,400, c3 분류기 700/700 이 같다. 동결 = 2,562행: 22/700, 49/1,400, 18/700 만 같다. 첫 트리는 2202·2145·1669(동결 = 2,566) vs 2198·2141·1666(2,562) |

(d4)로 실행자 설명이 맞음을 확인했다. 동결 v1 은 목표일 2026-01-05 인 4행(HP·CS·MGMR·DCHN, 기준일 2025-12-29)을 포함한 2,566행으로 학습됐다. 그래서 그 4행의 격리된 2026 정답 없이는 재학습으로 v1 제출본을 재현할 수 없다. v2 는 이 4행을 쓰지 않는다(지시대로 목표일 ≤ 2025-12-31).

## 4. (2) as_of·2026 누수

코드를 읽어 확인한 점은 다음과 같다.

- `make_upstream_features`·`upstream_point_features` 는 진입 직후 `cut_as_of(as_of)` 를 적용한다. `build_upstream` 은 행마다 그 행의 base_date 를 as_of 로 넘긴다.
- 상류 피처는 바로 위 지점 자료만 쓴다. `up1_diff` 의 자기 지점 값은 v1 피처 `cell_log_t0` 이다.
- `genus.load_target_algae` 는 읽은 즉시 2025-12-31 이후 측정을 버린다. `genus_targets` 는 2026 측정이 섞인 원자료를 거부한다. `guard_targets`·`guard_train` 은 기준일·목표일 > 2025-12-31 행과 test 분할을 거부한다.
- 운영 모듈·freeze/daily/verify 스크립트·노트북에는 정답 로더 참조가 없다(grep). 노트북의 리드타임 주석 1줄만 사후 표 파일 이름을 언급한다.

실제 원자료(5지점 측정 2,979행, 마지막 측정 2026-10-15)를 교란해 다시 계산했다.

| 시험 | 내용 | 결과 |
|---|---|---|
| U1 | 2026 측정 261행을 난수로 바꾸고 가짜 15행 추가 → 학습 2,562행 상류 피처 | 불변 |
| U2 | 학습 60행 + test 124행. 행마다 기준일 이후 측정 전부를 난수로 바꾸고 절반 삭제, 기준일 +1일 가짜 행 추가 | 184/184행 불변 |
| U2 감도 | 같은 행에서 상류 지점의 기준일 이하 마지막 측정을 ×10 | 상류가 있는 139/139행이 변함(시험이 공회전이 아님) |
| U3 | MGMR·DCHN 자기 지점 원자료 전체 교란 | 불변 |
| U4 | lag 0 정의 | 기준일 당일 상류 측정을 포함한다(예: MGMR test 행 up1_days = 0). 설계(V2_PLAN 4절, v1 `cell_log_t0` 와 같은 공개 시점 제약)대로다 |
| G1 | 속별 타깃 원자료 | 마지막 측정 2025-12-29 |
| G2·G3 | 실제 2026 측정을 버리고 합성 2026 측정 210행으로 바꾼 파일 → 속별 타깃·cg test 예측 | 둘 다 동일 |
| G4·G5 | 2026 측정이 섞인 원자료, 목표일 2026 행이 섞인 표본 → `genus_targets` | 둘 다 RuntimeError 로 중단 |
| V5·V6·V7 | 목표일 2026 행 → `guard_train`·`fit_final`, test 분할 행 → `guard_train` | 모두 RuntimeError 로 중단 |

## 5. (3) predict·daily 경로

| 시험 | 결과 |
|---|---|
| `python -m algaecast.models.predict --out <임시>`(v1 레지스트리) | 종료 코드 0, `submission/submission.csv` 와 **바이트 동일**(sha256 `182f4cb8…`) |
| 새 `predict_registry` vs HEAD(변경 전) `predict_registry`, v1 레지스트리 | test 124행·지점별 최신 행·2025-06 이후 행, 합계 444행에서 12열(점예측·분위·CQR·p_alert·플래그·tier·운영점)이 모두 같고 인덱스도 같다 |
| `python -m algaecast.models.predict --registry <dry 레지스트리>`(v2) | 종료 코드 0, dry-run `submission_v2.csv` 와 바이트 동일(`0c77ac8e…`). 형식은 BOM·LF·끝 줄바꿈, 헤더 = sample, 124행, sample 순서, int64, NaN 0, 음수 0, 최소 5·중앙 10,723·최대 44,218. v1 대비 \|Δlog10\| 중앙 0.0928·최대 0.3404 |
| `predict_registry` v1 vs v2(test 124) | 같은 열: q10·q50·q90·q10_cqr·q90_cqr·p_alert·watch·alert·tier·operating_point. tier 는 둘 다 alert 85·watch 11·normal 28. 점예측만 다르고, 점예측은 실험 C 와 log10 차 0.0 |
| `attach_model_features` v1 | 입력 프레임을 그대로 돌려준다(같은 객체) |
| `attach_model_features` v2 | 수집기 형식(iem_* 열, 2025-09-01 이후 창) 자료로 계산한 상류 5열이 전체 parquet 계산과 같다. 빈 자료면 5열이 모두 NaN 이고 경고를 남긴다 |
| `daily_run.upload_predictions(dry=True)` v1·v2 | 둘 다 ("dry-run", 5)를 반환했다. v2 에서 피처를 붙여 넘긴 예측과 붙이지 않고 수집 자료만 넘긴 예측이 같다. 분위·p_alert·tier 는 v1 과 같다 |
| `shap_and_reco_rows` v2 | SHAP 40행·권고 5행이 생성된다. 다만 설명 대상이 v2 가중치 **0.0** 인 c1 구성원이다(9절 1번) |

## 6. (4) dry-run 격리·동결 모드

- **dry-run 격리**
  - `scripts/freeze_v2.py --dry-run` 전후로 39파일 해시를 비교했다. 대상은 models/ 전체, submission/, dist/, config/, features_S1, splits, v1 OOF, 격리 파일, 조류 원자료다. 모두 같았다.
  - `git status` 도 실행 전후 같았다. 실행 시점 이후 바뀐 파일은 `data/processed/exp/v2_dryrun/` 아래뿐이다.
- **재실행 결과**
  - 회귀 model.pkl `d696f693…` 와 submission_v2 `0c77ac8e…` 가 실행자 값과 같았다(결정론적).
  - 2025 홀드아웃 지표도 실행자 값과 같았다(r2_raw 0.1755, rmse_log 0.7102, F1@10k 0.7045).
  - 확인 뒤 실행자의 원래 dry-run 산출물로 되돌렸다(`diff -r` 동일). BUILD.md 4절 해시가 그대로 유효하다.
- **동결 모드(`--freeze`) 실행**
  - models/·submission/ 사본을 `%TEMP%` 에 두고 `freeze_v2` 의 경로 상수와 레지스트리 경로만 바꿔 실제 모드 코드를 돌렸다. 실행 전후 저장소 해시는 같았다.
- **동결 모드 산출물**

| 확인 | 결과 |
|---|---|
| 레지스트리 | current regression 은 새 버전(ensemble_v2), classifier·quantile 은 v1 버전 그대로다. v1 회귀 항목·pkl 은 보존된다 |
| 회귀 pkl | sha256 `d696f693…`(dry-run 과 같음) |
| FROZEN.md(v1) | 바뀌지 않음 |
| submission.csv | v2(dry-run submission_v2 와 바이트 동일)로 바뀐다. v1 사본은 `dist/v1/submission_v1.csv` 에 원본과 바이트 동일하게 남는다 |
| FROZEN_v2.md 필수 항목 | 11/11 있다. 동결 커밋 줄, 동결 시각, EXP-confirm 근거, 학습 범위(2,562행·기준일·목표일·지점별), 시드 42, 가중치, 피처 35, 2025 홀드아웃, 분류기·분위 v1 유지, FROZEN.md 보존, submission sha256 이다. 제목에 dry-run 표기가 없고, 표 해시 3/3 과 submission sha256 이 실제 파일과 같다 |
| `verify_frozen.py --models-dir <사본>` | 종료 코드 0. FROZEN.md·FROZEN_v2.md 모두 OK, current 3개 OK |
| 두 번째 `--freeze` | "FROZEN_v2.md 가 이미 있다" 로 중단된다 |
| v1 registry.json 으로 덮인 상황(Release 태그 교체 누락) | verify_frozen 종료 코드 1(current regression MISMATCH). 일일 실행은 v1 으로 조용히 돌지 않고 멈춘다(fail-closed) |

## 7. (5) 테스트·정적 검사

- `pytest -q`(전체): **442 passed**, 60.3초, 종료 코드 0.
- `pytest tests/test_no_2026_targets_outside_live.py`: 5 passed, 종료 코드 0. dry-run·동결 모드 실행 뒤에도 같았다.
- `ruff check .`: 통과. `black --check -l 110 .`: 132파일 변경 없음.
- pytest 실행 전후 39파일 해시도 같았다.

## 8. (6) 노트북

- `.ipynb` 를 jupytext 로 py:percent 변환한 결과가 `01_train_eval.py` 와 같다(줄바꿈 문자만 다름). 커밋된 노트북에는 출력이 없다(변경 전과 같음).
- **실행 방법**
  - 노트북 코드를 실행하면서 `open`(audit hook)·`pd.read_parquet`·`pq.read_table`·`pd.read_csv` 경로를 모두 기록했다.
  - 데이터 재생성(`ALIGN.main`·`FEAT.main`)은 건너뛰고 기존 산출물을 썼다.
  - 그림·submission 출력 경로는 `%TEMP%` 로 바꿨다.
- **결과**
  - 오류 없이 0.5분에 끝났다.
  - 정답류 경로(test_targets·격리·posthoc)를 연 기록 0건, `eval.live`·`eval.posthoc` 미적재, 저장소 파일 변경 0건.
  - 읽은 parquet 은 features_S1, interim MGMR 일 달력, v1 OOF 캐시(2020~2025), 조류 원자료(행마다 as_of)다.
- **동결 전 상태라 레지스트리는 v1**
  - 노트북 4절이 v2 가중치를 다시 계산했고 값이 위 가중치와 같았다.
  - 5절 표의 v2 값은 r2_raw 0.176, rmse_log 0.710, r2_log 0.779, F1@10k 0.705 다.
  - 6절 submission 은 v1 제출본과 바이트 동일했다.
- 확인하지 못한 것: 노트북의 데이터 재생성 단계(`FEAT.main`)는 실행하지 않았다. 다만 이 단계는 v1 과 같은 코드다.

## 9. 발견 사항

1. **[major] v2 SHAP 설명 대상이 가중치 0 인 구성원이다.**
   - `registry.explain_member` 가 ensemble_v2 에서 `c1` 을 고른다. 그런데 v2 결합 가중치는 c1 0.000 이다.
   - 그래서 `shap_and_reco_rows` 가 만드는 대시보드 SHAP 기여·권고 문장(`explain_sentence`)은 점예측에 기여하지 않는 모델을 설명한다. v1 에서는 C1 가중치가 0.146 이었다.
   - 동결 산출물·제출본·예측값에는 영향이 없다. 설명 코드(upload/registry)는 동결 후에도 바꿀 수 있다.
   - 대시보드에 v2 를 반영하기 전에 설명 대상을 정해야 한다. 예: 가중치가 가장 큰 c2, 또는 구성원 SHAP 의 가중 합.
2. **[minor] 2026 사후 수치는 동결될 v2 의 값이 아니다.**
   - RESULT.md·V2_PLAN 의 2026 사후 수치(C r2_log 0.517·F1 0.824)는 격리 확대(ee9a9b0, 10-22 14:09) 전에 계산됐다. 사후 커밋은 be6585d, 10-22 11:10 이다.
   - 즉 2,566행으로 학습한 C 의 값이다. RESULT.md 의 'v1 구성 124행 재현 검산'과 (d4)가 이를 뒷받침한다.
   - 동결될 v2 는 2,562행으로 학습한다. (d3)로 미루어 test 예측이 log10 0.1 안팎 다를 수 있다. 2025 홀드아웃도 256행에서 252행으로 줄었다(0.177 → 0.1755).
   - BUILD.md 3.4 의 "confirm_2026 판정 경로가 같은 2,562행을 쓴다"는 현재 코드 기준의 설명이다.
   - 방법설명서·대시보드에 v2 의 2026 성능을 적을 때는 이 차이를 밝혀야 한다. 2026 사후 계산은 PREREG 상 1회라 다시 계산하지 않는 것이 맞다.
3. **[minor] `--freeze` 가 submission.csv 를 v2 로 바로 덮는다.**
   - V2_PLAN 0-2(제출 교체 여부)는 사용자 결정 사항이다. V2_PLAN ② 는 `submission_v2.csv` 를 따로 만들도록 적었다.
   - v1 보존본 `dist/v1/submission_v1.csv` 는 `.gitignore`(dist/) 대상이다. 다만 v1 submission.csv 는 git 추적 파일이라 이력으로 복구할 수 있다.
   - `--freeze` 실행 전에 교체 결정이 필요하다.
4. **[minor] FROZEN_v2.md 의 동결 커밋이 자리표시로 남는다.**
   - '커밋 후 기입' 자리표시를 사람이 채워야 하고, verify_frozen 은 이를 검사하지 않는다.
   - 운영점·CQR·임계 수치를 문서에 직접 적지 않고 config/model.yaml 을 가리킨다. v1 FROZEN.md 는 수치를 직접 적었다.
5. **[minor] 동결 뒤 v1 재현 경로가 따로 없다.**
   - 동결 뒤 `make reproduce` 는 v2 끼리 비교한다. v1 제출본 재현(V2_PLAN 3절 'v1 diff 0 유지')을 하려면 v1 current 임시 레지스트리를 만들어 `predict --registry` 로 돌려야 하는데, 이를 위한 스크립트나 Make 타깃이 없다.
6. **[minor] 실행자가 이미 보고한 남은 단계를 재확인했다.**
   - 남은 단계: daily.yml 태그 교체를 동결 커밋과 같은 push 에 넣을 것. 교체를 빠뜨리면 fail-closed 로 멈추는 것을 확인했다.
   - 태그 이름(model-v2 / v2-frozen)을 정해야 한다.
   - `predictions_rows` 의 2025 OOF 는 아직 v1 이다.
   - 패키지 README·방법설명서·대시보드 수치가 아직 v1 기준이다.

참고: 동결 v1 은 목표일 2026-01-05 인 4행(2026 측정)을 학습에 썼다((d4)). 이 4행은 test 조합은 아니다. v2 는 이 행을 쓰지 않는다.
