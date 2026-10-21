export type Tier = "normal" | "watch" | "alert";

export const TIER_LABEL: Record<Tier, string> = { normal: "정상", watch: "감시", alert: "경보" };
export const TIER_COLOR: Record<Tier, string> = { normal: "#6b7280", watch: "#d97706", alert: "#dc2626" };
export const TIER_BG: Record<Tier, string> = {
  normal: "bg-gray-100 text-gray-700 border-gray-300",
  watch: "bg-amber-100 text-amber-800 border-amber-400",
  alert: "bg-red-100 text-red-800 border-red-400",
};
export const TIER_ACTION: Record<Tier, string> = {
  normal: "통상 운영",
  watch: "모니터링 강화·설비 준비 점검",
  alert: "녹조제거설비 선제 배치 권고",
};

export function fmtCells(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return Math.round(v).toLocaleString("ko-KR");
}

export function fmtPct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return `${(v * 100).toFixed(digits)}%`;
}

export function fmtDate(v: string | Date | null | undefined): string {
  if (!v) return "–";
  const d = typeof v === "string" ? new Date(v) : v;
  if (Number.isNaN(d.getTime())) return "–";
  return `${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}

export function fmtDateFull(v: string | Date | null | undefined): string {
  if (!v) return "–";
  const d = typeof v === "string" ? new Date(v) : v;
  if (Number.isNaN(d.getTime())) return "–";
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}

export function fmtNum(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return v.toFixed(digits);
}

export function tierOf(t: string | null | undefined): Tier {
  return t === "alert" || t === "watch" ? t : "normal";
}

export const ALERT_LEVEL_LABEL: Record<number, string> = { 0: "없음", 1: "관심", 2: "경계", 3: "대발생" };
