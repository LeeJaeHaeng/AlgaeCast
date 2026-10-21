"use client";

import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { SITE } from "@/lib/copy";
import { fmtCells, fmtDate } from "@/lib/format";

export type SeriesPoint = { date: string; obs?: number | null; q50?: number | null; lo?: number | null; hi?: number | null; past_pred?: number | null; actual?: number | null };

const C = { obs: "#E6EDF7", pred: "#38BDF8", past: "#8A9BB8", grid: "#1E2A44", l1: "#FACC15", l2: "#F97316", l3: "#EF4444", text: "#8A9BB8" };
const LOG_LABEL: Record<number, string> = { 0: "0", 2: "100", 3: "1천", 4: "1만", 5: "10만", 6: "100만" };
const toLog = (v: number | null | undefined) => (v === null || v === undefined ? null : Math.log10(Math.max(v, 0) + 1));
const fromLog = (v: number) => Math.round(10 ** v - 1);

/** 지점 상세 큰 차트: 측정(선+점), 지난 예상값(회색 점), 이번 예상(파란 점 + 범위 띠), 관심/경계 기준선. 로그 축 */
export function BigChart({ points, height = 380 }: { points: SeriesPoint[]; height?: number }) {
  const data = points.map((p) => {
    const q = toLog(p.q50);
    const lo = toLog(p.lo);
    const hi = toLog(p.hi);
    return { date: p.date, obs: toLog(p.obs), q50: q, band: lo != null && hi != null ? [lo, hi] : null, past_pred: toLog(p.past_pred) };
  });
  const maxLv = Math.max(4.5, ...data.flatMap((d) => [d.obs ?? 0, d.q50 ?? 0, d.past_pred ?? 0, (d.band?.[1] as number) ?? 0])) + 0.3;
  const ticks = [0, 2, 3, 4, 5, 6].filter((t) => t <= maxLv);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 12, right: 20, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={C.grid} />
        <XAxis dataKey="date" tickFormatter={fmtDate} minTickGap={40} fontSize={12} stroke={C.text} />
        <YAxis domain={[0, maxLv]} ticks={ticks} tickFormatter={(v: number) => LOG_LABEL[v] ?? ""} fontSize={12} width={44} stroke={C.text} />
        <Tooltip
          contentStyle={{ background: "#111A2E", border: "1px solid #1E2A44", color: "#E6EDF7" }}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          formatter={((v: any, name: any) => {
            if (Array.isArray(v)) return [`${fmtCells(fromLog(v[0] as number))} ~ ${fmtCells(fromLog(v[1] as number))} 개/mL`, SITE.chart.band];
            return [typeof v === "number" ? `${fmtCells(fromLog(v))} 개/mL` : "–", String(name)];
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
          }) as any}
          labelFormatter={(l) => `날짜 ${fmtDate(String(l))}`}
        />
        <ReferenceLine y={3} stroke={C.l1} strokeDasharray="4 4" label={{ value: "관심 1천", fontSize: 12, position: "insideTopLeft", fill: C.l1 }} />
        <ReferenceLine y={4} stroke={C.l2} strokeDasharray="4 4" label={{ value: "경계 1만", fontSize: 12, position: "insideTopLeft", fill: C.l2 }} />
        {maxLv > 6 && <ReferenceLine y={6} stroke={C.l3} strokeDasharray="4 4" label={{ value: "대발생 100만", fontSize: 12, position: "insideTopLeft", fill: C.l3 }} />}
        <Scatter dataKey="past_pred" name={SITE.chart.pastPred} fill={C.past} shape="circle" isAnimationActive={false} />
        <Line dataKey="obs" name={SITE.chart.obs} stroke={C.obs} strokeWidth={1.6} dot={{ r: 2.5, fill: C.obs }} connectNulls isAnimationActive={false} />
        <Area dataKey="band" name={SITE.chart.band} stroke={C.pred} strokeWidth={1} fill={C.pred} fillOpacity={0.3} connectNulls={false} isAnimationActive={false} />
        <Scatter dataKey="q50" name={SITE.chart.next} fill={C.pred} shape="circle" isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

/** 물·날씨 보조 차트 */
export function EnvChart({ data, keys, height = 200, unit }: { data: Record<string, unknown>[]; keys: { k: string; label: string; color: string }[]; height?: number; unit?: string }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={C.grid} />
        <XAxis dataKey="date" tickFormatter={fmtDate} minTickGap={36} fontSize={12} stroke={C.text} />
        <YAxis fontSize={12} width={44} stroke={C.text} unit={unit} />
        <Tooltip contentStyle={{ background: "#111A2E", border: "1px solid #1E2A44", color: "#E6EDF7" }} labelFormatter={(l) => `날짜 ${fmtDate(String(l))}`} />
        {keys.map((k) => (
          <Line key={k.k} dataKey={k.k} name={k.label} stroke={k.color} dot={false} strokeWidth={1.6} connectNulls isAnimationActive={false} />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
