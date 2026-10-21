# as-of 피처 재현 검증 — 대회 번들 없이 공공 API 수집 창(올해 1/1 또는 ≥400일)만으로 재계산

- 비교 대상: 번들 기반 features_S1 의 최근 12개 base_date × 5지점 × 피처 30개 = 1,050 값
- **일치율(허용오차 |상대차| ≤ 1% 또는 |차| ≤ 1e-6): 95.9%**, 완전 일치(≤1e-9) 83.2%
- 불일치의 주원인: 연속 수위(level_cont_*) — WAMIS 비본댐 관측소 수집 실패분(본댐은 delist 대체). 창 확대(≥400일)로 consecutive_over_1k 는 100% 일치.

| 피처 | n | 일치율 | 최대 상대차 |
|---|---|---|---|
| horizon_days | 35 | 22.9% | 0 |
| level_cont_diff7 | 35 | 80.0% | 0.17 |
| level_cont_t0 | 35 | 80.0% | 0.498 |
| inflow_t0 | 35 | 94.3% | 0.162 |
| basin | 35 | 100.0% |  |
| cell_log_lag1w | 35 | 100.0% | 0 |
| cell_log_lag3w | 35 | 100.0% | 0 |
| cell_log_t0 | 35 | 100.0% | 0 |
| consecutive_over_1k | 35 | 100.0% | 0 |
| chla_lag1w | 35 | 100.0% | 0 |
| cell_slope_3 | 35 | 100.0% | 0 |
| cell_max_4w | 35 | 100.0% | 0 |
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
