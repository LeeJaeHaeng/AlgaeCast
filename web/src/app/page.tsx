import { Suspense } from "react";
import { Actions, type ActionGroup } from "@/components/control/Actions";
import { ControlMap } from "@/components/control/ControlMap";
import { Escalation } from "@/components/control/Escalation";
import { EventLog } from "@/components/control/EventLog";
import { MiniChart } from "@/components/control/MiniChart";
import { Banner, ScoreStrip, WeatherPanel } from "@/components/control/Panels";
import { SiteTile } from "@/components/control/SiteTile";
import { TopBar, type Leds, type LedState } from "@/components/control/TopBar";
import { unstable_cache } from "next/cache";
import { BOARD, COMBO, comboOf } from "@/lib/copy";
import { toLogItems } from "@/lib/eventlog";
import { fmtDateTimeKST, fmtTimeKST, tierOf } from "@/lib/format";
import { getCollectStatus, getEventLog, getForecastAll, getLatestRunAny, getMetrics, getRecentObsAll, getSiteStatus, getSites } from "@/lib/queries";

export const revalidate = 300;

/** Supabase 조회는 60초 캐시 (화면 새로고침 5분·여러 화면이 동시에 열려도 DB 부하 일정) */
const getBoardData = unstable_cache(
  async () => {
    const [status, sites, anyRun, events, obs, fc, metrics, collect] = await Promise.all([getSiteStatus(), getSites(), getLatestRunAny(), getEventLog(30, 80), getRecentObsAll(70), getForecastAll(), getMetrics(), getCollectStatus()]);
    return { status, sites, anyRun, events, obs, fc, metrics, collect };
  },
  ["board-data"],
  { revalidate: 60, tags: ["board-data"] },
);

function age(h: number, iso: string | null): LedState {
  if (!iso) return "unknown";
  return Date.now() - new Date(iso).getTime() < h * 3600_000 ? "ok" : "stale";
}

export default async function Home({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const expert = sp.view === "expert";
  const dbOk = true; // 조회 실패 시 Next 가 오류 화면을 내므로 여기 도달하면 저장소 정상
  const { status, sites, anyRun, events, obs, fc, metrics, collect } = await getBoardData();
  const renderedAt = new Date().toISOString();
  const today = new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" });
  const nextRefresh = fmtTimeKST(new Date(Date.now() + 5 * 60_000));

  // 우선순위 = 공식 발령×AI 예상 조합 순위 → 가능성 내림차순 (가중치 없음, docs/07·docs/12 §8.4)
  const rankOf = (s: (typeof status)[number]) => COMBO[comboOf(s.latest_alert_level, tierOf(s.tier))].rank;
  const ranked = [...status].sort((a, b) => rankOf(a) - rankOf(b) || (b.p_alert ?? 0) - (a.p_alert ?? 0));
  const latestBase = status.map((s) => s.base_date).filter(Boolean).sort().at(-1) ?? null;
  const latestObs = status.map((s) => s.latest_obs_date).filter(Boolean).sort().at(-1) ?? null;
  const leds: Leds = {
    collect: age(24, collect.fetched_at),
    predict: anyRun?.status === "failed" ? "fail" : latestBase && latestObs && latestBase >= latestObs ? "ok" : age(24, anyRun?.run_at ?? null),
    db: dbOk ? "ok" : "fail",
  };

  const actions: ActionGroup[] = ranked.map((s) => {
    const combo = comboOf(s.latest_alert_level, tierOf(s.tier));
    return { siteId: s.site_id, site: s.name, combo, items: COMBO[combo].actions.map((text, i) => ({ id: `${s.site_id}-${combo}-${i}`, text })) };
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
      <main className="grid min-h-0 grid-cols-[minmax(0,1fr)] gap-2 p-2 lg:grid-cols-[380px_minmax(0,1fr)_440px] 2xl:grid-rows-[minmax(0,1fr)_minmax(0,250px)]">
        {/* 좌: 지점 현황 */}
        <section className="order-1 flex min-h-0 min-w-0 flex-col gap-1.5 lg:row-span-1" aria-label={BOARD.panels.sites}>
          <h2 className="sr-only">{BOARD.panels.sites}</h2>
          {ranked.map((s, i) => (
            <SiteTile key={s.site_id} s={s} expert={expert} rank={i + 1} today={today} />
          ))}
        </section>
        {/* 중: 지도 */}
        <section className="panel order-3 min-h-[360px] overflow-hidden lg:order-2 2xl:min-h-0">
          <ControlMap sites={mapSites} expert={expert} />
        </section>
        {/* 우: 오늘의 조치 + 실시간 상황 기록 */}
        <div className="order-2 grid min-h-0 min-w-0 gap-2 lg:order-3 2xl:grid-rows-[minmax(0,60%)_minmax(0,1fr)]">
          <Actions groups={actions} />
          <EventLog items={logItems} expert={expert} />
        </div>
        {/* 하: 지점 모니터 5분할 + 날씨 */}
        <section className="order-4 grid min-h-0 min-w-0 grid-cols-[repeat(2,minmax(0,1fr))] gap-2 md:grid-cols-[repeat(5,minmax(0,1fr))] lg:col-span-2" aria-label={BOARD.panels.monitors}>
          <h2 className="sr-only">{BOARD.panels.monitors}</h2>
          {ranked.map((s) => (
            <MiniChart key={s.site_id} s={s} obs={obs.filter((o) => o.site_id === s.site_id)} expert={expert} today={today} />
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
