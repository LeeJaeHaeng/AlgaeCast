import Link from "next/link";
import { EventLog } from "@/components/control/EventLog";
import { ReplayBand, ReplayNotice } from "@/components/control/ReplayBand";
import { LOG_PAGE, REPLAY } from "@/lib/copy";
import { toLogItems } from "@/lib/eventlog";
import { getEventLog, getPredictionsAllAsOf, getReplayBounds, getReplayRun, getReplayTierSeed, getSites } from "@/lib/queries";
import { mergeLogAsOf, replayMinOf, replayQuery, replayState, tierChangesAsOf, type Replay } from "@/lib/replay";

export const revalidate = 300;

/**
 * 상황 기록 전체(최근 30일) — 메인의 "이전 기록 n건" 링크 대상.
 * 다시 보기(?asof): 그날까지 30일(날짜 ≤ asof), 파이프라인 갱신 기록은 빼고 '새 기록' 강조도 하지 않는다. 차트가 없어 '그 뒤 실제로는' 토글은 띠에서 뺀다.
 * 예상 단계 변화는 메인과 같이 다시 보기 run 예측으로 만든다(replay.ts tierChangesAsOf), 새 측정 기록만 뷰에서.
 */
export default async function LogPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const expert = sp.view === "expert";
  const runId = sp.asof !== undefined && sp.asof !== "" ? ((await getReplayRun())?.run_id ?? null) : null;
  const bounds = sp.asof !== undefined && sp.asof !== "" ? await getReplayBounds(runId) : null;
  const rstate = bounds ? replayState(sp.asof, bounds) : "none";
  const replay: Replay | null = bounds && rstate === "ok" ? { asof: sp.asof as string, after: sp.after === "1" } : null;
  const notice = bounds && (rstate === "bad" || rstate === "range") ? REPLAY.notice(replayMinOf(bounds), bounds.max ?? "–") : null;
  if (replay) {
    const [sites, preds, seed, obsLog] = await Promise.all([getSites(), getPredictionsAllAsOf(runId, replay.asof), getReplayTierSeed(runId), getEventLog(30, 500, replay.asof)]);
    const items = toLogItems(mergeLogAsOf(obsLog, tierChangesAsOf(preds, seed, sites, replay.asof), replay.asof, 30, 500));
    return (
      <>
        <ReplayBand replay={replay} path="/log" expert={expert} toggle={false} />
        <main className="mx-auto max-w-4xl space-y-4 p-4">
          <header className="flex items-center justify-between">
            <h1 className="text-2xl font-bold">{REPLAY.logTitle(replay.asof)}</h1>
            <Link href={`/${replayQuery({ replay, expert })}`} className="btn">
              {LOG_PAGE.back}
            </Link>
          </header>
          <EventLog items={items} expert={expert} fit={false} persist={false} title={REPLAY.panels.log} emptyText={REPLAY.logEmpty} />
        </main>
      </>
    );
  }
  const items = toLogItems(await getEventLog(30, 500));
  return (
    <>
      {notice && <ReplayNotice text={notice} />}
      <main className="mx-auto max-w-4xl space-y-4 p-4">
        <header className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">{LOG_PAGE.title}</h1>
          <Link href={expert ? "/?view=expert" : "/"} className="btn">
            {LOG_PAGE.back}
          </Link>
        </header>
        <EventLog items={items} expert={expert} fit={false} />
      </main>
    </>
  );
}
