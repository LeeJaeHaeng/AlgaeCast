"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { APP, BOARD } from "@/lib/copy";
import { fmtDateTimeKST } from "@/lib/format";

export type LedState = "ok" | "stale" | "fail" | "unknown";
export type Leds = { collect: LedState; predict: LedState; db: LedState };

const LED_COLOR: Record<LedState, string> = { ok: "var(--safe)", stale: "var(--watch)", fail: "var(--severe)", unknown: "var(--text-dim)" };
const REFRESH_MS = 5 * 60 * 1000;
const KIOSK_MS = 30 * 1000;

function clockText(d: Date) {
  return d.toLocaleString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit", weekday: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: "Asia/Seoul" });
}

/**
 * 상단 바(56px): 제목 · 상태 LED 3개 · 초 단위 시계 · 마지막/다음 갱신 · 전체화면/발표모드/순환/보기 전환.
 * 5분 자동 갱신(router.refresh), 키오스크(?kiosk=1) 30초 순환, 발표모드(data-theme=light) 는 localStorage 에 기억.
 */
export function TopBar({ leds, renderedAt, rotation, expert }: { leds: Leds; renderedAt: string; rotation: string[]; expert: boolean }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const kiosk = params.get("kiosk") === "1";
  const [now, setNow] = useState<Date | null>(null);
  const [nextAt, setNextAt] = useState<number>(() => Date.now() + REFRESH_MS);
  const [light, setLight] = useState(false);
  const [fs, setFs] = useState(false);
  const refreshTimer = useRef<number | null>(null);

  // 시계(1초)
  useEffect(() => {
    setNow(new Date());
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  // 5분 자동 갱신
  const doRefresh = useCallback(() => {
    router.refresh();
    setNextAt(Date.now() + REFRESH_MS);
  }, [router]);
  useEffect(() => {
    refreshTimer.current = window.setInterval(doRefresh, REFRESH_MS);
    return () => {
      if (refreshTimer.current) window.clearInterval(refreshTimer.current);
    };
  }, [doRefresh]);

  // 발표모드 기억
  useEffect(() => {
    try {
      const saved = localStorage.getItem("algaecast.theme");
      if (saved === "light") {
        setLight(true);
        document.documentElement.dataset.theme = "light";
      }
    } catch {}
    const onFs = () => setFs(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);
  const toggleLight = () => {
    const v = !light;
    setLight(v);
    document.documentElement.dataset.theme = v ? "light" : "dark";
    try {
      localStorage.setItem("algaecast.theme", v ? "light" : "dark");
    } catch {}
  };
  const toggleFs = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch {}
  };

  // 키오스크 순환: 메인 → 지점들 → 메인
  useEffect(() => {
    if (!kiosk || rotation.length === 0) return;
    const idx = rotation.indexOf(pathname);
    const next = rotation[(idx + 1) % rotation.length];
    const id = window.setTimeout(() => router.push(`${next}?kiosk=1${expert ? "&view=expert" : ""}`), KIOSK_MS);
    return () => window.clearTimeout(id);
  }, [kiosk, pathname, rotation, router, expert]);

  const q = (patch: Record<string, string | null>) => {
    const p = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) p.delete(k);
      else p.set(k, v);
    }
    const s = p.toString();
    return `${pathname}${s ? `?${s}` : ""}`;
  };
  const remainMin = Math.max(0, Math.ceil((nextAt - (now?.getTime() ?? nextAt)) / 60000));

  return (
    <header className="flex h-14 items-center gap-4 border-b border-border bg-panel px-4" role="banner">
      <Link href={expert ? "/?view=expert" : "/"} className="flex items-baseline gap-2">
        <span className="text-lg font-bold tracking-tight">{APP.title}</span>
        <span className="hidden text-xs text-dim xl:inline">{APP.subtitle}</span>
      </Link>
      <div className="flex items-center gap-3 text-sm" aria-label="시스템 상태">
        {(["collect", "predict", "db"] as const).map((k) => (
          <span key={k} className="flex items-center gap-1.5" title={BOARD.ledTip[leds[k]]}>
            <span className="led" style={{ color: LED_COLOR[leds[k]] }} aria-hidden />
            <span>{BOARD.leds[k]}</span>
            <span className="sr-only">{BOARD.ledTip[leds[k]]}</span>
          </span>
        ))}
      </div>
      <div className="ml-auto flex items-center gap-4 text-sm">
        <span className="text-dim">
          {BOARD.lastRefresh} <span className="text-text">{fmtDateTimeKST(renderedAt)}</span>
          <span className="mx-1.5 opacity-50">·</span>
          {BOARD.nextRefresh(remainMin)}
          <span className="sr-only">({BOARD.autoRefresh})</span>
        </span>
        <time className="rounded-md border border-border px-2 py-0.5 font-mono text-base" dateTime={now?.toISOString()} suppressHydrationWarning>
          {now ? clockText(now) : "--:--:--"}
        </time>
        {!kiosk && (
          <nav className="flex items-center gap-1.5" aria-label="상황판 제어">
            {APP.nav.slice(1).map((n) => (
              <Link key={n.href} href={expert ? `${n.href}?view=expert` : n.href} className="btn hidden 2xl:inline-block">
                {n.label}
              </Link>
            ))}
            <Link href={q({ view: expert ? null : "expert" })} className="btn" aria-pressed={expert}>
              {expert ? BOARD.btn.easy : BOARD.btn.expert}
            </Link>
            <button type="button" className="btn" onClick={toggleLight} aria-pressed={light}>
              {light ? BOARD.btn.presentOff : BOARD.btn.present}
            </button>
            <button type="button" className="btn" onClick={toggleFs} aria-pressed={fs}>
              {fs ? BOARD.btn.exitFullscreen : BOARD.btn.fullscreen}
            </button>
            <Link href={q({ kiosk: "1" })} className="btn">
              {BOARD.btn.kiosk}
            </Link>
          </nav>
        )}
        {kiosk && (
          <Link href={q({ kiosk: null })} className="btn">
            {BOARD.btn.kioskOff}
          </Link>
        )}
      </div>
    </header>
  );
}
