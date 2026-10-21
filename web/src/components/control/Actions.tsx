"use client";

import { useEffect, useMemo, useState } from "react";
import { BOARD, COMBO, type Combo } from "@/lib/copy";

export type ActionGroup = { siteId: string; site: string; combo: Combo; items: { id: string; text: string }[] };
const SHOW = 2;

function kstToday(): string {
  return new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" });
}

/** 오늘의 조치 — 지점별 묶음, 지점당 2줄 + 더 보기. 체크 상태는 브라우저(localStorage)에 날짜별 저장 */
export function Actions({ groups }: { groups: ActionGroup[] }) {
  const [done, setDone] = useState<Record<string, boolean>>({});
  const [open, setOpen] = useState<Record<string, boolean>>({});
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
  const all = groups.flatMap((g) => g.items);
  const n = all.filter((i) => done[i.id]).length;
  return (
    <section className="panel flex min-h-0 flex-col p-3" aria-label={BOARD.panels.actions}>
      <header className="mb-1 flex items-center justify-between">
        <h2 className="panel-title">{BOARD.panels.actions}</h2>
        <span className="text-xs text-dim">
          {BOARD.actionsDone(n, all.length)}
          <button type="button" className="ml-2 underline opacity-70 hover:opacity-100" onClick={reset}>
            {BOARD.actionsReset}
          </button>
        </span>
      </header>
      {all.length === 0 ? (
        <p className="text-sm text-dim">{BOARD.actionsEmpty}</p>
      ) : (
        <ul className="scroll-thin min-h-0 flex-1 space-y-0.5 overflow-y-auto pr-1" style={{ scrollSnapType: "y proximity" }}>
          {groups.map((g) => {
            const c = COMBO[g.combo];
            const shown = open[g.siteId] ? g.items : g.items.slice(0, SHOW);
            const rest = g.items.length - SHOW;
            return (
              <li key={g.siteId} className="rounded-md border border-border px-2 py-0.5">
                <div className="flex items-center justify-between text-[13px] leading-5">
                  <span className="font-semibold" style={{ color: c.color }}>
                    {c.icon} {g.site} <span className="font-normal opacity-80">{c.label}</span>
                  </span>
                  {rest > 0 && (
                    <button type="button" className="text-xs underline text-dim hover:text-text" onClick={() => setOpen({ ...open, [g.siteId]: !open[g.siteId] })} aria-expanded={Boolean(open[g.siteId])}>
                      {open[g.siteId] ? BOARD.actionsLess : BOARD.actionsMore(rest)}
                    </button>
                  )}
                </div>
                <ul>
                  {shown.map((it) => (
                    <li key={it.id}>
                      <label className={`flex cursor-pointer items-center gap-2 text-[13px] leading-5 ${done[it.id] ? "opacity-50" : ""}`}>
                        <input type="checkbox" className="h-4 w-4 shrink-0 accent-[var(--accent)]" checked={Boolean(done[it.id])} onChange={() => toggle(it.id)} />
                        <span className={`truncate ${done[it.id] ? "line-through" : ""}`}>{it.text}</span>
                      </label>
                    </li>
                  ))}
                </ul>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
