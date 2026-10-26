"use client";

import Link from "next/link";
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { REPLAY } from "@/lib/copy";
import { SCENES, replayQuery } from "@/lib/replay";

/**
 * 진입 버튼 크기(글자는 어느 크기든 '다시 보기'): md = 다른 버튼과 같음(13px),
 * sm = 11px·좁은 여백, xs = 10px 두 줄('다시'/'보기') — 상단 빈 자리가 좁은 폭에서만(ReplayEntry 가 고름)
 */
export type EntrySize = "md" | "sm" | "xs";
export const ENTRY_SIZE_STYLE: Record<EntrySize, CSSProperties> = {
  md: {},
  sm: { fontSize: "11px", padding: "4px 4px" },
  xs: { fontSize: "10px", lineHeight: "11px", padding: "1px 3px", width: "min-content", whiteSpace: "normal", wordBreak: "keep-all", textAlign: "center" },
};
// 값은 문자열(px 포함)로 둔다 — ReplayEntry 가 복제본 style 에 그대로 넣어 크기를 재기 때문(DOM style 에 숫자를 넣으면 무시됨)

/**
 * '다시 보기' 진입점: 버튼(.btn) 하나 + 눌렀을 때 장면 3개 목록(떠 있는 상자라 배치를 밀지 않음).
 * 기본 화면에서는 ReplayEntry 가 빈 자리에 띄우고, 다시 보기 화면에서는 상단 바 버튼 줄에 그대로 놓는다.
 * 목록 상자는 버튼 오른쪽 끝에 맞추되 화면 폭 안(좌우 8px)으로 보정한다 — 좁은 화면에서 왼쪽 밖으로 열리지 않게.
 */
export function ReplayMenu({ expert, current, className = "", size = "md" }: { expert: boolean; current?: string | null; className?: string; size?: EntrySize }) {
  const [open, setOpen] = useState(false);
  const [menuLeft, setMenuLeft] = useState<number | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  // 목록 상자 가로 자리: 버튼 오른쪽 끝 정렬 → 화면 안으로 보정(상자 기준 left px)
  useLayoutEffect(() => {
    if (!open) {
      setMenuLeft(null);
      return;
    }
    const place = () => {
      const box = ref.current?.getBoundingClientRect();
      const m = menuRef.current;
      if (!box || !m) return;
      const vw = document.documentElement.clientWidth;
      const w = m.offsetWidth;
      const left = Math.min(Math.max(8, box.right - w), vw - 8 - w);
      setMenuLeft(Math.round(left - box.left));
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open]);
  return (
    <div ref={ref} className={`relative ${className}`}>
      <button type="button" className={size === "xs" ? "btn" : "btn whitespace-nowrap"} style={ENTRY_SIZE_STYLE[size]} aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen(!open)} data-active={current ? "true" : undefined}>
        {REPLAY.button}
      </button>
      {open && (
        <div
          ref={menuRef}
          role="menu"
          aria-label={REPLAY.menuTitle}
          className="absolute top-full z-[1100] mt-1 w-80 max-w-[calc(100vw-1rem)] rounded-lg border border-[var(--replay)] bg-panel p-2 text-left shadow-lg"
          style={{ left: menuLeft ?? 0, visibility: menuLeft == null ? "hidden" : undefined }}
          data-replay-menu
        >
          <div className="px-1 text-sm font-semibold">{REPLAY.menuTitle}</div>
          <p className="mb-1 px-1 text-xs leading-relaxed text-dim">{REPLAY.menuLead}</p>
          <ul className="space-y-1">
            {SCENES.map((s, i) => {
              const c = REPLAY.scenes[s.id];
              return (
                <li key={s.id}>
                  <Link
                    role="menuitem"
                    href={`/${replayQuery({ replay: { asof: s.asof, after: false }, expert })}`}
                    onClick={() => setOpen(false)}
                    className="block rounded-md border border-border px-2 py-1 hover:border-[var(--replay)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--replay)]"
                    aria-current={current === s.asof ? "page" : undefined}
                  >
                    <span className="block text-sm font-semibold">
                      {REPLAY.sceneNo[i]} {c.title}
                    </span>
                    <span className="block text-xs text-dim">
                      {s.asof} · {c.sub}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
