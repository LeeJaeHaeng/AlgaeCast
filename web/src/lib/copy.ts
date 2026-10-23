/**
 * 화면 문구 모음 (docs/12_CONTROL_ROOM_UI.md §7·§8). 컴포넌트에는 문자열을 직접 쓰지 않고 여기서 가져온다.
 * - 쉽게 보기(기본): 영어 약어·내부 변수명 금지, 모든 숫자에 단위·기준 표기, 단정 대신 "가능성·예상"
 * - 전문가 보기(?view=expert): 기존 지표·내부 명칭 병기 허용
 * - 숫자는 numbers.ts(빌드 전 reports/eval 과 대조)에서 가져와 문장에 끼운다.
 */
import { CMP, MODELS, NUMBERS, OP_PCT } from "./numbers";

export type Tier = "normal" | "watch" | "alert";
export type FeatureGroup = "ar" | "water" | "hydro" | "weather" | "forecast" | "time_site" | "upstream";

/** "YYYY-MM-DD HH:MM"(한국 시간) → "2026년 10월 22일 오후 4시 27분" */
export const kstKo = (s: string): string => {
  const [d, t] = s.split(" ");
  const [y, m, dd] = d.split("-").map(Number);
  const [h, mi] = t.split(":").map(Number);
  return `${y}년 ${m}월 ${dd}일 ${h < 12 ? "오전" : "오후"} ${h % 12 === 0 ? 12 : h % 12}시${mi ? ` ${mi}분` : ""}`;
};
/** 소수 둘째 자리, 음수는 유니코드 마이너스 */
export const n2 = (v: number): string => v.toFixed(2).replace("-", "−");
const V1_SEALED = kstKo(MODELS.v1meta.sealedKST);
const V2_FROZEN = kstKo(MODELS.v2meta.frozenKST);
const V21_FROZEN = kstKo(MODELS.v21meta.frozenKST);

/** 2026 v2.1 수치 옆에 붙이는 고지 — 원천 표(tbl_holdout_2026_posthoc_v21.md)와 같은 문장(check_numbers 가 대조) */
export const V21_NOTICE = `수정본(v2.1·v1-fix)의 2026 은 블라인드가 아니다: 모델 선택·수정 규칙에 2026 을 쓰지 않았지만 팀은 v1·v2 의 2026 결과를 이미 봤다. 동결 커밋 ${MODELS.v21meta.commit}`;

/** 사후에 발견한 누수와 수정 — 화면·문서 공통 한 문장 */
export const LEAK_NOTE = `2026년 10월 23일, 데이터로 계산한 상수를 전수 점검하다가 이전 모델(v1 ${V1_SEALED} 봉인·v2 ${V2_FROZEN} 고정)의 일부 상수(지점별 수온 기준, 수위 기준 평균, 기상 관측소 선택)가 2026년 자료까지 포함한 전 기간으로 계산돼 있었음을 발견했습니다. 미리 등록한 규칙대로 고친 모델이 v2.1이며, 결과와 상관없이 v2.1을 씁니다.`;

/** 제출·운영 모델 = v2.1. v1·v2 는 수정 전 이력 */
export const MODEL = {
  v21: "v2.1 제출·운영 모델(누수 수정판)",
  v2: "v2(수정 전 이력)",
  v1: "v1 봉인본(수정 전 이력)",
  note: `제출·운영 모델은 v2.1(${V21_FROZEN} 고정, 커밋 ${MODELS.v21meta.commit})입니다. 화면의 예상값·예상 범위·넘을 가능성·단계는 모두 v2.1이 냅니다. 이전 모델의 일부 상수가 2026년 자료까지 포함해 계산돼 있던 것을 찾아 미리 등록한 규칙대로 고쳤습니다. v1·v2의 성적은 이력으로만 남깁니다.`,
} as const;

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
  footer: "데이터: 국립환경과학원 조류경보제 · 한국수자원공사 · 국가수자원관리종합정보시스템 · 기상청 · DataON 국가참조표준(공공데이터포털 자료는 공공누리·이용허락범위 제한 없음, DataON 수위 자료는 CC BY-NC-SA). 이 예상은 운영 참고용이며 공식 발령을 대체하지 않습니다.",
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
  tierAlert: { label: "대응 필요", tip: `1주일 안에 경계 수준을 넘을 가능성이 높습니다(가능성 ${OP_PCT}% 이상). 녹조제거설비 배치를 미리 준비해야 합니다.` },
  point: { label: "예상값", tip: "7일 뒤 녹조 농도 예상값입니다. 대회에 제출한 모델(v2.1)이 낸 한 값이며, 실제 값은 이보다 높거나 낮을 수 있습니다. 그 폭은 예상 범위로 함께 보여 줍니다." },
  q50: { label: "q50(분위 중앙값)", tip: "예상 범위를 내는 분위 회귀(v2.1)의 중앙값입니다. 쉽게 보기의 예상값(v2.1 한 값 예측)과 다를 수 있습니다." },
  range: { label: "예상 범위", tip: "7일 뒤 녹조 농도가 10번 중 8번은 이 범위 안에 들어오도록 맞춘 구간입니다(2023~2024년 자료로 보정)." },
  pAlert: { label: "다음 주(4~10일 뒤) 측정에서 1만을 넘을 가능성", tip: "다음 주(4~10일 뒤) 측정 중 한 번이라도 녹조 농도가 1만 개/mL 이상일 가능성입니다. 예상값이 1만 아래여도 예상 범위 위쪽이 1만을 넘으면 넘을 가능성이 높게 나올 수 있습니다." },
  baseDate: { label: "기준일", tip: "예상을 만들 때 마지막으로 사용한 측정일입니다. 이 날 이후의 자료는 쓰지 않았습니다." },
  targetDate: { label: "7일 뒤", tip: "기준일로부터 7일 뒤, 예상의 대상이 되는 날입니다." },
  leadTime: { label: "미리 알린 기간", tip: "실제로 경계 수준을 처음 넘은 날보다 며칠 앞서 '주의 관찰' 이상으로 바뀌었는지입니다." },
  persistence: { label: "지난주 값 그대로 쓰는 방법", tip: "'다음 주도 이번 주와 같을 것'이라고 보는 가장 단순한 비교 기준입니다." },
  why: { label: "왜 이렇게 예상했나", tip: "예상값을 올리거나 내린 요인을 기여도가 큰 순서로 보여 줍니다." },
  frozen: { label: "고정된 모델", tip: `예상값·예상 범위·넘을 가능성·단계는 제출·운영 모델 v2.1(${V21_FROZEN}, 한국 시간 고정)이 냅니다. 2025년까지 자료로만 만들었고 고정한 뒤에는 다시 학습하지 않습니다. 이전 모델(v1·v2)의 일부 상수에 2026년 자료가 들어간 것을 찾아 고친 판입니다. 자세한 내용은 '얼마나 잘 맞혔나'·'이 시스템은' 페이지에 있습니다.` },
  trend: { label: "추세", tip: "예상값이 현재 측정값보다 높으면 ↑, 낮으면 ↓, 비슷하면 → 입니다(±20% 기준)." },
} as const;

/** 단계(2단계 운영 체계) 표시 — §6 색·아이콘 */
export const TIER: Record<Tier, { label: string; icon: string; color: string; action: string; term: keyof typeof TERMS }> = {
  normal: { label: "안전", icon: "●", color: "var(--safe)", action: "평소대로 관리", term: "tierSafe" },
  watch: { label: "주의 관찰", icon: "▲", color: "var(--watch)", action: "모니터링 강화·설비 준비 점검", term: "tierWatch" },
  alert: { label: "대응 필요", icon: "◆", color: "var(--alert)", action: "녹조제거설비 선제 배치 권고", term: "tierAlert" },
};
/** 전문가 보기에서 병기하는 내부 명칭 */
export const TIER_EXPERT: Record<Tier, string> = { normal: "normal", watch: "watch (q90 ≥ 1만)", alert: `alert (p ≥ ${(OP_PCT / 100).toFixed(2)})` };


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
  upstream: "바로 위(상류) 지점 측정",
};

/** §8.1 근거 문장 템플릿 — 그룹별 기여 방향(+ 올림 / − 내림) */
export const REASON: Record<FeatureGroup, { up: string; down: string }> = {
  ar: { up: "최근 녹조가 이미 많습니다", down: "최근 녹조가 줄고 있습니다" },
  water: { up: "물 온도가 높은 날이 계속됐습니다", down: "물 온도가 내려가고 있습니다" },
  hydro: { up: "보·댐 방류가 적어 물이 고여 있습니다", down: "방류가 늘어 물이 잘 흐릅니다" },
  weather: { up: "한 달간 더웠고 비가 적었습니다", down: "비가 와서 녹조가 씻겨 나갈 수 있습니다" },
  forecast: { up: "앞으로 덥고 비가 적을 것으로 예보됐습니다", down: "앞으로 비가 올 것으로 예보됐습니다" },
  time_site: { up: "녹조가 많이 생기는 시기입니다", down: "녹조가 줄어드는 시기입니다" },
  upstream: { up: "바로 위(상류) 지점의 최근 측정이 녹조를 늘리는 쪽입니다", down: "바로 위(상류) 지점의 최근 측정이 녹조를 줄이는 쪽입니다" },
};
/** v2 상류 피처(up1_*) — DB 의 feature_group 은 "etc" 라 이름 접두어로 묶는다 */
export const UPSTREAM_PREFIX = "up1_";
/** 물 온도 보조 문구: 25℃ 이상 n일 */
export const reasonWaterDays = (n: number) => `(25℃ 이상 ${n}일)`;
/** 최근 30일에 25℃ 이상이 없을 때의 물 온도 상승 요인 문장 */
export const REASON_WATER_UP_MILD = "물 온도가 녹조에 유리한 수준입니다";

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
  tile: { now: "현재 측정", next: "예상값", nextSub: "7일 뒤", range: "예상 범위", chance: "다음 주(4~10일 뒤) 측정에서 1만을 넘을 가능성", official: "공식 발령", ai: "AI 예상", measuredOn: "측정일", baseOn: "기준일", axis: { k1: "1천", k10: "1만", k100: "10만" },
    outOfRange: "범위 밖",
    /** 전문가 보기 전용 — 분위 회귀 중앙값 */
    q50Expert: "q50(분위 중앙)" },
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
  monitorLegend: { obs: "측정", pred: "예상값", predShort: "예상값", band: "예상 범위", l1: "관심 1,000", l2: "경계 10,000" },
  weather: { temp: "7일 평균 기온", rain: "7일 비 합계", basis: "기상청 단기·중기예보, 기준일 발표분", none: "예보 자료 없음" },
  score: {
    caught: (hit: number, total: number) => `경계 사건 ${total}건 중 ${hit}건을 미리 알림`,
    lead: (days: number) => `중앙값 ${days}일 앞서`,
    year2026: (hit: number, total: number) => `2026년 경계 사건 ${total}건 중 ${hit}건`,
    year2026Sub: "2025년까지 자료로만 만든 v2.1",
    frozen: "제출·운영 v2.1",
    expert: (a25: string, b25: string, a26: string, b26: string) => `점예측 F1@10k 2025(같은 252행) v2.1 ${a25} · 지속성 ${b25} / 2026 사후 v2.1 ${a26}(비블라인드) · 지속성 ${b26}`,
    detail: "자세히 보기",
  },
  failBanner: (when: string) => `${when} 예측 갱신이 실패했습니다. 마지막 성공 결과를 표시하고 있습니다.`,
  staleBanner: (days: number) => `마지막 측정이 ${days}일 전입니다. 측정 주기(주 1~2회)보다 오래 비어 있으면 수집 상태를 확인하세요.`,
  unit: { cells: "개/mL", pct: "%", days: "일", temp: "℃", mm: "mm" },
  basis: { nier: "국립환경과학원 조류경보제 측정값", model: "고정된 모델 예상값", cqr: "10번 중 8번 들어오는 범위", chance: `대응 필요 기준 ${OP_PCT}%` },
} as const;

/** 지점 상세 문구 (§4) */
export const SITE = {
  back: "메인 상황판으로",
  nowBox: "현재 측정",
  forecastBox: "앞으로 7일",
  whyBox: "왜 이렇게 예상했나",
  historyBox: "지난 녹조 발생 기록과 미리 알림",
  recoBox: "권고 조치",
  envBox: "물·날씨 상황 (최근 6개월)",
  verifyBox: "지난 예상은 맞았나",
  tabs: { water: "물 온도", flow: "물 흐름(댐·보 방류)", weather: "날씨(기온·비·바람)" },
  chart: { title: "최근 1년 녹조 농도와 7일 뒤 예상", obs: "측정값", pastPred: "지난 예상값", band: "예상 범위", next: "예상값", legend: "흰 선·점 = 측정값 · 회색 점 = 그때그때의 예상값 · 파란 점·띠 = 이번 예상값과 예상 범위" },
  history: { none: "기록된 경계 사건이 없습니다.", caught: (d: number) => `${d}일 앞서 알림`, missed: "미리 알리지 못함", posthoc: "사후 계산 · 학습에 안 쓴 해", cols: { first: "처음 1만을 넘은 날", official: "공식 발령일", watch: "주의 관찰로 바뀐 날", lead: "미리 알린 기간" } },
  facility: (name: string) => `관련 시설: ${name}`,
  measuredBasis: "측정: 국립환경과학원 조류경보제",
  /** 메인에서 ⓘ 에 의존하던 두 가지를 큰 글자로 푸는 문장 */
  plain: {
    whyOver: (v: string, p: number) => `예상값은 ${v} 개/mL입니다. 예상값이 경계(1만)를 넘을 것으로 보입니다(가능성 ${p}%).`,
    whyHighChance: (v: string, p: number) => `예상값은 ${v} 개/mL로 1만 아래지만, 예상 범위의 위쪽이 1만을 넘기 때문에 다음 주 측정에서 1만을 넘을 가능성이 ${p}%로 나왔습니다.`,
    whyHighOnly: (v: string, p: number) => `예상값은 ${v} 개/mL로 1만 아래지만, 다음 주 측정에서 1만을 넘을 가능성은 ${p}%로 높게 나왔습니다.`,
    whyLowChance: (v: string, p: number) => `예상값은 ${v} 개/mL이고, 예상 범위의 위쪽도 1만에 닿지 않아 다음 주 측정에서 1만을 넘을 가능성은 ${p}%로 낮습니다.`,
    frozen: "2025년까지의 자료로 만든 뒤 고정한 모델이 낸 예상입니다.",
    /** 전문가 보기 전용 세부(봉인 시각·모델 구분) */
    frozenExpert: `예상값 = v2.1 pred_cell_count, q50·CQR q10/q90·p_alert(운영점 ${(OP_PCT / 100).toFixed(2)})·단계 = v2.1 분위·분류기(${V21_FROZEN} 고정, 커밋 ${MODELS.v21meta.commit}, 수정 피처로 다시 적합). 이력: v1 ${V1_SEALED} 봉인(커밋 ${MODELS.v1meta.commit}) · v2 ${V2_FROZEN} 고정(커밋 ${MODELS.v2meta.commit}).`,
  },
  reasonsIntro: "예상값을 올리거나 내린 요인을 기여도가 큰 순서로 세 가지만 골랐습니다.",
  verifySummary: (hit: number, n: number) => `공식 경보 단계 기준으로 최근 ${n}번의 예상 중 ${hit}번이 실제와 같은 단계였습니다.`,
  eventSummary: (n: number, m: number) => `이 지점 경계 사건 ${n}건 중 ${m}건 미리 알림`,
  chartLow: "100 미만·미검출",
  verifyCols: { base: "기준일", target: "목표일", pred: "예상값", actual: "실제", same: "같은 단계" },
  envNote: { water: "물 온도 25℃ 이상이면 녹조가 빨리 늡니다.", flow: "방류가 늘면 물이 흘러 녹조가 씻겨 내려갑니다.", weather: "덥고 비가 적은 날이 이어지면 녹조가 늡니다." },
} as const;

/** 얼마나 잘 맞혔나 (§5) */
export const PERF = {
  title: "얼마나 잘 맞혔나",
  lead: "2020년부터 2026년까지 실제 경계 사건을 얼마나 앞서 알렸는지, 그리고 약한 부분은 무엇인지 숨기지 않고 보여 줍니다.",
  big: {
    caught: { label: "경계 사건 미리 알림", sub: (med: number) => `중앙값 ${med}일 앞서 · 2020~2026년 · v2.1` },
    y2026: { label: "2026년 경계 사건", sub: (med: number) => `중앙값 ${med}일 앞서 · 2025년까지 자료로만 만든 모델(v2.1) · 블라인드 아님※` },
    r2log: { label: "녹조 농도 맞히기", value: (a: string, b: string) => `${a} / ${b}`, sub: "로그 기준 설명력 · 2025년 / 2026년 · v2.1 · 1에 가까울수록 좋음" },
    f1: { label: "경계 여부 맞히기", sub: (a: string, b: string, c: string, d: string) => `v2.1 · 지난주 값 그대로 쓰는 방법과 비슷 · 2025년 ${a} vs ${b} · 2026년 ${c} vs ${d}` },
  },
  models: MODEL.note,
  leak: LEAK_NOTE,
  v21Footnote: `※ 2026년 v2.1 값: ${V21_NOTICE}`,
  compare: {
    title: "v2.1과 수정 전 모델 나란히 — 한 값 예측 성적 (좋은 지표·나쁜 지표 모두)",
    lead: "v2.1은 데이터로 계산한 상수를 기준일까지 또는 학습 기간 자료로만 다시 계산해 고친 모델입니다. 2025년은 같은 자료로, 2026년은 v2.1 고정 뒤 한 번 계산해 수정 전 v2·v1과 나란히 놓았습니다.",
    cols: ["지표", "v2.1 제출·운영", "v2(수정 전)", "v1 봉인본(수정 전)", "지난주 값 그대로", "좋은 방향"],
    y2025: (n: number) => `2025년 검증 자료 — 같은 ${n}건으로 비교`,
    y2026: (n: number) => `2026년 사후 계산 — ${n}건 · 블라인드 아님※`,
    rows: {
      r2log: { label: "로그 기준 설명력", better: "1에 가까울수록", expert: "r2_log" },
      rmselog: { label: "로그 기준 오차", better: "작을수록", expert: "rmse_log" },
      r2raw: { label: "원단위 결정계수 (목표 0.6)", better: "1에 가까울수록 · 0 아래면 평균값보다 못함", expert: "r2_raw" },
      nseraw: { label: "원단위 효율계수 (목표 0.5)", better: "1에 가까울수록", expert: "nse_raw" },
      f1: { label: "경계(1만) 여부 맞히기", better: "1에 가까울수록", expert: "f1_10k" },
      point: { label: "한 값 예측이 1만 넘는 사건을 미리 잡은 수", better: "많을수록", expert: "점예측≥임계 선행 탐지" },
      watch: { label: "주의 관찰 단계로 미리 알린 사건 (중앙 앞선 날)", better: "많을수록", expert: "감시 q90_cqr≥임계" },
    },
    count: (hit: number, total: number) => `${total}건 중 ${hit}건`,
    countLead: (hit: number, total: number, med: number) => `${total}건 중 ${hit}건 (${med}일)`,
    prior: (v21: number, before: number, n: number) => `2020~2025년 경계 사건 ${n}건을 주의 관찰 단계로 미리 알린 수: v2.1 ${v21}건(수정 전 ${before}건). 이 차이 때문에 2020~2026년 합계가 수정 전 25건에서 ${NUMBERS.events.detected}건으로 바뀌었습니다.`,
    cv: (a: string, b: string, c: string, d: string) => `2020~2024년 연도별 교차검증(통합) 원단위 결정계수: v2.1 ${a} · 수정 전 v2 ${b} · v1 ${c} · 지난주 값 그대로 ${d}. 결합 가중치를 이 자료로 정했으므로 같은 자료에서 잰 값입니다.`,
    v1fix: (r25: string, r26: string, f26: string, p: number, n: number) => `v1 구성을 같은 규칙으로 고친 v1-fix(민감도 확인용): 2025년 원단위 결정계수 ${r25}, 2026년 ${r26} · 경계 여부 맞히기 2026년 ${f26} · 한 값 예측이 1만 넘는 사건을 미리 잡은 수 ${n}건 중 ${p}건. 주의 관찰·넘을 가능성은 v2.1과 같은 모델이라 결과도 같습니다.`,
    weak: (r26: string, f25: string, b25: string, f26: string, b26: string) => `약한 점: 2026년 원단위 결정계수는 v2.1도 ${r26}에 그쳐 봉우리 높이는 여전히 못 맞힙니다. 경계 여부 맞히기는 지난주 값 그대로 쓰는 방법보다 조금 낮습니다(2025년 ${f25} 대 ${b25}, 2026년 ${f26} 대 ${b26}).`,
    source: "출처 reports/eval/tbl_holdout_2025_v21.md · tbl_holdout_2026_posthoc_v21.md · models/FROZEN_v2.1.md · reports/experiments/FIX-v2.1",
  },
  sentence: "지난주 값을 그대로 쓰면 이미 경계인 곳은 잘 맞히지만, 경계로 처음 넘어가는 순간은 미리 알 수 없습니다. 이 시스템은 그 순간을 미리 알리는 데 강합니다.",
  onset: { title: "경계 사건을 미리 알린 비율", ours: "이 시스템 (주의 관찰 단계)", persist: "지난주 값 그대로 쓰는 방법", persistNote: "지난주 값을 그대로 쓰면 측정 간격이 벌어진 경우가 아니면 미리 알 수 없습니다" },
  timeline: { title: "경계 사건 28건 시간표", legend: "선 = 처음 알린 날 → 실제로 1만을 넘은 날 · 빨간 점 = 미리 알리지 못함 · 파란 테두리 점 = 2026년(학습에 안 쓴 해, v2.1 고정 뒤 사후 계산)", missed: "미리 알리지 못함", posthoc: "사후 계산" },
  target: {
    title: "원래 목표였던 지표",
    rows: (m: { r25: string; r26: string; n25: string; n26: string }) => [
      `원단위 결정계수: 목표 0.6 → v2.1 2025년 ${m.r25}, 2026년 ${m.r26}※`,
      `원단위 효율계수: 목표 0.5 → v2.1 2025년 ${m.n25}, 2026년 ${m.n26}※`,
    ],
    rowsNote: (v1: string, v2: string) => `2025년 같은 252건 값입니다(수정 전 v1 ${v1} · v2 ${v2}). ※ 2026년 v2.1 값은 블라인드가 아닙니다.`,
    why: ["2025년 가장 높았던 봉우리 1건(회남 8월 18일, 19만 개/mL)이 그 해 변화량의 43%를 차지해, 봉우리 높이를 못 맞히면 이 지표는 바로 낮아집니다.", "6가지 모델 방법과 3가지 보정 방법을 모두 시험했지만 어떤 조합도 0.2를 넘지 못했습니다. 주 1~2회 측정 자료로 7일 뒤 봉우리 높이를 맞히는 데는 한계가 있습니다.", `바로 위(상류) 지점 측정과 녹조 종류별 예측을 더한 v2.1도 2025년 ${n2(CMP.h25v21.r2raw)}, 2026년 ${n2(CMP.p26v21.r2raw)}에 그쳤습니다. 추가 고도화 실험도 미리 정한 채택 기준을 넘지 못했습니다.`],
  },
  mulmoa: { title: "국립환경과학원 물모아(공식 예측)와 비교", text: (n: number) => `자료 쌓는 중 (지금까지 ${n}건). 2026년 10월 19일 발표분부터 매일 저장하고 있으며, 실측이 도착하면 단계 맞힘 비교표가 채워집니다.` },
  expertTitle: "전문가용 지표표 (reports/eval)",
  basis: "출처: 2025년 = 학습에 쓰지 않은 검증 자료(같은 252건), 2026년 = v2.1 고정 뒤 한 번 계산한 사후 계산(블라인드 아님). 미리 알림 = 실제로 1만을 처음 넘은 날보다 앞서 '주의 관찰' 이상으로 바뀐 사건.",
} as const;

export const INSIGHTS = {
  title: "녹조 이야기",
  lead: "2012년부터 2026년까지 측정 자료에서 읽어 낸, 녹조가 언제 어디서 왜 늘어나는지에 대한 네 가지 이야기입니다.",
  early: {
    title: "① 올해는 유난히 빨랐지만, 해마다 점점 빨라지는 것은 아닙니다",
    body: "2026년 강정·고령은 5월 18일에 공식 관심 단계가 내려져 평년보다 약 두 달 빨랐습니다. 그런데 2016년부터의 첫 발령일을 지점 차이를 빼고 모아 보면 '해마다 빨라진다'는 흐름은 통계적으로 확인되지 않습니다(한 해에 약 1일 빨라지는 기울기, 우연일 가능성 64%). 첫 발령일은 해마다 크게 흔들리므로, 달력에 맞춘 고정 대응보다 예상에 따라 움직이는 탄력 운영이 필요합니다.",
    expert: "Mann-Kendall 검정, 지점 평균 제거 잔차 2016~2026: 관심 Sen −1.04일/년 p=0.64, 경계 −0.88일/년 p=0.76. 지점별 연도 중앙값 통합은 지점 구성 변화 때문에 해석 주의(p=0.01).",
    fig: "연도별 첫 발령일(가로축 연도, 세로축 1월 1일부터 며칠째). 2026년 강정·고령 점이 유독 아래(이른 날짜)에 있습니다.",
  },
  temp: {
    title: "② 물 온도가 오르면 녹조가 늘어납니다 — 지점마다 시작 온도가 다릅니다",
    body: "물 온도와 녹조 농도는 함께 움직입니다(로그 기준 상관 0.72). 다만 관심 수준(1천 개/mL)에 이르는 물 온도는 지점마다 달라서, 회남은 20.7℃에서 이미 시작하고 해평은 25.8℃가 돼야 시작합니다(2025년까지 측정). 그래서 이 시스템은 지점마다 다른 기준 온도를 특징으로 넣습니다. 이 기준 온도는 학습 기간 측정으로만 계산합니다.",
    rows: [["회남", 20.7], ["물금·매리", 22.8], ["칠서", 23.3], ["강정·고령", 24.0], ["해평", 25.8]] as [string, number][],
    unit: "관심 수준에 이르는 물 온도(℃, 2025년까지 측정)",
    expert: "LOESS 적합이 1,000 cells/mL 와 만나는 수온(T2 S6). Kruskal-Wallis H=175, p=7.3e-37. 수온–log 세포수 Spearman 0.74(Pearson 0.72), 기온 이동평균 7일과 수온 Spearman 0.92.",
  },
  sites: {
    title: "③ 같은 강이라도 지점마다 다르게 움직입니다",
    body: "낙동강 네 지점과 금강 회남은 녹조가 많아지는 시기도, 높이도 다릅니다. 하류(물금·매리, 칠서)는 6월부터 일찍 시작해 여름 내내 높고, 상류 해평은 늦게 시작해 짧게 끝납니다. 회남(대청댐)은 8월에 집중되고 봉우리가 매우 높습니다.",
    fig: "지점별 물 온도–녹조 농도 관계 곡선. 같은 물 온도에서도 지점마다 녹조 농도가 다릅니다.",
  },
  surge: {
    title: "④ 녹조는 일주일 사이에 열 배가 되기도 합니다",
    body: (n: number, temp: string, rain: string) => `2012년 이후 연속 측정 7일 안에 열 배 이상 늘어난 급증이 ${n}번 있었습니다. 급증 직전 일주일은 평균 기온 ${temp}℃로 덥고 비는 ${rain}mm에 그쳤습니다. 더운 날씨와 적은 비, 긴 일조가 이어지면 다음 측정에서 갑자기 뛸 수 있다는 뜻이며, 이 시스템이 '날씨'와 '물 흐름'을 함께 보는 이유입니다.`,
    cols: ["지점", "이전 측정일", "급증 측정일", "이전 농도", "급증 농도", "배수", "직전 7일 평균 기온", "직전 7일 비"],
  },
  source: "출처: reports/eda (T2 통계분석 S6·S7·S9), 국립환경과학원 조류경보제 측정값·기상청 자료.",
} as const;

export const ABOUT = {
  title: "이 시스템은",
  lead: "무엇을, 어떤 자료로, 어떻게 예상하는지와 아직 못 하는 것을 설명합니다.",
  what: "낙동강 네 곳(해평·강정·고령·칠서·물금·매리)과 금강 회남의 취수원에서, 마지막 측정일 기준 7일 뒤 녹조 농도를 예상하고 '안전 / 주의 관찰 / 대응 필요' 세 단계로 알려 주는 시스템입니다.",
  steps: [
    { n: "①", title: "자료 모으기", body: "매일 새벽 5시에 조류경보제 측정값, 댐·보 운영 자료, 하천 수위, 기상 관측과 예보를 받아 옵니다." },
    { n: "②", title: "특징 만들기", body: `기준일까지의 자료만으로 특징을 계산합니다(최근 녹조 흐름, 물 온도, 방류와 수위, 기온·비·바람, 계절·지점 ${MODELS.v1meta.features}가지, 한 값 예측은 바로 위(상류) 지점의 최근 측정 ${MODELS.v21meta.upstreamFeatures}가지를 더해 ${MODELS.v21meta.features}가지). 기준일 뒤의 자료는 쓰지 않습니다. 수위 기준 평균은 기준일 직전 1년 값만 씁니다.` },
    { n: "③", title: "예상하기", body: "2025년까지 자료로만 학습해 고정한 모델(v2.1)이 7일 뒤 예상값과 예상 범위, 다음 주 1만을 넘을 가능성을 냅니다. 지점별 수온 기준 같은 상수도 학습 기간 자료로만 계산합니다." },
    { n: "④", title: "단계 판정", body: `예상 범위 위쪽이 1만에 닿으면 주의 관찰, 넘을 가능성이 ${OP_PCT}% 이상이면 대응 필요. 공식 발령과 함께 보여 '경계 진입 예상 / 계속될 듯 / 나아질 가능성'으로 정리합니다.` },
  ],
  dataTitle: "쓰는 자료와 출처",
  dataCols: ["자료", "기관", "쓰임", "이용 조건"],
  data: [
    ["조류경보제 측정값(유해남조류 세포수·수온 등)", "국립환경과학원 (물환경정보시스템)", "예상의 목표값과 최근 녹조 흐름", "공공누리 1유형(출처표시) · 공공데이터포털"],
    ["다목적댐·보 운영(유입·방류·저수율·수위)", "한국수자원공사 (K-water)", "물 흐름 특징", "이용허락범위 제한 없음 · 공공데이터포털"],
    ["보·하천 수위(실시간·일 자료)", "국가수자원관리종합정보시스템 (WAMIS)", "물 흐름 특징, 2025년 이후 수위 연결", "WAMIS 개방 자료(인증키 없이 수집) · 같은 값이 공공데이터포털 한강홍수통제소 수자원 정보·표준수문DB(이용허락범위 제한 없음)에 있음 · 제출 패키지에는 원값 대신 가공 특징만 · 출처 표시: 한강홍수통제소 WAMIS"],
    ["댐유역 하천 일평균수위 (국가참조표준)", "K-water 생산 · DataON(KISTI) 등재", "2010~2024년 연속 수위 특징(DataON 활용)", "CC BY-NC-SA(저작자표시-비영리-동일조건변경허락) · 생산 한국수자원공사(오재우·이영창·이재용) · DOI 10.20925/KSRD.74670854.v5 · 이를 가공한 자료도 같은 조건으로만 재배포"],
    ["지상 기상 관측(기온·강수·바람·일조)", "기상청 (ASOS)", "날씨 특징", "공공누리 1유형(출처표시) · 공공데이터포털"],
    ["단기·중기 예보", "기상청", "앞으로 7일 날씨 특징·화면 표시", "공공누리 1유형(출처표시) · 공공데이터포털"],
    ["대회 제공 자료(지점·일자 조합, 댐 일자료)", "KISTI 2026 DATA·AI 분석 경진대회", "학습·평가 기준", "참가신청서 대회 규정 3항(승인 목적 외 이용·제3자 제공 금지, 대회 후 폐기, 성과물 출처 명시) · 저장소와 이 화면에 원자료를 올리지 않음"],
  ],
  aida: "AIDA(KISTI 인공지능 데이터)의 정규격자 기상·레이더 자료는 계획(docs/02 §6)에 올렸으나 이번 제출 모델에는 쓰지 않았습니다. 관측소 1곳 의존을 줄이는 다음 단계 과제입니다.",
  limitsTitle: "아직 못 하는 것 (솔직한 한계)",
  limits: [
    `올해(2026년) 성적은 지난해보다 낮습니다. 로그 기준 설명력 ${n2(NUMBERS.r2log.y2025)} → ${n2(NUMBERS.r2log.y2026)}※, 예상 범위 적중률 ${n2(NUMBERS.picp80.y2025)} → ${n2(NUMBERS.picp80.y2026)}※. 이례적으로 이른 발생 같은 새로운 패턴이 섞여 있습니다.`,
    LEAK_NOTE,
    "강정·고령의 2026년 5월 18일 이례적 조기 관심 발령은 미리 알리지 못했습니다(첫 초과 당일에야 주의 관찰). 봄철 자료가 학습 구간에 거의 없었기 때문입니다.",
    `원래 목표였던 원단위 결정계수 0.6 · 효율계수 0.5는 이루지 못했습니다(v2.1 2025년 ${n2(NUMBERS.r2raw.y2025)}, 2026년 ${n2(NUMBERS.r2raw.y2026)}※). 봉우리 높이를 맞히는 데 약합니다.`,
    "CCTV 영상이나 위성 사진은 아직 쓰지 않습니다. 주 1~2회 측정 사이의 변화를 보려면 다음 단계에서 필요합니다.",
  ],
  notOfficial: "이 시스템의 예상은 운영 참고용입니다. 국립환경과학원 조류경보제의 공식 발령을 대체하지 않으며, 화면에는 항상 공식 발령과 예상을 나란히 둡니다.",
  reproTitle: "다시 만들어 보려면",
  repro: ["저장소를 받아 Python 3.11 가상환경에 설치합니다(make setup).", "대회 자료를 data/raw/competition 에 두고 외부 자료를 받습니다(make collect).", "일 달력 정렬 → 특징 → 학습 → 평가(make align features train eval). 고정 모델 해시는 models/FROZEN_v2.1.md(제출·운영)와 이력 FROZEN.md·FROZEN_v2.md 와 대조합니다(scripts/verify_frozen.py).", "제출용 예측은 python -m algaecast.models.predict 로 다시 만들어지며, 새 환경에서 바이트 단위로 같은 파일이 나오는지 확인했습니다."],
  reproExpert: "GitHub: LeeJaeHaeng/AlgaeCast (비공개). 분할 학습 ≤2024 / 검증 2025 / 평가 2026, 연 단위 확장 창 교차검증, 시드 42, 누수 테스트 tests/test_no_leakage.py.",
  frozenLine: `제출·운영 모델 v2.1 고정: ${V21_FROZEN}(한국 시간), 커밋 ${MODELS.v21meta.commit}. 고정 뒤에는 제출 전까지 다시 학습하지 않습니다. 이력: v1 ${V1_SEALED} 봉인(커밋 ${MODELS.v1meta.commit}) · v2 ${V2_FROZEN} 고정(커밋 ${MODELS.v2meta.commit}).`,
  limitsFootnote: `※ 2026년 v2.1 값: ${V21_NOTICE}`,
  models: {
    title: "제출·운영 모델 v2.1 과 이전 모델(이력)",
    lead: MODEL.note,
    leak: LEAK_NOTE,
    cols: ["", "v2.1 제출·운영(누수 수정판)", "v2(수정 전 이력)", "v1 봉인본(수정 전 이력)"],
    rows: [
      ["고정 시각", `${V21_FROZEN} (커밋 ${MODELS.v21meta.commit})`, `${V2_FROZEN} (커밋 ${MODELS.v2meta.commit})`, `${V1_SEALED} (커밋 ${MODELS.v1meta.commit})`],
      ["예상값 = 한 값 예측 (화면의 큰 숫자 · 대회 제출값)", `세 가지 예측 + 녹조 종류별 예측의 가중 평균 · 특징 ${MODELS.v21meta.features}가지 · 가중치 ${MODELS.v21weights.c1.toFixed(3)} · ${MODELS.v21weights.c3.toFixed(3)} · ${MODELS.v21weights.c2.toFixed(3)} · ${MODELS.v21weights.cg.toFixed(3)}`, `같은 구성 · 특징 ${MODELS.v2meta.features}가지`, `세 가지 예측의 가중 평균 · 특징 ${MODELS.v1meta.features}가지`],
      ["예상 범위 · 넘을 가능성 · 단계", `수정 피처로 다시 적합(운영점 ${OP_PCT}%)`, "v1 봉인본(운영점 52%)", "v1 봉인본(운영점 52%)"],
      ["데이터로 계산한 상수", "기준일까지 또는 학습 기간 자료만", "일부가 2026년까지 전 기간", "일부가 2026년까지 전 기간"],
      ["2026년 경계 사건 미리 알림(주의 관찰)", `${CMP.p26watch.total}건 중 ${CMP.p26watch.v21}건 (중앙 ${CMP.p26watch.medianLeadV21}일)※`, `${CMP.p26watch.total}건 중 ${CMP.p26watch.v2}건`, `${CMP.p26watch.total}건 중 ${CMP.p26watch.v1}건(봉인 당시 상수 일부에 2026 자료 포함)`],
      ["2026년 한 값 예측이 1만 넘는 사건을 미리 잡은 수", `${CMP.p26point.total}건 중 ${CMP.p26point.v21}건※`, `${CMP.p26point.total}건 중 ${CMP.p26point.v2}건`, `${CMP.p26point.total}건 중 ${CMP.p26point.v1}건`],
    ] as [string, string, string, string][],
    expert: `v2.1 = 로그 앙상블(c1·c3·c2) + 상류 피처 5열(up1_*) + 속별 구성원 cg, log10 공간 NNLS 가중치 c1 ${MODELS.v21weights.c1.toFixed(3)} · c3 ${MODELS.v21weights.c3.toFixed(3)} · c2 ${MODELS.v21weights.c2.toFixed(3)} · cg ${MODELS.v21weights.cg.toFixed(3)}. 분류기(p_alert)·분위(q10/q50/q90)·CQR·운영점(r=3)도 수정 피처로 다시 적합. 수정 규칙 reports/experiments/FIX-v2.1/PREREG.md, 수정 전 v2 근거 EXP-confirm.`,
    frozenTable: "models/FROZEN_v2.1.md — 동결 모델 해시",
  },
} as const;

/** 공식 단계 기준(개/mL): 관심 1천, 경계 1만, 대발생 100만 */
export const levelOfCells = (v: number | null | undefined): number => (v == null ? 0 : v >= 1_000_000 ? 3 : v >= 10_000 ? 2 : v >= 1_000 ? 1 : 0);

/**
 * 예측 목표일 표시 규칙 (오늘 KST 기준). 지난 날짜에는 "7일 뒤" 를 쓰지 않는다.
 * - 목표일 > 오늘: "MM.DD 예상 (내일 / n일 뒤)"
 * - 목표일 ≤ 오늘, 실측 없음: "MM.DD 예상 · 측정 결과 대기 중"
 * - 실측 있음: "MM.DD 예상 7,400 → 실제 8,100 ✓/✗" (✓ = 예상값(v2.1 한 값)과 실측이 같은 공식 단계)
 */
export function targetLabel(targetDate: string | null | undefined, todayISO: string, point: number | null | undefined, obs: number | null | undefined, fmt: (v: number | null | undefined) => string, opts: { withValues?: boolean } = {}): { text: string; state: "future" | "waiting" | "verified"; hit?: boolean } {
  if (!targetDate) return { text: "–", state: "future" };
  const mmdd = `${targetDate.slice(5, 7)}.${targetDate.slice(8, 10)}`;
  const diff = Math.round((new Date(targetDate).getTime() - new Date(todayISO).getTime()) / 86_400_000);
  if (diff > 0) return { text: `${mmdd} 예상 (${diff === 1 ? "내일" : `${diff}일 뒤`})`, state: "future" };
  if (obs == null) return { text: `${mmdd} 예상 · 측정 결과 대기 중`, state: "waiting" };
  const hit = levelOfCells(point) === levelOfCells(obs);
  const vals = opts.withValues === false ? "" : ` ${fmt(point)} → 실제 ${fmt(obs)}`;
  return { text: `${mmdd} 예상${vals} ${hit ? "✓" : "✗"}`, state: "verified", hit };
}
/**
 * 예상값 설명 문장 규칙(쉽게 보기) — 예상값 = v2.1 한 값 예측, 범위 = CQR q10~q90, 가능성 = 분류기(모두 v2.1).
 * - 예상값 ≥ 1만: "예상값이 경계(1만)를 넘을 것으로 보입니다(가능성 n%)"
 * - 예상값 < 1만, 범위 위쪽 ≥ 1만: "예상 범위 위쪽이 1만을 넘기 때문" 문장
 * - 예상값 < 1만, 범위 위쪽 < 1만인데 가능성 ≥ 운영점(대응 필요 기준, numbers.ts OP_PCT): 가능성이 높다는 문장
 * - 그 밖: 범위 위쪽도 1만에 닿지 않아 가능성이 낮다는 문장
 */
export function explainForecast(point: number | null | undefined, q90: number | null | undefined, pPct: number, fmt: (v: number | null | undefined) => string): string {
  if ((point ?? 0) >= 10_000) return SITE.plain.whyOver(fmt(point), pPct);
  if ((q90 ?? 0) >= 10_000) return SITE.plain.whyHighChance(fmt(point), pPct);
  if (pPct >= OP_PCT) return SITE.plain.whyHighOnly(fmt(point), pPct);
  return SITE.plain.whyLowChance(fmt(point), pPct);
}
/** 예상값이 예상 범위(q10~q90) 밖인지 — 값은 바꾸지 않고 ⓘ 로만 알린다 */
export function outOfRange(point: number | null | undefined, q10: number | null | undefined, q90: number | null | undefined): "above" | "below" | null {
  if (point == null || q10 == null || q90 == null) return null;
  return point > q90 ? "above" : point < q10 ? "below" : null;
}
export const outOfRangeTip = (side: "above" | "below", q10: string, q90: string): string =>
  `예상값이 예상 범위(${q10} ~ ${q90} 개/mL)의 ${side === "above" ? "위" : "아래"}에 있습니다. 예상값은 한 값 예측(앙상블)이, 예상 범위는 분위 회귀가 따로 계산해 서로 어긋날 수 있습니다(둘 다 v2.1). 값은 고치지 않고 그대로 보여 줍니다.`;
export const LOG_MORE = (n: number) => `이전 기록 ${n}건`;
export const LOG_PAGE = { title: "상황 기록 (최근 30일)", back: "메인 상황판으로" };

/** 쉽게 보기에서 금지하는 표현(자동 점검용, §7·§10). 소문자 비교. */
export const BANNED_EASY = [
  "q50", "q10", "q90", "p_alert", "cqr", "shap", "oof", "lightgbm", "nnls", "tweedie", "hurdle", "optuna",
  "r²", "r2", "nse", "rmse", "mae", "f1", "picp", "auc", "cells/ml", "base_date", "target_date", "tier",
  "watch_flag", "alert_flag", "site_id", "run_id", "p ≥", "q90 ≥", "isotonic", "smearing", "expanding",
] as const;
