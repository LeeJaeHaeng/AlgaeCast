-- T7-R: v_site_status 에 최신 예측의 실측(obs_cell_count) 추가 — 목표일이 지난 예측의 "예상 → 실제" 표시용
create or replace view v_site_status as
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
       lr.priority_rank, lr.priority_score, lr.action, lr.rationale_ko,
       coalesce(lp.obs_cell_count, (select o.cell_count from observations o where o.site_id = lp.site_id and o.obs_date = lp.target_date)) as obs_cell_count
from sites s
left join latest_pred lp on lp.site_id = s.site_id
left join latest_obs lo on lo.site_id = s.site_id
left join latest_rec lr on lr.site_id = s.site_id;
