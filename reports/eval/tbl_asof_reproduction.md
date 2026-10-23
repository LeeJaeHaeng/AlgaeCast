# as-of 피처 재현 검증 — 대회 번들 없이 공공 API 수집 창(올해 1/1 또는 ≥400일)만으로 재계산

- 계산 일시 2026-10-23 14:59 KST · 기준: 제출·운영 모델 v2.1(동결 커밋 217260e) 피처 — 수위 편차 = 관측소별 직전 365일 평균 대비(as-of), 수온 임계 = ≤2025 측정(config/derived_constants.json) · 번들 쪽 = data/processed/features_S1.parquet(v2.1, 2026-10-23 생성), API 수집 창 2025-09-10 ~ 2026-10-15 · 비교 행 = 지점별 최근 7개 base_date(35행, 서로 다른 날짜 12개) · 원자료 reports/experiments/FIX-v2.1/rerun/asof_reproduction_v21.csv
- 비교 대상: 번들 기반 features_S1 의 최근 12개 base_date × 5지점 × 피처 30개 = 1,050 값
- **일치율(허용오차 |상대차| ≤ 1% 또는 |차| ≤ 1e-6): 96.2%**, 완전 일치(≤1e-9) 86.0%
- 불일치의 주원인(불일치 40건, 피처별로 값을 대조해 확인): ① horizon_days 27건 — 검증 함수가 GROUPS 피처만 계산해 API 쪽 값이 비어 있다(번들 = 대회 목표일 간격 4~10일, 일치 8건은 목표일이 없어 둘 다 결측인 행; 운영 feature_rows 는 7 고정). 자료 차이가 아니다. ② level_cont_diff7 6건·level_cont_t0 2건 — HP·GJGR 의 2026-09-03~09-14 base_date 에서만: 수집 창 시작(2025-09-10 = 2026-10-15 − 400일)이 직전 365일 기준 평균 창보다 늦어 기준 평균이 짧게 잡힌다(t0 는 base < 09-10, diff7 은 base < 09-17 이 해당). 번들 원천(level_continuous_long)을 2025-09-10 부터로 자르면 API 값과 같아지고, 자르지 않으면 번들 값과 같다. 최신 base_date 를 쓰는 일일 운영에는 해당하지 않는다. ③ chla_lag1w 3건 — MGMR·CS·DCHN 2026-10-15: 번들 원자료(2026-10-20 수집)에는 10-15 클로로필-a 가 비어 있었고 오늘 API 에는 값이 있어 '직전 측정'이 10-08 → 10-12 로 바뀐다(수집 시점 차이). ④ inflow_t0 2건 — HP·GJGR 2026-09-07: 상류 본댐 중 영주댐(2004101) 유입량이 번들 원천(bundle_wamis) 11.458 m³/s, API(K-water delist) 4.909 m³/s 로 다르다(다른 댐·전날은 같음). 두 원천 값이 다른 이유는 확인하지 못함. horizon_days 를 빼면 일치율 98.7%(1,002/1,015).

| 피처 | n | 일치율 | 최대 상대차 |
|---|---|---|---|
| horizon_days | 35 | 22.9% | 0 |
| level_cont_diff7 | 35 | 82.9% | 3.63 |
| chla_lag1w | 35 | 91.4% | 0.331 |
| inflow_t0 | 35 | 94.3% | 0.162 |
| level_cont_t0 | 35 | 94.3% | 0.0142 |
| basin | 35 | 100.0% |  |
| cell_log_lag3w | 35 | 100.0% | 0 |
| cell_log_lag1w | 35 | 100.0% | 0 |
| consecutive_over_1k | 35 | 100.0% | 0 |
| cell_slope_3 | 35 | 100.0% | 0 |
| cell_max_4w | 35 | 100.0% | 0 |
| cell_log_t0 | 35 | 100.0% | 0 |
| hm_mean7 | 35 | 100.0% | 0 |
| facility_type | 35 | 100.0% |  |
| dominant_genus | 35 | 100.0% |  |
| outflow_change7 | 35 | 100.0% | 0 |
| outflow_t0 | 35 | 100.0% | 0 |
| ph_t0 | 35 | 100.0% | 0 |
| rn_sum30 | 35 | 100.0% | 0 |
| season_day | 35 | 100.0% | 0 |
| storage_rate_t0 | 35 | 100.0% | 0 |
| ta_degree_days20 | 35 | 100.0% | 0 |
| weir_outflow_ma7 | 35 | 100.0% | 0 |
| weir_outflow_t0 | 35 | 100.0% | 0 |
| weir_residence_proxy | 35 | 100.0% | 0 |
| weir_storage_rate_t0 | 35 | 100.0% | 0 |
| ws_mean7 | 35 | 100.0% | 0 |
| wtemp_diff7 | 35 | 100.0% | 0 |
| wtemp_ma14 | 35 | 100.0% | 0 |
| wtemp_minus_site_thresh | 35 | 100.0% | 0 |
