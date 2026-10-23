# EXP-002 T4-c 경보 분류·분위·앙상블 (2026-10-23)

## 설정
- features_S1, perc75 30개, 폴드 docs/04 §2, 시드 42. 분류 타깃 (a) target_date ≥10k / (b) +4~+10일 창 ≥10k.
- 분류기 Optuna 150 trial(PR-AUC), 임계 CV OOF F1 최대. 회귀 OOF: C1 채택 파라미터, C3/C2 각 스터디 best.

## 결과
- reports/eval/tbl_alert_classification.md, tbl_quantile.md, tbl_ensemble.md

## 채택
- 경보 규칙: (iii) 분류기+회귀 스태킹(로지스틱) (2025 F1 0.703 vs B0 0.727)
- 앙상블: 채택 (가중 {'회귀 C1(smearing)': 0.16884653677260708, '회귀 C3 hurdle': 0.44558720282980235, '회귀 C2 tweedie': 0.38556626039759045})
- registry current: {'regression': '20261023_120255', 'classifier': '20261023_120255', 'quantile': '20261023_120257'}
