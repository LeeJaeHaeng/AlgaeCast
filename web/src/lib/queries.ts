import { supabase } from "./supabase";
import { REPLAY_MIN, REPLAY_RUN_ID, addDaysISO, afterWindow, weatherWindow, type WeatherObsLite } from "./replay";

export type SiteStatus = {
  site_id: string;
  name: string;
  basin: string;
  intake_weight: number | null;
  base_date: string | null;
  target_date: string | null;
  tier: string | null;
  watch_flag: boolean | null;
  alert_flag: boolean | null;
  q50: number | null;
  q10_cqr: number | null;
  q90_cqr: number | null;
  p_alert: number | null;
  pred_cell_count: number | null;
  operating_point: Record<string, unknown> | null;
  latest_obs_date: string | null;
  latest_cell_count: number | null;
  latest_alert_level: number | null;
  priority_rank: number | null;
  priority_score: number | null;
  action: string | null;
  rationale_ko: string | null;
  obs_cell_count: number | null;
};

export type Site = {
  site_id: string;
  name: string;
  basin: string;
  facility_type: string;
  facility_name: string | null;
  lat: number;
  lon: number;
  intake_capacity_tpd: number | null;
  catchment_area_km2: number | null;
  meta: Record<string, unknown> | null;
};

export type Observation = { obs_date: string; cell_count: number | null; water_temp: number | null; alert_level: number | null; dominant_genus: string | null };
export type Prediction = {
  base_date: string;
  target_date: string;
  pred_cell_count: number | null;
  q50: number | null;
  q10_cqr: number | null;
  q90_cqr: number | null;
  p_alert: number | null;
  tier: string | null;
  obs_cell_count: number | null;
  operating_point: Record<string, unknown> | null;
};
export type BloomEvent = {
  site_id: string;
  event_id: string;
  first_exceed_date: string;
  official_alert_date: string;
  first_watch_date: string | null;
  first_alert_date: string | null;
  lead_days_watch_e: number | null;
  lead_days_alert_e: number | null;
  lead_days_watch_d: number | null;
  lead_days_alert_d: number | null;
  detected_watch: boolean;
  detected_alert: boolean;
};
export type ModelRun = { run_id: string; run_at: string; model_name: string; model_version: string; git_commit: string | null; hyperparams: Record<string, unknown> | null };
export type Metric = { split: string; site_id: string | null; metric: string; value: number | null; ci_low: number | null; ci_high: number | null };
export type TransitionMetric = { split: string; method: string; segment: string; threshold: number; n: number | null; recall: number | null; precision: number | null; f1: number | null; false_alarm_rate: number | null };
export type Shap = { feature_name: string; feature_group: string | null; shap_value: number | null; feature_value: number | null; rank: number | null };
export type HydroRow = { obs_date: string; rainfall_mm: number | null; inflow_cms: number | null; outflow_cms: number | null; storage_rate: number | null; weir_level: number | null };
export type WeatherRow = { obs_date: string; ta_mean: number | null; rn_sum: number | null; ws_mean: number | null; hm_mean: number | null };

export async function getSiteStatus(): Promise<SiteStatus[]> {
  const { data, error } = await supabase().from("v_site_status").select("*");
  if (error) throw error;
  return (data ?? []) as SiteStatus[];
}

export async function getSites(): Promise<Site[]> {
  const { data, error } = await supabase().from("sites").select("*").order("site_id");
  if (error) throw error;
  return (data ?? []) as Site[];
}

export async function getLatestRun(): Promise<ModelRun | null> {
  const { data } = await supabase().from("model_runs").select("run_id,run_at,model_name,model_version,git_commit,hyperparams").eq("status", "success").order("run_at", { ascending: false }).limit(1);
  const r = data?.[0] as ModelRun | undefined;
  if (!r) return null;
  if (typeof r.hyperparams === "string") {
    try {
      r.hyperparams = JSON.parse(r.hyperparams as unknown as string);
    } catch {
      r.hyperparams = null;
    }
  }
  return r;
}

export async function getObservations(siteId: string, days = 180, asof?: string): Promise<Observation[]> {
  if (asof) {
    // 다시 보기: asof-days ≤ 관측일 ≤ asof (asof 이후 관측은 쿼리 단계에서 뺀다)
    const { data, error } = await supabase()
      .from("observations")
      .select("obs_date,cell_count,water_temp,alert_level,dominant_genus")
      .eq("site_id", siteId)
      .gte("obs_date", addDaysISO(asof, -days))
      .lte("obs_date", asof)
      .order("obs_date");
    if (error) throw error;
    return (data ?? []) as Observation[];
  }
  const since = new Date();
  since.setDate(since.getDate() - days);
  const { data, error } = await supabase()
    .from("observations")
    .select("obs_date,cell_count,water_temp,alert_level,dominant_genus")
    .eq("site_id", siteId)
    .gte("obs_date", since.toISOString().slice(0, 10))
    .order("obs_date");
  if (error) throw error;
  return (data ?? []) as Observation[];
}

/** 다시 보기 '그 뒤 실제로는': asof < 관측일 ≤ asof+21 (토글을 켰을 때만 부른다) */
export async function getObservationsAfter(siteId: string, asof: string): Promise<Observation[]> {
  const { from, to } = afterWindow(asof);
  const { data, error } = await supabase()
    .from("observations")
    .select("obs_date,cell_count,water_temp,alert_level,dominant_genus")
    .eq("site_id", siteId)
    .gte("obs_date", from)
    .lte("obs_date", to)
    .order("obs_date");
  if (error) throw error;
  return (data ?? []) as Observation[];
}

export async function getPredictions(siteId: string, runId: string | null, days = 400, asof?: string): Promise<Prediction[]> {
  if (asof) {
    // 다시 보기: 기준일 max(2026-01-01, asof-days) ~ asof 의 지난 예상값만(2025 이전 기준일은 v2.1 학습기간과 겹쳐 제외)
    const lo = addDaysISO(asof, -days) > REPLAY_MIN ? addDaysISO(asof, -days) : REPLAY_MIN;
    let rq = supabase()
      .from("predictions")
      .select("base_date,target_date,pred_cell_count,q50,q10_cqr,q90_cqr,p_alert,tier,obs_cell_count,operating_point")
      .eq("site_id", siteId)
      .gte("base_date", lo)
      .lte("base_date", asof)
      .order("base_date");
    if (runId) rq = rq.eq("run_id", runId);
    const { data, error } = await rq;
    if (error) throw error;
    return (data ?? []) as Prediction[];
  }
  const since = new Date();
  since.setDate(since.getDate() - days);
  let q = supabase()
    .from("predictions")
    .select("base_date,target_date,pred_cell_count,q50,q10_cqr,q90_cqr,p_alert,tier,obs_cell_count,operating_point")
    .eq("site_id", siteId)
    .gte("base_date", since.toISOString().slice(0, 10))
    .order("base_date");
  if (runId) q = q.eq("run_id", runId);
  const { data, error } = await q;
  if (error) throw error;
  return (data ?? []) as Prediction[];
}

export async function getBloomEvents(siteId?: string, asof?: string): Promise<BloomEvent[]> {
  let q = supabase().from("bloom_events").select("*").order("first_exceed_date", { ascending: false });
  if (siteId) q = q.eq("site_id", siteId);
  if (asof) q = q.lte("official_alert_date", asof); // 다시 보기: 그날까지 판정된 사건만
  const { data, error } = await q;
  if (error) throw error;
  return (data ?? []) as BloomEvent[];
}

export async function getMetrics(): Promise<Metric[]> {
  const { data, error } = await supabase().from("model_metrics").select("split,site_id,metric,value,ci_low,ci_high");
  if (error) throw error;
  return (data ?? []) as Metric[];
}

export async function getTransitionMetrics(): Promise<TransitionMetric[]> {
  const { data, error } = await supabase().from("transition_metrics").select("*").order("split").order("method");
  if (error) throw error;
  return (data ?? []) as TransitionMetric[];
}

export async function getShap(siteId: string, runId: string | null, baseDate?: string | null): Promise<Shap[]> {
  if (baseDate === null) return []; // 다시 보기인데 그날 예측이 없음
  let q = supabase().from("shap_contributions").select("feature_name,feature_group,shap_value,feature_value,rank,base_date").eq("site_id", siteId).order("base_date", { ascending: false }).order("rank").limit(8);
  if (runId) q = q.eq("run_id", runId);
  if (baseDate) q = q.eq("base_date", baseDate); // 다시 보기: 그날 기준일 것만(없으면 빈 목록)
  const { data } = await q;
  return (data ?? []) as Shap[];
}

export async function getHydro(siteId: string, days = 180, asof?: string): Promise<HydroRow[]> {
  if (asof) {
    const { data } = await supabase().from("hydrology_daily").select("obs_date,rainfall_mm,inflow_cms,outflow_cms,storage_rate,weir_level").eq("site_id", siteId).gte("obs_date", addDaysISO(asof, -days)).lte("obs_date", asof).order("obs_date");
    return (data ?? []) as HydroRow[];
  }
  const since = new Date();
  since.setDate(since.getDate() - days);
  const { data } = await supabase().from("hydrology_daily").select("obs_date,rainfall_mm,inflow_cms,outflow_cms,storage_rate,weir_level").eq("site_id", siteId).gte("obs_date", since.toISOString().slice(0, 10)).order("obs_date");
  return (data ?? []) as HydroRow[];
}

export async function getWeather(siteId: string, days = 180, asof?: string): Promise<WeatherRow[]> {
  if (asof) {
    const { data } = await supabase().from("weather_daily").select("obs_date,ta_mean,rn_sum,ws_mean,hm_mean").eq("site_id", siteId).gte("obs_date", addDaysISO(asof, -days)).lte("obs_date", asof).order("obs_date");
    return (data ?? []) as WeatherRow[];
  }
  const since = new Date();
  since.setDate(since.getDate() - days);
  const { data } = await supabase().from("weather_daily").select("obs_date,ta_mean,rn_sum,ws_mean,hm_mean").eq("site_id", siteId).gte("obs_date", since.toISOString().slice(0, 10)).order("obs_date");
  return (data ?? []) as WeatherRow[];
}

/** 리드타임 요약: 2020~2025(사전) 와 2026(사후 검증) 분리 */
export function leadSummary(events: BloomEvent[]) {
  const by = (pred: (e: BloomEvent) => boolean) => events.filter(pred);
  const summ = (evs: BloomEvent[]) => {
    const det = evs.filter((e) => e.detected_watch);
    const leads = det.map((e) => e.lead_days_watch_e ?? 0).sort((a, b) => a - b);
    const med = leads.length ? leads[Math.floor((leads.length - 1) / 2)] : null;
    return { n: evs.length, detected: det.length, median: med };
  };
  return { prior: summ(by((e) => e.first_exceed_date < "2026-01-01")), posthoc: summ(by((e) => e.first_exceed_date >= "2026-01-01")) };
}

/** 상태 무관 최신 run (실패 배너용) */
export async function getLatestRunAny(): Promise<{ run_at: string; status: string; notes: string | null } | null> {
  const { data } = await supabase().from("model_runs").select("run_at,status,notes").order("run_at", { ascending: false }).limit(1);
  return (data?.[0] as { run_at: string; status: string; notes: string | null }) ?? null;
}

/* ---------- T7-R 관제 상황판 추가 질의 ---------- */
export type EventRow = {
  event_time: string;
  event_date: string;
  kind: "tier_change" | "observation" | "run";
  site_id: string | null;
  site_name: string | null;
  tier_from: string | null;
  tier_to: string | null;
  cell_count: number | null;
  alert_level: number | null;
  p_alert: number | null;
  q50: number | null;
  q90_cqr: number | null;
  status: string | null;
  notes: string | null;
};

/** 실시간 상황 기록 (v_event_log, 최근 days 일) */
export async function getEventLog(days = 30, limit = 80, asof?: string): Promise<EventRow[]> {
  if (asof) {
    // 다시 보기: asof-days ≤ 날짜 ≤ asof 의 새 측정 기록만. 파이프라인 갱신(run)은 실시간 요소라 빼고,
    // 예상 단계 변화(tier_change)는 이 뷰가 최신 run 기준이라 쓰지 않는다 — 다시 보기 run 예측으로 만든다(replay.ts tierChangesAsOf)
    const { data } = await supabase()
      .from("v_event_log")
      .select("*")
      .gte("event_date", addDaysISO(asof, -days))
      .lte("event_date", asof)
      .eq("kind", "observation")
      .order("event_time", { ascending: false })
      .limit(limit);
    return (data ?? []) as EventRow[];
  }
  const since = new Date();
  since.setDate(since.getDate() - days);
  const { data } = await supabase()
    .from("v_event_log")
    .select("*")
    .gte("event_date", since.toISOString().slice(0, 10))
    .order("event_time", { ascending: false })
    .limit(limit);
  return (data ?? []) as EventRow[];
}

export type ObsLite = { site_id: string; obs_date: string; cell_count: number | null; alert_level: number | null; water_temp: number | null };
/** 전 지점 최근 관측 (지점 모니터용) */
export async function getRecentObsAll(days = 60, asof?: string): Promise<ObsLite[]> {
  if (asof) {
    const { data } = await supabase()
      .from("observations")
      .select("site_id,obs_date,cell_count,alert_level,water_temp")
      .gte("obs_date", addDaysISO(asof, -days))
      .lte("obs_date", asof)
      .order("obs_date");
    return (data ?? []) as ObsLite[];
  }
  const since = new Date();
  since.setDate(since.getDate() - days);
  const { data } = await supabase()
    .from("observations")
    .select("site_id,obs_date,cell_count,alert_level,water_temp")
    .gte("obs_date", since.toISOString().slice(0, 10))
    .order("obs_date");
  return (data ?? []) as ObsLite[];
}

export type ForecastLite = { site_id: string; obs_date: string; fc_ta_mean_d1_7: number | null; fc_rn_sum_d1_7: number | null };
/** 지점별 가장 최근 7일 예보 요약 (weather_daily 의 fc_* 컬럼, 발표일 기준) */
export async function getForecastAll(asof?: string): Promise<ForecastLite[]> {
  const since = new Date();
  since.setDate(since.getDate() - 14);
  let q = supabase()
    .from("weather_daily")
    .select("site_id,obs_date,fc_ta_mean_d1_7,fc_rn_sum_d1_7")
    .gte("obs_date", asof ? addDaysISO(asof, -14) : since.toISOString().slice(0, 10))
    .not("fc_ta_mean_d1_7", "is", null);
  if (asof) q = q.lte("obs_date", asof); // 다시 보기: 그날까지 발표된 예보만
  const { data } = await q.order("obs_date", { ascending: false });
  const seen = new Set<string>();
  const out: ForecastLite[] = [];
  for (const r of (data ?? []) as ForecastLite[]) {
    if (seen.has(r.site_id)) continue;
    seen.add(r.site_id);
    out.push(r);
  }
  return out;
}

/** 다시 보기 메인 날씨 칸(실측): 전 지점 ASOS 관측(weather_daily ta_mean·rn_sum), 그날−6 ≤ 관측일 ≤ 그날 — 그날 뒤 자료는 쿼리 단계에서 뺀다 */
export async function getWeatherWindowAll(asof: string): Promise<WeatherObsLite[]> {
  const { from, to } = weatherWindow(asof);
  const { data } = await supabase().from("weather_daily").select("site_id,obs_date,ta_mean,rn_sum").gte("obs_date", from).lte("obs_date", to).order("obs_date");
  return (data ?? []) as WeatherObsLite[];
}

/** 수집 상태 LED 용: 관측 최신 적재 시각·최신 측정일 */
export async function getCollectStatus(): Promise<{ fetched_at: string | null; obs_date: string | null }> {
  const { data } = await supabase().from("observations").select("fetched_at,obs_date").order("obs_date", { ascending: false }).limit(1);
  const r = data?.[0] as { fetched_at: string | null; obs_date: string | null } | undefined;
  return { fetched_at: r?.fetched_at ?? null, obs_date: r?.obs_date ?? null };
}

/* ---------- 과거 시점 다시 보기(?asof) ---------- */
/** 다시 보기 run: 고정한 run(REPLAY_RUN_ID, 2026 기준일 이력 보유)이 있으면 그것, 없으면 최신 성공 run */
export async function getReplayRun(): Promise<{ run_id: string } | null> {
  const { data } = await supabase().from("model_runs").select("run_id").eq("run_id", REPLAY_RUN_ID).eq("status", "success").limit(1);
  const r = data?.[0] as { run_id: string } | undefined;
  if (r) return r;
  return getLatestRun();
}

/** 다시 보기 범위: 현재 run 의 2026 첫 기준일 ~ 마지막 기준일 */
export async function getReplayBounds(runId: string | null): Promise<{ min: string | null; max: string | null }> {
  if (!runId) return { min: null, max: null };
  const [lo, hi] = await Promise.all([
    supabase().from("predictions").select("base_date").eq("run_id", runId).gte("base_date", REPLAY_MIN).order("base_date").limit(1),
    supabase().from("predictions").select("base_date").eq("run_id", runId).order("base_date", { ascending: false }).limit(1),
  ]);
  return { min: (lo.data?.[0] as { base_date: string } | undefined)?.base_date ?? null, max: (hi.data?.[0] as { base_date: string } | undefined)?.base_date ?? null };
}

export type PredictionLite = Prediction & { site_id: string; watch_flag: boolean | null; alert_flag: boolean | null };
/** 다시 보기: 전 지점의 지난 예상값(현재 run, 기준일 2026-01-01 ~ asof) */
export async function getPredictionsAllAsOf(runId: string | null, asof: string): Promise<PredictionLite[]> {
  if (!runId) return [];
  const { data, error } = await supabase()
    .from("predictions")
    .select("site_id,base_date,target_date,pred_cell_count,q50,q10_cqr,q90_cqr,p_alert,tier,watch_flag,alert_flag,obs_cell_count,operating_point")
    .eq("run_id", runId)
    .gte("base_date", REPLAY_MIN)
    .lte("base_date", asof)
    .order("base_date");
  if (error) throw error;
  return (data ?? []) as PredictionLite[];
}

/**
 * 다시 보기 상황 기록의 단계 변화 비교 시작점: 다시 보기 run 의 지점별 2026 직전(기준일 < 2026-01-01, 1년 안) 마지막 예상 단계.
 * 2026 첫 예측이 직전 단계와 같은지만 본다(v_event_log 와 같은 결과) — 단계 이름만 쓰고 그 예측의 값은 화면에 싣지 않는다.
 */
export async function getReplayTierSeed(runId: string | null): Promise<{ site_id: string; tier: string | null }[]> {
  if (!runId) return [];
  const { data, error } = await supabase()
    .from("predictions")
    .select("site_id,base_date,target_date,tier")
    .eq("run_id", runId)
    .lt("base_date", REPLAY_MIN)
    .gte("base_date", addDaysISO(REPLAY_MIN, -366))
    .order("base_date", { ascending: false })
    .order("target_date", { ascending: false });
  if (error) throw error;
  const seen = new Set<string>();
  const out: { site_id: string; tier: string | null }[] = [];
  for (const r of (data ?? []) as { site_id: string; tier: string | null }[]) {
    if (seen.has(r.site_id)) continue;
    seen.add(r.site_id);
    out.push({ site_id: r.site_id, tier: r.tier });
  }
  return out;
}

/** 다시 보기 '그 뒤 실제로는': 전 지점 asof < 관측일 ≤ asof+21 (토글을 켰을 때만 부른다) */
export async function getObsAfterAll(asof: string): Promise<ObsLite[]> {
  const { from, to } = afterWindow(asof);
  const { data } = await supabase().from("observations").select("site_id,obs_date,cell_count,alert_level,water_temp").gte("obs_date", from).lte("obs_date", to).order("obs_date");
  return (data ?? []) as ObsLite[];
}
