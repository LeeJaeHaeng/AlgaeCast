"use client";

import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { REPLAY, SITE } from "@/lib/copy";
import { fmtCells, fmtDate } from "@/lib/format";

export type SeriesPoint = { date: string; obs?: number | null; pred?: number | null; lo?: number | null; hi?: number | null; past_pred?: number | null; actual?: number | null };

const C = { obs: "#E6EDF7", pred: "#38BDF8", past: "#8A9BB8", grid: "#1E2A44", l1: "#FACC15", l2: "#F97316", l3: "#EF4444", text: "#8A9BB8", after: "#FDA4AF", replay: "#A78BFA" }; // 다시 보기 전용: after = 분홍(rose-300, 점선+점), replay = 그날 세로선(보라 실선) — 둘은 색·모양이 다르다
const LOG_LABEL: Record<number, string> = { 0: "0", 2: "100", 3: "1천", 4: "1만", 5: "10만", 6: "100만" };
const toLog = (v: number | null | undefined) => (v === null || v === undefined ? null : Math.log10(Math.max(v, 0) + 1));
const fromLog = (v: number) => Math.round(10 ** v - 1);

/** 범위 띠 앞뒤 여백 점(±days 일)을 브라우저에서 더한다 — 다시 보기에서 서버 자료에 그날 뒤 날짜를 싣지 않으려고(목표일 하나만 보냄) */
function padBand(points: SeriesPoint[], days: number): SeriesPoint[] {
  const out = [...points];
  for (const p of points) {
    if (p.pred == null || p.lo == null || p.hi == null) continue;
    for (const d of [-days, days]) {
      const t = new Date(`${p.date}T00:00:00Z`);
      t.setUTCDate(t.getUTCDate() + d);
      const date = t.toISOString().slice(0, 10);
      const i = out.findIndex((x) => x.date === date);
      if (i >= 0) out[i] = { ...out[i], lo: p.lo, hi: p.hi };
      else out.push({ date, obs: null, pred: null, lo: p.lo, hi: p.hi });
    }
  }
  return out.sort((a, b) => a.date.localeCompare(b.date));
}

/**
 * 지점 상세 큰 차트: 측정(선+점), 지난 예상값(회색 점), 이번 예상(파란 점 + 범위 띠), 관심/경계 기준선. 로그 축.
 * 다시 보기: asof = 그날 세로선(보라 실선), points[].actual = '그 뒤 실제로는'(asof 뒤 21일 실측, 분홍색 점선+점),
 * bandPad = 범위 띠 앞뒤 여백 날 수(브라우저에서 더함). 셋 다 없으면 기본 화면과 같은 차트.
 */
export function BigChart({ points: points0, height = 380, asof, bandPad }: { points: SeriesPoint[]; height?: number; asof?: string; bandPad?: number }) {
  const points = bandPad ? padBand(points0, bandPad) : points0;
  const FLOOR = 2; // 100 개/mL — 로그 축 바닥
  const LOW_Y = 1.6; // 100 미만·미검출 표시 높이(축 아래)
  const clampLow = (v: number | null) => (v == null ? null : v < FLOOR ? null : v);
  const data = points.map((p) => {
    const q = toLog(p.pred);
    const lo = toLog(p.lo);
    const hi = toLog(p.hi);
    const o = toLog(p.obs);
    return { date: p.date, obs: clampLow(o), low: o != null && o < FLOOR ? LOW_Y : null, pred: q, band: lo != null && hi != null ? [Math.max(lo, FLOOR), hi] : null, past_pred: clampLow(toLog(p.past_pred)), ...(p.actual !== undefined ? { actual: p.actual == null ? null : Math.max(toLog(p.actual) as number, LOW_Y) } : {}) };
  });
  const hasAfter = points.some((p) => p.actual != null);
  const maxLv = Math.max(4.5, ...data.flatMap((d) => [d.obs ?? 0, d.pred ?? 0, d.past_pred ?? 0, (d.band?.[1] as number) ?? 0, ("actual" in d ? (d.actual as number | null) : 0) ?? 0])) + 0.3;
  const ticks = [LOW_Y, 2, 3, 4, 5, 6].filter((t) => t <= maxLv);
  const label = (v: number) => (v === LOW_Y ? "100 미만" : LOG_LABEL[v] ?? "");
  return (
    <div style={{ height, minHeight: height }}>
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 12, right: 92, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={C.grid} />
        <XAxis dataKey="date" tickFormatter={fmtDate} minTickGap={40} fontSize={12} stroke={C.text} />
        <YAxis domain={[LOW_Y - 0.2, maxLv]} ticks={ticks} tickFormatter={label} fontSize={12} width={56} stroke={C.text} />
        <Tooltip
          contentStyle={{ background: "#111A2E", border: "1px solid #1E2A44", color: "#E6EDF7" }}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          formatter={((v: any, name: any) => {
            if (name === SITE.chartLow || (name === REPLAY.chartAfter && typeof v === "number" && v <= LOW_Y)) return ["100 개/mL 미만 또는 미검출", String(name)];
            if (Array.isArray(v)) return [`${fmtCells(fromLog(v[0] as number))} ~ ${fmtCells(fromLog(v[1] as number))} 개/mL`, SITE.chart.band];
            return [typeof v === "number" ? `${fmtCells(fromLog(v))} 개/mL` : "–", String(name)];
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
          }) as any}
          labelFormatter={(l) => `날짜 ${fmtDate(String(l))}`}
        />
        <ReferenceLine y={3} stroke={C.l1} strokeDasharray="4 4" label={{ value: "관심 1천", fontSize: 12, position: "right", fill: C.l1 }} />
        <ReferenceLine y={4} stroke={C.l2} strokeDasharray="4 4" label={{ value: "경계 1만", fontSize: 12, position: "right", fill: C.l2 }} />
        {maxLv > 6 && <ReferenceLine y={6} stroke={C.l3} strokeDasharray="4 4" label={{ value: "대발생 100만", fontSize: 12, position: "right", fill: C.l3 }} />}
        <ReferenceLine y={FLOOR} stroke={C.grid} />
        <Scatter dataKey="low" name={SITE.chartLow} fill={C.past} shape="circle" isAnimationActive={false} />
        <Scatter dataKey="past_pred" name={SITE.chart.pastPred} fill={C.past} shape="circle" isAnimationActive={false} />
        <Line dataKey="obs" name={SITE.chart.obs} stroke={C.obs} strokeWidth={1.6} dot={{ r: 2.5, fill: C.obs }} connectNulls={false} isAnimationActive={false} />
        <Area dataKey="band" name={SITE.chart.band} stroke={C.pred} strokeWidth={1} fill={C.pred} fillOpacity={0.3} connectNulls={false} isAnimationActive={false} />
        <Scatter dataKey="pred" name={SITE.chart.next} fill={C.pred} shape="circle" isAnimationActive={false} />
        {asof && <ReferenceLine x={asof} stroke={C.replay} strokeWidth={2} label={{ value: REPLAY.chartAsof, fontSize: 12, position: "insideTopRight", fill: C.replay }} />}
        {hasAfter && <Line dataKey="actual" name={REPLAY.chartAfter} stroke={C.after} strokeWidth={2} strokeDasharray="6 4" dot={{ r: 3.5, fill: C.after, stroke: C.after }} connectNulls isAnimationActive={false} />}
      </ComposedChart>
    </ResponsiveContainer>
    </div>
  );
}

/** 물·날씨 보조 차트. yWidth = Y축 칸 폭(px, 기본 44) — 눈금 글자가 긴 차트(물 흐름 "1350㎥/s")만 넓힌다 */
export function EnvChart({ data, keys, height = 200, unit, yWidth = 44 }: { data: Record<string, unknown>[]; keys: { k: string; label: string; color: string }[]; height?: number; unit?: string; yWidth?: number }) {
  return (
    <div style={{ height, minHeight: height }}>
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={C.grid} />
        <XAxis dataKey="date" tickFormatter={fmtDate} minTickGap={36} fontSize={12} stroke={C.text} />
        <YAxis fontSize={12} width={yWidth} stroke={C.text} unit={unit} />
        <Tooltip contentStyle={{ background: "#111A2E", border: "1px solid #1E2A44", color: "#E6EDF7" }} labelFormatter={(l) => `날짜 ${fmtDate(String(l))}`} />
        {keys.map((k) => (
          <Line key={k.k} dataKey={k.k} name={k.label} stroke={k.color} dot={false} strokeWidth={1.6} connectNulls isAnimationActive={false} />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
    </div>
  );
}
