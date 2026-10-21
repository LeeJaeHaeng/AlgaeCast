"use client";

import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { fmtCells, fmtDate } from "@/lib/format";

export type SeriesPoint = { date: string; obs?: number | null; q50?: number | null; lo?: number | null; hi?: number | null; past_pred?: number | null };

const LOG_LABEL: Record<number, string> = { 0: "0", 1: "10", 2: "100", 3: "1,000", 4: "10,000", 5: "100,000", 6: "1,000,000" };
const toLog = (v: number | null | undefined) => (v === null || v === undefined ? null : Math.log10(Math.max(v, 0) + 1));
const fromLog = (v: number) => Math.round(10 ** v - 1);

/** 메인 차트: log10(cells+1) 공간. 관측(점+선), q50 점, CQR 밴드, 기준선, 과거 예측(작은 점) */
export function ForecastChart({ points, height = 320 }: { points: SeriesPoint[]; height?: number }) {
  const data = points.map((p) => ({
    date: p.date,
    obs: toLog(p.obs),
    q50: toLog(p.q50),
    lo: toLog(p.lo),
    hi: toLog(p.hi),
    band: p.lo != null && p.hi != null ? [toLog(p.lo), toLog(p.hi)] : null,
    past_pred: toLog(p.past_pred),
  }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis dataKey="date" tickFormatter={fmtDate} minTickGap={28} fontSize={11} />
        <YAxis domain={[0, 6]} ticks={[0, 2, 3, 4, 5, 6]} tickFormatter={(v: number) => LOG_LABEL[v] ?? ""} fontSize={11} width={40} />
        <Tooltip
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          formatter={((v: any, name: any) => {
            if (Array.isArray(v)) return [`${fmtCells(fromLog(v[0] as number))} ~ ${fmtCells(fromLog(v[1] as number))}`, "80% 구간"];
            return [typeof v === "number" ? fmtCells(fromLog(v)) : "–", String(name)];
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
          }) as any}
          labelFormatter={(l) => `날짜 ${fmtDate(String(l))}`}
        />
        <ReferenceLine y={3} stroke="#16a34a" strokeDasharray="4 4" label={{ value: "관심 1,000", fontSize: 10, position: "insideTopLeft", fill: "#16a34a" }} />
        <ReferenceLine y={4} stroke="#d97706" strokeDasharray="4 4" label={{ value: "경계 10,000", fontSize: 10, position: "insideTopLeft", fill: "#d97706" }} />
        <ReferenceLine y={6} stroke="#dc2626" strokeDasharray="4 4" label={{ value: "대발생 1,000,000", fontSize: 10, position: "insideTopLeft", fill: "#dc2626" }} />
        <Area dataKey="band" name="80% 구간(CQR)" stroke="none" fill="#dc2626" fillOpacity={0.12} connectNulls />
        <Line dataKey="obs" name="관측" stroke="#0f172a" strokeWidth={1.5} dot={{ r: 2.5 }} connectNulls />
        <Scatter dataKey="past_pred" name="과거 예측" fill="#94a3b8" shape="circle" />
        <Line dataKey="q50" name="예측 q50" stroke="#dc2626" strokeWidth={2} dot={{ r: 3.5 }} connectNulls />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function Sparkline({ points, height = 90 }: { points: SeriesPoint[]; height?: number }) {
  const data = points.map((p) => ({ date: p.date, obs: toLog(p.obs), q50: toLog(p.q50) }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <YAxis domain={[0, 6]} hide />
        <XAxis dataKey="date" hide />
        <ReferenceLine y={4} stroke="#d97706" strokeDasharray="3 3" />
        <Line dataKey="obs" stroke="#0f172a" strokeWidth={1.2} dot={false} connectNulls isAnimationActive={false} />
        <Line dataKey="q50" stroke="#dc2626" strokeWidth={0} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function ShapBars({ items }: { items: { label: string; value: number; group: string }[] }) {
  const total = items.reduce((a, b) => a + Math.abs(b.value), 0) || 1;
  const data = items.map((i) => ({ ...i, pct: Math.round((100 * Math.abs(i.value)) / total), signed: i.value }));
  return (
    <ResponsiveContainer width="100%" height={40 + 28 * data.length}>
      <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24 }}>
        <XAxis type="number" hide />
        <YAxis type="category" dataKey="label" width={150} fontSize={11} />
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        <Tooltip formatter={((v: any, _n: any, p: any) => [`${(p?.payload as { pct: number })?.pct ?? 0}% (${(v as number) > 0 ? "상승" : "하락"} 요인)`, "기여"]) as any} />
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        <Bar dataKey="signed" name="기여" fill="#dc2626" isAnimationActive={false} label={{ position: "right", fontSize: 11, formatter: ((v: any) => `${(v as number) > 0 ? "▲" : "▼"}`) as any }} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Gauge({ p, threshold }: { p: number | null; threshold: number }) {
  const v = Math.max(0, Math.min(1, p ?? 0));
  const color = v >= threshold ? "#dc2626" : v >= threshold / 2 ? "#d97706" : "#6b7280";
  return (
    <div className="flex items-center gap-3" aria-label={`경보 확률 ${Math.round(v * 100)}%`}>
      <svg width="96" height="56" viewBox="0 0 96 56" role="img">
        <path d="M8 52 A40 40 0 0 1 88 52" stroke="#e2e8f0" strokeWidth="10" fill="none" />
        <path d="M8 52 A40 40 0 0 1 88 52" stroke={color} strokeWidth="10" fill="none" strokeDasharray={`${v * 125.6} 125.6`} />
        <line x1="48" y1="52" x2={48 + 40 * Math.cos(Math.PI * (1 - threshold))} y2={52 - 40 * Math.sin(Math.PI * (1 - threshold))} stroke="#0f172a" strokeWidth="2" />
      </svg>
      <div>
        <div className="text-2xl font-bold tabular-nums" style={{ color }}>
          {Math.round(v * 100)}%
        </div>
        <div className="text-xs text-slate-500">경보 운영점 {Math.round(threshold * 100)}%</div>
      </div>
    </div>
  );
}

export function SimpleLines({ data, keys, height = 200 }: { data: Record<string, unknown>[]; keys: { k: string; label: string; color: string }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis dataKey="date" tickFormatter={fmtDate} minTickGap={28} fontSize={11} />
        <YAxis fontSize={11} width={48} />
        <Tooltip labelFormatter={(l) => `날짜 ${fmtDate(String(l))}`} />
        {keys.map((k) => (
          <Line key={k.k} dataKey={k.k} name={k.label} stroke={k.color} dot={false} strokeWidth={1.5} connectNulls isAnimationActive={false} />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
