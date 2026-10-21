import Link from "next/link";
import { Info } from "@/components/Info";
import { BOARD, OFFICIAL_LEVEL, TIER, TIER_EXPERT } from "@/lib/copy";
import { fmtCells, fmtCellsKo, fmtDate, pctInt, tierOf, trendArrow } from "@/lib/format";
import type { SiteStatus } from "@/lib/queries";

/** 지점 현황 타일: 단계 색 띠 · 지점명 · 단계명 · 현재 측정값 · 7일 뒤 예상값 · 가능성 막대 · 추세 화살표 */
export function SiteTile({ s, expert, rank }: { s: SiteStatus; expert: boolean; rank: number }) {
  const t = tierOf(s.tier);
  const tier = TIER[t];
  const lvl = s.latest_alert_level ?? 0;
  const p = pctInt(s.p_alert);
  const arrow = trendArrow(s.latest_cell_count, s.q50);
  const fmt = expert ? fmtCells : fmtCellsKo;
  return (
    <Link
      href={`/sites/${s.site_id}${expert ? "?view=expert" : ""}`}
      data-site={s.site_id}
      className="panel relative flex min-h-0 flex-1 flex-col justify-between overflow-hidden px-3 py-2 pl-4 transition-colors hover:border-[var(--accent)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
      aria-label={`${rank}순위 ${s.name} ${tier.label}`}
    >
      <span className="absolute inset-y-0 left-0 w-1.5" style={{ background: tier.color }} aria-hidden />
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <span className="text-lg font-bold">{s.name}</span>
          <span className="text-base font-semibold" style={{ color: tier.color }}>
            {tier.icon} {tier.label}
          </span>
          {expert && <span className="text-xs text-dim">{TIER_EXPERT[t]}</span>}
        </div>
        <span className="rounded border px-1.5 py-0.5 text-xs" style={{ borderColor: OFFICIAL_LEVEL[lvl].color, color: OFFICIAL_LEVEL[lvl].color }} title={BOARD.basis.nier}>
          {BOARD.tile.official} {OFFICIAL_LEVEL[lvl].label}
        </span>
      </div>
      <div className="flex items-end gap-4">
        <div>
          <div className="text-xs text-dim">
            {BOARD.tile.now} <span className="opacity-70">({BOARD.tile.measuredOn} {fmtDate(s.latest_obs_date)})</span>
          </div>
          <div className="tile-num">
            {fmt(s.latest_cell_count)}
            <span className="ml-1 text-sm font-normal text-dim">{BOARD.unit.cells}</span>
          </div>
        </div>
        <div className="pb-1 text-2xl text-dim" aria-label={`추세 ${arrow}`}>
          {arrow}
        </div>
        <div>
          <div className="text-xs text-dim">
            {BOARD.tile.next} <span className="opacity-70">({BOARD.tile.baseOn} {fmtDate(s.base_date)})</span>
          </div>
          <div className="tile-num" style={{ color: tier.color }}>
            {fmt(s.q50)}
            <span className="ml-1 text-sm font-normal text-dim">{BOARD.unit.cells}</span>
          </div>
        </div>
      </div>
      <div>
        <div className="flex items-center justify-between text-xs text-dim">
          <span>
            {BOARD.tile.chance}
            <Info term="pAlert" />
            {expert && s.q10_cqr != null && (
              <span className="ml-2">
                범위 {fmtCells(s.q10_cqr)}~{fmtCells(s.q90_cqr)}
              </span>
            )}
          </span>
          <span className="text-sm font-semibold text-text">{p}%</span>
        </div>
        <div className="relative mt-0.5 h-2 w-full rounded-full bg-[var(--panel-border)]" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={p} aria-label={BOARD.tile.chance}>
          <div className="h-full rounded-full" style={{ width: `${p}%`, background: tier.color }} />
          <div className="absolute -top-0.5 h-3 w-0.5 bg-text/70" style={{ left: "52%" }} title="대응 필요 기준 52%" aria-hidden />
        </div>
      </div>
    </Link>
  );
}
