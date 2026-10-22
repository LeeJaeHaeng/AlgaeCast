# EXP-confirm 독립 검증

검증일 2026-10-22. 검증자는 실행자와 별도로 `PREREG.md`, `confirm.py`, 하네스 코드와 저장 OOF·`results.json` 을 읽었다. 판정 값은 독립 구현으로 다시 계산했고, 15개 구성 전부를 처음부터 다시 학습했다.
저장소 코드와 데이터는 고치지 않았다. 검증 스크립트는 세션 임시 폴더에만 두었다.
`test_targets_DO_NOT_USE.parquet`·`posthoc_2026.parquet` 는 읽지 않았고, 2026 계산도 하지 않았다.

## 결론: 사전등록 규칙상 **채택**

(a)·(b)·(c) 일곱 개 판정 값을 모두 독립적으로 재현했다. 소수 넷째 자리는 물론 부동소수 오차 수준(≤1e-16)까지 같다. 모두 사전등록 문턱을 충족한다.
판정을 바꿀 문제(critical·major)는 찾지 못했다. 아래 '참고 사항'은 기록용이고 판정에 영향이 없다.

| 조건 | 재계산 값 | results.json | 문턱 | 판정 |
|---|---|---|---|---|
| (a1) 시드 평균 Δ CV r2_raw (C − v1_s) | 0.116058 | 0.116058 | ≥ 0.080 | 충족 |
| (a2) 블록 부트스트랩 95% 하한 | 0.053210 (95% [0.0532, 0.1415], 중앙 0.1159, Δ̄≤0 비율 0.1%) | 0.053210 | > 0 | 충족 |
| (a3) 시드 평균 (C − K) | 0.083850 | 0.083850 | ≥ 0.040 | 충족 |
| (b1) 2025 r2_raw(5시드 평균) | 0.165906 | 0.165906 | ≥ 0.145829 | 충족 |
| (b2) 2025 rmse_log | 0.712881 | 0.712881 | ≤ 0.717870 | 충족 |
| (b3) 2025 F1@10k | 0.686608 | 0.686608 | ≥ 0.662353 | 충족 |
| (b4) 리드타임(q90≥10k) | 18/20 | 18 | ≥ 18 | 충족 |
| (c) 누수 테스트 4개 파일 | 67 통과 / 0 실패 | — | 전부 통과 | 충족 |

시드별 Δ(C − v1_s): 0.1115, 0.1236, 0.1136, 0.1272, 0.1045. 시드별 (C − K): 0.0777, 0.0815, 0.0830, 0.0916, 0.0854. 다섯 시드 모두 각 문턱을 넘는다.

## 1. 사전등록 일치

**순서.** 커밋 7e010d8 은 rebase 로 다시 쓰인 커밋이다. reflog 에 원래 커밋 d7dd16b(2026-10-22 10:52:10)가 남아 있다.
`confirm.py` 는 그보다 41초 늦은 10:52:51 에 처음 생겼고, 첫 OOF 는 10:53:25, `results.json` 은 10:57:13 에 만들어졌다. 따라서 사전등록 커밋이 코드 작성과 실행보다 먼저다.
`git diff d7dd16b 7e010d8 -- PREREG.md` 는 비어 있다. rebase 전후로 사전등록 내용이 바뀌지 않았다.

**코드 대조.** `confirm.py` 와 호출 경로를 PREREG 와 한 항목씩 대조했고, 다른 점은 없다.

| 항목 | PREREG | 코드 | 일치 |
|---|---|---|---|
| C 회귀 구성원 | C1·C3·C2, v1 하이퍼파라미터, v1 30 + R2 5열 | `H.run_members(dfx, base_columns()+f2, seeds=(s,), quantiles=False)` → `v1_specs()` | 예 |
| R2 열 | `CHOSEN`(lag 0, 1단계, all4_diff) 5열 | `up1_cell_log·up1_slope3·up1_wtemp·up1_days·up1_diff`. HP·DCHN 은 모두 NaN | 예 |
| 속별 cg | R3 G2(micro+rest, log, smearing, 자기회귀 피처 없음), 같은 35열 | `RC.genus_members(dfx, cols, s)`, `R3.CHOSEN`={g2, log/log, smear, features False} | 예 |
| 결합 | `ensemble_expanding(names=(c1,c3,c2,cg))`, log NNLS 합=1, 연도 확장, 2025 는 2020~2024 전체 | 같음 | 예 |
| 분위 | v1 동결 OOF(baseline/oof.parquet) q90 고정 | `H.load_baseline()` 의 q90. 저장 OOF 15개의 q90 이 baseline 과 비트 단위로 같다 | 예 |
| v1_s | 30피처, C1·C3·C2, 3구성원 NNLS, 같은 시드 | `config_members(df, None, s, False)` | 예 |
| K_s | R2 5열을 같은 결측 위치의 표준정규 난수로, 생성기 (20261022, s, 5), cg 도 35열 | `RC.control_columns(index, 5, s, mask=f2.notna())`. 독립 생성 난수와 비트 단위로 같고 결측 위치도 같다 | 예 |
| 시드 | (101, 202, 303, 404, 505), LightGBM random_state | `SEEDS` → `_lgb_params(random_state=seed)` | 예 |
| 부트스트랩 | (연도·지점) 블록 25개, 2,000회, 생성기 20261022, 시드별 Δ 재계산 평균, 2.5 백분위 | 같음. 블록 25개 확인 | 예 |
| 2025 기준 | 동결 v1(baseline_metrics.json) | 같음. baseline OOF 로 다시 계산해도 0.165829·0.707870·0.682353 | 예 |
| 문턱 | (a) 0.08·>0·0.04, (b) −0.02·+0.01·−0.02·18 | `THRESH`·`NONINF`·`>= 18` | 예 |

## 2. 판정 값 재계산

**행 순서.** OOF 파일 15개를 `harness.load_base()` 의 station_id·base_date·target_date·target_cells 와 대조했다. 15개 모두 같다(2,566행, CV 1,278행, 2025 256행).

**결합 재현.** 증강행 NNLS 를 독립 구현해 저장 구성원으로 결합을 다시 만들었다. 저장 `pred` 와의 log10 최대 절대차는 0, 2025 가중치 차이도 0이다.
참고로 합=1 을 정확히 강제하는 심플렉스 해와 비교하면 log10 최대차가 1.0e-3 이다. v1 과 같은 근사 방식이고 결과 차이는 무시할 만하다.

**지표 재계산.** r2_raw = 1 − SSE/SST, rmse_log 는 log10(x+1) 공간, F1@10k 는 ≥10,000 기준으로 직접 계산했다. 리드타임은 `harness.leadtime` 을 썼다. 15개 행 모두 `results.json` 과 1e-9 이내로 같다.

**부트스트랩.** 블록별 충분통계(n, Σo, Σo², 시드별 SSE)에 복원추출 횟수를 곱하는 방식으로 독립 구현했다. 하한·상한·중앙값이 저장 값과 1e-16 이내로 같다.

**처음부터 재학습.** 시드 5개 × {v1, C, K} 15개 구성을 모두 다시 학습했다(3.9분). 구성원(c1·c3·c2·cg)과 `pred` 의 log10 최대 절대차는 15개 모두 **0** 이다.
v1 시드 42 도 다시 학습해 `baseline/oof.parquet` 와 비교했고 차이는 0 이다. 그래서 features_S1 재생성(10:41)이 v1 행 내용을 바꾸지 않았음도 확인된다.

## 3. 2026 미사용

- 실행 경로는 `load_base`(`load_train_valid`, test 분할 제외 + `guard_no_2026`), R2·R3 `load_algae`(측정 ≤ 2025-12-31), `leadtime`(≤ 2025-12-31)이다. 프레임마다 `guard_no_2026` 을 다시 확인한다. 2026 행과 격리 타깃은 쓰지 않는다.
- 저장 OOF 15개의 base_date 최대는 **2025-12-29** 다(≤ 2025-12-31).
- `confirm.py` 와 import 대상(harness·r_combo·r2_upstream·r3_genus·models.data/train/cv)에는 `test_targets`·`posthoc_2026`·`load_test_targets` 참조가 없다.

## 4. 누수 테스트

- `pytest tests/test_no_leakage.py tests/test_exp_r2_upstream.py tests/test_exp_r3_genus.py tests/test_exp_harness.py`: **67 passed**(3.8초).
- 전체 `pytest`: **289 passed**(44.8초).

## 5. 참고 사항(판정 영향 없음)

1. **rebase 가 실행 중에 일어났다.** 10:54:09 에 로컬 커밋들이 origin/main(7f98a15) 위로 rebase 됐다(reflog 'rebase (start): checkout origin/main'). origin/main 이 더한 것은 mulmoa CSV 2개뿐이다. K_101 과 v1_202 사이였고, 그 순간 추적 파일이 잠시 지워졌다가 다시 생겼다(baseline_metrics.json 생성 시각 10:54:09).
   15개 구성 전부를 다시 학습해도 결과가 정확히 같으므로 영향은 없었다. 다만 공개 이력의 7e010d8 committer 시각(10:54:09)은 실행 시작보다 늦다. 사전등록이 먼저였다는 근거는 author 시각(10:52:10)과 로컬 reflog(d7dd16b)뿐이다.
   RESULT.md 에 이 경위를 한 줄 남겨 두기를 권한다.
2. **`confirm.py` 가 아직 미커밋이다.** 판정 커밋에 함께 넣어야 재현할 수 있다.
3. **`confirm_2026.py` 가 미리 작성돼 있다.** 판정 커밋 전인 11:00:30 에 미커밋 상태로 만들어졌다.
   실행 흔적(`posthoc_2026_C.parquet`·`posthoc_2026.json`)은 없다. HEAD 의 RESULT.md 가 '채택'으로 커밋돼 있지 않으면 중단하는 가드도 있다.
   2026 계산은 일어나지 않았다(작성은 PREREG 가 금지하는 '판정 전 2026 계산'에 해당하지 않음).
4. **2025 검증 4행은 target_date 가 2026-01-05 다.** HP·CS·MGMR·DCHN 의 base_date 2025-12-29 행이다. v1 분할 정의(base_date 기준 valid)의 일부라 동결 v1 기준과 똑같이 2025 평가 관측에만 쓰였다.
   학습에는 쓰이지 않았다. R3 속별 타깃은 2025-12-31 이후 측정을 버려 이 행에서 NaN 이다. 2026 test 124 조합과는 무관하다.
5. **2025 에서는 개선이 없다.** 같은 시드 v1_s 평균과 비교하면 C 의 2025 r2_raw 는 −0.0045(0.1659 vs 0.1704), rmse_log 는 +0.0071(0.7129 vs 0.7058)이다.
   사전등록 기준은 동결 v1 이라 판정과 무관하고, v1_s 기준으로 보더라도 비열등 여유(−0.02, +0.01) 안이다. 대조군 K 의 2025 r2_raw(0.1926)가 C 보다 높다.
   RESULT.md 의 해석('2025 는 비열등까지만 확인')과 근거 표 수치(v1_s 0.170·0.706·0.684, C 가중치 범위 등)는 재계산 값과 일치한다.
