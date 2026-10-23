# 모델 동결 v2.1 (FROZEN_v2.1) — 데이터 유래 상수 누수 수정판(운영·제출 모델)

- 동결 커밋: `커밋 후 기입` (이 커밋 이후 v2.1 모델·가중치·피처·운영점을 변경하지 않는다)
- 동결 시각(KST): 2026-10-23 12:08:19
- 수정 사유: 2026-10-23 참가자 지시로 데이터로 계산한 상수를 전수 점검한 결과, 수위 편차의 관측소 평균(2010~2026-10-20 전 기간),
  지점별 관심 도달 수온 임계(2026 세포수 포함 전 기간 LOESS), ASOS 관측소 선정(2026 수온 포함)이 기준일 이후 자료를 쓰고 있었고,
  보현산댐(2012607) 2025년 이후 수위가 다른 계열이었다. "기준일 이후 관측값 사용 금지" 규칙 위반이므로 사전등록
  (reports/experiments/FIX-v2.1/PREREG.md) 규칙대로 고쳤다. v2.1 은 결과와 무관하게 채택한다.
- 수정 규칙: R1 수위 편차 = 관측소별 직전 365일 평균 대비(as-of, 유효 ≥180일) · R2 wamis_ok:false 관측소 2025~ 결측 ·
  R3 수온 임계 = 학습기간 측정만(CV 폴드 V → ≤V−1, 2025 홀드아웃 → ≤2024, 최종 → ≤2025) ·
  R4 선택 결정 ≤2024 재계산(ASOS 물금·매리 257 → 288, 나머지 동일) · R5 피처 목록·하이퍼파라미터·구성원·운영점 규칙·CQR 절차 v2 와 동일 ·
  R6 데이터 적합 부분 전부 재적합(회귀 구성원·NNLS·smearing·분류기 b·분위·운영점·CQR)
- 최종 모델 수온 임계(측정 ≤2025, config/derived_constants.json): {"HP": 25.8, "GJGR": 24.0, "CS": 23.3, "MGMR": 22.8, "DCHN": 20.7}
- 운영점: {"prob_source": "clf_b", "cost_ratio": 3, "threshold": 0.46}; 임계 {"clf_a": 0.58, "clf_b": 0.8699999999999999, "stack_a": 0.8799999999999999, "stack_b": 0.8699999999999999};
  CQR {"alpha": 0.2, "qhat_log10": 0.1645788180704682, "n_calib": 531, "calib_years": [2023, 2024]} (config/model.yaml, 수정 피처 OOF 로 같은 절차 재산정)
- 구성: 회귀 = c1 C1 smearing·c3 C3 hurdle·c2 C2 tweedie(v1 하이퍼파라미터) + 속별 구성원 cg(G2), 결합 = log10 공간 NNLS(합=1)
- 피처 35개 = v1 선택 30(perc75, 결측 전략 S1) + 상류 5(up1_cell_log, up1_slope3, up1_wtemp, up1_days, up1_diff)
- 결합 가중치(2020~2024 연도 확장 CV OOF, 폴드별 임계, 시드 42): c1 0.055309, c3 0.279862, c2 0.266994, cg 0.397835
- 학습 범위: 기준일 ≤ 2025-12-31 이면서 목표일 ≤ 2025-12-31 인 학습·검증 행 전체 — 2,562행, 기준일 2012-04-02 ~ 2025-12-22,
  목표일 ≤ 2025-12-29. 지점별 {"CS": 553, "DCHN": 724, "GJGR": 513, "HP": 475, "MGMR": 297}
- 시드: 42 (config/seed.yaml)
- 2025 홀드아웃(학습 ≤2024 → 2025, 같은 가중치): {"rmse_log": 0.712, "r2_log": 0.7783, "r2_raw": 0.1754, "r2_pearson_raw": 0.2041, "nse_raw": 0.1754, "f1_10k": 0.7045}
- CV 평균(2020~2024): {"rmse_log": 0.7917, "r2_log": 0.6888, "r2_raw": 0.2486, "r2_pearson_raw": 0.3537, "nse_raw": 0.2486, "f1_10k": 0.5977}
- submission.csv(v2.1): 124행, sha256 `4741a3d37ef3ae9f71b381e083028d93e83ec378ae5d5a65beba2ed48545a8e7`.
  v2 제출본 보존 dist/v2/submission_v2.csv(FROZEN_v2.md 그대로), v2 대비 |Δlog10| 중앙 0.0507·최대 0.1927
- v1(FROZEN.md)·v2(FROZEN_v2.md) 동결 문서와 모델 파일은 이력으로 보존한다.

| name | version | sha256(model.pkl) | bytes | features_hash | 비고 |
|---|---|---|---|---|---|
| regression | 20261023_120818 | `d95e7a4e8dab50a59583dd8ecf8ab2482786ec05f7bfa1f256c657bec3a091f0` | 20,414,068 | a3076b49cfc7 | ensemble_v2(c1·c3·c2·cg, 피처 35) — v2.1 |
| classifier | 20261023_120255 | `cce848b6c1b5d1608d73403d5ef089bf8e4dc04bdc358eea8afd7fcb3ae1c77d` | 1,653,681 | 5bdc74f7c30d | v2.1 재적합(분류기 b, 수정 피처) |
| quantile | 20261023_120257 | `9b52945aa53e2af2a0189eb8368389410eabd001a6336620684baaca07258bee` | 7,926,563 | 5bdc74f7c30d | v2.1 재적합(q10·q50·q90, 수정 피처) |
| regression | 20261023_120255 | `4e341732fe4d9ba48be768a570dd9836b0050d9233a29d5cc924dbe87d4dfed7` | 15,371,621 | 5bdc74f7c30d | v1-fix(c1·c3·c2, 피처 30) — 민감도 보고용, current 아님 |

검증: `python scripts/verify_frozen.py` 가 FROZEN.md·FROZEN_v2.md·이 문서의 해시를 현재 파일과 대조하고,
registry current 가 이 문서의 버전과 같은지 확인한다.
