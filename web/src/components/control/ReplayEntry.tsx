"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ENTRY_SIZE_STYLE, ReplayMenu, type EntrySize } from "./ReplayMenu";

type Box = { l: number; t: number; r: number; b: number };
type Spot = { left: number; top: number; size: EntrySize; at: string };

/** 다른 요소와 띄울 간격(px): 가로 8, 세로 1, 화면 가장자리 4 */
const GAP_X = 8;
const GAP_Y = 1;
const EDGE = 4;
const SIZES: EntrySize[] = ["md", "sm", "xs"];

const boxOf = (r: DOMRect): Box => ({ l: r.left, t: r.top, r: r.right, b: r.bottom });
const visible = (e: Element) => {
  const cs = getComputedStyle(e);
  return cs.display !== "none" && cs.visibility !== "hidden";
};

/**
 * 기본 메인 화면의 '다시 보기' 진입 버튼 — 상단 바·상황 배너의 빈 자리를 재서 그 위에 띄운다(절대 위치, 상단 바·배너 배치는 그대로).
 * 후보(앞이 우선, 크기는 md → sm → xs 순): ① 상단 바 상태 LED 바로 오른쪽 ② 제목 줄 오른쪽 끝 ③ 버튼 줄 바로 오른쪽
 * ④ 상황 배너 오른쪽(조합별 개수가 보이면 그 왼쪽). 후보 상자가 화면 밖으로 나가거나(가로 넘침) 글자·버튼·LED·배너 문구와
 * 겹치면 버린다. 모두 안 되면 지도 오른쪽 위. 폭·글꼴·배너 문구가 바뀌면(크기 변화·글꼴 로드) 다시 잰다.
 * 처음 잴 때까지는 보이지 않는다(visibility hidden). 키오스크·다시 보기 화면에서는 쓰지 않는다(TopBar).
 */
export function ReplayEntry({ expert }: { expert: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [spot, setSpot] = useState<Spot | null>(null);

  const measure = useCallback(() => {
    const el = ref.current;
    const header = document.querySelector<HTMLElement>('header[role="banner"]');
    const btn = el?.querySelector<HTMLElement>("button");
    if (!el || !header || !btn) return;
    const sib = header.nextElementSibling;
    const banner = sib instanceof HTMLElement && sib.getAttribute("role") === "status" ? sib : null;
    const W = document.documentElement.clientWidth;

    // 크기별 버튼 폭·높이: 숨긴 복제본으로 잰다(지금 버튼은 그대로)
    const dims = {} as Record<EntrySize, { w: number; h: number }>;
    for (const s of SIZES) {
      const c = btn.cloneNode(true) as HTMLElement;
      c.removeAttribute("style");
      Object.assign(c.style, ENTRY_SIZE_STYLE[s], { position: "absolute", left: "0px", top: "0px", visibility: "hidden" });
      c.className = s === "xs" ? "btn" : "btn whitespace-nowrap";
      document.body.appendChild(c);
      const r = c.getBoundingClientRect();
      dims[s] = { w: Math.ceil(r.width), h: Math.ceil(r.height) };
      c.remove();
    }

    // 장애물: 상단 바의 보이는 글자·버튼·LED(줄바꿈으로 배너 쪽에 넘친 줄 포함), 배너의 아이콘·문구(줄임표로 잘린 부분은 보이는 만큼)·개수
    const obstacles: Box[] = [];
    for (const e of header.querySelectorAll<HTMLElement>("a, button, time, span, .led")) {
      if (el.contains(e) || e.classList.contains("sr-only") || !visible(e)) continue;
      const r = e.getBoundingClientRect();
      if (r.width >= 1 && r.height >= 1) obstacles.push(boxOf(r));
    }
    let counts: DOMRect | null = null;
    if (banner) {
      for (const e of banner.querySelectorAll<HTMLElement>("span")) {
        if (!visible(e)) continue;
        const r = e.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) continue;
        const rg = document.createRange();
        rg.selectNodeContents(e);
        const t = rg.getBoundingClientRect();
        obstacles.push({ l: Math.max(r.left, t.left), r: Math.min(r.right, t.right), t: t.height ? t.top : r.top, b: t.height ? t.bottom : r.bottom });
      }
      const last = banner.lastElementChild;
      if (last && last !== banner.firstElementChild && visible(last)) {
        const r = last.getBoundingClientRect();
        if (r.width >= 1) counts = r;
      }
    }

    const hr = header.getBoundingClientRect();
    const br = banner?.getBoundingClientRect() ?? null;
    const bottom = br ? br.bottom : hr.bottom; // 상단(상단 바 + 배너) 안에서만
    const leds = header.querySelector<HTMLElement>('[aria-label="시스템 상태"]')?.getBoundingClientRect() ?? null;
    const title = header.querySelector<HTMLElement>("a")?.getBoundingClientRect() ?? null;
    const nav = header.querySelector<HTMLElement>("nav")?.getBoundingClientRect() ?? null;
    const mid = (r: DOMRect) => (r.top + r.bottom) / 2;
    const cands: { at: string; x: (w: number) => number; cy: number }[] = [];
    if (leds && leds.width) cands.push({ at: "bar-leds", x: () => leds.right + 16, cy: mid(leds) });
    if (title && title.width) cands.push({ at: "bar-title", x: (w) => W - 16 - w, cy: mid(title) });
    if (nav && nav.width) cands.push({ at: "bar-nav", x: () => nav.right + GAP_X, cy: mid(nav) });
    if (br) cands.push({ at: "banner", x: (w) => (counts ? counts.left - 16 : br.right - 8) - w, cy: mid(br) });

    const free = (b: Box) =>
      b.l >= EDGE && b.r <= W - EDGE && b.t >= hr.top && b.b <= bottom && !obstacles.some((o) => b.l - GAP_X < o.r && b.r + GAP_X > o.l && b.t - GAP_Y < o.b && b.b + GAP_Y > o.t);

    let pick: { l: number; t: number; size: EntrySize; at: string } | null = null;
    for (const size of SIZES) {
      const { w, h } = dims[size];
      for (const c of cands) {
        const l = Math.round(c.x(w));
        const t = Math.round(c.cy - h / 2);
        if (free({ l, t, r: l + w, b: t + h })) {
          pick = { l, t, size, at: c.at };
          break;
        }
      }
      if (pick) break;
    }
    if (!pick) {
      // 상단에 자리가 없으면 지도 오른쪽 위(지도 범례는 왼쪽 위)
      const map = document.querySelector<HTMLElement>('main [role="region"]')?.getBoundingClientRect();
      if (!map) return;
      pick = { l: Math.round(map.right - 8 - dims.md.w), t: Math.round(map.top + 8), size: "md", at: "map" };
    }
    // 화면 좌표 → 절대 위치 기준(위치 지정된 조상이 없으면 문서 좌표)
    const op = el.offsetParent as HTMLElement | null;
    const base = op && op !== document.body ? op.getBoundingClientRect() : null;
    const left = base ? pick.l - base.left - (op?.clientLeft ?? 0) : pick.l + window.scrollX;
    const top = base ? pick.t - base.top - (op?.clientTop ?? 0) : pick.t + window.scrollY;
    setSpot((s) => (s && s.left === left && s.top === top && s.size === pick.size && s.at === pick.at ? s : { left, top, size: pick.size, at: pick.at }));
  }, []);

  useLayoutEffect(() => {
    measure();
  }, [measure]);
  useEffect(() => {
    let raf = 0;
    const again = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(measure);
    };
    window.addEventListener("resize", again);
    document.fonts?.ready.then(again).catch(() => {});
    document.fonts?.addEventListener?.("loadingdone", again);
    const ro = new ResizeObserver(again);
    const header = document.querySelector<HTMLElement>('header[role="banner"]');
    if (header) {
      ro.observe(header);
      for (const c of header.children) if (c !== ref.current) ro.observe(c);
      const sib = header.nextElementSibling;
      if (sib instanceof HTMLElement && sib.getAttribute("role") === "status") {
        ro.observe(sib);
        sib.querySelectorAll("span, div").forEach((e) => ro.observe(e));
      }
    }
    const late = window.setTimeout(again, 1600); // 발표모드 글꼴 지연 로드(layout.tsx 1.5초) 뒤 한 번 더
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", again);
      document.fonts?.removeEventListener?.("loadingdone", again);
      ro.disconnect();
      window.clearTimeout(late);
    };
  }, [measure]);

  return (
    <div
      ref={ref}
      className="z-[1100]"
      style={{ position: "absolute", left: spot?.left ?? 0, top: spot?.top ?? 0, visibility: spot ? undefined : "hidden" }}
      data-replay-entry
      data-entry-at={spot?.at}
      data-entry-size={spot?.size}
    >
      <ReplayMenu expert={expert} size={spot?.size ?? "md"} />
    </div>
  );
}
