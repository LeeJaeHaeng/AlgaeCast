# 2025 원단위 지표 민감도 — 최대 관측 1건 제외 / 지점별 최대 1건씩 제외

- 폴드 F1~F5(train ≤2019~2023 → valid 2020~2024) 평균 = cv_*, Final(train ≤2024 → 2025) = final_*. test(2026) 미접근. 지표 정의: docs/04 6.1 (r2_raw=sklearn 결정계수, r2_pearson_raw=상관²).
- B0 지속성 2025: rmse_log 0.891, r2_raw -0.280, r2_pearson_raw 0.150, nse_raw -0.280, F1@10k 0.727

| study | 변형 | 목적 | bias | max_obs | max_obs_site | pred_at_max | full_r2_raw | full_r2_pearson_raw | full_nse_raw | full_rmse_log | drop1_r2_raw | drop1_r2_pearson_raw | drop1_nse_raw | drop1_rmse_log | drop_site_max_r2_raw | drop_site_max_r2_pearson_raw | drop_site_max_nse_raw | drop_site_max_rmse_log |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ens_rmse_log_perc75_S1 | C4 C1·C2 앙상블 | rmse_log | none | 194194.0 | DCHN | 18965.281 | 0.137 | 0.176 | 0.137 | 0.716 | 0.146 | 0.226 | 0.146 | 0.715 | 0.262 | 0.358 | 0.262 | 0.704 |
| ens_rmse_log_perc75_S1 | C4 C1·C2 앙상블 | rmse_log | smearing | 194194.0 | DCHN | 18965.281 | 0.137 | 0.176 | 0.137 | 0.716 | 0.146 | 0.226 | 0.146 | 0.715 | 0.262 | 0.358 | 0.262 | 0.704 |
| ens_rmse_log_perc75_S1 | C4 C1·C2 앙상블 | rmse_log | isotonic | 194194.0 | DCHN | 65472.318 | -0.472 | 0.233 | -0.472 | 0.88 | -1.241 | 0.268 | -1.241 | 0.882 | -2.009 | 0.429 | -2.009 | 0.881 |
| hurdle_rmse_log_perc75_S1 | C3 hurdle | rmse_log | none | 194194.0 | DCHN | 20142.358 | 0.188 | 0.209 | 0.188 | 0.708 | 0.226 | 0.263 | 0.226 | 0.707 | 0.342 | 0.389 | 0.342 | 0.7 |
| hurdle_rmse_log_perc75_S1 | C3 hurdle | rmse_log | smearing | 194194.0 | DCHN | 20142.358 | 0.188 | 0.209 | 0.188 | 0.708 | 0.226 | 0.263 | 0.226 | 0.707 | 0.342 | 0.389 | 0.342 | 0.7 |
| hurdle_rmse_log_perc75_S1 | C3 hurdle | rmse_log | isotonic | 194194.0 | DCHN | 63491.0 | -0.434 | 0.232 | -0.434 | 0.878 | -1.163 | 0.269 | -1.163 | 0.879 | -1.986 | 0.395 | -1.986 | 0.879 |
| log_w_composite_perc75_S1 | C1 log+가중 | composite | none | 194194.0 | DCHN | 17756.083 | 0.157 | 0.191 | 0.157 | 0.722 | 0.19 | 0.241 | 0.19 | 0.72 | 0.337 | 0.381 | 0.337 | 0.705 |
| log_w_composite_perc75_S1 | C1 log+가중 | composite | smearing | 194194.0 | DCHN | 27772.876 | 0.109 | 0.191 | 0.109 | 0.713 | 0.029 | 0.241 | 0.029 | 0.712 | 0.093 | 0.381 | 0.093 | 0.702 |
| log_w_composite_perc75_S1 | C1 log+가중 | composite | isotonic | 194194.0 | DCHN | 42258.51 | -0.501 | 0.173 | -0.501 | 0.868 | -1.15 | 0.224 | -1.15 | 0.869 | -1.812 | 0.363 | -1.812 | 0.865 |
| log_w_rmse_log_perc75_S1 | C1 log+가중 | rmse_log | none | 194194.0 | DCHN | 16041.252 | 0.122 | 0.165 | 0.122 | 0.725 | 0.141 | 0.225 | 0.141 | 0.723 | 0.286 | 0.368 | 0.286 | 0.708 |
| log_w_rmse_log_perc75_S1 | C1 log+가중 | rmse_log | smearing | 194194.0 | DCHN | 17506.047 | 0.112 | 0.165 | 0.112 | 0.722 | 0.112 | 0.225 | 0.112 | 0.72 | 0.247 | 0.368 | 0.247 | 0.706 |
| log_w_rmse_log_perc75_S1 | C1 log+가중 | rmse_log | isotonic | 194194.0 | DCHN | 46080.755 | -0.438 | 0.21 | -0.438 | 0.888 | -1.064 | 0.275 | -1.064 | 0.889 | -1.71 | 0.438 | -1.71 | 0.885 |
| tweedie_composite_perc75_S1 | C2 tweedie/poisson | composite | none | 194194.0 | DCHN | 22850.082 | 0.173 | 0.203 | 0.173 | 0.733 | 0.179 | 0.24 | 0.179 | 0.732 | 0.313 | 0.382 | 0.313 | 0.721 |
| tweedie_composite_perc75_S1 | C2 tweedie/poisson | composite | smearing | 194194.0 | DCHN | 22850.082 | 0.173 | 0.203 | 0.173 | 0.733 | 0.179 | 0.24 | 0.179 | 0.732 | 0.313 | 0.382 | 0.313 | 0.721 |
| tweedie_composite_perc75_S1 | C2 tweedie/poisson | composite | isotonic | 194194.0 | DCHN | 22850.082 | 0.173 | 0.203 | 0.173 | 0.733 | 0.179 | 0.24 | 0.179 | 0.732 | 0.313 | 0.382 | 0.313 | 0.721 |
| tweedie_rmse_log_perc75_S1 | C2 tweedie/poisson | rmse_log | none | 194194.0 | DCHN | 21112.238 | 0.132 | 0.172 | 0.132 | 0.727 | 0.121 | 0.208 | 0.121 | 0.726 | 0.245 | 0.333 | 0.245 | 0.714 |
| tweedie_rmse_log_perc75_S1 | C2 tweedie/poisson | rmse_log | smearing | 194194.0 | DCHN | 21112.238 | 0.132 | 0.172 | 0.132 | 0.727 | 0.121 | 0.208 | 0.121 | 0.726 | 0.245 | 0.333 | 0.245 | 0.714 |
| tweedie_rmse_log_perc75_S1 | C2 tweedie/poisson | rmse_log | isotonic | 194194.0 | DCHN | 21112.238 | 0.132 | 0.172 | 0.132 | 0.727 | 0.121 | 0.208 | 0.121 | 0.726 | 0.245 | 0.333 | 0.245 | 0.714 |
