/**
 * 헤드라인 숫자 — 단일 원천. 빌드 전에 scripts/check_numbers.mjs 가 reports/eval 표와 대조해 다르면 빌드를 멈춘다.
 * 리드타임 기준: 첫 경계(1만 개/mL) 초과 측정일(E). 2020~2025 = tbl_leadtime.md(q90≥임계), 2026 = tbl_holdout_2026_posthoc.md(감시 q90_cqr≥임계).
 */
export const NUMBERS = {
  events: { total: 28, detected: 25, medianLeadDays: 14, persistenceDetected: 3 },
  y2026: { total: 8, detected: 7, medianLeadDays: 21, persistenceDetected: 2 },
  prior: { total: 20, detected: 18, medianLeadDays: 14, persistenceDetected: 1 },
  r2log: { y2025: 0.78, y2026: 0.49 },
  f1_10k: { y2025: 0.68, y2026: 0.71, persistence2025: 0.73, persistence2026: 0.84 },
  r2raw: { y2025: 0.17, y2026: -0.05 },
  nseraw: { y2025: 0.17, y2026: -0.05 },
} as const;

export const HEADLINE = `동결 모델이 처음 보는 2026년 경계 사건 ${NUMBERS.y2026.total}건 중 ${NUMBERS.y2026.detected}건을 중앙 ${NUMBERS.y2026.medianLeadDays}일 앞서 감시 단계로 포착(지속성 ${NUMBERS.y2026.persistenceDetected}건). 2020~2026 합계 ${NUMBERS.events.total}건 중 ${NUMBERS.events.detected}건(${Math.round((NUMBERS.events.detected / NUMBERS.events.total) * 100)}%, 중앙 ${NUMBERS.events.medianLeadDays}일 앞서), 지속성 ${NUMBERS.events.persistenceDetected}건.`;
