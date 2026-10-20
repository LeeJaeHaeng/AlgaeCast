# 피처 카탈로그 (T3-b, 전략 S1 기준)

- 샘플 2,979 (train 2310, valid 256, test 124, 타깃 없음/제외 289), 피처 101개
- 정의는 docs/03 4절 + config/features.yaml. 타깃 Spearman 은 train(≤2024) 의 log10(세포수+1) 기준.

## 연도 × 지점 샘플 수 (train/valid/test)
| 연도 | CS | DCHN | GJGR | HP | MGMR |
|---|---|---|---|---|---|
| 2012 | 0 | 44 | 0 | 0 | 0 |
| 2013 | 0 | 48 | 0 | 0 | 0 |
| 2014 | 0 | 50 | 0 | 0 | 0 |
| 2015 | 0 | 52 | 0 | 0 | 0 |
| 2016 | 55 | 52 | 49 | 49 | 0 |
| 2017 | 61 | 56 | 55 | 49 | 0 |
| 2018 | 55 | 50 | 49 | 44 | 0 |
| 2019 | 61 | 53 | 51 | 49 | 0 |
| 2020 | 51 | 51 | 49 | 47 | 31 |
| 2021 | 50 | 51 | 48 | 46 | 52 |
| 2022 | 59 | 52 | 52 | 48 | 60 |
| 2023 | 53 | 51 | 48 | 47 | 49 |
| 2024 | 58 | 58 | 57 | 52 | 58 |
| 2025 | 51 | 57 | 55 | 45 | 48 |
| 2026 | 25 | 25 | 27 | 20 | 27 |

## 타깃 상관 상위 15
| 피처 | 그룹 | 결측률 % | 타깃 Spearman | 비고 |
|---|---|---|---|---|
| cell_log_t0 | ar | 0.0 | 0.836 |  |
| cell_max_4w | ar | 1.0 | 0.793 |  |
| cell_mean_4w | ar | 1.0 | 0.785 |  |
| cell_log_lag1w | ar | 0.2 | 0.764 |  |
| wtemp_ma14 | water | 8.4 | 0.735 |  |
| wtemp_ma7 | water | 8.4 | 0.735 |  |
| wtemp_minus_site_thresh | water | 8.4 | 0.731 |  |
| wtemp_t0 | water | 8.4 | 0.726 |  |
| wtemp_ma30 | water | 8.4 | 0.725 |  |
| cell_log_lag2w | ar | 0.3 | 0.698 |  |
| wtemp_degree_days20 | water | 8.4 | 0.694 |  |
| ta_degree_days20 | weather | 0.0 | 0.692 |  |
| ta_mean_ma14 | weather | 0.0 | 0.687 |  |
| consecutive_over_1k | ar | 0.0 | 0.674 |  |
| ta_min_ma7 | weather | 0.0 | 0.667 |  |

## 전체
| 피처 | 그룹 | 결측률 % | 타깃 Spearman | 비고 |
|---|---|---|---|---|
| cell_log_t0 | ar | 0.0 | 0.836 |  |
| cell_log_lag1w | ar | 0.2 | 0.764 |  |
| cell_log_lag2w | ar | 0.3 | 0.698 |  |
| cell_log_lag3w | ar | 0.8 | 0.616 |  |
| cell_slope_3 | ar | 0.3 | 0.162 |  |
| cell_max_4w | ar | 1.0 | 0.793 |  |
| cell_mean_4w | ar | 1.0 | 0.785 |  |
| cell_n_obs_4w | ar | 0.0 | 0.379 |  |
| days_since_obs | ar | 0.0 |  |  |
| dominant_genus | ar | 0.0 |  | 범주 |
| alert_level_t0 | ar | 0.0 | 0.629 |  |
| consecutive_over_1k | ar | 0.0 | 0.674 |  |
| chla_t0 | ar | 8.4 | 0.27 |  |
| chla_lag1w | ar | 8.6 | 0.245 |  |
| cells_missing_t0 | ar | 0.0 | -0.103 |  |
| wtemp_t0 | water | 8.4 | 0.726 |  |
| ph_t0 | water | 8.4 | 0.178 |  |
| do_t0 | water | 8.4 | -0.496 |  |
| turb_t0 | water | 8.4 | 0.397 |  |
| transp_t0 | water | 8.4 | -0.284 |  |
| wtemp_ma7 | water | 8.4 | 0.735 |  |
| wtemp_ma14 | water | 8.4 | 0.735 |  |
| wtemp_ma30 | water | 8.4 | 0.725 |  |
| wtemp_diff7 | water | 8.6 | -0.063 |  |
| wtemp_days_over25 | water | 8.4 | 0.556 |  |
| wtemp_degree_days20 | water | 8.4 | 0.694 |  |
| wtemp_over_site_thresh_days | water | 8.4 | 0.651 |  |
| wtemp_minus_site_thresh | water | 8.4 | 0.731 |  |
| wtemp_missing_days30 | water | 0.0 | -0.098 |  |
| weir_inflow_t0 | hydro | 0.0 | 0.387 |  |
| weir_outflow_t0 | hydro | 0.0 | 0.377 |  |
| weir_level_t0 | hydro | 0.0 | -0.215 |  |
| weir_storage_t0 | hydro | 0.0 | -0.04 |  |
| weir_storage_rate_t0 | hydro | 0.0 | 0.004 |  |
| weir_outflow_sum7 | hydro | 0.0 | 0.413 |  |
| weir_outflow_sum14 | hydro | 0.0 | 0.437 |  |
| weir_flow_ma7 | hydro | 0.0 | 0.418 |  |
| weir_outflow_ma7 | hydro | 0.0 | 0.413 |  |
| weir_level_diff7 | hydro | 0.0 | 0.072 |  |
| weir_outflow_change7 | hydro | 0.0 | -0.06 |  |
| weir_residence_proxy | hydro | 0.0 | -0.308 |  |
| weir_residence_proxy_ma14 | hydro | 0.0 | -0.316 |  |
| dam_release_event_7d | hydro | 0.0 | 0.29 |  |
| weir_rain_sum7 | hydro | 0.0 | 0.242 |  |
| inflow_t0 | hydro | 0.0 | 0.243 |  |
| outflow_t0 | hydro | 0.0 | 0.362 |  |
| inflow_sum7 | hydro | 0.0 | 0.275 |  |
| outflow_sum7 | hydro | 0.0 | 0.377 |  |
| inflow_sum14 | hydro | 0.0 | 0.315 |  |
| outflow_sum14 | hydro | 0.0 | 0.392 |  |
| inflow_sum30 | hydro | 0.0 | 0.398 |  |
| outflow_sum30 | hydro | 0.0 | 0.414 |  |
| upstream_dam_release_sum7 | hydro | 0.0 | 0.377 |  |
| storage_t0 | hydro | 0.0 | 0.154 |  |
| storage_rate_t0 | hydro | 0.0 | 0.003 |  |
| residence_proxy | hydro | 0.0 | -0.343 |  |
| residence_proxy_ma14 | hydro | 0.0 | -0.344 |  |
| outflow_change7 | hydro | 0.0 | -0.041 |  |
| level_cont_t0 | hydro | 0.0 | -0.032 |  |
| level_cont_diff7 | hydro | 0.0 | -0.032 |  |
| weir_inflow_missing7 | hydro | 0.0 |  |  |
| weir_outflow_missing7 | hydro | 0.0 |  |  |
| inflow_missing7 | hydro | 0.0 |  |  |
| hydro_fac_available | hydro | 0.0 |  |  |
| ta_mean_t0 | weather | 0.0 | 0.644 |  |
| ta_mean_ma7 | weather | 0.0 | 0.666 |  |
| ta_mean_ma14 | weather | 0.0 | 0.687 |  |
| ta_max_ma7 | weather | 0.0 | 0.663 |  |
| ta_min_ma7 | weather | 0.0 | 0.667 |  |
| ta_degree_days20 | weather | 0.0 | 0.692 |  |
| rn_sum7 | weather | 0.0 | 0.183 |  |
| rn_sum14 | weather | 0.0 | 0.282 |  |
| rn_sum30 | weather | 0.0 | 0.457 |  |
| dry_days | weather | 0.0 | -0.213 |  |
| ss_sum7 | weather | 0.0 | -0.047 |  |
| si_sum7 | weather | 0.0 | 0.254 |  |
| ws_mean7 | weather | 0.0 | -0.049 |  |
| ws_max7 | weather | 0.0 | -0.142 |  |
| hm_mean7 | weather | 0.0 | 0.437 |  |
| rn_missing7 | weather | 0.0 | 0.018 |  |
| si_missing7 | weather | 0.0 | -0.044 |  |
| fc_ta_mean_d1_7 | forecast | 100.0 |  |  |
| fc_ta_max_d1_7 | forecast | 100.0 |  |  |
| fc_rn_sum_d1_7 | forecast | 100.0 |  |  |
| fc_pop_mean_d1_7 | forecast | 100.0 |  |  |
| fc_rain_days | forecast | 100.0 |  |  |
| fc_available | forecast | 0.0 |  |  |
| month_sin | time_site | 0.0 | -0.571 |  |
| month_cos | time_site | 0.0 | -0.394 |  |
| doy_sin | time_site | 0.0 | -0.515 |  |
| doy_cos | time_site | 0.0 | -0.488 |  |
| season_day | time_site | 0.0 | 0.39 |  |
| year | time_site | 0.0 | 0.093 |  |
| basin | time_site | 0.0 |  | 범주 |
| facility_type | time_site | 0.0 |  | 범주 |
| intake_capacity_tpd | time_site | 0.0 | -0.097 |  |
| intake_weight | time_site | 0.0 | 0.059 |  |
| catchment_area_km2 | time_site | 0.0 | 0.22 |  |
| total_storage_mcm | time_site | 12.6 | 0.01 |  |
| n_upstream_main_dams | time_site | 0.0 | 0.22 |  |
| horizon_days | time_site | 0.9 | -0.033 |  |
