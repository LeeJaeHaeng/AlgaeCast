/**
 * 헤드라인 숫자 — 단일 원천. 빌드 전에 scripts/check_numbers.mjs 가 reports/eval 표와 대조해 다르면 빌드를 멈춘다.
 * 리드타임 기준: 첫 경계(1만 개/mL) 초과 측정일(E). 2020~2025 = tbl_leadtime.md(q90≥임계), 2026 = tbl_holdout_2026_posthoc.md(감시 q90_cqr≥임계).
 * NUMBERS 의 점예측 지표(r2log·f1_10k·r2raw·nseraw)는 v1(블라인드 검증) 공개 원천 그대로다(2025 = tbl_holdout_2025.md 256행).
 * 지표 값은 reports/eval/headline_metrics.json 의 전체 정밀도 값에서 한 번만 반올림한 값이다(2026-10-22 정정: 0.7049·0.7045 를
 * 셋째 자리 0.705 로 거쳐 0.71 로 쓰던 이중 반올림을 0.70 으로 고침).
 * 감시·경보(리드타임)와 예상 범위 적중률(picp80)은 v1·v2 공통(분위·CQR·분류기는 v1 동결본).
 */
export const NUMBERS = {
  events: { total: 28, detected: 25, medianLeadDays: 14, persistenceDetected: 3 },
  y2026: { total: 8, detected: 7, medianLeadDays: 21, persistenceDetected: 2 },
  prior: { total: 20, detected: 18, medianLeadDays: 14, persistenceDetected: 1 },
  r2log: { y2025: 0.78, y2026: 0.49 },
  f1_10k: { y2025: 0.68, y2026: 0.7, persistence2025: 0.73, persistence2026: 0.84 },
  r2raw: { y2025: 0.17, y2026: -0.05 },
  nseraw: { y2025: 0.17, y2026: -0.05 },
  picp80: { y2025: 0.86, y2026: 0.69 },
} as const;

/**
 * 모델 두 가지. v1 = 블라인드 검증 모델(models/FROZEN.md, 봉인 뒤 2026 을 처음 계산),
 * v2 = 제출·운영 모델 = 최종 모델 C(models/FROZEN_v2.md): v1 로그 앙상블 + 상류 피처 5열 + 속별 구성원 cg, log 공간 결합 가중치.
 * 시각은 KST "YYYY-MM-DD HH:MM" (v1 = tbl_holdout_2026_posthoc_v2.md 머리글, v2 = FROZEN_v2.md 동결 시각).
 */
export const MODELS = {
  v1meta: { commit: "13ac483", sealedKST: "2026-10-21 09:44", features: 30 },
  v2meta: { commit: "9dca86c", frozenKST: "2026-10-22 16:27", features: 35, upstreamFeatures: 5 },
  v2weights: { c1: 0, c3: 0.266, c2: 0.373, cg: 0.361 },
} as const;

/**
 * v2(제출·운영) vs v1(블라인드 검증) 나란히 — 달라지는 것은 점예측(회귀)뿐이다.
 * 2025 = tbl_holdout_2025_v2.md 의 **같은 252행** 값(v1 공개 256행 값 NUMBERS 와 소수 둘째 자리에서 다를 수 있음 — 섞지 말 것).
 * 2026 = tbl_holdout_2026_posthoc_v2.md(test 124조합). v2 의 2026 값은 블라인드가 아니다(화면에 고지문 필수, copy.ts V2_NOTICE).
 */
export const V2CMP = {
  h25v2: { n: 252, rmselog: 0.71, r2log: 0.78, r2raw: 0.18, nseraw: 0.18, f1_10k: 0.7 },
  h25v1: { n: 252, rmselog: 0.71, r2log: 0.78, r2raw: 0.16, nseraw: 0.16, f1_10k: 0.68 },
  h25b0: { n: 252, rmselog: 0.9, r2log: 0.65, r2raw: -0.28, nseraw: -0.28, f1_10k: 0.73 },
  cvR2raw: { v2: 0.29, v1: 0.17, b0: 0 },
  p26v2: { n: 124, rmselog: 0.72, r2log: 0.52, r2raw: -0.01, nseraw: -0.01, f1_10k: 0.82 },
  p26v1: { n: 124, rmselog: 0.74, r2log: 0.49, r2raw: -0.05, nseraw: -0.05, f1_10k: 0.7 },
  p26b0: { n: 124, rmselog: 0.9, r2log: 0.24, r2raw: -0.3, nseraw: -0.3, f1_10k: 0.84 },
  /** 2026 경계 사건 8건 — 점예측이 1만 이상을 미리 낸 사건 수(달라짐), 감시 단계 선행 탐지(v1·v2 같음) */
  p26point: { total: 8, v2: 5, v1: 2, persistence: 2 },
  p26watch: { total: 8, v2: 7, v1: 7, medianLeadV2: 21, medianLeadV1: 21 },
} as const;

export const HEADLINE = `v1 동결 모델이 처음 보는 2026년 경계 사건 ${NUMBERS.y2026.total}건 중 ${NUMBERS.y2026.detected}건을 중앙 ${NUMBERS.y2026.medianLeadDays}일 앞서 감시 단계로 포착(지속성 ${NUMBERS.y2026.persistenceDetected}건). 2020~2026 합계 ${NUMBERS.events.total}건 중 ${NUMBERS.events.detected}건(${Math.round((NUMBERS.events.detected / NUMBERS.events.total) * 100)}%, 중앙 ${NUMBERS.events.medianLeadDays}일 앞서), 지속성 ${NUMBERS.events.persistenceDetected}건. 제출·운영 모델은 v2(커밋 ${MODELS.v2meta.commit})이며 감시·경보 결과는 v1과 같다.`;
