# 역변환 편향 보정 비교 (none / Duan smearing / isotonic(이전 폴드 OOF))

- 폴드 F1~F5(train ≤2019~2023 → valid 2020~2024) 평균 = cv_*, Final(train ≤2024 → 2025) = final_*. test(2026) 미접근. 지표 정의: docs/04 6.1 (r2_raw=sklearn 결정계수, r2_pearson_raw=상관²).
- B0 지속성 2025: rmse_log 0.891, r2_raw -0.280, r2_pearson_raw 0.150, nse_raw -0.280, F1@10k 0.727

| study | cv_r2_raw:isotonic | cv_r2_raw:none | cv_r2_raw:smearing | final_nse_raw:isotonic | final_nse_raw:none | final_nse_raw:smearing | final_r2_raw:isotonic | final_r2_raw:none | final_r2_raw:smearing | final_rmse_log:isotonic | final_rmse_log:none | final_rmse_log:smearing |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ens_rmse_log_perc75_S1 | 0.053 | 0.159 | 0.159 | -0.472 | 0.137 | 0.137 | -0.472 | 0.137 | 0.137 | 0.88 | 0.716 | 0.716 |
| hurdle_rmse_log_perc75_S1 | 0.117 | 0.164 | 0.164 | -0.434 | 0.188 | 0.188 | -0.434 | 0.188 | 0.188 | 0.878 | 0.708 | 0.708 |
| log_w_composite_perc75_S1 | 0.051 | 0.183 | 0.229 | -0.501 | 0.157 | 0.109 | -0.501 | 0.157 | 0.109 | 0.868 | 0.722 | 0.713 |
| log_w_rmse_log_perc75_S1 | 0.074 | 0.162 | 0.17 | -0.438 | 0.122 | 0.112 | -0.438 | 0.122 | 0.112 | 0.888 | 0.725 | 0.722 |
| tweedie_composite_perc75_S1 | 0.179 | 0.179 | 0.179 | 0.173 | 0.173 | 0.173 | 0.173 | 0.173 | 0.173 | 0.733 | 0.733 | 0.733 |
| tweedie_rmse_log_perc75_S1 | 0.158 | 0.158 | 0.158 | 0.132 | 0.132 | 0.132 | 0.132 | 0.132 | 0.132 | 0.727 | 0.727 | 0.727 |
