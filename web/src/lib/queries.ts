import { supabase } from "./supabase";

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

export async function getObservations(siteId: string, days = 180): Promise<Observation[]> {
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

export async function getPredictions(siteId: string, runId: string | null, days = 400): Promise<Prediction[]> {
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

export async function getBloomEvents(siteId?: string): Promise<BloomEvent[]> {
  let q = supabase().from("bloom_events").select("*").order("first_exceed_date", { ascending: false });
  if (siteId) q = q.eq("site_id", siteId);
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

export async function getShap(siteId: string, runId: string | null): Promise<Shap[]> {
  let q = supabase().from("shap_contributions").select("feature_name,feature_group,shap_value,feature_value,rank,base_date").eq("site_id", siteId).order("base_date", { ascending: false }).order("rank").limit(8);
  if (runId) q = q.eq("run_id", runId);
  const { data } = await q;
  return (data ?? []) as Shap[];
}

export async function getHydro(siteId: string, days = 180): Promise<HydroRow[]> {
  const since = new Date();
  since.setDate(since.getDate() - days);
  const { data } = await supabase().from("hydrology_daily").select("obs_date,rainfall_mm,inflow_cms,outflow_cms,storage_rate,weir_level").eq("site_id", siteId).gte("obs_date", since.toISOString().slice(0, 10)).order("obs_date");
  return (data ?? []) as HydroRow[];
}

export async function getWeather(siteId: string, days = 180): Promise<WeatherRow[]> {
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
