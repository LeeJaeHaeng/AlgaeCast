# 04. 통계분석·모델링·튜닝·평가 명세서

## 1. 통계분석 (T2, `notebooks/02_stats.ipynb` → `reports/eda/`)

| # | 분석 | 방법 | 산출물 | 보고서 용도 |
|---|---|---|---|---|
| S1 | 타깃 분포 | 원단위·log10(x+1) 히스토그램, 0값 비율, 분위수, Anderson-Darling | `fig_target_dist.png` | 변환 근거 |
| S2 | 지점별 계절성 | 월별 상자그림, STL 분해(주기 52주) | `fig_seasonal_<site>.png` | 월 피처 근거 |
| S3 | lag 상관 | 세포수(log) vs 각 변수의 0~30일 lag Spearman 히트맵 | `fig_lag_corr.png` | 창 길이(7/14/30) 선정 근거 |
| S4 | 선행연구 재현 | 수온 0.630, 월 0.374, 유입량 0.188, 방류량 0.187(송찬영 외, 2023) 동일 지표 재계산 | `tbl_corr_vs_prior.md` | 데이터 타당성 |
| S5 | 정상성 | ADF, KPSS (지점별) | `tbl_stationarity.md` | 차분 여부 |
| S6 | 지점 이질성 | Kruskal-Wallis(세포수), 지점별 세포수-수온 LOESS 곡선 | `fig_site_response.png` | 지점 범주형 피처 근거 |
| S7 | 조기화 추세 | 연도별 첫 경보일(관심/경계) Mann-Kendall + Sen's slope | `tbl_onset_trend.md` | 정책 브리프 핵심 그림 |
| S8 | 결측 구조 | 변수×월 결측률 히트맵, 결측여부~유입량·강수 로지스틱 회귀(OR, p) | `fig_missing.png`, `tbl_mnar.md` | 결측 전략 근거 |
| S9 | 급증 사례 | 5일 내 10배 이상 증가 사건 목록과 선행 7일 수온·방류 패턴 | `tbl_bloom_events.md` | 발표 사례 |
| S10 | 다중공선성·중요도 | VIF, Mutual Information, Boruta | `tbl_feature_select.md` | 피처 선별 |

**T2 실행 메모 (2026-10-21, `notebooks/02_stats.py` ↔ `02_stats.ipynb` jupytext 페어링, `make eda`)**: 결과는 `reports/eda/SUMMARY.md`·`captions.md`·tbl_*.md. S7 '통합' 은 2012~2015 년에 회남만 있어 지점 구성 변화가 추세로 잡히므로 지점 평균 제거 잔차(2016~) 검정을 정본으로 한다(관심 Sen −1.0 일/년, p=0.64 → 유의한 조기화 없음; 단순 연도 중앙값은 −3.7 일/년 p=0.01 이지만 교란). S8 은 주 1회 채수가 유지돼 '미채수' 대신 측정 간격 ≥9일(지연 채수)을 종속변수로 썼고 유입량 OR 1.44(p=0.007) 로 MNAR 가설을 약하게 지지. S9 는 주 1회 채수라 5일 이내 사건이 4건뿐이어서 연속 측정(≤7일) 사이 10배 증가(62건)로 확장. S10 의 VIF·MI·Boruta 는 T3-c 에서 수행.

## 2. 검증 설계

```
지점별 자료 시작 (T0-b 데이터 카드 기준): 회남 2012-04 / 해평·강정고령·칠서 2016-01 / 물금·매리 2020-05
연도:   2012 … 2015 | 2016 … 2019 | 2020 | 2021 | 2022 | 2023 | 2024 || 2025 || 2026(5~10월)
        회남만        5지점(물금 제외)  물금 합류
        ───────────── 학습(CV) ─────────────────────────────── || 검증 || 평가
Fold1  train ≤2019 → valid 2020   (물금·매리는 valid 에만 등장, train 표본 0)
Fold2  train ≤2020 → valid 2021
Fold3  train ≤2021 → valid 2022
Fold4  train ≤2022 → valid 2023
Fold5  train ≤2023 → valid 2024
Final  train ≤2024 → holdout 2025 (모든 지표 보고)
Submit train ≤2025 → predict 2026 (sample_submission, 5~10월 124조합)
```
- 폴드는 위 5개로 고정(2026-10-20 확정, 실제 데이터 기준). 조류 시즌(4~11월) 샘플만 학습할지 전체 사용할지는 CV로 결정하고 보고.
- **물금·매리(2022G05)는 표본 부족 지점**(2020-05 시작, train 250 / valid 48 / test 27 조합): 지점별 분해 표(tbl_by_site)와 CV 폴드 표에 '표본 부족' 표기를 붙이고, Fold1 의 물금 valid 성능은 학습 표본이 없는 지점이므로 별도 행으로 분리 보고한다.
- 샘플 단위 = (site, base_date). 동일 base_date의 지점들은 같은 폴드.
- 랜덤 분할 절대 금지.

## 3. 베이스라인
| 이름 | 정의 |
|---|---|
| B0 지속성 | pred = 기준일 최근 측정값 |
| B1 계절 평균 | pred = 지점×월 학습기간 중앙값(log) |
| B2 선형 추세 | 최근 3회 기울기 외삽 (상한·하한 클리핑) |
| B3 NIER 공식 예측 | 물환경정보시스템 조류예측정보/AI 정밀예측 (가용 기간만) |
| B4 ElasticNet | 전체 피처 선형 모델 |

## 4. 모델

### 4.1 주력: LightGBM (log 타깃, regression_l2 또는 huber)
- `site_code`, `dominant_genus`, `basin`, `facility_type` → categorical
- 샘플 가중치: 최근 연도 가중(연도 차이당 0.9 감쇠) 실험
- 타깃: log10(y+1). 예측 후 10^ŷ − 1, 음수 0 클리핑

### 4.2 분위 회귀: LightGBM objective=quantile, alpha ∈ {0.1, 0.5, 0.9}
- 중앙값 모델 최적 파라미터 고정, alpha만 변경
- 경계 초과 확률 p(y≥10,000): 분위 예측 3점으로 로그정규 근사 또는 분류기(binary LightGBM, 동일 피처) 병행 → 둘 비교 후 보고

### 4.3 CatBoost (depth, lr, l2_leaf_reg, iterations early-stop)
### 4.4 ElasticNet (StandardScaler, alpha, l1_ratio)
### 4.5 앙상블
- 검증 폴드 OOF 예측에 NNLS(합=1) 가중 → 최종. 단일 모델이 더 좋으면 단일 채택(보고에 명시).
**T4-c 결과 메모 (2026-10-21, EXP-002)**: 경보(≥10k) 분류는 2025 F1 에서 어떤 방식도 지속성(0.727)을 넘지 못했고(분류기 0.724, q90 규칙 0.727 동률, 스태킹 0.703) PR-AUC(0.58→0.78)·Brier(0.105→0.082)만 개선. 운영 정의 타깃(+4~+10일 창)에서는 q90 규칙 0.758 > 지속성 0.745. CV OOF F1 기준 채택 규칙은 분류기+회귀 스태킹. NNLS 앙상블(C1·C3·C2) 은 CV rmse_log 0.805(<0.818)·2025 r2_raw 0.166(>0.109) 로 채택 → registry regression. 분위 PICP80 0.66 으로 과소 커버(T5 에서 보정 검토).

### 4.6 hurdle 변형 (T2 반영, 2026-10-21; T4 후보)
- 타깃 0값이 25.3%(T2 S1)이므로 **출현 여부 분류기(세포수>0, LightGBM binary) × 양수 조건부 회귀(log 타깃, 양수 표본만)** 의 hurdle 구조를 후보에 추가. 점추정 = P(>0)·E[y|y>0] 또는 P(>0)≥0.5 일 때 조건부 예측. 분위 예측은 혼합분포로 산출. 단일 log 회귀와 log-RMSE·F1@1,000 비교 후 채택.

### 4.7 조건부: LSTM / Temporal Fusion Transformer
- 학습 샘플 < 3,000이면 생략. 시도 시 `reports/experiments/EXP-LSTM.md`에 비교만 기록.

## 5. 하이퍼파라미터 튜닝 (Optuna)

### 5.1 공통
- Sampler: TPESampler(seed=42, multivariate=True) / Pruner: MedianPruner(n_startup_trials=20)
- 목적함수: CV 폴드 평균 log-RMSE (폴드 표준편차는 로그만)
- 저장: `optuna.db` (sqlite) + `reports/experiments/tune_<model>.md` (상위 10 trial 표, 파라미터 중요도 그림)
- 상위 5 trial을 시드 {0, 1, 2}로 재학습 → 평균·표준편차 → 분산 큰 조합 제외

### 5.2 LightGBM 탐색 공간
| 파라미터 | 공간 |
|---|---|
| num_leaves | int 8~64 |
| max_depth | int 3~10 |
| learning_rate | float log 0.01~0.1 |
| n_estimators | 2000 + early_stopping(50) |
| min_child_samples | int 10~100 |
| feature_fraction | 0.5~1.0 |
| bagging_fraction / bagging_freq | 0.5~1.0 / 1~5 |
| lambda_l1, lambda_l2 | float log 1e-3~10 |
| min_split_gain | 0~1 |
| objective | {l2, huber(alpha 0.9~1.5)} |
- trial 300, 시간 상한 2시간

### 5.3 CatBoost
depth 4~8, learning_rate log 0.01~0.1, l2_leaf_reg 1~10, bagging_temperature 0~1, random_strength 0~2 — trial 150

### 5.4 ElasticNet
alpha log 1e-4~10, l1_ratio 0~1 — trial 50

## 6. 평가 프로토콜

### 6.1 지표 (`src/algaecast/eval/metrics.py`)
| 지표 | 공간 | 식/정의 |
|---|---|---|
| RMSE_log, MAE_log | log10 | 대회 1차 |
| R2_raw | 원단위 | sklearn r2_score = 1 − Σ(o−p)²/Σ(o−ō)² (NSE 와 수식 동일; 편향·척도 오차 벌점) |
| R2_pearson_raw | 원단위 | Pearson 상관계수 제곱 (편향·척도 무시한 설명력) |
| NSE_raw | 원단위 | 1 − Σ(o−p)²/Σ(o−ō)² (학습 평균이 아닌 검증 관측 평균) |
| R2_log, KGE_log | log | 보완 |
| F1, Precision, Recall @10k | 분류 | obs≥10,000 vs pred≥10,000 |
| F1 @1k | 분류 | 관심 단계 |
| PICP_80, MPIW_80 | 구간 | 0.1~0.9 분위 |
| Brier | 확률 | 경계 초과 확률 |

**구현 메모 (T0-c, `src/algaecast/eval/metrics.py`)**: 분류 임계값은 '이상'(≥, 경보 기준과 동일; README 의 '초과' 표기와 다르나 정확히 10,000 인 값은 데이터에 없음). PICP/MPIW 는 교차 구간(q90<q10)을 정렬해 계산하고 `n_crossed_q` 로 건수를 보고(T4-c 분위 모델은 저장 전 정렬 권장). MPIW 기본 공간은 log10(x+1). KGE 는 log 공간·ddof=0. 관측 분산 0 이면 R²·NSE·KGE 는 NaN. 부트스트랩은 백분위법(percentile), 시드 42, (site, base_date) 행 단위가 기본이며 `groups` 로 군집 재표본 가능.

**R² 정의 (T4-b, 2026-10-21)**: 대회 요강은 R² 의 정의(결정계수 vs 상관계수 제곱)를 명시하지 않으므로 **r2_raw(sklearn 결정계수)·r2_pearson_raw(상관계수 제곱)·nse_raw 세 가지를 모든 표에 병기**한다. 원단위 결정계수는 극단값 1~2건에 지배되므로 log 역변환 편향 보정(단순/Duan smearing/isotonic)과 함께 보고하고, 방법 설명서에는 '어느 정의로도' 목표 달성 여부를 기술한다.

**T4-b 결과 메모 (2026-10-21, reports/experiments/EXP-001.md)**: 4개 변형·3개 보정·2개 목적함수 모두 2025 원단위 결정계수 0.11~0.19, 상관² 0.16~0.21, 로그 R² 0.76~0.79. 2025 최대 관측(회남 8/18 194,194 cells/mL, 2025 분산의 43%)을 제외해도 결정계수 ≤0.14 로 **원단위 R² 0.6 / NSE 0.5 목표는 현 자료·피처로 달성 불가**임을 방법 설명서에 명시하고, 목표 지표는 log-RMSE·log R²·경보 F1 로 보고한다. isotonic 역변환은 모든 변형에서 악화(미채택). 채택은 CV 복합점수 기준 C1(log+가중, 복합 목적)+Duan smearing.

### 6.2 보고 표 (모두 `reports/eval/`)
1. `tbl_baseline.md` — B0~B4
2. `tbl_models_cv.md` — 모델별 CV 폴드 평균±표준편차
3. `tbl_holdout_2025.md` — 모든 지표 + 부트스트랩 95% CI (1,000회, (site, base_date) 리샘플)
4. `tbl_by_site.md`, `tbl_by_month.md` — 분해
5. `tbl_missing_strategy.md` — S1/S2/S3 × 모델
6. `tbl_ablation.md` — 피처 그룹(AR/수온수질/수문/기상/예보/시간) 제거 시 변화
7. `tbl_stat_tests.md` — Diebold-Mariano(vs B0, B3), Wilcoxon(모델 간), p값
8. `tbl_benchmark_nier.md` — **경보 단계 분류 비교** (6.4절): 물모아 AI 녹조 예측(단계) vs 우리 모델(단계로 변환) vs 실측 단계, 동일 (지점, base_date, target_date) 조합만
9. `fig_residuals.png` — 잔차 vs 예측, Q-Q, Ljung-Box 결과
10. `fig_shap_global.png`, `fig_shap_cases.png` — 전역 + 경계 초과 사례 5건 waterfall
11. `fig_pred_vs_obs_<site>.png` — 시계열 겹쳐 그리기(관측, 예측, 80% 밴드, 경보선)

### 6.3 해석 규칙 (방법 설명서에 그대로)
- 원단위 R²·NSE는 대발생 사건 몇 건에 민감 → log 지표와 병기, 대발생 제외 시 값도 각주
- **T5 결과 서술(2026-10-21, 수치 채움)**: 2025 전체 F1@10k 은 지속성과 동률(앙상블 0.682, 분류기(a) 0.724, q90 규칙 0.727 = B0 0.727). 그러나 **상태 전환 구간**(tbl_transitions.md)에서 지속성은 정의상 진입(onset, 2025 n=12) Recall 0·이탈 헛경보율 1 인 반면 분류기(a) 진입 Recall 0.33, q90 규칙 0.67; **확률 품질**은 PR-AUC 0.58→0.78, Brier 0.105→0.082 로 개선; **리드타임**(tbl_leadtime.md, 2020~25 경계 발령 20건): q90 규칙 선행 탐지 18/20·중앙 14일(헛경보 116), 분류기(a) 7/20·7일(65), 스태킹 6/20·9일(33), 지속성 1/20. 운영점은 r=3 기준 분류기(b) 임계 0.52(tbl_operating_points.md). CQR 보정 후 2025 PICP80 0.86(목표 0.78~0.82 초과, 과대 커버; tbl_cqr.md). DM 검정: 앙상블 vs B0 p<0.001, vs B4 p=0.08(tbl_stat_tests.md). 수문 그룹 ablation: 제거 시 CV rmse_log 0.819→0.835 악화하나 진입 Recall 은 0.21→0.33 상승(tbl_ablation.md) → 융합의 가치는 회귀 정확도·리드타임으로 서술.
- **한계(2026 사후 검증, 2026-10-21)**: 동결 모델의 2026 test 124 조합 성능은 log R² 0.49(2025 0.78), PICP80 0.69(2025 0.86), F1@10k 0.705 로 지속성(0.841)보다 낮다. 강정·고령 2026-05-18 이례 조기 관심 발령은 감시(1k) 가 첫 초과일 당일(5/11 base) 에 켜져 리드 0일로 사전 포착에 실패했다. 원인: 2026 분포 변화(이례적 조기 발령·급증, 학습 구간에 없는 패턴). 개선 방향: 제출 후 2026 포함 재학습(운영 v2), 조기 시즌(4~6월) 샘플 가중치·조기 발령 피처. 리드타임(2026 경계 사건 8건 중 7건, 중앙 21일)은 유지됐다. 방법설명서 10장(한계·향후)에 동일 내용 기록.
- **원단위 지표 서술 원칙(T4-b)**: 원단위 R²·NSE 는 표 첫 줄에 그대로 보고하고 민감도 표(2025 봉우리 1건 = 분산 43%)를 병기한다. 서술: "6개 변형 × 3개 보정 실험에서 어떤 조합도 원단위 R² 0.2 를 넘지 못함 → 주간 샘플링 자료의 7일 예측에서 원단위 R² 는 봉우리 높이 재현을 측정하며, 운영 목적(발령 선행 판단)에는 로그 R² 0.78 과 경보 F1 이 부합한다." (T4-b 승인 문구, 2026-10-21)
- CI가 목표치를 걸치면 "목표 달성"이 아니라 "목표 수준과 통계적으로 구분되지 않음"으로 서술
- 벤치마크 비교는 동일 (site, base_date, target_date)만, 표본 수 명시. 물모아 발표는 `issued_date ≤ base_date` 인 가장 최근 발표분만 사용(발표 이후 정보 금지)
- 벤치마크는 회귀 지표가 아니라 **단계 분류 지표**로 비교한다(6.4절). 물모아가 단계만 제공하기 때문이며, 세포수·확률·예측구간은 우리 모델만 제공하는 추가 정보로 별도 기술한다

### 6.4 NIER/물모아 벤치마크 비교 설계 — 경보 단계 분류 (2026-10-20 변경)

**변경 이유**: 대회가 명시한 벤치마크(국립환경과학원 'AI 녹조 정밀 예측 정보')는 물모아 플랫폼에서 **D+1~D+7 단계(0~4)** 만 공개하고
세포수 수치 예측을 제공하지 않는다(`docs/reference/mulmoa_api_notes.md`). 따라서 원래 계획(동일 조합에서 log-RMSE 등 회귀 비교)은
성립하지 않으므로, 비교 단위를 유지한 채 지표를 단계 분류로 바꾼다. 또한 서버가 지점당 최근 3회 발표분만 보관해 2026-10-20 이전
발표는 확보할 수 없으므로, 비교 표본은 2026-10 스냅샷 이후 (+ `reports/eval/live_benchmark.csv` 누적분)으로 한정하고 n 을 명시한다.

| 항목 | 정의 |
|---|---|
| 비교 단위 | (지점, base_date, target_date). 물모아 측은 `issued_date ≤ base_date` 인 최신 발표의 `forecast_date == target_date` 단계 (`collect/nier_forecast.benchmark_table`) |
| 단계 코드 | 물모아 범례(상수원): 0단계 <1,000 / 1단계 1,000~10,000 / 2단계 10,000~100,000 / 3단계 100,000~1,000,000 / 4단계 ≥1,000,000 cells/mL (`nier_forecast.LEVEL_BOUNDS`) |
| 실측 단계 | target_date 실측 세포수를 같은 범례로 변환 (`level_from_cells`) |
| 우리 모델 단계 (a) 단순 임계 | 예측 세포수(점추정 또는 q50)를 같은 범례로 변환 → `pred_level_simple`. 경보 명칭은 상수원 기준(관심 ≥1,000 / 경계 ≥10,000 / 대발생 ≥1,000,000)으로 병기 |
| 우리 모델 단계 (b) 2회 연속 규칙 | 조류경보제 운영 규칙(발령·해제 모두 2회 연속 측정)을 적용한 `pred_level_2consec`: base_date 까지의 실측 시퀀스로 현재 발령 상태를 계산한 뒤, target_date 예측 단계가 현재 상태보다 높으면 (base_date 실측, target 예측) 2회 연속 충족 시에만 상향, 낮으면 (base_date 실측, target 예측) 두 값이 모두 현재 상태 미만일 때 둘이 모두 충족하는 단계로 바로 하향(해제 포함, 매뉴얼 1.4.1.4), 그 외 현재 상태 유지. 물모아 발표 단계에는 적용하지 않는다(발표값 그대로) |
| 지표 1 | 단계 정확도 = mean(pred_level == obs_level) — 물모아 / 우리(a) / 우리(b) 각각, horizon(lag_days)별 분해 |
| 지표 2 | 경계 이상(단계 ≥2, 즉 ≥10,000 cells/mL) 이진 Precision / Recall / F1 — 세 비교군 동일 정의 (`eval/metrics.f1_at` 와 일치) |
| 지표 3 | 5×5 혼동행렬(실측 단계 × 예측 단계) — 비교군별 `fig_benchmark_confusion.png` |
| 추가 정보 | 우리 모델만 제공: 세포수 점추정(log-RMSE 등 6.1 지표), 경계 초과 확률 `p_over_10k`(Brier, 신뢰도 곡선), 80% 예측구간(PICP/MPIW). 표 하단에 "물모아 단계 비교에서는 평가 불가한 정보" 로 기술 |
| 표본 | 비교군 공통 조합만(교집합), n·기간·발표일 범위를 표 제목에 명시. 물모아 결측(발표 없음) 조합은 제외하고 건수 보고 |
| 라이브 검증 | `scripts/update_live_benchmark.py` 가 매일 물모아 발표와 조류경보제 실측을 (site_code, issued_date, target_date) 로 매칭해 `reports/eval/live_benchmark.csv` 누적 (컬럼 site_code, issued_date, target_date, mulmoa_level, obs_cells, obs_level, hit). T5 이후 같은 키로 `pred_level`, `p_over_10k` 를 붙인다 |

## 7. 설명가능성·의사결정 변환
- **2단계 경보 운영 체계(T5 확정)**: 감시(watch) = CQR 보정 q90 ≥ 10,000 → "모니터링 강화·설비 준비 점검" / 경보(alert) = 분류기(b, +4~+10일 창) p ≥ 0.52(비용비 r=3 운영점) → "녹조제거설비 선제 배치 권고" / 둘 다 아니면 정상(normal).
- **헤드라인(전 문서·대시보드·발표 통일, 2026-10-23 v2.1 갱신)**: "2025년까지 자료로만 만든 모델(v2.1)로 2026년 경계 사건 8건 중 7건을 중앙 21일 앞서 감시 단계로 포착(지속성 2건). 2020~2026 합계 28건 중 24건(86%, 중앙 14일 앞서), 지속성 3건." v2.1 의 2026 결과는 동결 뒤 1회 사후 계산이며 블라인드라 부르지 않는다. 각주: 리드타임은 첫 경계 초과 측정일 기준이며 공식 발령일 기준으로는 2020~25 중앙 21일·2026 중앙 31일. 출처 reports/eval/tbl_leadtime.md(v2.1 OOF), tbl_holdout_2026_posthoc_v21.md. 이전 헤드라인(2026-10-21, "동결 모델이 처음 보는 … 28건 중 25건(89%)")은 v1 봉인 당시 일부 상수(지점별 수온 임계 등)가 2026 자료를 포함해 계산된 사실을 사후 발견해 이력으로만 남긴다(reports/experiments/FIX-v2.1/RESULT.md).
- 수문 그룹 서술: 세포수 회귀 정확도·융합 가치 근거로만 쓰고, 진입(onset) 탐지 근거로는 쓰지 않는다(T5 ablation: 제거 시 진입 Recall 0.21→0.33 상승).
- SHAP TreeExplainer → 전역 중요도, 지점별 요약, 사례 waterfall
- 담당자 문장 생성 규칙: 상위 3개 기여 피처를 그룹명으로 치환 ("수온 상승", "방류량 감소", "누적강우 부족") + 기여 비율(%)
- 설비 배치 우선순위(T6 승인 후 확정): **단계(경보→감시→정상) 안에서 p_alert 내림차순**, 가중치는 곱하지 않는다. 취수 시설용량은 공식 출처가 확인된 지점만 `config/sites.yaml intake_capacity_source` 에 URL 과 함께 기록하고, 대시보드 '취수량 반영' 토글은 5지점 모두 official 일 때만 제공(현재 강정·고령 매곡취수장은 지자체 공식 페이지 미확인 → 토글 미제공)

## 8. 실험 기록 양식 (`reports/experiments/EXP-###.md`)
```
# EXP-012 LightGBM huber + S2 결측
- 날짜 / 커밋 / 데이터 버전(features_S2 sha)
- 변경점
- CV: RMSE_log 0.512±0.031 / R2_raw 0.58 / F1@10k 0.66
- 결론 / 다음 실험
```
