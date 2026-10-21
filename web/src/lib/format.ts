import { TIER, type Tier } from "./copy";

export type { Tier };

/** 색은 CSS 변수(§6 토큰)로만 쓴다 — 발표모드에서 함께 바뀜 */
export const TIER_LABEL: Record<Tier, string> = { normal: TIER.normal.label, watch: TIER.watch.label, alert: TIER.alert.label };
export const TIER_COLOR: Record<Tier, string> = { normal: TIER.normal.color, watch: TIER.watch.color, alert: TIER.alert.color };
export const TIER_HEX: Record<Tier, string> = { normal: "#22C55E", watch: "#FACC15", alert: "#F97316" };
export const TIER_ACTION: Record<Tier, string> = { normal: TIER.normal.action, watch: TIER.watch.action, alert: TIER.alert.action };
export const TIER_ORDER: Record<Tier, number> = { alert: 0, watch: 1, normal: 2 };

export function tierOf(t: string | null | undefined): Tier {
  return t === "alert" || t === "watch" ? t : "normal";
}

/** 정수 천 단위 (전문가 보기·표) */
export function fmtCells(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return Math.round(v).toLocaleString("ko-KR");
}

/** 쉽게 보기: 1만 이상은 '만' 단위로 반올림 (§7). 예: 96,339 → 9.6만, 2,531 → 2,500, 290 → 290 */
export function fmtCellsKo(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const n = Math.max(0, v);
  if (n >= 1_000_000) return `${Math.round(n / 10_000).toLocaleString("ko-KR")}만`;
  if (n >= 100_000) return `${(n / 10_000).toFixed(0)}만`;
  if (n >= 10_000) return `${(n / 10_000).toFixed(1)}만`;
  if (n >= 1_000) return (Math.round(n / 100) * 100).toLocaleString("ko-KR");
  return Math.round(n).toLocaleString("ko-KR");
}

export function fmtPct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return `${(v * 100).toFixed(digits)}%`;
}
export function pctInt(v: number | null | undefined): number {
  return v === null || v === undefined || Number.isNaN(v) ? 0 : Math.round(v * 100);
}

function toDate(v: string | Date): Date {
  return typeof v === "string" ? new Date(v) : v;
}
export function fmtDate(v: string | Date | null | undefined): string {
  if (!v) return "–";
  const d = toDate(v);
  if (Number.isNaN(d.getTime())) return "–";
  return `${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}
export function fmtDateKo(v: string | Date | null | undefined): string {
  if (!v) return "–";
  const d = toDate(v);
  if (Number.isNaN(d.getTime())) return "–";
  return `${d.getMonth() + 1}월 ${d.getDate()}일`;
}
export function fmtDateFull(v: string | Date | null | undefined): string {
  if (!v) return "–";
  const d = toDate(v);
  if (Number.isNaN(d.getTime())) return "–";
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}
/** KST 시각 HH:MM */
export function fmtTimeKST(v: string | Date | null | undefined): string {
  if (!v) return "–";
  const d = toDate(v);
  if (Number.isNaN(d.getTime())) return "–";
  return d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Seoul" });
}
export function fmtDateTimeKST(v: string | Date | null | undefined): string {
  if (!v) return "–";
  const d = toDate(v);
  if (Number.isNaN(d.getTime())) return "–";
  return d.toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Seoul" });
}
export function fmtNum(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return v.toFixed(digits);
}
export function daysBetween(a: string | Date, b: string | Date): number {
  return Math.round((toDate(b).getTime() - toDate(a).getTime()) / 86_400_000);
}
export function addDays(d: string | Date, n: number): Date {
  const x = new Date(toDate(d));
  x.setDate(x.getDate() + n);
  return x;
}

export const ALERT_LEVEL_LABEL: Record<number, string> = { 0: "없음", 1: "관심", 2: "경계", 3: "대발생" };

/** 추세 화살표: 예상/현재 비율 ±20% */
export function trendArrow(now: number | null | undefined, next: number | null | undefined): "↑" | "↓" | "→" {
  if (!now || next === null || next === undefined) return "→";
  const r = next / Math.max(now, 1);
  return r > 1.2 ? "↑" : r < 0.8 ? "↓" : "→";
}
