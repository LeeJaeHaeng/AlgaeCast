import Link from "next/link";
import { EventLog } from "@/components/control/EventLog";
import { LOG_PAGE } from "@/lib/copy";
import { toLogItems } from "@/lib/eventlog";
import { getEventLog } from "@/lib/queries";

export const revalidate = 300;

/** 상황 기록 전체(최근 30일) — 메인의 "이전 기록 n건" 링크 대상 */
export default async function LogPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const expert = sp.view === "expert";
  const items = toLogItems(await getEventLog(30, 500));
  return (
    <main className="mx-auto max-w-4xl space-y-4 p-4">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">{LOG_PAGE.title}</h1>
        <Link href={expert ? "/?view=expert" : "/"} className="btn">
          {LOG_PAGE.back}
        </Link>
      </header>
      <EventLog items={items} expert={expert} fit={false} />
    </main>
  );
}
