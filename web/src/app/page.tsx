import { Suspense } from "react";
import { Actions, type ActionGroup } from "@/components/control/Actions";
import { ControlMap } from "@/components/control/ControlMap";
import { Escalation } from "@/components/control/Escalation";
import { EventLog } from "@/components/control/EventLog";
import { MiniChart } from "@/components/control/MiniChart";
import { Banner, ReplayScoreStrip, ReplayWeatherPanel, ScoreStrip, WeatherPanel } from "@/components/control/Panels";
import { ReplayBand, ReplayNotice } from "@/components/control/ReplayBand";
import { SiteTile } from "@/components/control/SiteTile";
import { TopBar, type Leds, type LedState } from "@/components/control/TopBar";
import { unstable_cache } from "next/cache";
import { BOARD, COMBO, REPLAY, comboOf } from "@/lib/copy";
import { toLogItems } from "@/lib/eventlog";
import { fmtDateTimeKST, fmtTimeKST, tierOf } from "@/lib/format";
import { getCollectStatus, getEventLog, getForecastAll, getLatestRunAny, getObsAfterAll, getPredictionsAllAsOf, getRecentObsAll, getReplayBounds, getReplayRun, getReplayTierSeed, getSiteStatus, getSites, getWeatherWindowAll, type ForecastLite, type ObsLite } from "@/lib/queries";
import { REPLAY_RUN_ID, afterWindow, buildStatusAsOf, mergeLogAsOf, obsAsOf, replayMinOf, replayQuery, replayState, summarizeWeatherAsOf, tierChangesAsOf, type Replay, type WeatherSummary } from "@/lib/replay";

export const revalidate = 300;

/** Supabase 조회는 60초 캐시 (화면 새로고침 5분·여러 화면이 동시에 열려도 DB 부하 일정) */
const getBoardData = unstable_cache(
  async () => {
    // 성적표 띠 숫자는 numbers.ts(빌드 전 대조) — DB model_metrics(v1 값)는 읽지 않는다
    const [status, sites, anyRun, events, obs, fc, collect] = await Promise.all([getSiteStatus(), getSites(), getLatestRunAny(), getEventLog(30, 80), getRecentObsAll(70), getForecastAll(), getCollectStatus()]);
    return { status, sites, anyRun, events, obs, fc, collect };
  },
  ["board-data"],
  { revalidate: 60, tags: ["board-data"] },
);

/** 다시 보기 범위(다시 보기 run 의 2026 첫 기준일 ~ 마지막 기준일) — asof 파라미터가 있을 때만 부른다 */
const getBounds = unstable_cache(async () => getReplayBounds((await getReplayRun())?.run_id ?? null), ["replay-bounds", REPLAY_RUN_ID], { revalidate: 300, tags: ["board-data"] });

/**
 * 다시 보기 자료: 관측은 관측일 ≤ asof, 예측은 기준일 ≤ asof 인 다시 보기 run(REPLAY_RUN_ID, 없으면 최신 run)의 지난 예상값(쿼리 단계에서 거름).
 * '그 뒤 실제로는'(after)을 켰을 때만 asof 뒤 21일 관측을 따로 가져온다. 인자(asof, after)가 캐시 키에 들어간다.
 * 상황 기록: 새 측정 기록은 뷰(v_event_log)에서, 예상 단계 변화는 같은 다시 보기 run 예측으로 만든다(타일·지도와 같은 run).
 * 날씨 칸: 예보(getForecastAll) 대신 그날까지 7일 ASOS 관측(getWeatherWindowAll, 그날−6 ~ 그날)을 지점별로 집계한다(summarizeWeatherAsOf).
 */
const getReplayBoardData = unstable_cache(
  async (asof: string, after: boolean) => {
    const run = await getReplayRun();
    const runId = run?.run_id ?? null;
    const [sites, preds, seed, obs120, obsLog, wxRows, afterObs] = await Promise.all([getSites(), getPredictionsAllAsOf(runId, asof), getReplayTierSeed(runId), getRecentObsAll(120, asof), getEventLog(30, 80, asof), getWeatherWindowAll(asof), after ? getObsAfterAll(asof) : Promise.resolve([] as ObsLite[])]);
    const status = buildStatusAsOf(sites, preds, obs120, asof);
    const events = mergeLogAsOf(obsLog, tierChangesAsOf(preds, seed, sites, asof), asof, 30, 80);
    const wx = summarizeWeatherAsOf(
      wxRows,
      sites.map((s) => s.site_id),
      asof,
    );
    return { status, sites, events, obs: obsAsOf(obs120, asof, 70), wx, afterObs };
  },
  ["board-replay", "log-from-run", "weather-obs", REPLAY_RUN_ID],
  { revalidate: 300, tags: ["board-data"] },
);

function age(h: number, iso: string | null): LedState {
  if (!iso) return "unknown";
  return Date.now() - new Date(iso).getTime() < h * 3600_000 ? "ok" : "stale";
}

export default async function Home({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const expert = sp.view === "expert";
  // 다시 보기(?asof=YYYY-MM-DD): 허용 범위 안이면 그날 화면, 형식이 틀리거나 범위 밖이면 현재 화면 + 한 줄 안내
  const bounds = sp.asof !== undefined && sp.asof !== "" ? await getBounds() : null;
  const rstate = bounds ? replayState(sp.asof, bounds) : "none";
  const replay: Replay | null = bounds && rstate === "ok" ? { asof: sp.asof as string, after: sp.after === "1" } : null;
  const notice = bounds && (rstate === "bad" || rstate === "range") ? REPLAY.notice(replayMinOf(bounds), bounds.max ?? "–") : null;
  const dbOk = true; // 조회 실패 시 Next 가 오류 화면을 내므로 여기 도달하면 저장소 정상
  const { status, sites, anyRun, events, obs, fc, wx, collect, afterObs } = replay
    ? { ...(await getReplayBoardData(replay.asof, replay.after)), anyRun: null, collect: { fetched_at: null, obs_date: null }, fc: [] as ForecastLite[] }
    : { ...(await getBoardData()), afterObs: [] as ObsLite[], wx: [] as WeatherSummary[] };
  const renderedAt = replay ? replay.asof : new Date().toISOString();
  const today = replay ? replay.asof : new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" });
  const lq = replay ? replayQuery({ replay, expert }) : undefined; // 다시 보기 안 링크: asof 유지
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
    return { site_id: s.site_id, name: s.name, lat: s.lat, lon: s.lon, tier: st?.tier ?? null, point: st?.pred_cell_count ?? null, p_alert: st?.p_alert ?? null, latest_alert_level: st?.latest_alert_level ?? null, latest_cell_count: st?.latest_cell_count ?? null };
  });
  const tiers = Object.fromEntries(status.map((s) => [s.site_id, tierOf(s.tier)]));
  const rotation = ["/", ...ranked.map((s) => `/sites/${s.site_id}`)];

  return (
    <div className={replay || notice ? "board board-replay" : "board"}>
      {replay && <ReplayBand replay={replay} path="/" expert={expert} />}
      {notice && <ReplayNotice text={notice} />}
      <Suspense fallback={<div className="h-14 border-b border-border bg-panel" />}>
        <TopBar leds={leds} renderedAt={renderedAt} rotation={rotation} expert={expert} replay={replay} />
      </Suspense>
      <Banner status={status} nextRefresh={nextRefresh} tail={replay ? REPLAY.bannerTail(replay.asof) : undefined} />
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
            <SiteTile key={s.site_id} s={s} expert={expert} rank={i + 1} today={today} linkQuery={lq} />
          ))}
        </section>
        {/* 중: 지도 */}
        <section className="panel order-3 min-h-[360px] overflow-hidden lg:order-2 2xl:min-h-0">
          <ControlMap sites={mapSites} expert={expert} linkQuery={lq} />
        </section>
        {/* 우: 오늘의 조치 + 실시간 상황 기록 */}
        <div className="order-2 grid min-h-0 min-w-0 gap-2 lg:order-3 2xl:grid-rows-[minmax(0,60%)_minmax(0,1fr)]">
          {replay ? (
            <>
              <Actions groups={actions} storageDay={`replay-${replay.asof}`} labels={{ title: REPLAY.panels.actions, reset: REPLAY.actionsReset, empty: REPLAY.actionsEmpty }} />
              <EventLog items={logItems} expert={expert} persist={false} moreHref={`/log${lq}`} title={REPLAY.panels.log} emptyText={REPLAY.logEmpty} />
            </>
          ) : (
            <>
              <Actions groups={actions} />
              <EventLog items={logItems} expert={expert} />
            </>
          )}
        </div>
        {/* 하: 지점 모니터 5분할 + 날씨 */}
        <section className="order-4 grid min-h-0 min-w-0 grid-cols-[repeat(2,minmax(0,1fr))] gap-2 md:grid-cols-[repeat(5,minmax(0,1fr))] lg:col-span-2" aria-label={BOARD.panels.monitors}>
          <h2 className="sr-only">{BOARD.panels.monitors}</h2>
          {ranked.map((s) => (
            <MiniChart key={s.site_id} s={s} obs={obs.filter((o) => o.site_id === s.site_id)} expert={expert} today={today} linkQuery={lq} after={replay?.after ? { obs: afterObs.filter((o) => o.site_id === s.site_id), to: afterWindow(replay.asof).to } : undefined} />
          ))}
        </section>
        <div className="order-5 min-h-0">
          {replay ? <ReplayWeatherPanel sites={ranked} wx={wx} asof={replay.asof} /> : <WeatherPanel sites={ranked} fc={fc} />}
        </div>
      </main>
      {replay ? <ReplayScoreStrip expert={expert} after={replay.after} /> : <ScoreStrip expert={expert} />}
      {!replay && <Escalation tiers={tiers} />}
    </div>
  );
}
