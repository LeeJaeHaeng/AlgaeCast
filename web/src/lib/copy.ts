/**
 * 화면 문구 모음 (docs/12_CONTROL_ROOM_UI.md §7·§8). 컴포넌트에는 문자열을 직접 쓰지 않고 여기서 가져온다.
 * - 쉽게 보기(기본): 영어 약어·내부 변수명 금지, 모든 숫자에 단위·기준 표기, 단정 대신 "가능성·예상"
 * - 전문가 보기(?view=expert): 기존 지표·내부 명칭 병기 허용
 */

export type Tier = "normal" | "watch" | "alert";
export type FeatureGroup = "ar" | "water" | "hydro" | "weather" | "forecast" | "time_site";

/** 서비스 이름·내비게이션 (§5 페이지 이름) */
export const APP = {
  title: "녹조 통합관제 상황판",
  short: "녹조 상황판",
  subtitle: "7일 뒤 녹조를 미리 보는 취수원 관제",
  competition: "2026 DATA·AI 분석 경진대회 출품작",
  nav: [
    { href: "/", label: "메인 상황판" },
    { href: "/performance", label: "얼마나 잘 맞혔나" },
    { href: "/insights", label: "녹조 이야기" },
    { href: "/about", label: "이 시스템은" },
  ],
  footer: "데이터: 국립환경과학원 조류경보제 · 한국수자원공사 · 국가수자원관리종합정보시스템 · 기상청 (공공누리). 이 예상은 운영 참고용이며 공식 발령을 대체하지 않습니다.",
  // CARTO Dark Matter(docs/12) 는 2026-10 현재 API 키가 필요해 키 없이 쓰는 Esri Dark Gray Canvas 로 대체
  mapAttribution: 'Tiles &copy; <a href="https://www.esri.com/">Esri</a> — Esri, HERE, Garmin, &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
} as const;

/** §8 용어표 — 화면 표시어 + ⓘ 설명 */
export const TERMS = {
  cells: { label: "녹조 농도", unit: "개/mL", tip: "물 1mL에 들어 있는 유해남조류(독소를 낼 수 있는 녹조) 세포 수입니다." },
  level1: { label: "관심", tip: "녹조 농도 1,000개/mL 이상이 2회 연속 측정되면 공식 발령됩니다." },
  level2: { label: "경계", tip: "녹조 농도 10,000개/mL 이상이 2회 연속 측정되면 공식 발령됩니다. 정수장 고도처리가 필요한 수준입니다." },
  level3: { label: "대발생", tip: "녹조 농도 1,000,000개/mL 이상이 2회 연속 측정되면 공식 발령됩니다." },
  official: { label: "공식 발령", tip: "국립환경과학원 조류경보제가 실제 측정값으로 내린 단계입니다. 이 시스템의 예상과는 별개입니다." },
  tierSafe: { label: "안전", tip: "1주일 안에 경계 수준(10,000개/mL)을 넘을 가능성이 낮습니다." },
  tierWatch: { label: "주의 관찰", tip: "예상 범위의 위쪽 끝이 경계 수준(10,000개/mL)에 닿습니다. 채수를 늘리고 자주 확인해야 합니다." },
  tierAlert: { label: "대응 필요", tip: "1주일 안에 경계 수준을 넘을 가능성이 높습니다(가능성 52% 이상). 녹조제거설비 배치를 미리 준비해야 합니다." },
  q50: { label: "가장 가능성 높은 값", tip: "7일 뒤 녹조 농도로 가장 가능성이 높은 한 값입니다. 실제 값은 이보다 높거나 낮을 수 있습니다." },
  range: { label: "예상 범위", tip: "7일 뒤 녹조 농도가 10번 중 8번은 이 범위 안에 들어오도록 맞춘 구간입니다(2023~2024년 자료로 보정)." },
  pAlert: { label: "다음 주(4~10일 뒤) 측정에서 1만을 넘을 가능성", tip: "다음 주(4~10일 뒤) 측정 중 한 번이라도 녹조 농도가 1만 개/mL 이상일 가능성입니다. 가장 가능성 높은 값이 1만 아래여도 예상 범위 위쪽이 1만을 넘으면 넘을 가능성이 높게 나올 수 있습니다." },
  baseDate: { label: "기준일", tip: "예상을 만들 때 마지막으로 사용한 측정일입니다. 이 날 이후의 자료는 쓰지 않았습니다." },
  targetDate: { label: "7일 뒤", tip: "기준일로부터 7일 뒤, 예상의 대상이 되는 날입니다." },
  leadTime: { label: "미리 알린 기간", tip: "실제로 경계 수준을 처음 넘은 날보다 며칠 앞서 '주의 관찰' 이상으로 바뀌었는지입니다." },
  persistence: { label: "지난주 값 그대로 쓰는 방법", tip: "'다음 주도 이번 주와 같을 것'이라고 보는 가장 단순한 비교 기준입니다." },
  why: { label: "왜 이렇게 예상했나", tip: "예상값을 올리거나 내린 요인을 기여도가 큰 순서로 보여 줍니다." },
  frozen: { label: "고정된 모델", tip: "2026년 10월 20일에 학습을 멈추고 봉인한 모델입니다. 제출 전까지 다시 학습하지 않습니다." },
  trend: { label: "추세", tip: "가장 가능성 높은 값이 현재 측정값보다 높으면 ↑, 낮으면 ↓, 비슷하면 → 입니다(±20% 기준)." },
} as const;

/** 단계(2단계 운영 체계) 표시 — §6 색·아이콘 */
export const TIER: Record<Tier, { label: string; icon: string; color: string; action: string; term: keyof typeof TERMS }> = {
  normal: { label: "안전", icon: "●", color: "var(--safe)", action: "평소대로 관리", term: "tierSafe" },
  watch: { label: "주의 관찰", icon: "▲", color: "var(--watch)", action: "모니터링 강화·설비 준비 점검", term: "tierWatch" },
  alert: { label: "대응 필요", icon: "◆", color: "var(--alert)", action: "녹조제거설비 선제 배치 권고", term: "tierAlert" },
};
/** 전문가 보기에서 병기하는 내부 명칭 */
export const TIER_EXPERT: Record<Tier, string> = { normal: "normal", watch: "watch (q90 ≥ 1만)", alert: "alert (p ≥ 0.52)" };


/** 공식 발령(측정) × AI 예상 단계 조합 라벨 — 타일·조치·지도 범례·배너의 공통 체계 (docs/12 §8.4). rank 가 낮을수록 위 */
export type Combo = "enter" | "watch" | "persist" | "improve" | "safe";
export function comboOf(officialLevel: number | null | undefined, tier: Tier): Combo {
  const over = (officialLevel ?? 0) >= 2; // 공식 경계 이상
  if (!over) return tier === "alert" ? "enter" : tier === "watch" ? "watch" : "safe";
  return tier === "alert" ? "persist" : "improve";
}
export const COMBO: Record<Combo, { rank: number; label: string; bannerWord: string; icon: string; color: string; hex: string; tip: string; actions: string[]; reco: (site: string, pPct: number) => string }> = {
  enter: {
    rank: 1, label: "경계 진입 예상 — 미리 대비", bannerWord: "경계 진입 예상", icon: "◆", color: "var(--severe)", hex: "#EF4444",
    tip: "지금은 공식 경계가 아니지만, 다음 주 측정에서 1만 개/mL를 넘을 가능성이 높습니다. 가장 먼저 대비할 지점입니다.",
    actions: ["녹조제거설비 배치 위치·인력 확인하기", "정수장에 고도처리(분말활성탄·오존) 준비 요청하기", "취수구 수심 조정 가능 여부 확인하기"],
    reco: (site, p) => `${site}: 다음 주 측정에서 1만 개/mL를 넘을 가능성이 높습니다(${p}%). 녹조제거설비를 미리 배치하고, 정수장에 고도처리 준비를 요청하세요.`,
  },
  watch: {
    rank: 2, label: "지켜보기", bannerWord: "지켜보기", icon: "▲", color: "var(--watch)", hex: "#FACC15",
    tip: "공식 경계는 아니고, 예상 범위의 위쪽이 1만 개/mL에 닿습니다. 자주 확인해야 합니다.",
    actions: ["채수를 주 2회로 늘리기", "설비 가동 준비 상태 점검하기"],
    reco: (site) => `${site}: 경계 수준을 넘을 수도 있습니다. 채수를 주 2회로 늘리고 상황을 자주 확인하세요.`,
  },
  persist: {
    rank: 3, label: "경계 계속될 듯", bannerWord: "경계 계속", icon: "◆", color: "var(--alert)", hex: "#F97316",
    tip: "이미 공식 경계이고, 다음 주에도 1만 개/mL 이상이 이어질 가능성이 높습니다. 현재 대응을 유지합니다.",
    actions: ["설비 가동·고도처리 등 현재 대응 유지하기", "새 측정 결과 확인하고 관계 기관과 공유하기"],
    reco: (site, p) => `${site}: 경계가 다음 주에도 계속될 가능성이 높습니다(${p}%). 녹조제거설비 가동과 정수장 고도처리 등 현재 대응을 유지하세요.`,
  },
  improve: {
    rank: 4, label: "나아질 가능성 — 해제 준비", bannerWord: "나아질 가능성", icon: "▼", color: "var(--accent)", hex: "#38BDF8",
    tip: "지금은 공식 경계이지만, 다음 주에는 1만 개/mL 아래로 내려갈 가능성이 있습니다. 해제에 대비합니다.",
    actions: ["해제 판단에 대비해 채수 주기 유지하기", "설비 축소 시점 미리 검토하기"],
    reco: (site) => `${site}: 녹조가 줄어들 가능성이 있습니다. 해제 판단에 대비해 채수를 유지하고 상황을 확인하세요.`,
  },
  safe: {
    rank: 5, label: "안전", bannerWord: "안전", icon: "●", color: "var(--safe)", hex: "#22C55E",
    tip: "공식 경계가 아니고, 다음 주에 1만 개/mL를 넘을 가능성도 낮습니다.",
    actions: ["평소 일정대로 측정 결과 확인하기"],
    reco: (site) => `${site}: 1주일 안에 큰 변화는 없을 것으로 보입니다. 평소대로 관리하세요.`,
  },
};
export const COMBO_ORDER: Combo[] = ["enter", "watch", "persist", "improve", "safe"];

/** 공식 발령 단계(측정 기준) */
export const OFFICIAL_LEVEL: Record<number, { label: string; color: string }> = {
  0: { label: "발령 없음", color: "var(--text-dim)" },
  1: { label: "관심", color: "var(--watch)" },
  2: { label: "경계", color: "var(--alert)" },
  3: { label: "대발생", color: "var(--severe)" },
};

/** §8 피처 그룹 → 쉬운 이름 */
export const GROUP_LABEL: Record<FeatureGroup, string> = {
  ar: "최근 녹조 흐름",
  water: "물 온도",
  hydro: "물 흐름(댐·보 방류)",
  weather: "날씨(기온·비·바람)",
  forecast: "날씨 예보",
  time_site: "계절·지점 특성",
};

/** §8.1 근거 문장 템플릿 — 그룹별 기여 방향(+ 올림 / − 내림) */
export const REASON: Record<FeatureGroup, { up: string; down: string }> = {
  ar: { up: "최근 녹조가 이미 많습니다", down: "최근 녹조가 줄고 있습니다" },
  water: { up: "물 온도가 높은 날이 계속됐습니다", down: "물 온도가 내려가고 있습니다" },
  hydro: { up: "보·댐 방류가 적어 물이 고여 있습니다", down: "방류가 늘어 물이 잘 흐릅니다" },
  weather: { up: "한 달간 더웠고 비가 적었습니다", down: "비가 와서 녹조가 씻겨 나갈 수 있습니다" },
  forecast: { up: "앞으로 덥고 비가 적을 것으로 예보됐습니다", down: "앞으로 비가 올 것으로 예보됐습니다" },
  time_site: { up: "녹조가 많이 생기는 시기입니다", down: "녹조가 줄어드는 시기입니다" },
};
/** 물 온도 보조 문구: 25℃ 이상 n일 */
export const reasonWaterDays = (n: number) => `(25℃ 이상 ${n}일)`;

/** §8.2 권고 조치 템플릿 */
export const recommendation = (tier: Tier, site: string, pPct: number): string => {
  if (tier === "alert") return `${site}: 1주일 안에 경계 수준을 넘을 가능성이 높습니다(${pPct}%). 녹조제거설비를 미리 배치하고, 정수장에 고도처리 준비를 요청하세요.`;
  if (tier === "watch") return `${site}: 경계 수준을 넘을 수도 있습니다. 채수를 주 2회로 늘리고 상황을 자주 확인하세요.`;
  return `${site}: 1주일 안에 큰 변화는 없을 것으로 보입니다. 평소대로 관리하세요.`;
};

/** 오늘의 조치 체크리스트 항목(단계별, 동사로 끝남) */
export const ACTIONS: Record<Tier, string[]> = {
  alert: ["녹조제거설비 배치 위치·인력 확인하기", "정수장에 고도처리(분말활성탄·오존) 준비 요청하기", "취수구 수심 조정 가능 여부 확인하기"],
  watch: ["채수를 주 2회로 늘리기", "설비 가동 준비 상태 점검하기"],
  normal: ["평소 일정대로 측정 결과 확인하기"],
};

/** §8.3 상황 배너 템플릿 — 조합 순위 순으로 "{지점, 지점} {라벨}" 을 · 로 잇는다. 전부 안전이면 다음 갱신 시각 */
export const banner = (groups: { combo: Combo; sites: string[] }[], nextRefresh: string): string => {
  const live = groups.filter((g) => g.combo !== "safe" && g.sites.length);
  if (!live.length) return `전 지점 안전 · 다음 갱신 ${nextRefresh}`;
  return live.map((g) => `${g.sites.join(", ")} ${COMBO[g.combo].bannerWord}`).join(" · ");
};

/** 메인 상황판 문구 */
export const BOARD = {
  leds: { collect: "수집", predict: "예측", db: "저장소" },
  ledTip: { ok: "정상 (24시간 이내 갱신)", stale: "지연 (24시간 넘게 갱신 없음)", fail: "실패 (마지막 작업이 실패했습니다)", unknown: "확인 중" },
  lastRefresh: "마지막 갱신",
  nextRefresh: (min: number) => `화면 새로고침 ${min}분 뒤 · 데이터 갱신 매일 05:00`,
  autoRefresh: "5분마다 자동 갱신",
  btn: { fullscreen: "전체화면", exitFullscreen: "전체화면 끝내기", present: "발표모드", presentOff: "관제모드", kiosk: "순환", kioskOff: "순환 끝내기", easy: "쉽게 보기", expert: "전문가 보기" },
  counts: { alert: "대응 필요", watch: "주의 관찰", safe: "안전" },
  panels: { sites: "지점 현황", map: "지점 지도", actions: "오늘의 조치", log: "실시간 상황 기록", monitors: "지점 모니터 (최근 60일)", weather: "향후 7일 날씨", score: "성적표" },
  tile: { now: "현재 측정", next: "가장 가능성 높은 값", nextSub: "7일 뒤", range: "예상 범위", chance: "다음 주(4~10일 뒤) 측정에서 1만을 넘을 가능성", official: "공식 발령", ai: "AI 예상", measuredOn: "측정일", baseOn: "기준일", axis: { k1: "1천", k10: "1만", k100: "10만" } },
  mapLegend: "마커 색 = 상태 라벨 · 테두리 = 공식 발령 · 물길 = 낙동강·금강 본류",
  mapPulse: "경계 진입 예상 지점은 깜빡입니다",
  mapRivers: "물길 © OpenStreetMap contributors",
  actionsDone: (done: number, total: number) => `${total}개 중 ${done}개 완료`,
  actionsEmpty: "오늘 할 조치가 없습니다.",
  actionsReset: "오늘 체크 초기화",
  actionsMore: (n: number) => `+${n}개 더 보기`,
  actionsLess: "접기",
  log: {
    tierChange: (site: string, from: string | null, to: string) => (from ? `${site} 예상 단계 ${from} → ${to}` : `${site} 예상 단계 ${to}`),
    observation: (site: string, cells: string, official: string) => `${site} 새 측정 ${cells} · 공식 발령 ${official}`,
    runOk: "예측 갱신 완료",
    runFail: "예측 갱신 실패 — 마지막 성공 결과를 표시 중",
    empty: "최근 30일 기록이 없습니다.",
  },
  monitorLegend: { obs: "측정값", pred: "7일 뒤 예상", band: "예상 범위", l1: "관심 1,000", l2: "경계 10,000" },
  weather: { temp: "7일 평균 기온", rain: "7일 비 합계", basis: "기상청 단기·중기예보, 기준일 발표분", none: "예보 자료 없음" },
  score: {
    caught: (hit: number, total: number) => `경계 사건 ${total}건 중 ${hit}건을 미리 알림`,
    lead: (days: number) => `중앙값 ${days}일 앞서`,
    year2026: (hit: number, total: number) => `2026년 처음 보는 사건 ${total}건 중 ${hit}건`,
    frozen: "고정된 모델",
    detail: "자세히 보기",
  },
  failBanner: (when: string) => `${when} 예측 갱신이 실패했습니다. 마지막 성공 결과를 표시하고 있습니다.`,
  staleBanner: (days: number) => `마지막 측정이 ${days}일 전입니다. 측정 주기(주 1~2회)보다 오래 비어 있으면 수집 상태를 확인하세요.`,
  unit: { cells: "개/mL", pct: "%", days: "일", temp: "℃", mm: "mm" },
  basis: { nier: "국립환경과학원 조류경보제 측정값", model: "고정된 모델 예상값", cqr: "10번 중 8번 들어오는 범위", chance: "대응 필요 기준 52%" },
} as const;

/** 지점 상세 문구 (§4) */
export const SITE = {
  back: "메인 상황판으로",
  nowBox: "현재 측정",
  forecastBox: "앞으로 7일",
  whyBox: "왜 이렇게 예상했나",
  historyBox: "지난 녹조 발생 기록과 미리 알림",
  recoBox: "권고 조치",
  envBox: "물·날씨 상황",
  tabs: { water: "물 온도", flow: "물 흐름(댐·보 방류)", weather: "날씨(기온·비·바람)" },
  chart: { title: "최근 1년 녹조 농도와 7일 뒤 예상", obs: "측정값", pastPred: "지난 예상값", band: "예상 범위", next: "7일 뒤 예상" },
  history: { none: "기록된 경계 사건이 없습니다.", caught: (d: number) => `${d}일 앞서 알림`, missed: "미리 알리지 못함", cols: { first: "처음 넘은 날", official: "공식 발령일", watch: "주의 관찰 시작", lead: "미리 알린 기간" } },
  facility: (name: string) => `관련 시설: ${name}`,
  measuredBasis: "측정: 국립환경과학원 조류경보제",
} as const;

/** 얼마나 잘 맞혔나 (§5) */
export const PERF = {
  title: "얼마나 잘 맞혔나",
  lead: "2020년부터 2026년까지 실제 경계 발령 사건을 얼마나 앞서 알렸는지 보여 줍니다.",
  big: { caught: "미리 알린 사건", median: "앞서 알린 날수(중앙값)", y2026: "2026년 처음 보는 사건" },
  timeline: "경계 사건 시간표",
  compare: "지난주 값 그대로 쓰는 방법과 비교",
  compareNote: "같은 사건을 '지난주 값 그대로 쓰는 방법'은 몇 건이나 미리 알렸는지 나란히 둡니다.",
  limits: "솔직하게 밝히는 한계",
  expertTitle: "전문가용 지표표",
} as const;

export const INSIGHTS = { title: "녹조 이야기", lead: "7년치 측정 자료에서 읽어 낸, 녹조가 언제 어디서 왜 늘어나는지에 대한 이야기입니다." } as const;
export const ABOUT = { title: "이 시스템은", lead: "무엇을, 어떤 자료로, 어떻게 예상하는지 설명합니다." } as const;

/** 쉽게 보기에서 금지하는 표현(자동 점검용, §7·§10). 소문자 비교. */
export const BANNED_EASY = [
  "q50", "q10", "q90", "p_alert", "cqr", "shap", "oof", "lightgbm", "nnls", "tweedie", "hurdle", "optuna",
  "r²", "r2", "nse", "rmse", "mae", "f1", "picp", "auc", "cells/ml", "base_date", "target_date", "tier",
  "watch_flag", "alert_flag", "site_id", "run_id", "p ≥", "q90 ≥", "isotonic", "smearing", "expanding",
] as const;
