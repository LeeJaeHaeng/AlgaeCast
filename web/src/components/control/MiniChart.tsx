import Link from "next/link";
import { BOARD, TIER } from "@/lib/copy";
import { fmtCells, fmtCellsKo, fmtDate, tierOf } from "@/lib/format";
import type { ObsLite, SiteStatus } from "@/lib/queries";

const W = 300;
const H = 230;
const PAD = { l: 34, r: 10, t: 8, b: 18 };
const toLog = (v: number | null | undefined) => (v == null ? null : Math.min(6, Math.log10(Math.max(v, 0) + 1)));

/** 지점 모니터 미니 차트(SVG, 서버 렌더): 최근 60일 측정 + 관심/경계 기준선 + 7일 뒤 예상점·범위 */
export function MiniChart({ s, obs, days = 60, expert }: { s: SiteStatus; obs: ObsLite[]; days?: number; expert: boolean }) {
  const t = tierOf(s.tier);
  const end = s.target_date ? new Date(s.target_date) : new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - days - 7);
  const x = (d: string | Date) => PAD.l + ((new Date(d).getTime() - start.getTime()) / (end.getTime() - start.getTime())) * (W - PAD.l - PAD.r) ;
  const y = (lv: number) => PAD.t + (1 - lv / 6) * (H - PAD.t - PAD.b);
  const pts = obs.filter((o) => o.cell_count != null && new Date(o.obs_date) >= start).map((o) => ({ x: x(o.obs_date), y: y(toLog(o.cell_count)!), v: o.cell_count! }));
  const path = pts.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const fmt = expert ? fmtCells : fmtCellsKo;
  const tx = s.target_date ? x(s.target_date) : null;
  const q50 = toLog(s.q50);
  const lo = toLog(s.q10_cqr);
  const hi = toLog(s.q90_cqr);
  const last = pts.at(-1);
  const title = `${s.name}: ${BOARD.monitorLegend.obs} 최근 ${days}일, ${BOARD.monitorLegend.pred} ${fmt(s.q50)} ${BOARD.unit.cells}`;
  return (
    <Link href={`/sites/${s.site_id}${expert ? "?view=expert" : ""}`} className="panel flex min-h-0 flex-col p-2 hover:border-[var(--accent)]" aria-label={title}>
      <div className="flex items-center justify-between px-1 text-sm">
        <span className="font-semibold">{s.name}</span>
        <span style={{ color: TIER[t].color }}>
          {TIER[t].icon} {TIER[t].label}
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="min-h-0 w-full flex-1" role="img" aria-label={title} preserveAspectRatio="xMidYMid meet">
        {/* 기준선 */}
        {[3, 4].map((lv) => (
          <g key={lv}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(lv)} y2={y(lv)} stroke={lv === 4 ? "var(--alert)" : "var(--watch)"} strokeDasharray="3 3" strokeWidth={1} opacity={0.8} />
            <text x={PAD.l - 3} y={y(lv) + 3} fontSize={9} textAnchor="end" fill="var(--text-dim)">
              {lv === 4 ? "1만" : "1천"}
            </text>
          </g>
        ))}
        <text x={PAD.l - 3} y={y(0) + 3} fontSize={9} textAnchor="end" fill="var(--text-dim)">
          0
        </text>
        {/* 측정 */}
        <path d={path} fill="none" stroke="var(--line-obs)" strokeWidth={1.6} />
        {pts.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r={2.2} fill="var(--line-obs)" />
        ))}
        {/* 예상 범위·점 */}
        {tx != null && lo != null && hi != null && <rect x={tx - 5} y={y(hi)} width={10} height={Math.max(1, y(lo) - y(hi))} fill="var(--band)" stroke="var(--accent)" strokeWidth={0.5} rx={2} />}
        {tx != null && q50 != null && <circle cx={tx} cy={y(q50)} r={4.5} fill="var(--accent)" stroke="var(--bg)" strokeWidth={1.5} />}
        {last && tx != null && q50 != null && <line x1={last.x} y1={last.y} x2={tx} y2={y(q50)} stroke="var(--accent)" strokeDasharray="2 3" strokeWidth={1} />}
        {/* x 라벨 */}
        <text x={PAD.l} y={H - 5} fontSize={9} fill="var(--text-dim)">
          {fmtDate(start)}
        </text>
        {tx != null && (
          <text x={Math.min(tx, W - PAD.r)} y={H - 5} fontSize={9} textAnchor="end" fill="var(--accent)">
            {BOARD.tile.next} {fmtDate(s.target_date)}
          </text>
        )}
      </svg>
      <div className="flex justify-between px-1 text-xs text-dim">
        <span>
          {BOARD.monitorLegend.obs} {fmt(s.latest_cell_count)} ({fmtDate(s.latest_obs_date)})
        </span>
        <span style={{ color: "var(--accent)" }}>
          {BOARD.monitorLegend.pred} {fmt(s.q50)} {BOARD.unit.cells}
        </span>
      </div>
    </Link>
  );
}
