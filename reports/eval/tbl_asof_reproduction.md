# as-of 피처 재현 검증 — 대회 번들 없이 공공 API 최근 120일만으로 재계산

- 비교 대상: 번들 기반 features_S1 의 최근 12개 base_date × 5지점 × 피처 30개 = 1,050 값
- **일치율(허용오차 |상대차| ≤ 1% 또는 |차| ≤ 1e-6): 94.6%**, 완전 일치(≤1e-9) 81.9%
- 불일치의 주원인: 120일 창 밖 이력이 필요한 피처(consecutive_over_1k 장기 연속, 과거 연도 월 중앙값 채움), 수집 시점 차이(API 갱신·보정), 2consec 단계는 피처 미사용.

| 피처 | n | 일치율 | 최대 상대차 |
|---|---|---|---|
| horizon_days | 35 | 22.9% | 0 |
| consecutive_over_1k | 35 | 60.0% | 0.111 |
| level_cont_diff7 | 35 | 80.0% | 0.17 |
| level_cont_t0 | 35 | 80.0% | 0.498 |
| inflow_t0 | 35 | 94.3% | 0.162 |
| basin | 35 | 100.0% |  |
| cell_log_lag3w | 35 | 100.0% | 0 |
| cell_log_lag1w | 35 | 100.0% | 0 |
| chla_lag1w | 35 | 100.0% | 0 |
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
