# 역변환 편향 보정 비교 (none / Duan smearing / isotonic(이전 폴드 OOF))

- 폴드 F1~F5(train ≤2019~2023 → valid 2020~2024) 평균 = cv_*, Final(train ≤2024 → 2025) = final_*. test(2026) 미접근. 지표 정의: docs/04 6.1 (r2_raw=sklearn 결정계수 = NSE(대회 공식 R² 아님), r2_pearson_raw=상관² = 대회 공식 R²(공식 Q&A 2026-10-30 ②)).
- B0 지속성 2025: rmse_log 0.896, r2_raw -0.283, r2_pearson_raw 0.148, nse_raw -0.283, F1@10k 0.727

| study | cv_r2_raw:isotonic | cv_r2_raw:none | cv_r2_raw:smearing | final_nse_raw:isotonic | final_nse_raw:none | final_nse_raw:smearing | final_r2_raw:isotonic | final_r2_raw:none | final_r2_raw:smearing | final_rmse_log:isotonic | final_rmse_log:none | final_rmse_log:smearing |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ens_rmse_log_perc75_S1 | 0.031 | 0.15 | 0.15 | -0.259 | 0.143 | 0.143 | -0.259 | 0.143 | 0.143 | 0.878 | 0.709 | 0.709 |
| hurdle_rmse_log_perc75_S1 | 0.096 | 0.148 | 0.148 | -0.148 | 0.189 | 0.189 | -0.148 | 0.189 | 0.189 | 0.878 | 0.713 | 0.713 |
| log_w_composite_perc75_S1 | 0.081 | 0.17 | 0.223 | -0.637 | 0.14 | 0.117 | -0.637 | 0.14 | 0.117 | 0.9 | 0.721 | 0.716 |
| log_w_rmse_log_perc75_S1 | 0.006 | 0.147 | 0.156 | -0.202 | 0.101 | 0.097 | -0.202 | 0.101 | 0.097 | 0.911 | 0.728 | 0.725 |
| tweedie_composite_perc75_S1 | 0.156 | 0.156 | 0.156 | 0.153 | 0.153 | 0.153 | 0.153 | 0.153 | 0.153 | 0.732 | 0.732 | 0.732 |
| tweedie_rmse_log_perc75_S1 | 0.143 | 0.143 | 0.143 | 0.146 | 0.146 | 0.146 | 0.146 | 0.146 | 0.146 | 0.727 | 0.727 | 0.727 |
