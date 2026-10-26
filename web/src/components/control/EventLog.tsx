"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { BOARD, LOG_MORE } from "@/lib/copy";
import { fmtDate, fmtDateTimeKST } from "@/lib/format";

export type LogItem = { id: string; time: string; kind: "tier_change" | "observation" | "run"; text: string; tone: "alert" | "watch" | "normal" | "info" | "fail"; expertNote?: string; dateOnly?: boolean };

const TONE: Record<LogItem["tone"], string> = { alert: "var(--alert)", watch: "var(--watch)", normal: "var(--safe)", info: "var(--accent)", fail: "var(--severe)" };
const LINE_PX = 26;

/**
 * 실시간 상황 기록 — 패널 높이에 들어가는 줄 수만 렌더(잘린 줄 없음), 나머지는 "이전 기록 n건" 링크(/log).
 * 지난 방문 이후 새로 들어온 줄은 3초 강조.
 * 다시 보기: persist=false(지난 화면이라 '새 기록' 강조·기억 없음), moreHref·title·emptyText 로 asof 유지·'그날까지' 문구.
 */
export function EventLog({ items, expert, fit = true, persist = true, moreHref, title, emptyText }: { items: LogItem[]; expert: boolean; fit?: boolean; persist?: boolean; moreHref?: string; title?: string; emptyText?: string }) {
  const [newIds, setNewIds] = useState<Set<string>>(new Set());
  const [max, setMax] = useState<number>(fit ? 8 : items.length);
  const listRef = useRef<HTMLOListElement>(null);
  useEffect(() => {
    if (!persist) return;
    try {
      const seen = new Set<string>(JSON.parse(localStorage.getItem("algaecast.log.seen") ?? "[]"));
      const fresh = items.filter((i) => !seen.has(i.id)).map((i) => i.id);
      if (seen.size > 0) setNewIds(new Set(fresh));
      localStorage.setItem("algaecast.log.seen", JSON.stringify(items.map((i) => i.id).slice(0, 200)));
    } catch {}
  }, [items, persist]);
  useEffect(() => {
    if (!fit) return;
    const el = listRef.current;
    if (!el) return;
    const measure = () => setMax(Math.max(1, Math.floor((el.clientHeight - LINE_PX) / LINE_PX)));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit]);
  const shown = fit ? items.slice(0, max) : items;
  const rest = items.length - shown.length;
  return (
    <section className="panel flex min-h-0 flex-col p-3" aria-label={title ?? BOARD.panels.log} aria-live="polite">
      <h2 className="panel-title mb-2">{title ?? BOARD.panels.log}</h2>
      {items.length === 0 ? (
        <p className="text-sm text-dim">{emptyText ?? BOARD.log.empty}</p>
      ) : (
        <ol ref={listRef} className="min-h-0 flex-1 overflow-hidden text-sm">
          {shown.map((it) => (
            <li key={it.id} className={`flex items-center gap-2 rounded px-1 ${newIds.has(it.id) ? "hl-new" : ""}`} style={{ height: LINE_PX }}>
              <time className="w-[5.6rem] shrink-0 whitespace-nowrap font-mono text-xs text-dim" dateTime={it.time}>
                {it.dateOnly ? fmtDate(it.time) : fmtDateTimeKST(it.time).replace(/\. /g, ".")}
              </time>
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: TONE[it.tone] }} aria-hidden />
              <span className="min-w-0 truncate">
                {it.text}
                {expert && it.expertNote && <span className="ml-1 text-xs text-dim">{it.expertNote}</span>}
              </span>
            </li>
          ))}
          {rest > 0 && (
            <li className="flex items-center px-1 text-xs" style={{ height: LINE_PX }}>
              <Link href={moreHref ?? (expert ? "/log?view=expert" : "/log")} className="underline" style={{ color: "var(--accent)" }}>
                {LOG_MORE(rest)}
              </Link>
            </li>
          )}
        </ol>
      )}
    </section>
  );
}
