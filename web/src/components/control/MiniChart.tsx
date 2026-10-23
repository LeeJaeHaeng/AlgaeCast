import Link from "next/link";
import { BOARD, COMBO, comboOf, targetLabel } from "@/lib/copy";
import { fmtCells, fmtCellsKo, fmtDate, tierOf } from "@/lib/format";
import type { ObsLite, SiteStatus } from "@/lib/queries";

const toLog = (v: number | null | undefined) => (v == null ? null : Math.log10(Math.max(v, 0) + 1));

/**
 * 지점 모니터 미니 차트(서버 렌더). 데이터 범위 기반 로그 축: 최소 100, 최대 = max(관측 최대×1.5, 예상 범위 위쪽×1.1).
 * 선·점은 퍼센트 좌표 SVG(preserveAspectRatio none + non-scaling-stroke)라 패널을 꽉 채우고, 글자는 HTML 이라 크기가 유지된다.
 */
export function MiniChart({ s, obs, days = 60, expert, today }: { s: SiteStatus; obs: ObsLite[]; days?: number; expert: boolean; today: string }) {
  const t = tierOf(s.tier);
  const c = COMBO[comboOf(s.latest_alert_level, t)];
  const end = s.target_date ? new Date(s.target_date) : new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - days - 7);
  const rows = obs.filter((o) => o.cell_count != null && new Date(o.obs_date) >= start);
  const obsMax = Math.max(0, ...rows.map((o) => o.cell_count!));
  const yLo = 2; // 100
  const yHi = Math.max(3.5, toLog(Math.max(obsMax * 1.5, (s.q90_cqr ?? 0) * 1.1))!);
  const xp = (d: string | Date) => ((new Date(d).getTime() - start.getTime()) / (end.getTime() - start.getTime())) * 100;
  const yp = (v: number | null | undefined) => {
    const lv = toLog(v);
    return lv == null ? null : (1 - (Math.min(Math.max(lv, yLo), yHi) - yLo) / (yHi - yLo)) * 100;
  };
  const pts = rows.map((o) => ({ x: xp(o.obs_date), y: yp(o.cell_count)! }));
  const path = pts.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" ");
  const fmt = expert ? fmtCells : fmtCellsKo;
  const tx = s.target_date ? xp(s.target_date) : null;
  const point = s.pred_cell_count; // 예상값 = v2 한 값 예측
  const py = yp(point);
  const lo = yp(s.q10_cqr);
  const hi = yp(s.q90_cqr);
  const last = pts.at(-1);
  const ticks = [
    { lv: 3, label: BOARD.tile.axis.k1, color: "var(--watch)" },
    { lv: 4, label: BOARD.tile.axis.k10, color: "var(--alert)" },
    { lv: 5, label: BOARD.tile.axis.k100, color: "var(--severe)" },
  ].filter((k) => k.lv > yLo && k.lv < yHi);
  const tl = targetLabel(s.target_date, today, point, s.obs_cell_count, fmt, { withValues: false });
  const title = `${s.name}: ${BOARD.monitorLegend.obs} 최근 ${days}일, ${BOARD.monitorLegend.pred} ${fmt(point)} ${BOARD.unit.cells}`;
  return (
    <Link href={`/sites/${s.site_id}${expert ? "?view=expert" : ""}`} className="panel flex min-h-[240px] flex-col p-2 hover:border-[var(--accent)] 2xl:min-h-0" aria-label={title}>
      <div className="flex items-center justify-between px-1 text-sm">
        <span className="font-semibold">{s.name}</span>
        <span style={{ color: c.color }}>
          {c.icon} {c.bannerWord}
        </span>
      </div>
      <div className="relative min-h-0 flex-1 pb-5 pl-9 pr-2 pt-2">
        <div className="relative h-full w-full">
          {/* y 눈금(HTML, 12px) — 플롯 영역 기준 퍼센트 위치 */}
          {ticks.map((k) => (
            <span key={k.lv} className="absolute -left-9 w-8 -translate-y-1/2 text-right text-xs leading-none" style={{ top: `${yp(10 ** k.lv - 1)}%`, color: k.color }}>
              {k.label}
            </span>
          ))}
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full overflow-visible" role="img" aria-label={title}>
            {ticks.map((k) => (
              <line key={k.lv} x1={0} x2={100} y1={yp(10 ** k.lv - 1)!} y2={yp(10 ** k.lv - 1)!} stroke={k.color} strokeDasharray="4 4" strokeWidth={1} vectorEffect="non-scaling-stroke" opacity={0.8} />
            ))}
            <path d={path} fill="none" stroke="var(--line-obs)" strokeWidth={1.8} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
            {pts.map((p, i) => (
              <path key={i} d={`M${p.x.toFixed(2)},${p.y.toFixed(2)}h0`} stroke="var(--line-obs)" strokeWidth={5} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
            ))}
            {tx != null && lo != null && hi != null && <line x1={tx} x2={tx} y1={hi} y2={lo} stroke="var(--accent)" strokeWidth={8} strokeLinecap="round" opacity={0.35} vectorEffect="non-scaling-stroke" />}
            {last && tx != null && py != null && <line x1={last.x} y1={last.y} x2={tx} y2={py} stroke="var(--accent)" strokeDasharray="3 4" strokeWidth={1.2} vectorEffect="non-scaling-stroke" />}
            {tx != null && py != null && <path d={`M${tx.toFixed(2)},${py.toFixed(2)}h0`} stroke="var(--accent)" strokeWidth={11} strokeLinecap="round" vectorEffect="non-scaling-stroke" />}
            {tx != null && s.obs_cell_count != null && <path d={`M${tx.toFixed(2)},${yp(s.obs_cell_count)!.toFixed(2)}h0`} stroke="var(--line-obs)" strokeWidth={7} strokeLinecap="round" vectorEffect="non-scaling-stroke" />}
          </svg>
          <span className="absolute -bottom-5 left-0 text-xs text-dim">{fmtDate(start)}</span>
          {tx != null && (
            <span className="absolute -bottom-5 right-0 text-xs" style={{ color: "var(--accent)" }}>
              {tl.text}
            </span>
          )}
        </div>
      </div>
      <div className="flex justify-between gap-2 whitespace-nowrap px-1 text-xs text-dim">
        <span className="truncate">
          {BOARD.monitorLegend.obs} {fmt(s.latest_cell_count)} ({fmtDate(s.latest_obs_date)})
        </span>
        <span className="truncate" style={{ color: "var(--accent)" }} title={BOARD.tile.next}>
          {BOARD.monitorLegend.predShort} {fmt(point)} {BOARD.unit.cells}
          {tl.state === "verified" && ` → 실제 ${fmt(s.obs_cell_count)} ${tl.hit ? "✓" : "✗"}`}
        </span>
      </div>
    </Link>
  );
}
