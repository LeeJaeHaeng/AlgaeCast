-- T7-R (docs/12 §9): 실시간 상황 기록 뷰 v_event_log
-- predictions(예상 단계 변화) + observations(새 측정 도착) + model_runs(갱신·실패) 를 하나의 시간순 기록으로 합친다.
-- 예상 단계 변화는 최신 성공 run 안에서 지점별 기준일 순서로 직전 단계와 비교한다.
create or replace view v_event_log as
with latest_run as (
  select run_id from model_runs where status = 'success' order by run_at desc limit 1
), pred_seq as (
  select distinct on (p.site_id, p.base_date)
         p.site_id, p.base_date, p.tier, p.p_alert, p.q50, p.q90_cqr
  from predictions p join latest_run using (run_id)
  order by p.site_id, p.base_date, p.target_date desc
), pred_chg as (
  select site_id, base_date, tier,
         lag(tier) over (partition by site_id order by base_date) as prev_tier,
         p_alert, q50, q90_cqr
  from pred_seq
)
select (c.base_date::timestamp at time zone 'Asia/Seoul') + interval '9 hours' as event_time,  -- 기준일 09시(KST)
       c.base_date as event_date,
       'tier_change'::text as kind,
       c.site_id, s.name as site_name,
       c.prev_tier as tier_from, c.tier as tier_to,
       null::double precision as cell_count, null::smallint as alert_level,
       c.p_alert, c.q50, c.q90_cqr,
       null::text as status, null::text as notes
from pred_chg c join sites s using (site_id)
where c.prev_tier is distinct from c.tier
union all
select (o.obs_date::timestamp at time zone 'Asia/Seoul') + interval '12 hours' as event_time,  -- 측정일 정오(KST) 기준; fetched_at 은 일괄 적재 시각이라 쓰지 않음
       o.obs_date, 'observation', o.site_id, s.name,
       null, null, o.cell_count, o.alert_level, null, null, null, null, null
from observations o join sites s using (site_id)
union all
select r.run_at, (r.run_at at time zone 'Asia/Seoul')::date, 'run', null, null,
       null, null, null, null, null, null, null, r.status, r.notes
from model_runs r;
