# T4-b 변형 × 역변환 보정 비교 (perc75, S1)

- 폴드 F1~F5(train ≤2019~2023 → valid 2020~2024) 평균 = cv_*, Final(train ≤2024 → 2025) = final_*. test(2026) 미접근. 지표 정의: docs/04 6.1 (r2_raw=sklearn 결정계수, r2_pearson_raw=상관²).
- B0 지속성 2025: rmse_log 0.891, r2_raw -0.280, r2_pearson_raw 0.150, nse_raw -0.280, F1@10k 0.727
- **채택(CV 복합점수 J 최소)**: log_w_composite_perc75_S1 / bias=smearing (J=0.8789)

| study | 변형 | 목적 | bias | cv_rmse_log | cv_mae_log | cv_r2_log | cv_r2_raw | cv_r2_pearson_raw | cv_nse_raw | cv_f1_10k | final_rmse_log | final_mae_log | final_r2_log | final_r2_raw | final_r2_pearson_raw | final_nse_raw | final_f1_10k | J_cv |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| log_w_composite_perc75_S1 | C1 log+가중 | composite | smearing | 0.819 | 0.59 | 0.666 | 0.229 | 0.307 | 0.229 | 0.496 | 0.713 | 0.519 | 0.777 | 0.109 | 0.191 | 0.109 | 0.682 | 0.879 |
| log_w_composite_perc75_S1 | C1 log+가중 | composite | none | 0.807 | 0.593 | 0.676 | 0.183 | 0.307 | 0.183 | 0.417 | 0.722 | 0.54 | 0.772 | 0.157 | 0.191 | 0.157 | 0.615 | 0.895 |
| log_w_rmse_log_perc75_S1 | C1 log+가중 | rmse_log | smearing | 0.811 | 0.59 | 0.675 | 0.17 | 0.273 | 0.17 | 0.545 | 0.722 | 0.538 | 0.771 | 0.112 | 0.165 | 0.112 | 0.69 | 0.903 |
| ens_rmse_log_perc75_S1 | C4 C1·C2 앙상블 | rmse_log | none | 0.802 | 0.593 | 0.68 | 0.159 | 0.275 | 0.159 | 0.509 | 0.716 | 0.529 | 0.775 | 0.137 | 0.176 | 0.137 | 0.659 | 0.904 |
| ens_rmse_log_perc75_S1 | C4 C1·C2 앙상블 | rmse_log | smearing | 0.802 | 0.593 | 0.68 | 0.159 | 0.275 | 0.159 | 0.509 | 0.716 | 0.529 | 0.775 | 0.137 | 0.176 | 0.137 | 0.659 | 0.904 |
| log_w_rmse_log_perc75_S1 | C1 log+가중 | rmse_log | none | 0.81 | 0.592 | 0.676 | 0.162 | 0.273 | 0.162 | 0.389 | 0.725 | 0.544 | 0.769 | 0.122 | 0.165 | 0.122 | 0.675 | 0.907 |
| hurdle_rmse_log_perc75_S1 | C3 hurdle | rmse_log | smearing | 0.814 | 0.625 | 0.671 | 0.164 | 0.284 | 0.164 | 0.545 | 0.708 | 0.539 | 0.78 | 0.188 | 0.209 | 0.188 | 0.674 | 0.909 |
| hurdle_rmse_log_perc75_S1 | C3 hurdle | rmse_log | none | 0.814 | 0.625 | 0.671 | 0.164 | 0.284 | 0.164 | 0.545 | 0.708 | 0.539 | 0.78 | 0.188 | 0.209 | 0.188 | 0.674 | 0.909 |
| tweedie_rmse_log_perc75_S1 | C2 tweedie/poisson | rmse_log | none | 0.81 | 0.584 | 0.676 | 0.158 | 0.249 | 0.158 | 0.504 | 0.727 | 0.53 | 0.768 | 0.132 | 0.172 | 0.132 | 0.683 | 0.909 |
| tweedie_rmse_log_perc75_S1 | C2 tweedie/poisson | rmse_log | smearing | 0.81 | 0.584 | 0.676 | 0.158 | 0.249 | 0.158 | 0.504 | 0.727 | 0.53 | 0.768 | 0.132 | 0.172 | 0.132 | 0.683 | 0.909 |
| tweedie_rmse_log_perc75_S1 | C2 tweedie/poisson | rmse_log | isotonic | 0.81 | 0.584 | 0.676 | 0.158 | 0.249 | 0.158 | 0.504 | 0.727 | 0.53 | 0.768 | 0.132 | 0.172 | 0.132 | 0.683 | 0.909 |
| tweedie_composite_perc75_S1 | C2 tweedie/poisson | composite | isotonic | 0.835 | 0.613 | 0.653 | 0.179 | 0.282 | 0.179 | 0.412 | 0.733 | 0.546 | 0.764 | 0.173 | 0.203 | 0.173 | 0.633 | 0.913 |
| tweedie_composite_perc75_S1 | C2 tweedie/poisson | composite | smearing | 0.835 | 0.613 | 0.653 | 0.179 | 0.282 | 0.179 | 0.412 | 0.733 | 0.546 | 0.764 | 0.173 | 0.203 | 0.173 | 0.633 | 0.913 |
| tweedie_composite_perc75_S1 | C2 tweedie/poisson | composite | none | 0.835 | 0.613 | 0.653 | 0.179 | 0.282 | 0.179 | 0.412 | 0.733 | 0.546 | 0.764 | 0.173 | 0.203 | 0.173 | 0.633 | 0.913 |
| hurdle_rmse_log_perc75_S1 | C3 hurdle | rmse_log | isotonic | 0.973 | 0.731 | 0.54 | 0.117 | 0.249 | 0.117 | 0.573 | 0.878 | 0.652 | 0.662 | -0.434 | 0.232 | -0.434 | 0.733 | 1.028 |
| log_w_rmse_log_perc75_S1 | C1 log+가중 | rmse_log | isotonic | 0.979 | 0.732 | 0.534 | 0.074 | 0.256 | 0.074 | 0.448 | 0.888 | 0.655 | 0.654 | -0.438 | 0.21 | -0.438 | 0.672 | 1.053 |
| ens_rmse_log_perc75_S1 | C4 C1·C2 앙상블 | rmse_log | isotonic | 0.979 | 0.737 | 0.535 | 0.053 | 0.247 | 0.053 | 0.556 | 0.88 | 0.656 | 0.66 | -0.472 | 0.233 | -0.472 | 0.714 | 1.063 |
| log_w_composite_perc75_S1 | C1 log+가중 | composite | isotonic | 0.985 | 0.737 | 0.53 | 0.051 | 0.247 | 0.051 | 0.382 | 0.868 | 0.641 | 0.669 | -0.501 | 0.173 | -0.501 | 0.729 | 1.068 |

## 지점별 — Final(2025)
| study | bias | station_id | n | rmse_log | mae_log | r2_log | r2_raw | r2_pearson_raw | nse_raw | f1_10k |
|---|---|---|---|---|---|---|---|---|---|---|
| ens_rmse_log_perc75_S1 | none | CS | 51 | 0.644 | 0.471 | 0.776 | 0.39 | 0.511 | 0.39 | 0.588 |
| ens_rmse_log_perc75_S1 | none | DCHN | 57 | 0.718 | 0.547 | 0.826 | 0.182 | 0.443 | 0.182 | 0.783 |
| ens_rmse_log_perc75_S1 | none | GJGR | 55 | 0.775 | 0.584 | 0.709 | -0.008 | 0.073 | -0.008 | 0.696 |
| ens_rmse_log_perc75_S1 | none | HP | 45 | 0.677 | 0.476 | 0.756 | 0.134 | 0.21 | 0.134 | 0.0 |
| ens_rmse_log_perc75_S1 | none | MGMR | 48 | 0.752 | 0.555 | 0.713 | -0.019 | 0.167 | -0.019 | 0.556 |
| ens_rmse_log_perc75_S1 | smearing | CS | 51 | 0.644 | 0.471 | 0.776 | 0.39 | 0.511 | 0.39 | 0.588 |
| ens_rmse_log_perc75_S1 | smearing | DCHN | 57 | 0.718 | 0.547 | 0.826 | 0.182 | 0.443 | 0.182 | 0.783 |
| ens_rmse_log_perc75_S1 | smearing | GJGR | 55 | 0.775 | 0.584 | 0.709 | -0.008 | 0.073 | -0.008 | 0.696 |
| ens_rmse_log_perc75_S1 | smearing | HP | 45 | 0.677 | 0.476 | 0.756 | 0.134 | 0.21 | 0.134 | 0.0 |
| ens_rmse_log_perc75_S1 | smearing | MGMR | 48 | 0.752 | 0.555 | 0.713 | -0.019 | 0.167 | -0.019 | 0.556 |
| ens_rmse_log_perc75_S1 | isotonic | CS | 51 | 0.826 | 0.593 | 0.632 | -4.586 | 0.432 | -4.586 | 0.667 |
| ens_rmse_log_perc75_S1 | isotonic | DCHN | 57 | 0.88 | 0.624 | 0.738 | 0.373 | 0.406 | 0.373 | 0.897 |
| ens_rmse_log_perc75_S1 | isotonic | GJGR | 55 | 0.904 | 0.668 | 0.604 | -0.985 | 0.083 | -0.985 | 0.722 |
| ens_rmse_log_perc75_S1 | isotonic | HP | 45 | 0.91 | 0.735 | 0.559 | 0.159 | 0.289 | 0.159 | 0.25 |
| ens_rmse_log_perc75_S1 | isotonic | MGMR | 48 | 0.882 | 0.672 | 0.605 | -1.192 | 0.197 | -1.192 | 0.692 |
| hurdle_rmse_log_perc75_S1 | none | CS | 51 | 0.651 | 0.469 | 0.771 | 0.429 | 0.473 | 0.429 | 0.588 |
| hurdle_rmse_log_perc75_S1 | none | DCHN | 57 | 0.706 | 0.566 | 0.832 | 0.192 | 0.52 | 0.192 | 0.833 |
| hurdle_rmse_log_perc75_S1 | none | GJGR | 55 | 0.772 | 0.586 | 0.711 | 0.017 | 0.081 | 0.017 | 0.609 |
| hurdle_rmse_log_perc75_S1 | none | HP | 45 | 0.697 | 0.533 | 0.742 | 0.197 | 0.21 | 0.197 | 0.0 |
| hurdle_rmse_log_perc75_S1 | none | MGMR | 48 | 0.702 | 0.531 | 0.749 | 0.156 | 0.229 | 0.156 | 0.7 |
| hurdle_rmse_log_perc75_S1 | smearing | CS | 51 | 0.651 | 0.469 | 0.771 | 0.429 | 0.473 | 0.429 | 0.588 |
| hurdle_rmse_log_perc75_S1 | smearing | DCHN | 57 | 0.706 | 0.566 | 0.832 | 0.192 | 0.52 | 0.192 | 0.833 |
| hurdle_rmse_log_perc75_S1 | smearing | GJGR | 55 | 0.772 | 0.586 | 0.711 | 0.017 | 0.081 | 0.017 | 0.609 |
| hurdle_rmse_log_perc75_S1 | smearing | HP | 45 | 0.697 | 0.533 | 0.742 | 0.197 | 0.21 | 0.197 | 0.0 |
| hurdle_rmse_log_perc75_S1 | smearing | MGMR | 48 | 0.702 | 0.531 | 0.749 | 0.156 | 0.229 | 0.156 | 0.7 |
| hurdle_rmse_log_perc75_S1 | isotonic | CS | 51 | 0.831 | 0.592 | 0.627 | -4.845 | 0.384 | -4.845 | 0.6 |
| hurdle_rmse_log_perc75_S1 | isotonic | DCHN | 57 | 0.877 | 0.648 | 0.74 | 0.458 | 0.459 | 0.458 | 0.857 |
| hurdle_rmse_log_perc75_S1 | isotonic | GJGR | 55 | 0.89 | 0.642 | 0.616 | -1.036 | 0.075 | -1.036 | 0.786 |
| hurdle_rmse_log_perc75_S1 | isotonic | HP | 45 | 0.902 | 0.719 | 0.567 | -0.785 | 0.077 | -0.785 | 0.0 |
| hurdle_rmse_log_perc75_S1 | isotonic | MGMR | 48 | 0.891 | 0.671 | 0.596 | -1.048 | 0.253 | -1.048 | 0.727 |
| log_w_composite_perc75_S1 | none | CS | 51 | 0.685 | 0.51 | 0.747 | 0.377 | 0.477 | 0.377 | 0.588 |
| log_w_composite_perc75_S1 | none | DCHN | 57 | 0.72 | 0.568 | 0.825 | 0.167 | 0.503 | 0.167 | 0.727 |
| log_w_composite_perc75_S1 | none | GJGR | 55 | 0.799 | 0.589 | 0.691 | -0.038 | 0.06 | -0.038 | 0.571 |
| log_w_composite_perc75_S1 | none | HP | 45 | 0.676 | 0.5 | 0.757 | 0.082 | 0.224 | 0.082 | 0.0 |
| log_w_composite_perc75_S1 | none | MGMR | 48 | 0.71 | 0.521 | 0.743 | 0.139 | 0.2 | 0.139 | 0.588 |
| log_w_composite_perc75_S1 | smearing | CS | 51 | 0.68 | 0.489 | 0.751 | -0.3 | 0.477 | -0.3 | 0.588 |
| log_w_composite_perc75_S1 | smearing | DCHN | 57 | 0.696 | 0.502 | 0.836 | 0.294 | 0.503 | 0.294 | 0.846 |
| log_w_composite_perc75_S1 | smearing | GJGR | 55 | 0.802 | 0.585 | 0.688 | -0.178 | 0.06 | -0.178 | 0.64 |
| log_w_composite_perc75_S1 | smearing | HP | 45 | 0.668 | 0.491 | 0.762 | 0.159 | 0.224 | 0.159 | 0.0 |
| log_w_composite_perc75_S1 | smearing | MGMR | 48 | 0.699 | 0.522 | 0.752 | -0.1 | 0.2 | -0.1 | 0.632 |
| log_w_composite_perc75_S1 | isotonic | CS | 51 | 0.815 | 0.592 | 0.642 | -4.296 | 0.423 | -4.296 | 0.609 |
| log_w_composite_perc75_S1 | isotonic | DCHN | 57 | 0.907 | 0.634 | 0.722 | 0.394 | 0.401 | 0.394 | 0.857 |
| log_w_composite_perc75_S1 | isotonic | GJGR | 55 | 0.885 | 0.657 | 0.62 | -1.249 | 0.067 | -1.249 | 0.733 |
| log_w_composite_perc75_S1 | isotonic | HP | 45 | 0.879 | 0.696 | 0.588 | 0.161 | 0.17 | 0.161 | 0.0 |
| log_w_composite_perc75_S1 | isotonic | MGMR | 48 | 0.844 | 0.63 | 0.638 | -1.243 | 0.157 | -1.243 | 0.75 |
| log_w_rmse_log_perc75_S1 | none | CS | 51 | 0.674 | 0.501 | 0.755 | 0.194 | 0.458 | 0.194 | 0.588 |
| log_w_rmse_log_perc75_S1 | none | DCHN | 57 | 0.731 | 0.569 | 0.819 | 0.155 | 0.35 | 0.155 | 0.8 |
| log_w_rmse_log_perc75_S1 | none | GJGR | 55 | 0.781 | 0.58 | 0.705 | -0.059 | 0.068 | -0.059 | 0.696 |
| log_w_rmse_log_perc75_S1 | none | HP | 45 | 0.686 | 0.507 | 0.749 | 0.096 | 0.18 | 0.096 | 0.0 |
| log_w_rmse_log_perc75_S1 | none | MGMR | 48 | 0.739 | 0.553 | 0.722 | 0.068 | 0.184 | 0.068 | 0.588 |
| log_w_rmse_log_perc75_S1 | smearing | CS | 51 | 0.67 | 0.495 | 0.758 | 0.069 | 0.458 | 0.069 | 0.588 |
| log_w_rmse_log_perc75_S1 | smearing | DCHN | 57 | 0.725 | 0.556 | 0.822 | 0.175 | 0.35 | 0.175 | 0.8 |
| log_w_rmse_log_perc75_S1 | smearing | GJGR | 55 | 0.781 | 0.576 | 0.705 | -0.086 | 0.068 | -0.086 | 0.75 |
| log_w_rmse_log_perc75_S1 | smearing | HP | 45 | 0.685 | 0.505 | 0.75 | 0.109 | 0.18 | 0.109 | 0.0 |
| log_w_rmse_log_perc75_S1 | smearing | MGMR | 48 | 0.735 | 0.55 | 0.726 | 0.028 | 0.184 | 0.028 | 0.588 |
| log_w_rmse_log_perc75_S1 | isotonic | CS | 51 | 0.848 | 0.617 | 0.612 | -4.496 | 0.427 | -4.496 | 0.583 |
| log_w_rmse_log_perc75_S1 | isotonic | DCHN | 57 | 0.9 | 0.639 | 0.726 | 0.306 | 0.323 | 0.306 | 0.815 |
| log_w_rmse_log_perc75_S1 | isotonic | GJGR | 55 | 0.923 | 0.669 | 0.587 | -1.01 | 0.1 | -1.01 | 0.722 |
| log_w_rmse_log_perc75_S1 | isotonic | HP | 45 | 0.907 | 0.717 | 0.562 | -0.227 | 0.071 | -0.227 | 0.0 |
| log_w_rmse_log_perc75_S1 | isotonic | MGMR | 48 | 0.855 | 0.642 | 0.628 | -0.861 | 0.235 | -0.861 | 0.667 |
| tweedie_composite_perc75_S1 | none | CS | 51 | 0.639 | 0.478 | 0.78 | 0.379 | 0.493 | 0.379 | 0.625 |
| tweedie_composite_perc75_S1 | none | DCHN | 57 | 0.724 | 0.551 | 0.823 | 0.221 | 0.547 | 0.221 | 0.783 |
| tweedie_composite_perc75_S1 | none | GJGR | 55 | 0.816 | 0.601 | 0.677 | -0.031 | 0.061 | -0.031 | 0.5 |
| tweedie_composite_perc75_S1 | none | HP | 45 | 0.705 | 0.533 | 0.736 | 0.1 | 0.157 | 0.1 | 0.0 |
| tweedie_composite_perc75_S1 | none | MGMR | 48 | 0.761 | 0.559 | 0.705 | 0.075 | 0.19 | 0.075 | 0.632 |
| tweedie_composite_perc75_S1 | smearing | CS | 51 | 0.639 | 0.478 | 0.78 | 0.379 | 0.493 | 0.379 | 0.625 |
| tweedie_composite_perc75_S1 | smearing | DCHN | 57 | 0.724 | 0.551 | 0.823 | 0.221 | 0.547 | 0.221 | 0.783 |
| tweedie_composite_perc75_S1 | smearing | GJGR | 55 | 0.816 | 0.601 | 0.677 | -0.031 | 0.061 | -0.031 | 0.5 |
| tweedie_composite_perc75_S1 | smearing | HP | 45 | 0.705 | 0.533 | 0.736 | 0.1 | 0.157 | 0.1 | 0.0 |
| tweedie_composite_perc75_S1 | smearing | MGMR | 48 | 0.761 | 0.559 | 0.705 | 0.075 | 0.19 | 0.075 | 0.632 |
| tweedie_composite_perc75_S1 | isotonic | CS | 51 | 0.639 | 0.478 | 0.78 | 0.379 | 0.493 | 0.379 | 0.625 |
| tweedie_composite_perc75_S1 | isotonic | DCHN | 57 | 0.724 | 0.551 | 0.823 | 0.221 | 0.547 | 0.221 | 0.783 |
| tweedie_composite_perc75_S1 | isotonic | GJGR | 55 | 0.816 | 0.601 | 0.677 | -0.031 | 0.061 | -0.031 | 0.5 |
| tweedie_composite_perc75_S1 | isotonic | HP | 45 | 0.705 | 0.533 | 0.736 | 0.1 | 0.157 | 0.1 | 0.0 |
| tweedie_composite_perc75_S1 | isotonic | MGMR | 48 | 0.761 | 0.559 | 0.705 | 0.075 | 0.19 | 0.075 | 0.632 |
| tweedie_rmse_log_perc75_S1 | none | CS | 51 | 0.636 | 0.461 | 0.782 | 0.191 | 0.511 | 0.191 | 0.625 |
| tweedie_rmse_log_perc75_S1 | none | DCHN | 57 | 0.719 | 0.541 | 0.825 | 0.193 | 0.518 | 0.193 | 0.783 |
| tweedie_rmse_log_perc75_S1 | none | GJGR | 55 | 0.816 | 0.6 | 0.677 | 0.008 | 0.08 | 0.008 | 0.696 |
| tweedie_rmse_log_perc75_S1 | none | HP | 45 | 0.698 | 0.501 | 0.741 | 0.172 | 0.293 | 0.172 | 0.0 |
| tweedie_rmse_log_perc75_S1 | none | MGMR | 48 | 0.744 | 0.538 | 0.718 | -0.03 | 0.131 | -0.03 | 0.632 |
| tweedie_rmse_log_perc75_S1 | smearing | CS | 51 | 0.636 | 0.461 | 0.782 | 0.191 | 0.511 | 0.191 | 0.625 |
| tweedie_rmse_log_perc75_S1 | smearing | DCHN | 57 | 0.719 | 0.541 | 0.825 | 0.193 | 0.518 | 0.193 | 0.783 |
| tweedie_rmse_log_perc75_S1 | smearing | GJGR | 55 | 0.816 | 0.6 | 0.677 | 0.008 | 0.08 | 0.008 | 0.696 |
| tweedie_rmse_log_perc75_S1 | smearing | HP | 45 | 0.698 | 0.501 | 0.741 | 0.172 | 0.293 | 0.172 | 0.0 |
| tweedie_rmse_log_perc75_S1 | smearing | MGMR | 48 | 0.744 | 0.538 | 0.718 | -0.03 | 0.131 | -0.03 | 0.632 |
| tweedie_rmse_log_perc75_S1 | isotonic | CS | 51 | 0.636 | 0.461 | 0.782 | 0.191 | 0.511 | 0.191 | 0.625 |
| tweedie_rmse_log_perc75_S1 | isotonic | DCHN | 57 | 0.719 | 0.541 | 0.825 | 0.193 | 0.518 | 0.193 | 0.783 |
| tweedie_rmse_log_perc75_S1 | isotonic | GJGR | 55 | 0.816 | 0.6 | 0.677 | 0.008 | 0.08 | 0.008 | 0.696 |
| tweedie_rmse_log_perc75_S1 | isotonic | HP | 45 | 0.698 | 0.501 | 0.741 | 0.172 | 0.293 | 0.172 | 0.0 |
| tweedie_rmse_log_perc75_S1 | isotonic | MGMR | 48 | 0.744 | 0.538 | 0.718 | -0.03 | 0.131 | -0.03 | 0.632 |
