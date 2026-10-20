# 03. 주기 정렬·결측 처리·피처 정의서

## 1. 누수 방지 규칙 (최우선)
모든 피처 함수는 다음 시그니처를 따른다.
```python
def make_<group>_features(df_daily: pd.DataFrame, as_of: date, site_code: str) -> dict[str, float]:
    """as_of(base_date) 이전(포함) 행만 사용. as_of 이후 행은 함수 진입 직후 drop."""
```
- 진입 직후 `df = df[df.obs_date <= as_of]` 강제. 이 한 줄이 없는 함수는 PR 리젝.
- 예보 피처만 예외: `issued_at <= as_of`인 **발표분**의 미래 예보값은 허용 (관측값 아님).
- `tests/test_no_leakage.py`: 각 피처 함수에 대해 as_of 이후 값을 임의로 뒤집어도 출력이 동일한지 검사.
- 학습 샘플 생성: `(site, base_date)`마다 피처 벡터 + 타깃(`target_date` 측정값, log10(x+1)).

## 2. 이종 주기 정렬

### 2.1 기준 격자
- 일 단위 달력(지점별, 2015-01-01~2026-10-31)을 기준 테이블로 둔다.
- 수문·기상은 일 단위라 그대로 조인.
- 수질·조류(주 1~2회)는 측정일에만 값 존재. 기준일 피처는 "기준일 포함 최근 측정값"과 "측정 경과일(days_since_obs)"을 함께 쓴다.

### 2.2 정렬 방법 비교 (보고서 표)
| 방법 | 설명 | 장단 |
|---|---|---|
| Last observation (LOCF) | 최근 측정값 유지 | 단순, 보수적. 기본값 |
| 선형보간 (과거 두 점만) | 과거 2점 기울기 외삽 금지, 2점 사이만 보간 | 누수 없음, 추세 반영 |
| 모델기반 | 수온·Chl-a로 세포수 KNN 추정 | 결측 구간 보완, 복잡 |

### 2.3 타깃 매칭
- `target_date` = base_date+7에 가장 가까운 측정일, |차이| ≤ 3일. sample_submission 지정값 사용.
- 학습 샘플도 동일 규칙으로 생성 (horizon_days = target_date − base_date, 4~10). horizon을 피처로 추가.

## 3. 결측 처리 (대회 평가 항목)

### 3.1 결측 유형 진단 (T2에서 수행)
- 변수별·지점별·월별 결측률 히트맵
- "유량 증가 시 미채수" 가설 검정: 결측 여부 ~ 당일 유입량·강수 로지스틱 회귀 (MNAR 증거)
- 결측 길이 분포 (연속 결측 주 수)

### 3.2 전략 3종 (모두 구현, 성능 비교)
| 전략 | 세포수 등 수질 | 수문·기상 |
|---|---|---|
| S1 전진채움 | LOCF + days_since_obs | 선형보간(≤3일), 그 이상은 월 중앙값 |
| S2 보간 | 과거 2점 선형보간, 결측 플래그 | 동일 |
| S3 모델기반 | IterativeImputer(BayesianRidge) 또는 KNN(k=5), 과거 창만 | 동일 |
- 결측 지시 변수(`<var>_missing`)는 모든 전략에서 유지 → 결측 자체가 정보(고유량).
- 성능표: 전략 × 모델 → log-RMSE, R²; 최종 선택 근거 기록.

## 4. 피처 정의서

### 4.1 자기회귀 (AR)
| 피처명 | 정의 | 창 |
|---|---|---|
| cell_log_t0 | log10(최근 측정 세포수+1) | 기준일 포함 최근 |
| cell_log_lag1w / lag2w / lag3w | 1·2·3회 이전 측정값(log) | |
| cell_slope_3 | 최근 3회 측정의 선형 기울기(log/일) | |
| cell_max_4w / cell_mean_4w | 최근 28일 최대·평균(log) | 28일 |
| days_since_obs | 기준일 − 최근 측정일 | |
| dominant_genus | 최근 우점종(범주: Microcystis/Dolichospermum/Oscillatoria/Aphanizomenon/기타) | |
| alert_level_t0 | 기준일 경보단계(0~3) | |
| consecutive_over_1k | 1,000 연속 초과 횟수 | |
| chla_t0, chla_lag1w | 클로로필-a | |

### 4.2 수온·수질
| 피처명 | 정의 |
|---|---|
| wtemp_t0 | 최근 측정 수온 |
| wtemp_ma7 / ma14 / ma30 | 수온 이동평균 (일 단위 수질자동측정망 있으면 그것, 없으면 측정값 보간) |
| wtemp_diff7 | 7일 전 대비 변화 |
| wtemp_days_over25 | 최근 30일 중 25℃ 초과 일수 |
| wtemp_degree_days20 | Σmax(수온−20,0) 최근 30일 (성장 적산온도) |
| ph_t0, do_t0, turb_t0, transp_t0 | pH, DO, 탁도, 투명도 |
| tp_t0, tn_t0, np_ratio | 총인, 총질소, TN/TP |
| tp_ma30 | 총인 30일 평균 |

### 4.3 수문
| 피처명 | 정의 |
|---|---|
| inflow_t0, outflow_t0 | 당일 유입·방류량 |
| inflow_sum7 / 14 / 30 | 누적 유입 |
| outflow_sum7 / 14 / 30 | 누적 방류 |
| storage_t0, storage_rate_t0 | 저수량, 저수율 |
| residence_proxy | 저수량 / (방류량 7일 평균) [일] — 체류시간 대리 |
| residence_proxy_ma14 | 14일 평균 |
| outflow_change7 | 방류량 7일 변화율 |
| weir_level_t0, weir_level_diff7 | 보 상류 수위, 7일 변화 (WAMIS) |
| dam_release_event_7d | 최근 7일 수문 방류 이벤트 횟수 |
| upstream_dam_release_sum7 | 상류 다목적댐 방류 합 (sites.yaml 매핑) |

### 4.4 기상 (관측)
| 피처명 | 정의 |
|---|---|
| ta_mean_ma7 / ma14, ta_max_ma7 | 기온 이동평균 |
| rn_sum7 / 14 / 30 | 누적강수 (ASOS) |
| rn_basin_sum7 / 14 | 유역 면적강수 (MT-02/03, AI-02) |
| dry_days | 마지막 5mm 이상 강우 이후 경과일 |
| ss_sum7, si_sum7 | 일조·일사 7일 합 |
| ws_mean7, ws_max7 | 풍속 7일 평균·최대 (혼합) |
| hm_mean7 | 습도 |
| soil_moisture_t0, et_sum7 | 토양수분, 증발산 (MT-02) |

### 4.5 예보 (base_date 발표분, 창의성)
| 피처명 | 정의 |
|---|---|
| fc_ta_mean_d1_7 | 기준일 발표 단기+중기 예보의 +1~+7일 평균기온 |
| fc_ta_max_d1_7 | 최고기온 평균 |
| fc_rn_sum_d1_7 | 예보 강수량 합 (단기) / 강수확률 평균 (중기) |
| fc_rain_days | 강수확률 ≥60% 일수 |
| maple_rn_6h | MAPLE 기준일 초단기 누적강수 (AI-03) |
- 과거 발표분이 없는 기간은 결측 처리 + 플래그. 학습 시 해당 피처 기여도를 ablation으로 보고.

### 4.6 시간·지점
| 피처명 | 정의 |
|---|---|
| month_sin, month_cos | 월 주기 |
| doy_sin, doy_cos | 연중일 주기 |
| season_day | 5/1 기준 경과일 (조류 시즌) |
| horizon_days | target_date − base_date |
| site_code | 범주 (LightGBM categorical / CatBoost cat) |
| basin | 낙동강/금강 |
| facility_type | 보/댐 |
| catchment_area_km2, total_storage_mcm | 정적 제원 |
| intake_capacity_tpd | 취수능력 (물금 84만 톤 등, 정책 가중치용) |

## 5. 피처 선별 절차
1. 상관·VIF: VIF > 10 변수 중 도메인상 덜 중요한 것 제거
2. Boruta (shadow feature, 100 iter) → confirmed + tentative 유지
3. CV 기반 역방향 제거: 제거해도 log-RMSE가 1% 이상 악화되지 않으면 제거
4. 최종 피처 수 ≤ (학습 행 수 / 20)
5. 결과를 `config/features.yaml`에 고정 (피처명 리스트 + 생성 함수 매핑)

## 6. 산출물
- `data/processed/features_S1.parquet`, `_S2`, `_S3` (전략별)
- `data/processed/splits.json` (train/valid/test의 (site, base_date) 목록)
- `reports/features/feature_catalog.md` (피처명, 정의, 결측률, 타깃 Spearman)
- `tests/test_no_leakage.py` 통과 로그
