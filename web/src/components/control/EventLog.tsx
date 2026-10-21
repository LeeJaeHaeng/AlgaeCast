"use client";

import { useEffect, useState } from "react";
import { BOARD } from "@/lib/copy";
import { fmtDateTimeKST } from "@/lib/format";

export type LogItem = { id: string; time: string; kind: "tier_change" | "observation" | "run"; text: string; tone: "alert" | "watch" | "normal" | "info" | "fail"; expertNote?: string };

const TONE: Record<LogItem["tone"], string> = { alert: "var(--alert)", watch: "var(--watch)", normal: "var(--safe)", info: "var(--accent)", fail: "var(--severe)" };

/** 실시간 상황 기록 — 지난 방문 이후 새로 들어온 줄은 3초 강조 */
export function EventLog({ items, expert }: { items: LogItem[]; expert: boolean }) {
  const [newIds, setNewIds] = useState<Set<string>>(new Set());
  useEffect(() => {
    try {
      const seen = new Set<string>(JSON.parse(localStorage.getItem("algaecast.log.seen") ?? "[]"));
      const fresh = items.filter((i) => !seen.has(i.id)).map((i) => i.id);
      if (seen.size > 0) setNewIds(new Set(fresh));
      localStorage.setItem("algaecast.log.seen", JSON.stringify(items.map((i) => i.id).slice(0, 200)));
    } catch {}
  }, [items]);
  return (
    <section className="panel flex min-h-0 flex-col p-3" aria-label={BOARD.panels.log} aria-live="polite">
      <h2 className="panel-title mb-2">{BOARD.panels.log}</h2>
      {items.length === 0 ? (
        <p className="text-sm text-dim">{BOARD.log.empty}</p>
      ) : (
        <ol className="scroll-thin min-h-0 flex-1 space-y-1 overflow-y-auto pr-1 text-sm">
          {items.map((it) => (
            <li key={it.id} className={`flex gap-2 rounded px-1 py-0.5 leading-snug ${newIds.has(it.id) ? "hl-new" : ""}`}>
              <time className="shrink-0 font-mono text-xs text-dim" dateTime={it.time}>
                {fmtDateTimeKST(it.time)}
              </time>
              <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ background: TONE[it.tone] }} aria-hidden />
              <span>
                {it.text}
                {expert && it.expertNote && <span className="ml-1 text-xs text-dim">{it.expertNote}</span>}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
