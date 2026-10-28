/**
 * 헤드라인 숫자 — 단일 원천. 빌드 전에 scripts/check_numbers.mjs 가 reports 원천 표와 대조해 다르면 빌드를 멈춘다.
 * 제출·운영 모델 = T24(2026-10-28 전환, models/FROZEN_T24.md): 운영사무국 답변 '학습은 24년까지'에 따라 사전등록 규칙대로
 * v2.1(데이터 유래 상수 누수 수정판) 구성을 대회 공식 학습 분할(split=train, 2024년까지)로만 학습한 모델. v2.1(최종 ≤2025)은
 * 2026-10-23~28 제출·운영 이력, v1(2026-10-21 봉인)·v2(2026-10-22 고정)는 수정 전 이력.
 * 리드타임 기준: 첫 경계(1만 개/mL) 초과 측정일(E). 2020~2025 = tbl_leadtime.md(v2.1 구성 OOF = T24 와 같음, q90≥임계),
 * 2026 = reports/experiments/contingency_T24/tbl_holdout_2026_posthoc_T24.md(T24, 감시 q90_cqr≥임계).
 * 지표 값은 reports/eval/headline_metrics.json 의 전체 정밀도 값에서 한 번만 반올림한 값이다(이중 반올림 금지).
 * 2025 = 같은 252행(T24 의 홀드아웃 = v2.1 Final 폴드, tbl_holdout_2025_v21.json), 2026 = test 124조합(T24 동결 뒤 1회 사후 계산, 블라인드 아님).
 */
export const NUMBERS = {
  events: { total: 28, detected: 24, medianLeadDays: 14, persistenceDetected: 3 },
  y2026: { total: 8, detected: 7, medianLeadDays: 21, persistenceDetected: 2 },
  prior: { total: 20, detected: 17, medianLeadDays: 14, persistenceDetected: 1 },
  r2log: { y2025: 0.78, y2026: 0.5 },
  f1_10k: { y2025: 0.7, y2026: 0.82, persistence2025: 0.73, persistence2026: 0.84 },
  r2raw: { y2025: 0.18, y2026: 0 },
  nseraw: { y2025: 0.18, y2026: 0 },
  picp80: { y2025: 0.85, y2026: 0.72 },
} as const;

/**
 * 모델. t24 = 제출·운영(models/FROZEN_T24.md, 2026-10-28 전환, 가중치·구성 = v2.1). v21 = 2026-10-23~28 제출·운영 이력
 * (models/FROZEN_v2.1.md). v1·v2 = 수정 전 이력(models/FROZEN.md·FROZEN_v2.md). 시각은 KST "YYYY-MM-DD HH:MM".
 */
export const MODELS = {
  t24meta: { commit: "a961caf", frozenKST: "2026-10-26 13:17", features: 35, upstreamFeatures: 5, trainRows: 2310 },
  t24weights: { c1: 0.055, c3: 0.28, c2: 0.267, cg: 0.398 },
  v21meta: { commit: "217260e", frozenKST: "2026-10-23 12:08", features: 35, upstreamFeatures: 5 },
  v21weights: { c1: 0.055, c3: 0.28, c2: 0.267, cg: 0.398 },
  v1meta: { commit: "13ac483", sealedKST: "2026-10-21 09:44", features: 30 },
  v2meta: { commit: "9dca86c", frozenKST: "2026-10-22 16:27", features: 35, upstreamFeatures: 5 },
} as const;

/**
 * T24(제출·운영)와 수정 전 모델(v2·v1) 나란히. v21 = v2.1(최종 ≤2025, 이력), v1fix = v1 구성을 수정 피처로 다시 적합한
 * 회귀(민감도 보고용, 감시·경보는 v2.1 분류기·분위). 2025 = 같은 252행(tbl_holdout_2025_v21.md — T24 는 v2.1 Final 폴드라 값이 같음,
 * v2·v1 값은 수정 전 계산 그대로). 2026 = contingency_T24/tbl_holdout_2026_posthoc_T24.md(T24·v2.1)·tbl_holdout_2026_posthoc_v21.md(v2·v1·v1-fix).
 */
export const CMP = {
  h25t24: { n: 252, rmselog: 0.71, r2log: 0.78, r2raw: 0.18, nseraw: 0.18, f1_10k: 0.7 },
  h25v21: { n: 252, rmselog: 0.71, r2log: 0.78, r2raw: 0.18, nseraw: 0.18, f1_10k: 0.7 },
  h25v2: { n: 252, rmselog: 0.71, r2log: 0.78, r2raw: 0.18, nseraw: 0.18, f1_10k: 0.7 },
  h25v1: { n: 252, rmselog: 0.71, r2log: 0.78, r2raw: 0.16, nseraw: 0.16, f1_10k: 0.68 },
  h25v1fix: { n: 252, rmselog: 0.71, r2log: 0.78, r2raw: 0.17, nseraw: 0.17, f1_10k: 0.67 },
  h25b0: { n: 252, rmselog: 0.9, r2log: 0.65, r2raw: -0.28, nseraw: -0.28, f1_10k: 0.73 },
  cvR2raw: { t24: 0.29, v21: 0.29, v2: 0.29, v1: 0.17, v1fix: 0.19, b0: 0 },
  p26t24: { n: 124, rmselog: 0.73, r2log: 0.5, r2raw: 0, nseraw: 0, f1_10k: 0.82 },
  p26v21: { n: 124, rmselog: 0.72, r2log: 0.52, r2raw: 0, nseraw: 0, f1_10k: 0.83 },
  p26v2: { n: 124, rmselog: 0.72, r2log: 0.52, r2raw: -0.01, nseraw: -0.01, f1_10k: 0.82 },
  p26v1: { n: 124, rmselog: 0.74, r2log: 0.49, r2raw: -0.05, nseraw: -0.05, f1_10k: 0.7 },
  p26v1fix: { n: 124, rmselog: 0.73, r2log: 0.5, r2raw: -0.03, nseraw: -0.03, f1_10k: 0.76 },
  p26b0: { n: 124, rmselog: 0.9, r2log: 0.24, r2raw: -0.3, nseraw: -0.3, f1_10k: 0.84 },
  /** 2026 경계 사건 8건 — 점예측이 1만 이상을 미리 낸 사건 수, 감시 단계 선행 탐지 */
  p26point: { total: 8, t24: 4, v21: 5, v2: 5, v1: 2, v1fix: 2, persistence: 2 },
  p26watch: { total: 8, t24: 7, v21: 7, v2: 7, v1: 7, medianLeadT24: 21, medianLeadV21: 21, medianLeadV2: 21, medianLeadV1: 21 },
  /** 2020~2025 경계 사건 20건 감시 포착 — v2.1 구성 OOF(수정 피처, T24 와 같음) */
  priorWatch: { total: 20, t24: 17, v21: 17 },
} as const;

export const HEADLINE = `2024년까지 자료로만 학습한 모델(T24, 대회 공식 학습 분할)로 2026년 경계 사건 ${NUMBERS.y2026.total}건 중 ${NUMBERS.y2026.detected}건을 중앙 ${NUMBERS.y2026.medianLeadDays}일 앞서 감시 단계로 포착(지속성 ${NUMBERS.y2026.persistenceDetected}건). 2020~2026 합계 ${NUMBERS.events.total}건 중 ${NUMBERS.events.detected}건(${Math.round((NUMBERS.events.detected / NUMBERS.events.total) * 100)}%, 중앙 ${NUMBERS.events.medianLeadDays}일 앞서), 지속성 ${NUMBERS.events.persistenceDetected}건.`;

/** 운영점 — 분류기(b) 넘을 가능성이 이 값 이상이면 '대응 필요'(놓침:헛경보 비용비 3, CV 기대비용 최소). check_numbers 가 config/model.yaml 과 대조 */
export const OPERATING_POINT = { threshold: 0.46, costRatio: 3 } as const;
export const OP_PCT = Math.round(OPERATING_POINT.threshold * 100);
