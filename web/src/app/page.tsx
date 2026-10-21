import { Suspense } from "react";
import { Actions, type ActionItem } from "@/components/control/Actions";
import { ControlMap } from "@/components/control/ControlMap";
import { Escalation } from "@/components/control/Escalation";
import { EventLog } from "@/components/control/EventLog";
import { MiniChart } from "@/components/control/MiniChart";
import { Banner, ScoreStrip, WeatherPanel } from "@/components/control/Panels";
import { SiteTile } from "@/components/control/SiteTile";
import { TopBar, type Leds, type LedState } from "@/components/control/TopBar";
import { ACTIONS, BOARD } from "@/lib/copy";
import { toLogItems } from "@/lib/eventlog";
import { TIER_ORDER, fmtDateTimeKST, fmtTimeKST, tierOf } from "@/lib/format";
import { getCollectStatus, getEventLog, getForecastAll, getLatestRunAny, getMetrics, getRecentObsAll, getSiteStatus, getSites } from "@/lib/queries";

export const revalidate = 300;

function age(h: number, iso: string | null): LedState {
  if (!iso) return "unknown";
  return Date.now() - new Date(iso).getTime() < h * 3600_000 ? "ok" : "stale";
}

export default async function Home({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const expert = sp.view === "expert";
  let dbOk = true;
  const [status, sites, anyRun, events, obs, fc, metrics, collect] = await Promise.all([getSiteStatus(), getSites(), getLatestRunAny(), getEventLog(30, 80), getRecentObsAll(70), getForecastAll(), getMetrics(), getCollectStatus()]).catch((e) => {
    dbOk = false;
    throw e;
  });
  const renderedAt = new Date().toISOString();
  const nextRefresh = fmtTimeKST(new Date(Date.now() + 5 * 60_000));

  // 우선순위 = 단계 → 경계 넘을 가능성 (가중치 없음, docs/07)
  const ranked = [...status].sort((a, b) => TIER_ORDER[tierOf(a.tier)] - TIER_ORDER[tierOf(b.tier)] || (b.p_alert ?? 0) - (a.p_alert ?? 0));
  const latestBase = status.map((s) => s.base_date).filter(Boolean).sort().at(-1) ?? null;
  const latestObs = status.map((s) => s.latest_obs_date).filter(Boolean).sort().at(-1) ?? null;
  const leds: Leds = {
    collect: age(24, collect.fetched_at),
    predict: anyRun?.status === "failed" ? "fail" : latestBase && latestObs && latestBase >= latestObs ? "ok" : age(24, anyRun?.run_at ?? null),
    db: dbOk ? "ok" : "fail",
  };

  const actions: ActionItem[] = ranked.flatMap((s) => {
    const t = tierOf(s.tier);
    return ACTIONS[t].map((text, i) => ({ id: `${s.site_id}-${t}-${i}`, site: s.name, tier: t, text }));
  });
  const logItems = toLogItems(events);
  const mapSites = sites.map((s) => {
    const st = status.find((x) => x.site_id === s.site_id);
    return { site_id: s.site_id, name: s.name, lat: s.lat, lon: s.lon, tier: st?.tier ?? null, q50: st?.q50 ?? null, p_alert: st?.p_alert ?? null, latest_alert_level: st?.latest_alert_level ?? null, latest_cell_count: st?.latest_cell_count ?? null };
  });
  const tiers = Object.fromEntries(status.map((s) => [s.site_id, tierOf(s.tier)]));
  const rotation = ["/", ...ranked.map((s) => `/sites/${s.site_id}`)];

  return (
    <div className="board">
      <Suspense fallback={<div className="h-14 border-b border-border bg-panel" />}>
        <TopBar leds={leds} renderedAt={renderedAt} rotation={rotation} expert={expert} />
      </Suspense>
      <Banner status={status} nextRefresh={nextRefresh} />
      {anyRun?.status === "failed" && (
        <div className="border-b border-[var(--severe)] bg-[color-mix(in_srgb,var(--severe)_20%,var(--bg))] px-4 py-1 text-sm" role="alert">
          {BOARD.failBanner(fmtDateTimeKST(anyRun.run_at))}
        </div>
      )}
      <main className="grid min-h-0 grid-cols-1 gap-2 p-2 lg:grid-cols-[380px_minmax(0,1fr)_440px] lg:grid-rows-[minmax(0,1fr)_minmax(0,300px)]">
        {/* 좌: 지점 현황 */}
        <section className="order-1 flex min-h-0 flex-col gap-2 lg:row-span-1" aria-label={BOARD.panels.sites}>
          <h2 className="sr-only">{BOARD.panels.sites}</h2>
          {ranked.map((s, i) => (
            <SiteTile key={s.site_id} s={s} expert={expert} rank={i + 1} />
          ))}
        </section>
        {/* 중: 지도 */}
        <section className="panel order-3 min-h-[320px] overflow-hidden lg:order-2 lg:min-h-0">
          <ControlMap sites={mapSites} expert={expert} />
        </section>
        {/* 우: 오늘의 조치 + 실시간 상황 기록 */}
        <div className="order-2 grid min-h-0 grid-rows-[minmax(0,44%)_minmax(0,1fr)] gap-2 lg:order-3">
          <Actions items={actions} />
          <EventLog items={logItems} expert={expert} />
        </div>
        {/* 하: 지점 모니터 5분할 + 날씨 */}
        <section className="order-4 grid min-h-0 grid-cols-2 gap-2 md:grid-cols-5 lg:col-span-2" aria-label={BOARD.panels.monitors}>
          <h2 className="sr-only">{BOARD.panels.monitors}</h2>
          {ranked.map((s) => (
            <MiniChart key={s.site_id} s={s} obs={obs.filter((o) => o.site_id === s.site_id)} expert={expert} />
          ))}
        </section>
        <div className="order-5 min-h-0">
          <WeatherPanel sites={ranked} fc={fc} />
        </div>
      </main>
      <ScoreStrip metrics={metrics} expert={expert} />
      <Escalation tiers={tiers} />
    </div>
  );
}
