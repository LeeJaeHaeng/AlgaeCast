/**
 * 과거 시점 다시 보기(?asof=YYYY-MM-DD) — 순수 함수 모음. 서버 페이지(/, /sites/[id], /log)가 쓰고 scripts/test_replay.mjs 가 검사한다.
 * 규칙
 * - 관측은 관측일 ≤ asof 만(쿼리 단계에서 .lte 로 거르고, 여기서 한 번 더 거른다).
 * - 예측은 DB 에 이미 있는 다시 보기 전용 run(REPLAY_RUN_ID, 없으면 최신 run)의 지난 예상값 중 지점마다 기준일 ≤ asof 인 가장 최근 것
 *   (같은 기준일이면 목표일 늦은 것 — v_site_status 와 같은 순서).
 *   예측 행의 실측(obs_cell_count)은 목표일 ≤ asof 일 때만 남긴다(목표일이 asof 뒤면 그 실측은 asof 이후 관측이다).
 *   DB 예측 행에 실측이 비어 있으면(일부 지점 2026 행) 목표일 ≤ asof 일 때만 그 날의 관측값으로 채운다(fillActualAsOf, DB 는 바꾸지 않음).
 * - 2025 이전 기준일 예측은 제출 모델 v2.1 의 학습기간(≤2025)과 겹쳐 '그날까지의 자료만'이 성립하지 않으므로 쓰지 않는다(REPLAY_MIN).
 * - 사건 표는 그날까지 판정된 사건(공식 발령일 ≤ asof)만.
 * - 상황 기록의 예상 단계 변화는 v_event_log(최신 run 기준 뷰)를 쓰지 않고 다시 보기 run 의 예측으로 직접 만든다(tierChangesAsOf) —
 *   타일·지도와 같은 run 이 되게. 새 측정 도착 기록만 뷰에서 가져온다(run 과 무관).
 * - '그 뒤 실제로는'(after=1)은 asof < 관측일 ≤ asof+21 만 따로 가져와 겹친다(꺼져 있으면 아예 가져오지 않음).
 * 이 파일은 런타임 import 가 없어야 한다(node --test 가 타입만 지워서 바로 실행).
 */
import type { BloomEvent, EventRow, ObsLite, Prediction, Site, SiteStatus } from "./queries";

/** 다시 보기 가장 이른 날(정책): 2026-01-01. 실제 하한은 이 날 이후 첫 기준일(데이터) */
export const REPLAY_MIN = "2026-01-01";
/**
 * 다시 보기 전용 run(설정 상수는 이 한 곳). 2026 기준일 이력(2026-05-04 ~ 2026-10-22, 134행)을 모두 가진 v2.1 run 이다.
 * 이유: 매일 도는 파이프라인의 새 run 은 기준일 이력을 다 싣지 않을 수 있어 '최신 run' 에 기대면 장면 날짜가 범위 밖으로 빠질 수 있다.
 * 이 run 이 DB 에 없으면(삭제 등) 최신 성공 run 으로 대신한다(queries.getReplayRun). 장면 3개가 범위 안인지는 scripts/check_asof.mjs 가 본다.
 */
export const REPLAY_RUN_ID = "9269d95d-9b8f-4d12-babe-02f9f60b41c5";
/** '그 뒤 실제로는' 겹쳐 보는 날 수 */
export const AFTER_DAYS = 21;
/** 상황 기록 창(일) — 실시간 화면과 같음 */
export const LOG_DAYS = 30;
/** 다시 보기 메인 날씨 칸(실측)의 창 길이(일): 그날−6 ~ 그날 */
export const WEATHER_DAYS = 7;

export type SceneId = "pre" | "onset" | "miss";
/** 미리 정한 장면 3개 — 날짜·근거는 DB bloom_events·predictions(현재 run) 에서 정함(docs/handoff/REPORT_다시보기.md) */
export const SCENES: { id: SceneId; asof: string; siteId: string; eventId: string }[] = [
  // ① 강정·고령 경계 사건(첫 초과 E 2026-08-03) 7일 전 기준일: 예상값 10,662 · q90 45,882 · p 0.773(대응 필요) → 경계 진입 예상
  { id: "pre", asof: "2026-07-27", siteId: "2011G56", eventId: "GJGR-2026-08-03" },
  // ② 같은 사건 첫 초과일(측정 98,859, 공식 발령은 아직 관심)
  { id: "onset", asof: "2026-08-03", siteId: "2011G56", eventId: "GJGR-2026-08-03" },
  // ③ 놓친 사례: 회남 경계 사건(E 2026-07-13) 7일 전 기준일: 예상값 55 · q90 858 · p 0.003(안전) — 2026 경계 8건 중 감시·경보 모두 못 잡은 유일한 사건
  { id: "miss", asof: "2026-07-06", siteId: "3008G30", eventId: "DCHN-2026-07-13" },
];
export const sceneOf = (asof: string | null | undefined) => SCENES.find((s) => s.asof === asof);

export type Replay = { asof: string; after: boolean };
export type ReplayBounds = { min: string | null; max: string | null };

/** YYYY-MM-DD 이고 실제 있는 날짜인지 */
export function isIsoDate(s: unknown): s is string {
  if (typeof s !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const [y, m, d] = s.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
}

/** 날짜 문자열(YYYY-MM-DD) ± n일 (UTC 계산이라 시간대와 무관) */
export function addDaysISO(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/**
 * URL 파라미터 판정. asof 가 없으면 "none", 형식이 틀리면 "bad", 허용 범위 밖이면 "range", 맞으면 "ok".
 * 허용 범위 = max(REPLAY_MIN, 데이터 첫 기준일) ≤ asof ≤ 데이터 마지막 기준일.
 */
export function replayState(raw: string | undefined, bounds: ReplayBounds): "none" | "bad" | "range" | "ok" {
  if (raw === undefined || raw === "") return "none";
  if (!isIsoDate(raw)) return "bad";
  const lo = bounds.min && bounds.min > REPLAY_MIN ? bounds.min : REPLAY_MIN;
  if (!bounds.max || raw < lo || raw > bounds.max) return "range";
  return "ok";
}

/** 다시 보기 상태(맞을 때만). after 는 "1" 일 때만 켬 */
export function parseReplay(sp: { asof?: string; after?: string }, bounds: ReplayBounds): Replay | null {
  return replayState(sp.asof, bounds) === "ok" ? { asof: sp.asof as string, after: sp.after === "1" } : null;
}

/** 다시 보기 범위의 하한(정책·데이터 중 늦은 날) */
export const replayMinOf = (bounds: ReplayBounds) => (bounds.min && bounds.min > REPLAY_MIN ? bounds.min : REPLAY_MIN);

/** 관측일 ≤ asof (days 가 있으면 asof-days ≤ 관측일 도) */
export function obsAsOf<T extends { obs_date: string }>(rows: T[], asof: string, days?: number): T[] {
  const lo = days == null ? null : addDaysISO(asof, -days);
  return rows.filter((r) => r.obs_date <= asof && (lo == null || r.obs_date >= lo));
}

/** '그 뒤 실제로는': asof < 관측일 ≤ asof + AFTER_DAYS */
export function afterWindow(asof: string, days = AFTER_DAYS): { from: string; to: string } {
  return { from: addDaysISO(asof, 1), to: addDaysISO(asof, days) };
}
export function obsAfter<T extends { obs_date: string }>(rows: T[], asof: string, days = AFTER_DAYS): T[] {
  const { to } = afterWindow(asof, days);
  return rows.filter((r) => r.obs_date > asof && r.obs_date <= to);
}

/** 다시 보기 날씨 칸의 창: 그날−(days−1) ≤ 관측일 ≤ 그날 (7일이면 asof−6 ~ asof). 창 끝 = 그날 — 그날 뒤 자료는 들어오지 않는다 */
export function weatherWindow(asof: string, days = WEATHER_DAYS): { from: string; to: string } {
  return { from: addDaysISO(asof, -(days - 1)), to: asof };
}

export type WeatherObsLite = { site_id: string; obs_date: string; ta_mean: number | null; rn_sum: number | null };
export type WeatherSummary = { site_id: string; ta_mean: number | null; rn_sum: number | null; days: number };
const round1 = (v: number) => Math.round(v * 10) / 10;

/**
 * 다시 보기 메인 '그날까지 7일 날씨(실측)': 지점별 7일 평균 기온(℃, 소수 1자리)·7일 비 합계(mm, 소수 1자리).
 * - 창 밖 행(특히 그날 뒤)은 버린다(쿼리 단계 .gte/.lte 에 더해 한 번 더 거른다). 같은 날 행이 둘이면 값 있는 칸이 이긴다.
 * - days = 창 안에서 기온이나 비 값이 하나라도 있는 날 수(7 미만이면 화면에 'n일 자료'). 기온은 값 있는 날 평균, 비는 값 있는 날 합계.
 *   값이 하나도 없으면 null(화면 '–'). 화면(ReplayWeatherPanel)과 검사(scripts/check_asof.mjs)가 같은 함수를 쓴다.
 */
export function summarizeWeatherAsOf(rows: WeatherObsLite[], siteIds: string[], asof: string, days = WEATHER_DAYS): WeatherSummary[] {
  const { from, to } = weatherWindow(asof, days);
  return siteIds.map((sid) => {
    const byDate = new Map<string, { ta: number | null; rn: number | null }>();
    for (const r of rows) {
      if (r.site_id !== sid || r.obs_date < from || r.obs_date > to) continue;
      const cur = byDate.get(r.obs_date) ?? { ta: null, rn: null };
      byDate.set(r.obs_date, { ta: r.ta_mean ?? cur.ta, rn: r.rn_sum ?? cur.rn });
    }
    const vals = [...byDate.values()];
    const ta = vals.map((v) => v.ta).filter((v): v is number => v != null);
    const rn = vals.map((v) => v.rn).filter((v): v is number => v != null);
    return {
      site_id: sid,
      ta_mean: ta.length ? round1(ta.reduce((a, b) => a + b, 0) / ta.length) : null,
      rn_sum: rn.length ? round1(rn.reduce((a, b) => a + b, 0)) : null,
      days: vals.filter((v) => v.ta != null || v.rn != null).length,
    };
  });
}

/** 예측 행의 실측은 목표일 ≤ asof 일 때만 남긴다 */
export function maskFutureActual<T extends { target_date: string; obs_cell_count: number | null }>(p: T, asof: string): T {
  return p.target_date <= asof ? p : { ...p, obs_cell_count: null };
}

/**
 * 예측 행의 실측이 비어 있으면 목표일 관측값으로 채운다 — 목표일 ≤ asof 일 때만(asof 뒤 관측은 쓰지 않음).
 * DB predictions.obs_cell_count 가 일부 지점(칠서·물금·매리·회남)의 2026 행에서 비어 있어 '지난 예상은 맞았나' 가 비던 것.
 */
export function fillActualAsOf<T extends { target_date: string; obs_cell_count: number | null }>(preds: T[], obs: { obs_date: string; cell_count: number | null }[], asof: string): T[] {
  const byDate = new Map(obs.filter((o) => o.obs_date <= asof && o.cell_count != null).map((o) => [o.obs_date, o.cell_count as number]));
  return preds.map((p) => (p.target_date > asof ? { ...p, obs_cell_count: null } : p.obs_cell_count != null ? p : { ...p, obs_cell_count: byDate.get(p.target_date) ?? null }));
}

/** 그날 볼 수 있던 지난 예상값들(기준일 REPLAY_MIN ~ asof, 실측은 목표일 ≤ asof 만) */
export function predsAsOf<T extends { base_date: string; target_date: string; obs_cell_count: number | null }>(preds: T[], asof: string): T[] {
  return preds.filter((p) => p.base_date >= REPLAY_MIN && p.base_date <= asof).map((p) => maskFutureActual(p, asof));
}

/** 지점의 그날 예측: 기준일 ≤ asof 중 가장 최근(같은 기준일이면 목표일 늦은 것) */
export function pickPredAsOf<T extends { site_id: string; base_date: string; target_date: string; obs_cell_count: number | null }>(preds: T[], siteId: string, asof: string): T | null {
  const c = predsAsOf(
    preds.filter((p) => p.site_id === siteId),
    asof,
  ).sort((a, b) => b.base_date.localeCompare(a.base_date) || b.target_date.localeCompare(a.target_date));
  return c[0] ?? null;
}

/** 그날까지 판정된 사건(공식 발령일 ≤ asof) */
export function eventsAsOf<T extends Pick<BloomEvent, "official_alert_date">>(events: T[], asof: string): T[] {
  return events.filter((e) => e.official_alert_date <= asof);
}

/** 상황 기록: asof-days ≤ 날짜 ≤ asof, 파이프라인 갱신(run) 기록은 실시간 요소라 뺀다 */
export function logAsOf<T extends Pick<EventRow, "event_date" | "kind">>(rows: T[], asof: string, days = LOG_DAYS): T[] {
  const lo = addDaysISO(asof, -days);
  return rows.filter((r) => r.kind !== "run" && r.event_date <= asof && r.event_date >= lo);
}

type TierPred = { site_id: string; base_date: string; target_date: string; tier: string | null; p_alert: number | null; q50: number | null; q90_cqr: number | null };

/**
 * 다시 보기 상황 기록의 '예상 단계 변화' — supabase/migrations/0002_event_log.sql(v_event_log)의 tier_change 와 같은 규칙을
 * 다시 보기 run 의 예측(preds, 기준일 2026-01-01 ~ asof)으로 계산한다. v_event_log 는 '최신 성공 run' 으로 만들어져
 * 고정 run(REPLAY_RUN_ID)과 어긋날 수 있어서다.
 * 규칙: 지점·기준일마다 목표일 늦은 한 행 → 기준일 순서로 직전 단계와 다르면 기록(직전이 없으면 tier_from = null).
 * seed = 지점별 2026 직전(기준일 < 2026-01-01) 마지막 예상 단계 — 2026 첫 예측의 '직전 단계' 비교에만 쓴다(단계 이름만, 값은 쓰지 않음).
 * 시각 = 기준일 09시(KST) = 그날 00:00 UTC(뷰와 같은 값). 창 = asof-days ≤ 기준일 ≤ asof.
 */
export function tierChangesAsOf(preds: TierPred[], seed: { site_id: string; tier: string | null }[], sites: Pick<Site, "site_id" | "name">[], asof: string, days = LOG_DAYS): EventRow[] {
  const lo = addDaysISO(asof, -days);
  const out: EventRow[] = [];
  for (const s of [...sites].sort((a, b) => a.site_id.localeCompare(b.site_id))) {
    const byBase = new Map<string, TierPred>();
    for (const p of preds) {
      if (p.site_id !== s.site_id || p.base_date > asof) continue;
      const cur = byBase.get(p.base_date);
      if (!cur || p.target_date > cur.target_date) byBase.set(p.base_date, p);
    }
    let prev: string | null = seed.find((x) => x.site_id === s.site_id)?.tier ?? null;
    for (const p of [...byBase.values()].sort((a, b) => a.base_date.localeCompare(b.base_date))) {
      const tier = p.tier ?? null;
      if (tier !== prev && p.base_date >= lo)
        out.push({ event_time: `${p.base_date}T00:00:00+00:00`, event_date: p.base_date, kind: "tier_change", site_id: s.site_id, site_name: s.name, tier_from: prev, tier_to: tier, cell_count: null, alert_level: null, p_alert: p.p_alert, q50: p.q50, q90_cqr: p.q90_cqr, status: null, notes: null });
      prev = tier;
    }
  }
  return out;
}

/** 다시 보기 상황 기록 = 새 측정 기록(뷰) + 예상 단계 변화(다시 보기 run) → 그날까지 days 일, 시각 내림차순, 앞 limit 줄 */
export function mergeLogAsOf<T extends Pick<EventRow, "event_time" | "event_date" | "kind">>(obsRows: T[], tierRows: T[], asof: string, days = LOG_DAYS, limit = 80): T[] {
  return logAsOf([...obsRows.filter((r) => r.kind === "observation"), ...tierRows], asof, days)
    .sort((a, b) => Date.parse(b.event_time) - Date.parse(a.event_time))
    .slice(0, limit);
}

type PredRow = Prediction & { site_id: string; watch_flag?: boolean | null; alert_flag?: boolean | null };

/**
 * 그날 기준 지점 상태(v_site_status 와 같은 모양). 최근 관측 = 관측일 ≤ asof 중 마지막 행(세포수 없는 행 포함 — 뷰와 같음),
 * 실측(목표일) = 예측 행의 실측 또는 목표일 관측(둘 다 목표일 ≤ asof 일 때만).
 */
export function buildStatusAsOf(sites: Pick<Site, "site_id" | "name" | "basin">[], preds: PredRow[], obs: ObsLite[], asof: string): SiteStatus[] {
  const seen = obsAsOf(obs, asof);
  return sites.map((s) => {
    const p = pickPredAsOf(preds, s.site_id, asof);
    const o = seen.filter((x) => x.site_id === s.site_id).sort((a, b) => b.obs_date.localeCompare(a.obs_date))[0];
    const atTarget = p && p.target_date <= asof ? seen.find((x) => x.site_id === s.site_id && x.obs_date === p.target_date)?.cell_count ?? null : null;
    return {
      site_id: s.site_id,
      name: s.name,
      basin: s.basin,
      intake_weight: null,
      base_date: p?.base_date ?? null,
      target_date: p?.target_date ?? null,
      tier: p?.tier ?? null,
      watch_flag: p?.watch_flag ?? null,
      alert_flag: p?.alert_flag ?? null,
      q50: p?.q50 ?? null,
      q10_cqr: p?.q10_cqr ?? null,
      q90_cqr: p?.q90_cqr ?? null,
      p_alert: p?.p_alert ?? null,
      pred_cell_count: p?.pred_cell_count ?? null,
      operating_point: p?.operating_point ?? null,
      latest_obs_date: o?.obs_date ?? null,
      latest_cell_count: o?.cell_count ?? null,
      latest_alert_level: o?.alert_level ?? null,
      priority_rank: null,
      priority_score: null,
      action: null,
      rationale_ko: null,
      obs_cell_count: p && p.target_date <= asof ? (p.obs_cell_count ?? atTarget) : null,
    };
  });
}

/**
 * 다시 보기 안의 링크 쿼리. 다시 보기 화면(/, /sites/*, /log)으로 가는 링크는 asof·after 를 유지하고, 전문가 보기·순환도 함께 둔다.
 * 반환은 "?..." 또는 "" (파라미터 없으면 빈 문자열 — 기본 화면 링크와 같은 모양).
 */
/** 다시 보기 큰 차트: 같은 날짜 점을 하나로 합친다(값이 있는 칸이 이김). 범주형 X축에 같은 날짜가 두 번 생기면
 *  그날 세로선(ReferenceLine x=asof)이 그려지지 않고, 목표일 예상 점이 같은 날 측정 점과 다른 자리에 찍힌다. */
export function mergeSameDate<T extends { date: string }>(points: T[]): T[] {
  const m = new Map<string, T>();
  for (const p of points) {
    const prev = m.get(p.date);
    if (!prev) m.set(p.date, p);
    else {
      const filled = Object.fromEntries(Object.entries(p).filter(([, v]) => v !== null && v !== undefined));
      m.set(p.date, { ...prev, ...filled } as T);
    }
  }
  return [...m.values()].sort((a, b) => a.date.localeCompare(b.date));
}

export function replayQuery(o: { replay?: Replay | null; expert?: boolean; kiosk?: boolean }): string {
  const p = new URLSearchParams();
  if (o.replay) {
    p.set("asof", o.replay.asof);
    if (o.replay.after) p.set("after", "1");
  }
  if (o.kiosk) p.set("kiosk", "1");
  if (o.expert) p.set("view", "expert");
  const s = p.toString();
  return s ? `?${s}` : "";
}
