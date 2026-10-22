# 모델 동결 v2 (FROZEN_v2) — 운영 모델 C

- 동결 커밋: `9dca86ccb236625e3decba6fcf49442c071d51d1` (이 커밋 이후 v2 모델·가중치·피처·운영점을 변경하지 않는다). Release `model-frozen-v2-9dca86c`(자산 models-frozen-v2-9dca86c.tar.gz)
- 동결 시각(KST): 2026-10-22 16:27:48
- 근거: 사전등록 확인 실험 EXP-confirm 통과(reports/experiments/EXP-confirm/RESULT.md),
  설계·동등성 reports/v2/BUILD.md. 원단위 고도화 2차(EXP-005) 최종 판정 기준 미충족·P3(단기예보 격자) 미통과로
  C 를 그대로 동결한다(reports/experiments/EXP-005/EXP-summary2.md, P3/RESULT.md)
- 운영점: {"prob_source": "clf_b", "cost_ratio": 3, "threshold": 0.52}; 임계 {"clf_a": 0.6399999999999999, "clf_b": 0.83, "stack_a": 0.8999999999999999, "stack_b": 0.8999999999999999};
  CQR {"alpha": 0.2, "qhat_log10": 0.1574868459595269, "n_calib": 531, "calib_years": [2023, 2024]} (config/model.yaml, v1 동결값 그대로)
- 구성: 회귀 = v1 로그 앙상블(c1 C1 smearing·c3 C3 hurdle·c2 C2 tweedie, v1 하이퍼파라미터) + 속별 구성원 cg
  (G2 = Microcystis + 나머지 3속, 부분별 log 회귀(C1 설정)·smearing), 결합 = log10 공간 NNLS(합=1)
- 피처 35개 = v1 선택 30(perc75, 결측 전략 S1)
  + 상류 5(up1_cell_log, up1_slope3, up1_wtemp, up1_days, up1_diff;
  lag 0, 상류 1단계, 해평·회남 NaN). 모든 구성원이 같은 열을 쓴다.
- 결합 가중치(2020~2024 연도 확장 CV OOF, 시드 42): c1 0.000000, c3 0.266051, c2 0.373269, cg 0.360680
- 학습 범위: 기준일 ≤ 2025-12-31 이면서 목표일 ≤ 2025-12-31 인 학습·검증 행 전체 — 2,562행,
  기준일 2012-04-02 ~ 2025-12-22,
  목표일 ≤ 2025-12-29. 지점별 {"CS": 553, "DCHN": 724, "GJGR": 513, "HP": 475, "MGMR": 297}
- 시드: 42 (config/seed.yaml)
- 2025 홀드아웃(학습 ≤2024 → 2025, 같은 가중치): {"rmse_log": 0.7102, "r2_log": 0.7794, "r2_raw": 0.1755, "r2_pearson_raw": 0.2108, "nse_raw": 0.1755, "f1_10k": 0.7045}
- 분류기·분위·CQR·운영점: v1 동결본 그대로
  (아래 classifier·quantile 버전, config/model.yaml cqr·operating_point).
  v1 동결 문서 models/FROZEN.md 와 v1 회귀 파일은 보존한다(v1 제출본 사본 dist/v1/submission_v1.csv).
- submission.csv(v2): 124행, sha256 `0c77ac8efd3142bbb386e791b3109ca3506eb7b99730490310ed5fe9d133c3b6`

| name | version | sha256(model.pkl) | bytes | features_hash | 비고 |
|---|---|---|---|---|---|
| regression | 20261022_162747 | `d696f6933eff04130f722a52cda614f1f0cf091a06cf518b67acd18b2b1f34e2` | 20,430,437 | a3076b49cfc7 | ensemble_v2(c1·c3·c2·cg, 피처 35) |
| classifier | 20261021_091109 | `81e913ad85a2ec586738c33c1f2d24ecc45d92993e1f4f567d96b27ba46f5c63` | 1,658,726 | 5bdc74f7c30d | v1 동결본(분류기 b) |
| quantile | 20261021_091110 | `3b26c445d5b728233e94015d58b52ef32f7f8a811777f015d6f37cb013f48478` | 7,947,776 | 5bdc74f7c30d | v1 동결본(q10·q50·q90) |

검증: `python scripts/verify_frozen.py` 가 models/FROZEN.md(v1)와 이 문서의 해시를 현재 파일과 대조하고,
registry current 가 이 문서의 버전과 같은지 확인한다.
