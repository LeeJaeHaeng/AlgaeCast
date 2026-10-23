import Link from "next/link";
import { Info } from "@/components/Info";
import { BOARD, COMBO, OFFICIAL_LEVEL, TERMS, TIER, comboOf, outOfRange, outOfRangeTip, targetLabel } from "@/lib/copy";
import { fmtCells, fmtCellsKo, fmtDateKo, pctInt, tierOf, trendArrow } from "@/lib/format";
import type { SiteStatus } from "@/lib/queries";

/** 고정 로그 축 100 ~ 1,000,000 (1천 = 25%, 1만 = 50%) */
const AX_LO = 2;
const AX_HI = 6;
export const axisPct = (v: number | null | undefined) => (v == null ? null : Math.max(0, Math.min(100, ((Math.log10(Math.max(v, 1) + 1) - AX_LO) / (AX_HI - AX_LO)) * 100)));

/** 예상 범위 막대: q10~q90 범위 + 예상값(v2 한 값) 점 + 1천·1만·10만 기준선(라벨 포함). 점이 범위 밖이어도 그대로 찍는다 */
export function RangeBar({ q10, point, q90, color, height = 10 }: { q10: number | null; point: number | null; q90: number | null; color: string; height?: number }) {
  const lo = axisPct(q10);
  const hi = axisPct(q90);
  const mid = axisPct(point);
  return (
    <div className="relative w-full" style={{ height: height + 12 }} aria-hidden>
      <div className="absolute inset-x-0 h-1 rounded-full bg-[var(--panel-border)]" style={{ top: height / 2 - 2 }} />
      {[{ p: 25, c: "var(--watch)", l: BOARD.tile.axis.k1 }, { p: 50, c: "var(--alert)", l: BOARD.tile.axis.k10 }, { p: 75, c: "var(--severe)", l: BOARD.tile.axis.k100 }].map((t) => (
        <div key={t.p} className="absolute top-0" style={{ left: `${t.p}%` }}>
          <div className="w-px" style={{ height, background: t.c, opacity: 0.9 }} />
          <div className="-translate-x-1/2 text-[10px] leading-3" style={{ color: t.c }}>
            {t.l}
          </div>
        </div>
      ))}
      {lo != null && hi != null && <div className="absolute h-2 rounded-full" style={{ top: height / 2 - 4, left: `${lo}%`, width: `${Math.max(1, hi - lo)}%`, background: `color-mix(in srgb, ${color} 45%, transparent)`, border: `1px solid ${color}` }} />}
      {mid != null && <div className="absolute h-3 w-3 -translate-x-1/2 rounded-full border-2 border-[var(--bg)]" style={{ top: height / 2 - 6, left: `${mid}%`, background: color }} />}
    </div>
  );
}

/** 지점 현황 타일: 지점명+조합 라벨+공식 발령 칩 / 현재 측정 → 예상값(v2 한 값, 32px) / 예상 범위 막대 / 1만 넘을 가능성. q50 은 전문가 보기에만 */
export function SiteTile({ s, expert, rank, today }: { s: SiteStatus; expert: boolean; rank: number; today: string }) {
  const t = tierOf(s.tier);
  const combo = comboOf(s.latest_alert_level, t);
  const c = COMBO[combo];
  const lvl = s.latest_alert_level ?? 0;
  const p = pctInt(s.p_alert);
  const point = s.pred_cell_count;
  const arrow = trendArrow(s.latest_cell_count, point);
  const fmt = expert ? fmtCells : fmtCellsKo;
  const tl = targetLabel(s.target_date, today, point, s.obs_cell_count, fmt, { withValues: false });
  const oor = outOfRange(point, s.q10_cqr, s.q90_cqr);
  const datesTip = `${TERMS.baseDate.label} ${fmtDateKo(s.base_date)} (${TERMS.baseDate.tip}) · ${BOARD.tile.measuredOn} ${fmtDateKo(s.latest_obs_date)} · ${BOARD.tile.ai} ${TIER[t].label}`;
  return (
    <Link
      href={`/sites/${s.site_id}${expert ? "?view=expert" : ""}`}
      data-site={s.site_id}
      className="panel relative flex min-h-[132px] flex-1 flex-col justify-between gap-1 overflow-hidden px-3 py-1 pl-4 2xl:min-h-0 2xl:gap-0 transition-colors hover:border-[var(--accent)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
      aria-label={`${s.name} ${c.label} (${rank}순위)`}
      style={combo === "enter" ? { boxShadow: `inset 0 0 0 1px ${c.color}, 0 0 14px color-mix(in srgb, ${c.color} 35%, transparent)` } : undefined}
    >
      <span className="absolute inset-y-0 left-0 w-1.5" style={{ background: c.color }} aria-hidden />
      {/* 1행: 지점명 + 조합 라벨 + 공식 발령 칩 */}
      <div className="flex items-center gap-2 leading-tight">
        <span className="shrink-0 whitespace-nowrap text-[15px] font-bold tracking-tight">{s.name}</span>
        <span className="min-w-0 truncate text-[15px] font-bold tracking-tight" style={{ color: c.color }}>
          {c.icon} {c.label}
        </span>
        <Info text={`${c.tip} ${datesTip}`} />
        <span className="ml-auto shrink-0 rounded border px-1 py-0.5 text-[11px]" style={{ borderColor: OFFICIAL_LEVEL[lvl].color, color: OFFICIAL_LEVEL[lvl].color }} title={BOARD.basis.nier}>
          {BOARD.tile.official} {OFFICIAL_LEVEL[lvl].label}
        </span>
      </div>
      {/* 2행: 현재 측정 → 예상값 (라벨 줄 + 숫자 줄) */}
      <div className="grid grid-cols-[auto_auto_minmax(0,1fr)] items-end gap-x-3">
        <div className="col-span-3 flex min-w-0 items-center text-xs leading-4 text-dim lg:whitespace-nowrap">
          {BOARD.tile.now}
          <span className="mx-2 opacity-50">→</span>
          {BOARD.tile.next}
          <Info term="point" />
          <span className={`ml-1 min-w-0 truncate ${tl.state === "verified" ? (tl.hit ? "text-[var(--safe)]" : "text-[var(--severe)]") : ""}`}>· {tl.text}</span>
        </div>
        <div className="tile-num whitespace-nowrap">
          {fmt(s.latest_cell_count)}
          <span className="ml-1 text-xs font-normal text-dim">{BOARD.unit.cells}</span>
        </div>
        <div className="pb-1 text-xl text-dim" aria-label={`추세 ${arrow}`}>
          {arrow}
        </div>
        <div className="tile-num whitespace-nowrap" style={{ color: c.color }} data-point>
          {fmt(point)}
          <span className="ml-1 text-xs font-normal text-dim">{BOARD.unit.cells}</span>
          {oor && (
            <span className="ml-1 text-[11px] font-normal text-dim" data-out-of-range={oor}>
              {BOARD.tile.outOfRange}
              <Info text={outOfRangeTip(oor, fmt(s.q10_cqr), fmt(s.q90_cqr))} />
            </span>
          )}
          {tl.state === "verified" && s.obs_cell_count != null && (
            <span className="ml-2 text-base font-semibold text-text">
              → 실제 {fmt(s.obs_cell_count)} {tl.hit ? "✓" : "✗"}
            </span>
          )}
        </div>
      </div>
      {/* 3행: 예상 범위 막대 */}
      <div className="flex items-start gap-2">
        <span className="flex shrink-0 items-center pt-0.5 text-xs text-dim">
          {BOARD.tile.range}
          <Info term="range" />
          {expert && s.q10_cqr != null && <span className="ml-1 text-[10px]">{`${fmtCells(s.q10_cqr)}~${fmtCells(s.q90_cqr)}`}</span>}
        </span>
        <div className="min-w-0 flex-1">
          <RangeBar q10={s.q10_cqr} point={point} q90={s.q90_cqr} color={c.color} />
        </div>
        {expert && s.q50 != null && (
          <span className="shrink-0 whitespace-nowrap pt-0.5 text-[11px] text-dim" title={TERMS.q50.tip} data-q50>
            {BOARD.tile.q50Expert} <span className="font-semibold text-text">{fmt(s.q50)}</span>
          </span>
        )}
      </div>
      {/* 4행: 1만 넘을 가능성 */}
      <div className="flex items-center gap-2 text-xs text-dim">
        <span className="flex min-w-0 shrink items-center">
          <span className="truncate">{BOARD.tile.chance}</span>
          <Info term="pAlert" />
        </span>
        <div className="relative h-2 min-w-0 flex-1 rounded-full bg-[var(--panel-border)]" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={p} aria-label={BOARD.tile.chance}>
          <div className="h-full rounded-full" style={{ width: `${p}%`, background: c.color }} />
          <div className="absolute -top-0.5 h-3 w-0.5 bg-text/70" style={{ left: "52%" }} title={BOARD.basis.chance} aria-hidden />
        </div>
        <span className="w-10 shrink-0 text-right text-lg font-bold text-text">{p}%</span>
      </div>
    </Link>
  );
}
