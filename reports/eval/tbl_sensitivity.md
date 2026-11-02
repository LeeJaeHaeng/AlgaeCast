# 2025 원단위 지표 민감도 — 최대 관측 1건 제외 / 지점별 최대 1건씩 제외

- 폴드 F1~F5(train ≤2019~2023 → valid 2020~2024) 평균 = cv_*, Final(train ≤2024 → 2025) = final_*. test(2026) 미접근. 지표 정의: docs/04 6.1 (r2_raw=sklearn 결정계수 = NSE(대회 공식 R² 아님), r2_pearson_raw=상관² = 대회 공식 R²(공식 Q&A 2026-10-30 ②)).
- B0 지속성 2025: rmse_log 0.896, r2_raw -0.283, r2_pearson_raw 0.148, nse_raw -0.283, F1@10k 0.727

| study | 변형 | 목적 | bias | max_obs | max_obs_site | pred_at_max | full_r2_raw | full_r2_pearson_raw | full_nse_raw | full_rmse_log | drop1_r2_raw | drop1_r2_pearson_raw | drop1_nse_raw | drop1_rmse_log | drop_site_max_r2_raw | drop_site_max_r2_pearson_raw | drop_site_max_nse_raw | drop_site_max_rmse_log |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ens_rmse_log_perc75_S1 | C4 C1·C2 앙상블 | rmse_log | none | 194194.0 | DCHN | 18460.403 | 0.143 | 0.176 | 0.143 | 0.709 | 0.16 | 0.22 | 0.16 | 0.707 | 0.282 | 0.344 | 0.282 | 0.696 |
| ens_rmse_log_perc75_S1 | C4 C1·C2 앙상블 | rmse_log | smearing | 194194.0 | DCHN | 18460.403 | 0.143 | 0.176 | 0.143 | 0.709 | 0.16 | 0.22 | 0.16 | 0.707 | 0.282 | 0.344 | 0.282 | 0.696 |
| ens_rmse_log_perc75_S1 | C4 C1·C2 앙상블 | rmse_log | isotonic | 194194.0 | DCHN | 58866.412 | -0.259 | 0.237 | -0.259 | 0.878 | -0.827 | 0.276 | -0.827 | 0.88 | -1.403 | 0.44 | -1.403 | 0.88 |
| hurdle_rmse_log_perc75_S1 | C3 hurdle | rmse_log | none | 194194.0 | DCHN | 19750.769 | 0.189 | 0.213 | 0.189 | 0.713 | 0.232 | 0.262 | 0.232 | 0.712 | 0.37 | 0.396 | 0.37 | 0.703 |
| hurdle_rmse_log_perc75_S1 | C3 hurdle | rmse_log | smearing | 194194.0 | DCHN | 19750.769 | 0.189 | 0.213 | 0.189 | 0.713 | 0.232 | 0.262 | 0.232 | 0.712 | 0.37 | 0.396 | 0.37 | 0.703 |
| hurdle_rmse_log_perc75_S1 | C3 hurdle | rmse_log | isotonic | 194194.0 | DCHN | 58274.042 | -0.148 | 0.23 | -0.148 | 0.878 | -0.627 | 0.256 | -0.627 | 0.879 | -1.059 | 0.407 | -1.059 | 0.878 |
| log_w_composite_perc75_S1 | C1 log+가중 | composite | none | 194194.0 | DCHN | 14715.503 | 0.14 | 0.178 | 0.14 | 0.721 | 0.185 | 0.233 | 0.185 | 0.719 | 0.321 | 0.364 | 0.321 | 0.707 |
| log_w_composite_perc75_S1 | C1 log+가중 | composite | smearing | 194194.0 | DCHN | 22794.252 | 0.117 | 0.178 | 0.117 | 0.716 | 0.081 | 0.233 | 0.081 | 0.715 | 0.146 | 0.364 | 0.146 | 0.708 |
| log_w_composite_perc75_S1 | C1 log+가중 | composite | isotonic | 194194.0 | DCHN | 59009.593 | -0.637 | 0.198 | -0.637 | 0.9 | -1.497 | 0.235 | -1.497 | 0.901 | -2.15 | 0.377 | -2.15 | 0.899 |
| log_w_rmse_log_perc75_S1 | C1 log+가중 | rmse_log | none | 194194.0 | DCHN | 11902.799 | 0.101 | 0.143 | 0.101 | 0.728 | 0.137 | 0.203 | 0.137 | 0.725 | 0.238 | 0.311 | 0.238 | 0.714 |
| log_w_rmse_log_perc75_S1 | C1 log+가중 | rmse_log | smearing | 194194.0 | DCHN | 13058.172 | 0.097 | 0.143 | 0.097 | 0.725 | 0.121 | 0.203 | 0.121 | 0.723 | 0.211 | 0.311 | 0.211 | 0.713 |
| log_w_rmse_log_perc75_S1 | C1 log+가중 | rmse_log | isotonic | 194194.0 | DCHN | 41582.667 | -0.202 | 0.206 | -0.202 | 0.911 | -0.617 | 0.266 | -0.617 | 0.912 | -1.029 | 0.406 | -1.029 | 0.913 |
| tweedie_composite_perc75_S1 | C2 tweedie/poisson | composite | none | 194194.0 | DCHN | 21246.906 | 0.153 | 0.19 | 0.153 | 0.732 | 0.156 | 0.217 | 0.156 | 0.731 | 0.276 | 0.338 | 0.276 | 0.721 |
| tweedie_composite_perc75_S1 | C2 tweedie/poisson | composite | smearing | 194194.0 | DCHN | 21246.906 | 0.153 | 0.19 | 0.153 | 0.732 | 0.156 | 0.217 | 0.156 | 0.731 | 0.276 | 0.338 | 0.276 | 0.721 |
| tweedie_composite_perc75_S1 | C2 tweedie/poisson | composite | isotonic | 194194.0 | DCHN | 21246.906 | 0.153 | 0.19 | 0.153 | 0.732 | 0.156 | 0.217 | 0.156 | 0.731 | 0.276 | 0.338 | 0.276 | 0.721 |
| tweedie_rmse_log_perc75_S1 | C2 tweedie/poisson | rmse_log | none | 194194.0 | DCHN | 21165.013 | 0.146 | 0.18 | 0.146 | 0.727 | 0.145 | 0.209 | 0.145 | 0.726 | 0.272 | 0.332 | 0.272 | 0.714 |
| tweedie_rmse_log_perc75_S1 | C2 tweedie/poisson | rmse_log | smearing | 194194.0 | DCHN | 21165.013 | 0.146 | 0.18 | 0.146 | 0.727 | 0.145 | 0.209 | 0.145 | 0.726 | 0.272 | 0.332 | 0.272 | 0.714 |
| tweedie_rmse_log_perc75_S1 | C2 tweedie/poisson | rmse_log | isotonic | 194194.0 | DCHN | 21165.013 | 0.146 | 0.18 | 0.146 | 0.727 | 0.145 | 0.209 | 0.145 | 0.726 | 0.272 | 0.332 | 0.272 | 0.714 |
