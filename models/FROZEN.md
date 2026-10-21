# 모델 동결 (FROZEN) — 2026 사후 검증 전 고정

- 동결 커밋: `13ac4832f5ff641c42c766da20c2f983b3c7915c` (이 커밋 이후 모델·임계·피처·운영점을 변경하지 않는다)
- 피처 세트: config/features.yaml selected (perc75, 30개), 결측 전략 S1
- 운영점: {"prob_source": "clf_b", "cost_ratio": 3, "threshold": 0.52}; 임계 {"clf_a": 0.6399999999999999, "clf_b": 0.83, "stack_a": 0.8999999999999999, "stack_b": 0.8999999999999999}; CQR {"alpha": 0.2, "qhat_log10": 0.1574868459595269, "n_calib": 531, "calib_years": [2023, 2024]}

| name | version | sha256(model.pkl) | bytes | features_hash | holdout 2025 |
|---|---|---|---|---|---|
| regression | 20261021_091108 | `dc45d72bb878e863d0680a750859956e12d3a161978087d7d74bcbb9f32d9403` | 15,402,662 | 5bdc74f7c30d | {"rmse_log": 0.7079, "r2_log": 0.7802, "r2_raw": 0.1658, "r2_pearson_raw": 0.1938, "nse_raw": 0.1658, "f1_10k": 0.6824} |
| classifier | 20261021_091109 | `81e913ad85a2ec586738c33c1f2d24ecc45d92993e1f4f567d96b27ba46f5c63` | 1,658,726 | 5bdc74f7c30d | {"pr_auc": 0.8034, "brier": 0.0828, "f1": 0.6947, "thr": 0.83} |
| quantile | 20261021_091110 | `3b26c445d5b728233e94015d58b52ef32f7f8a811777f015d6f37cb013f48478` | 7,947,776 | 5bdc74f7c30d | {"picp80": 0.6602, "mpiw80_log": 1.3752} |

검증: `python scripts/verify_frozen.py` 가 위 해시와 현재 파일을 대조한다.
