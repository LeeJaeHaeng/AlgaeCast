-- AlgaeCast-7 초기 스키마 (docs/05_ERD.md §3 그대로, T6)
create extension if not exists "uuid-ossp";

create table sites (
  site_id text primary key,
  name text not null,
  basin text not null,
  facility_type text not null check (facility_type in ('weir','dam')),
  facility_name text,
  lat double precision not null,
  lon double precision not null,
  intake_weight double precision not null default 0.5,
  intake_capacity_tpd double precision,
  catchment_area_km2 double precision,
  meta jsonb default '{}'::jsonb
);

create table stations (
  id serial primary key,
  site_id text references sites(site_id) on delete cascade,
  kind text not null check (kind in ('asos','dam','weir','basin','wq')),
  station_code text not null,
  station_name text,
  source text,
  unique (site_id, kind, station_code)
);

create table observations (
  id bigserial primary key,
  site_id text references sites(site_id) on delete cascade,
  obs_date date not null,
  cell_count double precision,
  water_temp double precision, ph double precision, do_mgl double precision,
  turbidity double precision, transparency double precision, chla double precision,
  tp double precision, tn double precision,
  dominant_genus text,
  alert_level smallint check (alert_level between 0 and 3),
  source text,
  fetched_at timestamptz default now(),
  unique (site_id, obs_date)
);
create index on observations (site_id, obs_date desc);

create table hydrology_daily (
  id bigserial primary key,
  site_id text references sites(site_id) on delete cascade,
  obs_date date not null,
  rainfall_mm double precision, inflow_cms double precision, outflow_cms double precision,
  storage_mcm double precision, storage_rate double precision,
  water_level double precision, weir_level double precision,
  source text,
  unique (site_id, obs_date)
);

create table weather_daily (
  id bigserial primary key,
  site_id text references sites(site_id) on delete cascade,
  obs_date date not null,
  ta_mean double precision, ta_max double precision, ta_min double precision,
  rn_sum double precision, rn_basin double precision,
  ws_mean double precision, hm_mean double precision,
  ss_sum double precision, si_sum double precision,
  fc_ta_mean_d1_7 double precision, fc_rn_sum_d1_7 double precision,
  source text,
  unique (site_id, obs_date)
);

create table model_runs (
  run_id uuid primary key default uuid_generate_v4(),
  run_at timestamptz default now(),
  model_name text not null,
  model_version text not null,
  git_commit text,
  features_hash text,
  hyperparams jsonb,
  status text not null default 'success',
  notes text
);

create table predictions (
  id bigserial primary key,
  run_id uuid references model_runs(run_id) on delete cascade,
  site_id text references sites(site_id) on delete cascade,
  base_date date not null,
  target_date date not null,
  horizon_days smallint,
  pred_cell_count double precision, pred_log double precision,
  q10 double precision, q50 double precision, q90 double precision,
  p_over_1k double precision, p_over_10k double precision, p_over_1m double precision,
  pred_alert_level smallint,
  obs_cell_count double precision,
  q10_cqr double precision, q90_cqr double precision,
  p_alert double precision,
  watch_flag boolean default false, alert_flag boolean default false,
  tier text check (tier in ('normal','watch','alert')),
  operating_point jsonb,
  unique (run_id, site_id, base_date, target_date)
);
create index on predictions (site_id, base_date desc);

create table alerts (
  id bigserial primary key,
  site_id text references sites(site_id) on delete cascade,
  issued_date date not null,
  released_date date,
  level smallint not null,
  source text
);

create table shap_contributions (
  id bigserial primary key,
  run_id uuid references model_runs(run_id) on delete cascade,
  site_id text references sites(site_id) on delete cascade,
  base_date date not null,
  feature_name text not null,
  feature_group text,
  shap_value double precision,
  feature_value double precision,
  rank smallint
);
create index on shap_contributions (run_id, site_id, base_date);

create table recommendations (
  id bigserial primary key,
  run_id uuid references model_runs(run_id) on delete cascade,
  site_id text references sites(site_id) on delete cascade,
  base_date date not null,
  priority_score double precision,
  priority_rank smallint,
  action text,
  rationale_ko text
);

create table model_metrics (
  id bigserial primary key,
  run_id uuid references model_runs(run_id) on delete cascade,
  split text not null,
  site_id text,
  metric text not null,
  value double precision,
  ci_low double precision,
  ci_high double precision
);

-- 최신 성공 run의 예측만 보는 뷰
create view v_latest_predictions as
select p.* from predictions p
join (select run_id from model_runs where status='success' order by run_at desc limit 1) r using (run_id);

create view v_latest_recommendations as
select r.* from recommendations r
join (select run_id from model_runs where status='success' order by run_at desc limit 1) m using (run_id);


-- T5 확정: 경계 사건 리드타임 (eval/transitions.py 결과)
create table bloom_events (
  id bigserial primary key,
  site_id text references sites(site_id) on delete cascade,
  event_id text not null,
  first_exceed_date date not null,
  official_alert_date date not null,
  first_watch_date date,
  first_alert_date date,
  lead_days_watch_e integer, lead_days_alert_e integer,
  lead_days_watch_d integer, lead_days_alert_d integer,
  detected_watch boolean default false,
  detected_alert boolean default false,
  unique (site_id, event_id)
);

-- 상태 전환 구간 지표 (tbl_transitions)
create table transition_metrics (
  id bigserial primary key,
  split text not null,
  method text not null,
  segment text not null check (segment in ('onset','offset','stay_above','stay_below','all')),
  threshold double precision not null,
  n integer,
  recall double precision, precision double precision, f1 double precision,
  false_alarm_rate double precision,
  unique (split, method, segment, threshold)
);

-- 지점별 최신 상태 (최신 성공 run 의 최신 base_date)
create view v_site_status as
with latest_run as (
  select run_id from model_runs where status = 'success' order by run_at desc limit 1
), latest_pred as (
  select distinct on (p.site_id) p.*
  from predictions p join latest_run using (run_id)
  order by p.site_id, p.base_date desc, p.target_date desc
), latest_obs as (
  select distinct on (site_id) site_id, obs_date, cell_count, alert_level
  from observations order by site_id, obs_date desc
), latest_rec as (
  select r.site_id, r.priority_rank, r.priority_score, r.action, r.rationale_ko
  from recommendations r join latest_run using (run_id)
  where r.base_date = (select max(base_date) from recommendations r2 where r2.run_id = r.run_id and r2.site_id = r.site_id)
)
select s.site_id, s.name, s.basin, s.intake_weight,
       lp.base_date, lp.target_date, lp.tier, lp.watch_flag, lp.alert_flag,
       lp.q50, lp.q10_cqr, lp.q90_cqr, lp.p_alert, lp.pred_cell_count, lp.operating_point,
       lo.obs_date as latest_obs_date, lo.cell_count as latest_cell_count, lo.alert_level as latest_alert_level,
       lr.priority_rank, lr.priority_score, lr.action, lr.rationale_ko
from sites s
left join latest_pred lp on lp.site_id = s.site_id
left join latest_obs lo on lo.site_id = s.site_id
left join latest_rec lr on lr.site_id = s.site_id;

-- RLS
alter table sites enable row level security;
alter table stations enable row level security;
alter table observations enable row level security;
alter table hydrology_daily enable row level security;
alter table weather_daily enable row level security;
alter table model_runs enable row level security;
alter table predictions enable row level security;
alter table alerts enable row level security;
alter table shap_contributions enable row level security;
alter table recommendations enable row level security;
alter table model_metrics enable row level security;
alter table bloom_events enable row level security;
alter table transition_metrics enable row level security;

do $$ declare t text;
begin
  foreach t in array array['sites','stations','observations','hydrology_daily','weather_daily','model_runs','predictions','alerts','shap_contributions','recommendations','model_metrics','bloom_events','transition_metrics']
  loop
    execute format('create policy "%s_read" on %I for select to anon, authenticated using (true);', t, t);
  end loop;
end $$;
-- 쓰기는 service_role만 (RLS 우회)
