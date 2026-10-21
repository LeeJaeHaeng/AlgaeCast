"use client";

import { useEffect, useMemo, useState } from "react";
import { BOARD } from "@/lib/copy";

export type ActionItem = { id: string; site: string; tier: "normal" | "watch" | "alert"; text: string };

function kstToday(): string {
  return new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" });
}

/** 오늘의 조치 체크리스트 — 체크 상태는 브라우저(localStorage)에 날짜별로 저장 */
export function Actions({ items }: { items: ActionItem[] }) {
  const [done, setDone] = useState<Record<string, boolean>>({});
  const [day, setDay] = useState<string>("");
  const key = useMemo(() => `algaecast.actions.${day}`, [day]);
  useEffect(() => {
    const d = kstToday();
    setDay(d);
    try {
      setDone(JSON.parse(localStorage.getItem(`algaecast.actions.${d}`) ?? "{}"));
    } catch {
      setDone({});
    }
  }, []);
  const toggle = (id: string) => {
    const next = { ...done, [id]: !done[id] };
    setDone(next);
    try {
      localStorage.setItem(key, JSON.stringify(next));
    } catch {}
  };
  const reset = () => {
    setDone({});
    try {
      localStorage.removeItem(key);
    } catch {}
  };
  const n = items.filter((i) => done[i.id]).length;
  const color = { alert: "var(--alert)", watch: "var(--watch)", normal: "var(--safe)" } as const;
  return (
    <section className="panel flex min-h-0 flex-col p-3" aria-label={BOARD.panels.actions}>
      <header className="mb-2 flex items-center justify-between">
        <h2 className="panel-title">{BOARD.panels.actions}</h2>
        <span className="text-xs text-dim">
          {BOARD.actionsDone(n, items.length)}
          <button type="button" className="ml-2 underline opacity-70 hover:opacity-100" onClick={reset}>
            {BOARD.actionsReset}
          </button>
        </span>
      </header>
      {items.length === 0 ? (
        <p className="text-sm text-dim">{BOARD.actionsEmpty}</p>
      ) : (
        <ul className="scroll-thin min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1">
          {items.map((it) => (
            <li key={it.id}>
              <label className={`flex cursor-pointer items-start gap-2 rounded-md border border-border px-2 py-1.5 text-sm leading-snug ${done[it.id] ? "opacity-50" : ""}`}>
                <input type="checkbox" className="mt-1 h-4 w-4 accent-[var(--accent)]" checked={Boolean(done[it.id])} onChange={() => toggle(it.id)} />
                <span>
                  <span className="mr-1.5 font-semibold" style={{ color: color[it.tier] }}>
                    {it.site}
                  </span>
                  <span className={done[it.id] ? "line-through" : ""}>{it.text}</span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
