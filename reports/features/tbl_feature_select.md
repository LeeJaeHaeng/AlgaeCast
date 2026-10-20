# 피처 선별 (T3-c, 전략 S1, train 2,310행)

- 후보 101 → 예보 제외 95 → VIF 후 58 → Boruta(perc 75) confirmed 18 / tentative 8 / rejected 32 → 최종 **30** (상한 115)
- 보호 피처: ['cell_log_t0', 'wtemp_ma14', 'wtemp_minus_site_thresh', 'weir_outflow_ma7', 'horizon_days']; 범주형 ['dominant_genus', 'basin', 'facility_type'] 은 항상 유지
- 보 피처 그룹 ablation: Δ CV rmse_log(포함 − 제외) = -0.0145 → 유지

## 보 피처 ablation
| 구성 | 피처 수 | CV rmse_log | CV r2_log | CV f1_10k | Final rmse_log |
|---|---|---|---|---|---|
| 보 피처 포함 (4개) | 30 | 0.8281 | 0.6583 | 0.4032 | 0.7314 |
| 보 피처 제외 | 26 | 0.8426 | 0.648 | 0.4609 | 0.747 |

## Boruta 결과
| 피처 | hits | mean_gain | 판정 |
|---|---|---|---|
| cell_log_t0 | 100 | 22443.4 | confirmed |
| cell_log_lag1w | 100 | 1301.8 | confirmed |
| cell_max_4w | 100 | 4413.3 | confirmed |
| wtemp_ma14 | 100 | 884.8 | confirmed |
| wtemp_minus_site_thresh | 100 | 1055.7 | confirmed |
| inflow_t0 | 100 | 283.8 | confirmed |
| ta_degree_days20 | 100 | 987.2 | confirmed |
| rn_sum30 | 100 | 720.8 | confirmed |
| season_day | 100 | 534.8 | confirmed |
| cell_slope_3 | 99 | 258.3 | confirmed |
| weir_outflow_t0 | 99 | 236.2 | confirmed |
| level_cont_diff7 | 96 | 213.4 | confirmed |
| outflow_change7 | 95 | 217.8 | confirmed |
| consecutive_over_1k | 94 | 619.7 | confirmed |
| level_cont_t0 | 89 | 197.9 | confirmed |
| wtemp_diff7 | 87 | 186.5 | confirmed |
| weir_storage_rate_t0 | 82 | 186.5 | confirmed |
| hm_mean7 | 74 | 177.0 | confirmed |
| ss_sum7 | 29 | 149.3 | rejected |
| residence_proxy_ma14 | 27 | 147.1 | rejected |
| alert_level_t0 | 22 | 87.0 | rejected |
| chla_t0 | 18 | 142.3 | rejected |
| do_t0 | 16 | 137.3 | rejected |
| weir_outflow_change7 | 12 | 138.0 | rejected |
| month_cos | 9 | 117.7 | rejected |
| weir_rain_sum7 | 7 | 128.1 | rejected |
| rn_sum14 | 7 | 122.6 | rejected |
| turb_t0 | 3 | 116.8 | rejected |
| weir_level_diff7 | 3 | 128.1 | rejected |
| transp_t0 | 1 | 118.8 | rejected |
| outflow_sum14 | 1 | 98.4 | rejected |
| outflow_sum30 | 1 | 104.8 | rejected |
| cell_n_obs_4w | 0 | 3.1 | rejected |
| cells_missing_t0 | 0 | 3.4 | rejected |
| wtemp_days_over25 | 0 | 31.4 | rejected |
| wtemp_over_site_thresh_days | 0 | 38.8 | rejected |
| wtemp_missing_days30 | 0 | 0.0 | rejected |
| dam_release_event_7d | 0 | 13.0 | rejected |
| rn_sum7 | 0 | 82.9 | rejected |
| dry_days | 0 | 91.0 | rejected |
| ws_max7 | 0 | 79.4 | rejected |
| rn_missing7 | 0 | 0.0 | rejected |
| si_missing7 | 0 | 2.5 | rejected |
| year | 0 | 58.0 | rejected |
| intake_weight | 0 | 6.2 | rejected |
| catchment_area_km2 | 0 | 29.1 | rejected |
| horizon_days | 0 | 16.7 | rejected |
| dominant_genus | 0 | 7.0 | rejected |
| basin | 0 | 0.2 | rejected |
| facility_type | 0 | 2.5 | rejected |
| chla_lag1w | 66 | 175.6 | tentative |
| weir_outflow_ma7 | 58 | 175.6 | tentative |
| storage_rate_t0 | 47 | 162.8 | tentative |
| ph_t0 | 45 | 164.3 | tentative |
| cell_log_lag3w | 44 | 165.2 | tentative |
| outflow_t0 | 40 | 155.8 | tentative |
| weir_residence_proxy | 37 | 151.6 | tentative |
| ws_mean7 | 35 | 151.2 | tentative |

## 제거 목록·사유
| 피처 | 제거 사유 |
|---|---|
| fc_ta_mean_d1_7 | 예보 피처 — 2026-10-21 이후만 가용, 전 샘플 결측 → 선별 제외, 후속 재검토(T8 이후) |
| fc_ta_max_d1_7 | 예보 피처 — 2026-10-21 이후만 가용, 전 샘플 결측 → 선별 제외, 후속 재검토(T8 이후) |
| fc_rn_sum_d1_7 | 예보 피처 — 2026-10-21 이후만 가용, 전 샘플 결측 → 선별 제외, 후속 재검토(T8 이후) |
| fc_pop_mean_d1_7 | 예보 피처 — 2026-10-21 이후만 가용, 전 샘플 결측 → 선별 제외, 후속 재검토(T8 이후) |
| fc_rain_days | 예보 피처 — 2026-10-21 이후만 가용, 전 샘플 결측 → 선별 제외, 후속 재검토(T8 이후) |
| fc_available | 예보 피처 — 2026-10-21 이후만 가용, 전 샘플 결측 → 선별 제외, 후속 재검토(T8 이후) |
| days_since_obs | 상수 |
| weir_inflow_missing7 | 상수 |
| weir_outflow_missing7 | 상수 |
| inflow_missing7 | 상수 |
| hydro_fac_available | 상수 |
| weir_outflow_sum7 | VIF inf > 10 (반복 제거) |
| outflow_sum7 | VIF inf > 10 (반복 제거) |
| intake_capacity_tpd | VIF inf > 10 (반복 제거) |
| n_upstream_main_dams | VIF 9156601.7 > 10 (반복 제거) |
| weir_level_t0 | VIF 3679.8 > 10 (반복 제거) |
| ta_mean_ma7 | VIF 1594.5 > 10 (반복 제거) |
| weir_flow_ma7 | VIF 1399.0 > 10 (반복 제거) |
| wtemp_t0 | VIF 862.3 > 10 (반복 제거) |
| wtemp_ma7 | VIF 397.4 > 10 (반복 제거) |
| wtemp_ma30 | VIF 168.7 > 10 (반복 제거) |
| total_storage_mcm | VIF 138.3 > 10 (반복 제거) |
| ta_min_ma7 | VIF 135.3 > 10 (반복 제거) |
| ta_mean_ma14 | VIF 97.9 > 10 (반복 제거) |
| cell_mean_4w | VIF 82.3 > 10 (반복 제거) |
| doy_cos | VIF 66.7 > 10 (반복 제거) |
| doy_sin | VIF 59.7 > 10 (반복 제거) |
| cell_log_lag2w | VIF 44.7 > 10 (반복 제거) |
| inflow_sum14 | VIF 42.2 > 10 (반복 제거) |
| storage_t0 | VIF 40.8 > 10 (반복 제거) |
| weir_residence_proxy_ma14 | VIF 40.6 > 10 (반복 제거) |
| weir_inflow_t0 | VIF 38.9 > 10 (반복 제거) |
| ta_max_ma7 | VIF 26.5 > 10 (반복 제거) |
| wtemp_degree_days20 | VIF 26.0 > 10 (반복 제거) |
| weir_outflow_sum14 | VIF 23.0 > 10 (반복 제거) |
| residence_proxy | VIF 22.1 > 10 (반복 제거) |
| weir_storage_t0 | VIF 21.0 > 10 (반복 제거) |
| upstream_dam_release_sum7 | VIF 19.7 > 10 (반복 제거) |
| si_sum7 | VIF 15.8 > 10 (반복 제거) |
| inflow_sum7 | VIF 13.7 > 10 (반복 제거) |
| month_sin | VIF 13.0 > 10 (반복 제거) |
| inflow_sum30 | VIF 12.5 > 10 (반복 제거) |
| ta_mean_t0 | VIF 10.7 > 10 (반복 제거) |
| ss_sum7 | Boruta rejected (hits 29/100) |
| residence_proxy_ma14 | Boruta rejected (hits 27/100) |
| alert_level_t0 | Boruta rejected (hits 22/100) |
| chla_t0 | Boruta rejected (hits 18/100) |
| do_t0 | Boruta rejected (hits 16/100) |
| weir_outflow_change7 | Boruta rejected (hits 12/100) |
| month_cos | Boruta rejected (hits 9/100) |
| weir_rain_sum7 | Boruta rejected (hits 7/100) |
| rn_sum14 | Boruta rejected (hits 7/100) |
| turb_t0 | Boruta rejected (hits 3/100) |
| weir_level_diff7 | Boruta rejected (hits 3/100) |
| transp_t0 | Boruta rejected (hits 1/100) |
| outflow_sum14 | Boruta rejected (hits 1/100) |
| outflow_sum30 | Boruta rejected (hits 1/100) |
| cell_n_obs_4w | Boruta rejected (hits 0/100) |
| cells_missing_t0 | Boruta rejected (hits 0/100) |
| wtemp_days_over25 | Boruta rejected (hits 0/100) |
| wtemp_over_site_thresh_days | Boruta rejected (hits 0/100) |
| wtemp_missing_days30 | Boruta rejected (hits 0/100) |
| dam_release_event_7d | Boruta rejected (hits 0/100) |
| rn_sum7 | Boruta rejected (hits 0/100) |
| dry_days | Boruta rejected (hits 0/100) |
| ws_max7 | Boruta rejected (hits 0/100) |
| rn_missing7 | Boruta rejected (hits 0/100) |
| si_missing7 | Boruta rejected (hits 0/100) |
| year | Boruta rejected (hits 0/100) |
| intake_weight | Boruta rejected (hits 0/100) |
| catchment_area_km2 | Boruta rejected (hits 0/100) |

## 최종 피처
cell_log_t0, cell_max_4w, cell_log_lag1w, wtemp_minus_site_thresh, ta_degree_days20, wtemp_ma14, rn_sum30, consecutive_over_1k, season_day, inflow_t0, cell_slope_3, weir_outflow_t0, outflow_change7, level_cont_diff7, level_cont_t0, wtemp_diff7, weir_storage_rate_t0, hm_mean7, weir_outflow_ma7, chla_lag1w, cell_log_lag3w, ph_t0, storage_rate_t0, outflow_t0, weir_residence_proxy, ws_mean7, horizon_days, dominant_genus, facility_type, basin
