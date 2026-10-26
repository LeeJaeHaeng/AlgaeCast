"use client";

import { useEffect, useRef } from "react";
import { placeTip } from "@/lib/tip";

/**
 * ⓘ 버튼 + 설명 상자(클라이언트) — 마우스 올림/포커스 시 보임(키보드 접근 가능, 보이기·숨기기는 CSS).
 * 설명 상자는 화면 기준 고정 위치(position: fixed)라 평소(투명)에는 문서 폭·높이에 잡히지 않는다
 * (예전 absolute 상자는 오른쪽 끝 ⓘ 에서 화면 밖까지 나가 1350·1366 폭 페이지를 가로로 넘치게 했다).
 * 열릴 때(마우스 올림·포커스)와 열린 채 스크롤·창 크기 변경 때 lib/tip.placeTip 으로 위치를 다시 잡는다.
 * 문구(tip)는 서버 쪽 Info 가 넘긴다 — copy.ts 가 페이지 클라이언트 묶음에 들어가지 않게.
 */
export function InfoTip({ tip, className = "" }: { tip: string; className?: string }) {
  const wrapRef = useRef<HTMLSpanElement>(null);
  const tipRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const wrap = wrapRef.current;
    const box = tipRef.current;
    if (!wrap || !box) return;
    const place = () => {
      const de = document.documentElement;
      const { x, y } = placeTip(wrap.getBoundingClientRect(), { width: box.offsetWidth, height: box.offsetHeight }, { width: de.clientWidth, height: de.clientHeight });
      box.style.setProperty("--tip-x", `${x}px`);
      box.style.setProperty("--tip-y", `${y}px`);
    };
    const placeIfOpen = () => {
      if (wrap.matches(":hover, :focus-within")) place();
    };
    wrap.addEventListener("pointerenter", place);
    wrap.addEventListener("focusin", place);
    window.addEventListener("scroll", placeIfOpen, { capture: true, passive: true });
    window.addEventListener("resize", placeIfOpen, { passive: true });
    return () => {
      wrap.removeEventListener("pointerenter", place);
      wrap.removeEventListener("focusin", place);
      window.removeEventListener("scroll", placeIfOpen, { capture: true });
      window.removeEventListener("resize", placeIfOpen);
    };
  }, []);

  return (
    <span ref={wrapRef} className={`group relative inline-block align-middle ${className}`}>
      <button type="button" className="ml-1 inline-flex h-5 w-5 items-center justify-center rounded-full border border-current text-[11px] leading-none text-dim hover:text-text focus:text-text" aria-label={`설명: ${tip}`}>
        i
      </button>
      {/* 좌표는 CSS 변수로만 — 좁은 화면 지점 상세(globals.css .site-detail ≤767px)는 화면 아래 고정 상자 규칙이 그대로 덮어씀 */}
      <span ref={tipRef} role="tooltip" className="pointer-events-none fixed left-(--tip-x) top-(--tip-y) z-50 w-64 max-w-[calc(100vw-1rem)] rounded-lg border border-border bg-panel p-2 text-left text-xs font-normal leading-relaxed text-text opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        {tip}
      </span>
    </span>
  );
}
