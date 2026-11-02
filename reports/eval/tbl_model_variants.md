# T4-b 변형 × 역변환 보정 비교 (perc75, S1)

- 폴드 F1~F5(train ≤2019~2023 → valid 2020~2024) 평균 = cv_*, Final(train ≤2024 → 2025) = final_*. test(2026) 미접근. 지표 정의: docs/04 6.1 (r2_raw=sklearn 결정계수 = NSE(대회 공식 R² 아님), r2_pearson_raw=상관² = 대회 공식 R²(공식 Q&A 2026-10-30 ②)).
- B0 지속성 2025: rmse_log 0.896, r2_raw -0.283, r2_pearson_raw 0.148, nse_raw -0.283, F1@10k 0.727
- **채택(CV 복합점수 J 최소)**: log_w_composite_perc75_S1 / bias=smearing (J=0.8795)

| study | 변형 | 목적 | bias | cv_rmse_log | cv_mae_log | cv_r2_log | cv_r2_raw | cv_r2_pearson_raw | cv_nse_raw | cv_f1_10k | final_rmse_log | final_mae_log | final_r2_log | final_r2_raw | final_r2_pearson_raw | final_nse_raw | final_f1_10k | J_cv |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| log_w_composite_perc75_S1 | C1 log+가중 | composite | smearing | 0.815 | 0.583 | 0.67 | 0.223 | 0.296 | 0.223 | 0.531 | 0.716 | 0.52 | 0.776 | 0.117 | 0.178 | 0.117 | 0.697 | 0.88 |
| log_w_composite_perc75_S1 | C1 log+가중 | composite | none | 0.803 | 0.586 | 0.68 | 0.17 | 0.296 | 0.17 | 0.391 | 0.721 | 0.543 | 0.773 | 0.14 | 0.178 | 0.14 | 0.641 | 0.899 |
| ens_rmse_log_perc75_S1 | C4 C1·C2 앙상블 | rmse_log | none | 0.803 | 0.594 | 0.68 | 0.15 | 0.269 | 0.15 | 0.498 | 0.709 | 0.531 | 0.78 | 0.143 | 0.176 | 0.143 | 0.625 | 0.909 |
| ens_rmse_log_perc75_S1 | C4 C1·C2 앙상블 | rmse_log | smearing | 0.803 | 0.594 | 0.68 | 0.15 | 0.269 | 0.15 | 0.498 | 0.709 | 0.531 | 0.78 | 0.143 | 0.176 | 0.143 | 0.625 | 0.909 |
| log_w_rmse_log_perc75_S1 | C1 log+가중 | rmse_log | smearing | 0.813 | 0.595 | 0.674 | 0.156 | 0.254 | 0.156 | 0.498 | 0.725 | 0.546 | 0.77 | 0.097 | 0.143 | 0.097 | 0.625 | 0.912 |
| hurdle_rmse_log_perc75_S1 | C3 hurdle | rmse_log | smearing | 0.809 | 0.621 | 0.674 | 0.148 | 0.262 | 0.148 | 0.505 | 0.713 | 0.541 | 0.777 | 0.189 | 0.213 | 0.189 | 0.635 | 0.913 |
| hurdle_rmse_log_perc75_S1 | C3 hurdle | rmse_log | none | 0.809 | 0.621 | 0.674 | 0.148 | 0.262 | 0.148 | 0.505 | 0.713 | 0.541 | 0.777 | 0.189 | 0.213 | 0.189 | 0.635 | 0.913 |
| log_w_rmse_log_perc75_S1 | C1 log+가중 | rmse_log | none | 0.812 | 0.597 | 0.674 | 0.147 | 0.254 | 0.147 | 0.502 | 0.728 | 0.553 | 0.768 | 0.101 | 0.143 | 0.101 | 0.597 | 0.916 |
| tweedie_rmse_log_perc75_S1 | C2 tweedie/poisson | rmse_log | none | 0.81 | 0.584 | 0.677 | 0.143 | 0.237 | 0.143 | 0.447 | 0.727 | 0.538 | 0.769 | 0.146 | 0.18 | 0.146 | 0.675 | 0.916 |
| tweedie_rmse_log_perc75_S1 | C2 tweedie/poisson | rmse_log | smearing | 0.81 | 0.584 | 0.677 | 0.143 | 0.237 | 0.143 | 0.447 | 0.727 | 0.538 | 0.769 | 0.146 | 0.18 | 0.146 | 0.675 | 0.916 |
| tweedie_rmse_log_perc75_S1 | C2 tweedie/poisson | rmse_log | isotonic | 0.81 | 0.584 | 0.677 | 0.143 | 0.237 | 0.143 | 0.447 | 0.727 | 0.538 | 0.769 | 0.146 | 0.18 | 0.146 | 0.675 | 0.916 |
| tweedie_composite_perc75_S1 | C2 tweedie/poisson | composite | isotonic | 0.835 | 0.61 | 0.653 | 0.156 | 0.257 | 0.156 | 0.499 | 0.732 | 0.555 | 0.765 | 0.153 | 0.19 | 0.153 | 0.597 | 0.925 |
| tweedie_composite_perc75_S1 | C2 tweedie/poisson | composite | smearing | 0.835 | 0.61 | 0.653 | 0.156 | 0.257 | 0.156 | 0.499 | 0.732 | 0.555 | 0.765 | 0.153 | 0.19 | 0.153 | 0.597 | 0.925 |
| tweedie_composite_perc75_S1 | C2 tweedie/poisson | composite | none | 0.835 | 0.61 | 0.653 | 0.156 | 0.257 | 0.156 | 0.499 | 0.732 | 0.555 | 0.765 | 0.153 | 0.19 | 0.153 | 0.597 | 0.925 |
| hurdle_rmse_log_perc75_S1 | C3 hurdle | rmse_log | isotonic | 0.966 | 0.725 | 0.546 | 0.096 | 0.249 | 0.096 | 0.469 | 0.878 | 0.644 | 0.663 | -0.148 | 0.23 | -0.148 | 0.743 | 1.034 |
| log_w_composite_perc75_S1 | C1 log+가중 | composite | isotonic | 0.963 | 0.714 | 0.549 | 0.081 | 0.262 | 0.081 | 0.373 | 0.9 | 0.661 | 0.646 | -0.637 | 0.198 | -0.637 | 0.711 | 1.04 |
| ens_rmse_log_perc75_S1 | C4 C1·C2 앙상블 | rmse_log | isotonic | 0.967 | 0.726 | 0.545 | 0.031 | 0.247 | 0.031 | 0.473 | 0.878 | 0.652 | 0.663 | -0.259 | 0.237 | -0.259 | 0.737 | 1.067 |
| log_w_rmse_log_perc75_S1 | C1 log+가중 | rmse_log | isotonic | 0.984 | 0.742 | 0.529 | 0.006 | 0.26 | 0.006 | 0.53 | 0.911 | 0.666 | 0.637 | -0.202 | 0.206 | -0.202 | 0.732 | 1.09 |

## 지점별 — Final(2025)
| study | bias | station_id | n | rmse_log | mae_log | r2_log | r2_raw | r2_pearson_raw | nse_raw | f1_10k |
|---|---|---|---|---|---|---|---|---|---|---|
| ens_rmse_log_perc75_S1 | none | CS | 50 | 0.656 | 0.495 | 0.77 | 0.38 | 0.462 | 0.38 | 0.588 |
| ens_rmse_log_perc75_S1 | none | DCHN | 56 | 0.721 | 0.543 | 0.827 | 0.169 | 0.472 | 0.169 | 0.727 |
| ens_rmse_log_perc75_S1 | none | GJGR | 55 | 0.745 | 0.563 | 0.731 | 0.003 | 0.079 | 0.003 | 0.636 |
| ens_rmse_log_perc75_S1 | none | HP | 44 | 0.668 | 0.487 | 0.756 | 0.117 | 0.172 | 0.117 | 0.0 |
| ens_rmse_log_perc75_S1 | none | MGMR | 47 | 0.742 | 0.559 | 0.726 | 0.032 | 0.153 | 0.032 | 0.556 |
| ens_rmse_log_perc75_S1 | smearing | CS | 50 | 0.656 | 0.495 | 0.77 | 0.38 | 0.462 | 0.38 | 0.588 |
| ens_rmse_log_perc75_S1 | smearing | DCHN | 56 | 0.721 | 0.543 | 0.827 | 0.169 | 0.472 | 0.169 | 0.727 |
| ens_rmse_log_perc75_S1 | smearing | GJGR | 55 | 0.745 | 0.563 | 0.731 | 0.003 | 0.079 | 0.003 | 0.636 |
| ens_rmse_log_perc75_S1 | smearing | HP | 44 | 0.668 | 0.487 | 0.756 | 0.117 | 0.172 | 0.117 | 0.0 |
| ens_rmse_log_perc75_S1 | smearing | MGMR | 47 | 0.742 | 0.559 | 0.726 | 0.032 | 0.153 | 0.032 | 0.556 |
| ens_rmse_log_perc75_S1 | isotonic | CS | 50 | 0.838 | 0.587 | 0.625 | -3.451 | 0.384 | -3.451 | 0.64 |
| ens_rmse_log_perc75_S1 | isotonic | DCHN | 56 | 0.9 | 0.667 | 0.731 | 0.368 | 0.393 | 0.368 | 0.857 |
| ens_rmse_log_perc75_S1 | isotonic | GJGR | 55 | 0.894 | 0.66 | 0.612 | -0.979 | 0.095 | -0.979 | 0.788 |
| ens_rmse_log_perc75_S1 | isotonic | HP | 44 | 0.872 | 0.697 | 0.585 | 0.033 | 0.152 | 0.033 | 0.0 |
| ens_rmse_log_perc75_S1 | isotonic | MGMR | 47 | 0.882 | 0.652 | 0.613 | -0.506 | 0.208 | -0.506 | 0.75 |
| hurdle_rmse_log_perc75_S1 | none | CS | 50 | 0.652 | 0.468 | 0.773 | 0.438 | 0.475 | 0.438 | 0.588 |
| hurdle_rmse_log_perc75_S1 | none | DCHN | 56 | 0.69 | 0.539 | 0.842 | 0.186 | 0.515 | 0.186 | 0.8 |
| hurdle_rmse_log_perc75_S1 | none | GJGR | 55 | 0.79 | 0.607 | 0.697 | -0.021 | 0.065 | -0.021 | 0.609 |
| hurdle_rmse_log_perc75_S1 | none | HP | 44 | 0.699 | 0.54 | 0.733 | 0.163 | 0.185 | 0.163 | 0.0 |
| hurdle_rmse_log_perc75_S1 | none | MGMR | 47 | 0.722 | 0.545 | 0.741 | 0.203 | 0.237 | 0.203 | 0.556 |
| hurdle_rmse_log_perc75_S1 | smearing | CS | 50 | 0.652 | 0.468 | 0.773 | 0.438 | 0.475 | 0.438 | 0.588 |
| hurdle_rmse_log_perc75_S1 | smearing | DCHN | 56 | 0.69 | 0.539 | 0.842 | 0.186 | 0.515 | 0.186 | 0.8 |
| hurdle_rmse_log_perc75_S1 | smearing | GJGR | 55 | 0.79 | 0.607 | 0.697 | -0.021 | 0.065 | -0.021 | 0.609 |
| hurdle_rmse_log_perc75_S1 | smearing | HP | 44 | 0.699 | 0.54 | 0.733 | 0.163 | 0.185 | 0.163 | 0.0 |
| hurdle_rmse_log_perc75_S1 | smearing | MGMR | 47 | 0.722 | 0.545 | 0.741 | 0.203 | 0.237 | 0.203 | 0.556 |
| hurdle_rmse_log_perc75_S1 | isotonic | CS | 50 | 0.824 | 0.575 | 0.637 | -2.989 | 0.367 | -2.989 | 0.571 |
| hurdle_rmse_log_perc75_S1 | isotonic | DCHN | 56 | 0.856 | 0.629 | 0.757 | 0.425 | 0.426 | 0.425 | 0.857 |
| hurdle_rmse_log_perc75_S1 | isotonic | GJGR | 55 | 0.923 | 0.675 | 0.587 | -0.838 | 0.064 | -0.838 | 0.759 |
| hurdle_rmse_log_perc75_S1 | isotonic | HP | 44 | 0.909 | 0.706 | 0.548 | -2.167 | 0.062 | -2.167 | 0.5 |
| hurdle_rmse_log_perc75_S1 | isotonic | MGMR | 47 | 0.878 | 0.639 | 0.616 | -0.209 | 0.247 | -0.209 | 0.783 |
| log_w_composite_perc75_S1 | none | CS | 50 | 0.697 | 0.527 | 0.74 | 0.363 | 0.43 | 0.363 | 0.588 |
| log_w_composite_perc75_S1 | none | DCHN | 56 | 0.729 | 0.565 | 0.823 | 0.133 | 0.443 | 0.133 | 0.727 |
| log_w_composite_perc75_S1 | none | GJGR | 55 | 0.769 | 0.58 | 0.714 | -0.032 | 0.062 | -0.032 | 0.636 |
| log_w_composite_perc75_S1 | none | HP | 44 | 0.667 | 0.503 | 0.757 | 0.155 | 0.341 | 0.155 | 0.0 |
| log_w_composite_perc75_S1 | none | MGMR | 47 | 0.727 | 0.53 | 0.737 | 0.132 | 0.188 | 0.132 | 0.625 |
| log_w_composite_perc75_S1 | smearing | CS | 50 | 0.692 | 0.497 | 0.744 | -0.095 | 0.43 | -0.095 | 0.588 |
| log_w_composite_perc75_S1 | smearing | DCHN | 56 | 0.711 | 0.504 | 0.832 | 0.245 | 0.443 | 0.245 | 0.846 |
| log_w_composite_perc75_S1 | smearing | GJGR | 55 | 0.769 | 0.561 | 0.714 | -0.148 | 0.062 | -0.148 | 0.692 |
| log_w_composite_perc75_S1 | smearing | HP | 44 | 0.67 | 0.5 | 0.755 | 0.257 | 0.341 | 0.257 | 0.0 |
| log_w_composite_perc75_S1 | smearing | MGMR | 47 | 0.728 | 0.533 | 0.736 | -0.034 | 0.188 | -0.034 | 0.632 |
| log_w_composite_perc75_S1 | isotonic | CS | 50 | 0.841 | 0.575 | 0.623 | -4.672 | 0.374 | -4.672 | 0.588 |
| log_w_composite_perc75_S1 | isotonic | DCHN | 56 | 0.941 | 0.681 | 0.706 | 0.497 | 0.512 | 0.497 | 0.846 |
| log_w_composite_perc75_S1 | isotonic | GJGR | 55 | 0.89 | 0.652 | 0.616 | -1.492 | 0.053 | -1.492 | 0.692 |
| log_w_composite_perc75_S1 | isotonic | HP | 44 | 0.946 | 0.739 | 0.511 | 0.31 | 0.311 | 0.31 | 0.0 |
| log_w_composite_perc75_S1 | isotonic | MGMR | 47 | 0.877 | 0.667 | 0.617 | -1.835 | 0.218 | -1.835 | 0.7 |
| log_w_rmse_log_perc75_S1 | none | CS | 50 | 0.662 | 0.504 | 0.766 | 0.343 | 0.437 | 0.343 | 0.588 |
| log_w_rmse_log_perc75_S1 | none | DCHN | 56 | 0.769 | 0.598 | 0.804 | 0.098 | 0.346 | 0.098 | 0.6 |
| log_w_rmse_log_perc75_S1 | none | GJGR | 55 | 0.756 | 0.581 | 0.723 | -0.063 | 0.059 | -0.063 | 0.636 |
| log_w_rmse_log_perc75_S1 | none | HP | 44 | 0.664 | 0.505 | 0.759 | 0.156 | 0.29 | 0.156 | 0.0 |
| log_w_rmse_log_perc75_S1 | none | MGMR | 47 | 0.765 | 0.562 | 0.708 | 0.062 | 0.159 | 0.062 | 0.588 |
| log_w_rmse_log_perc75_S1 | smearing | CS | 50 | 0.657 | 0.494 | 0.77 | 0.288 | 0.437 | 0.288 | 0.588 |
| log_w_rmse_log_perc75_S1 | smearing | DCHN | 56 | 0.765 | 0.585 | 0.806 | 0.117 | 0.346 | 0.117 | 0.636 |
| log_w_rmse_log_perc75_S1 | smearing | GJGR | 55 | 0.755 | 0.577 | 0.724 | -0.086 | 0.059 | -0.086 | 0.696 |
| log_w_rmse_log_perc75_S1 | smearing | HP | 44 | 0.662 | 0.504 | 0.76 | 0.176 | 0.29 | 0.176 | 0.0 |
| log_w_rmse_log_perc75_S1 | smearing | MGMR | 47 | 0.764 | 0.557 | 0.709 | 0.034 | 0.159 | 0.034 | 0.588 |
| log_w_rmse_log_perc75_S1 | isotonic | CS | 50 | 0.817 | 0.559 | 0.643 | -2.578 | 0.456 | -2.578 | 0.636 |
| log_w_rmse_log_perc75_S1 | isotonic | DCHN | 56 | 0.97 | 0.709 | 0.688 | 0.375 | 0.39 | 0.375 | 0.815 |
| log_w_rmse_log_perc75_S1 | isotonic | GJGR | 55 | 0.905 | 0.656 | 0.603 | -0.741 | 0.089 | -0.741 | 0.788 |
| log_w_rmse_log_perc75_S1 | isotonic | HP | 44 | 0.92 | 0.717 | 0.537 | 0.27 | 0.366 | 0.27 | 0.4 |
| log_w_rmse_log_perc75_S1 | isotonic | MGMR | 47 | 0.934 | 0.692 | 0.566 | -0.692 | 0.214 | -0.692 | 0.72 |
| tweedie_composite_perc75_S1 | none | CS | 50 | 0.669 | 0.502 | 0.761 | 0.33 | 0.399 | 0.33 | 0.588 |
| tweedie_composite_perc75_S1 | none | DCHN | 56 | 0.727 | 0.557 | 0.825 | 0.199 | 0.542 | 0.199 | 0.727 |
| tweedie_composite_perc75_S1 | none | GJGR | 55 | 0.799 | 0.615 | 0.691 | -0.066 | 0.05 | -0.066 | 0.5 |
| tweedie_composite_perc75_S1 | none | HP | 44 | 0.684 | 0.53 | 0.744 | 0.138 | 0.276 | 0.138 | 0.0 |
| tweedie_composite_perc75_S1 | none | MGMR | 47 | 0.765 | 0.563 | 0.708 | 0.071 | 0.166 | 0.071 | 0.588 |
| tweedie_composite_perc75_S1 | smearing | CS | 50 | 0.669 | 0.502 | 0.761 | 0.33 | 0.399 | 0.33 | 0.588 |
| tweedie_composite_perc75_S1 | smearing | DCHN | 56 | 0.727 | 0.557 | 0.825 | 0.199 | 0.542 | 0.199 | 0.727 |
| tweedie_composite_perc75_S1 | smearing | GJGR | 55 | 0.799 | 0.615 | 0.691 | -0.066 | 0.05 | -0.066 | 0.5 |
| tweedie_composite_perc75_S1 | smearing | HP | 44 | 0.684 | 0.53 | 0.744 | 0.138 | 0.276 | 0.138 | 0.0 |
| tweedie_composite_perc75_S1 | smearing | MGMR | 47 | 0.765 | 0.563 | 0.708 | 0.071 | 0.166 | 0.071 | 0.588 |
| tweedie_composite_perc75_S1 | isotonic | CS | 50 | 0.669 | 0.502 | 0.761 | 0.33 | 0.399 | 0.33 | 0.588 |
| tweedie_composite_perc75_S1 | isotonic | DCHN | 56 | 0.727 | 0.557 | 0.825 | 0.199 | 0.542 | 0.199 | 0.727 |
| tweedie_composite_perc75_S1 | isotonic | GJGR | 55 | 0.799 | 0.615 | 0.691 | -0.066 | 0.05 | -0.066 | 0.5 |
| tweedie_composite_perc75_S1 | isotonic | HP | 44 | 0.684 | 0.53 | 0.744 | 0.138 | 0.276 | 0.138 | 0.0 |
| tweedie_composite_perc75_S1 | isotonic | MGMR | 47 | 0.765 | 0.563 | 0.708 | 0.071 | 0.166 | 0.071 | 0.588 |
| tweedie_rmse_log_perc75_S1 | none | CS | 50 | 0.675 | 0.501 | 0.757 | 0.22 | 0.4 | 0.22 | 0.625 |
| tweedie_rmse_log_perc75_S1 | none | DCHN | 56 | 0.718 | 0.531 | 0.829 | 0.196 | 0.512 | 0.196 | 0.783 |
| tweedie_rmse_log_perc75_S1 | none | GJGR | 55 | 0.816 | 0.613 | 0.677 | -0.012 | 0.073 | -0.012 | 0.696 |
| tweedie_rmse_log_perc75_S1 | none | HP | 44 | 0.667 | 0.494 | 0.757 | 0.145 | 0.263 | 0.145 | 0.0 |
| tweedie_rmse_log_perc75_S1 | none | MGMR | 47 | 0.737 | 0.537 | 0.73 | 0.035 | 0.141 | 0.035 | 0.588 |
| tweedie_rmse_log_perc75_S1 | smearing | CS | 50 | 0.675 | 0.501 | 0.757 | 0.22 | 0.4 | 0.22 | 0.625 |
| tweedie_rmse_log_perc75_S1 | smearing | DCHN | 56 | 0.718 | 0.531 | 0.829 | 0.196 | 0.512 | 0.196 | 0.783 |
| tweedie_rmse_log_perc75_S1 | smearing | GJGR | 55 | 0.816 | 0.613 | 0.677 | -0.012 | 0.073 | -0.012 | 0.696 |
| tweedie_rmse_log_perc75_S1 | smearing | HP | 44 | 0.667 | 0.494 | 0.757 | 0.145 | 0.263 | 0.145 | 0.0 |
| tweedie_rmse_log_perc75_S1 | smearing | MGMR | 47 | 0.737 | 0.537 | 0.73 | 0.035 | 0.141 | 0.035 | 0.588 |
| tweedie_rmse_log_perc75_S1 | isotonic | CS | 50 | 0.675 | 0.501 | 0.757 | 0.22 | 0.4 | 0.22 | 0.625 |
| tweedie_rmse_log_perc75_S1 | isotonic | DCHN | 56 | 0.718 | 0.531 | 0.829 | 0.196 | 0.512 | 0.196 | 0.783 |
| tweedie_rmse_log_perc75_S1 | isotonic | GJGR | 55 | 0.816 | 0.613 | 0.677 | -0.012 | 0.073 | -0.012 | 0.696 |
| tweedie_rmse_log_perc75_S1 | isotonic | HP | 44 | 0.667 | 0.494 | 0.757 | 0.145 | 0.263 | 0.145 | 0.0 |
| tweedie_rmse_log_perc75_S1 | isotonic | MGMR | 47 | 0.737 | 0.537 | 0.73 | 0.035 | 0.141 | 0.035 | 0.588 |
