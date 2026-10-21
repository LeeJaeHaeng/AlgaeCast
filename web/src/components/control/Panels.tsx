import Link from "next/link";
import { Info } from "@/components/Info";
import { BOARD, TIER, banner as bannerText } from "@/lib/copy";
import { fmtDate, tierOf, trendArrow } from "@/lib/format";
import type { ForecastLite, Metric, SiteStatus } from "@/lib/queries";

/** 상황 배너(48px): 색 = 가장 높은 단계, 문구 = §8.3 템플릿, 우측 = 대응 필요/주의 관찰/안전 개수 */
export function Banner({ status, nextRefresh }: { status: SiteStatus[]; nextRefresh: string }) {
  const alerts = status.filter((s) => tierOf(s.tier) === "alert").sort((a, b) => (b.p_alert ?? 0) - (a.p_alert ?? 0));
  const watches = status.filter((s) => tierOf(s.tier) === "watch");
  const safe = status.length - alerts.length - watches.length;
  const top = alerts[0] ?? null;
  const rising = top ? trendArrow(top.latest_cell_count, top.q50) === "↑" : false;
  const text = bannerText(
    alerts.map((s) => s.name),
    watches.map((s) => s.name),
    top?.name ?? null,
    nextRefresh,
    rising,
  );
  const tone = alerts.length ? "alert" : watches.length ? "watch" : "normal";
  const color = TIER[tone].color;
  return (
    <div className="flex h-12 items-center justify-between gap-4 border-b border-border px-4" style={{ background: `color-mix(in srgb, ${color} 18%, var(--bg))` }} role="status" aria-live="polite">
      <div className="flex items-center gap-3 truncate font-bold" style={{ fontSize: "var(--banner-font)", color }}>
        <span aria-hidden>{TIER[tone].icon}</span>
        <span className="truncate">{text}</span>
      </div>
      <div className="flex shrink-0 items-center gap-4 text-base">
        <Count label={BOARD.counts.alert} n={alerts.length} color={TIER.alert.color} icon={TIER.alert.icon} />
        <Count label={BOARD.counts.watch} n={watches.length} color={TIER.watch.color} icon={TIER.watch.icon} />
        <Count label={BOARD.counts.safe} n={safe} color={TIER.normal.color} icon={TIER.normal.icon} />
      </div>
    </div>
  );
}
function Count({ label, n, color, icon }: { label: string; n: number; color: string; icon: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span style={{ color }}>{icon}</span>
      <span className="text-dim">{label}</span>
      <span className="text-xl font-bold" style={{ color }}>
        {n}
      </span>
    </span>
  );
}

/** 향후 7일 날씨: 지점별 7일 평균 기온·비 합계 예보(기상청 단기·중기, 기준일 발표분) */
export function WeatherPanel({ sites, fc }: { sites: SiteStatus[]; fc: ForecastLite[] }) {
  return (
    <section className="panel flex min-h-0 flex-col p-3" aria-label={BOARD.panels.weather}>
      <h2 className="panel-title mb-1">{BOARD.panels.weather}</h2>
      <table className="tbl text-sm">
        <thead>
          <tr>
            <th>지점</th>
            <th className="text-right">{BOARD.weather.temp}</th>
            <th className="text-right">{BOARD.weather.rain}</th>
          </tr>
        </thead>
        <tbody>
          {sites.map((s) => {
            const f = fc.find((x) => x.site_id === s.site_id);
            return (
              <tr key={s.site_id}>
                <td>{s.name}</td>
                <td className="text-right">{f?.fc_ta_mean_d1_7 != null ? `${f.fc_ta_mean_d1_7.toFixed(1)}${BOARD.unit.temp}` : "–"}</td>
                <td className="text-right">{f?.fc_rn_sum_d1_7 != null ? `${Math.round(f.fc_rn_sum_d1_7)}${BOARD.unit.mm}` : "–"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-auto pt-1 text-xs text-dim">
        {BOARD.weather.basis}
        {fc[0] ? ` (${fmtDate(fc[0].obs_date)} 발표)` : ` — ${BOARD.weather.none}`}
      </p>
    </section>
  );
}

/** 성적표 띠(40px): 2020~2026 경계 사건 포착·중앙 리드타임·2026 사후 — 고정된 모델 */
export function ScoreStrip({ metrics, expert }: { metrics: Metric[]; expert: boolean }) {
  const g = (split: string, m: string) => metrics.find((x) => x.split === split && x.site_id == null && x.metric === m)?.value ?? null;
  const ev25 = g("holdout2025", "leadtime_events") ?? 0;
  const det25 = g("holdout2025", "leadtime_detected_watch") ?? 0;
  const ev26 = g("posthoc2026", "leadtime_events") ?? 0;
  const det26 = g("posthoc2026", "leadtime_detected_watch") ?? 0;
  const med = g("posthoc2026", "leadtime_median_days_watch_E") ?? g("holdout2025", "leadtime_median_days_watch_E") ?? 0;
  return (
    <footer className="flex h-10 items-center gap-6 border-t border-border bg-panel px-4 text-sm" aria-label={BOARD.panels.score}>
      <span className="panel-title">{BOARD.panels.score}</span>
      <span>
        <b className="text-base">{BOARD.score.caught(det25 + det26, ev25 + ev26)}</b>
        <span className="text-dim"> (2020~2026년)</span>
      </span>
      <span>
        {BOARD.score.year2026(det26, ev26)}
        <Info term="leadTime" />
      </span>
      <span>
        {BOARD.score.lead(med)} <span className="text-dim">(2026년, 처음 넘은 날 기준)</span>
      </span>
      {expert && (
        <span className="text-dim">
          2025 홀드아웃 rmse_log {g("holdout2025", "rmse_log")?.toFixed(3)} · F1@10k {g("holdout2025", "f1_10k")?.toFixed(3)} · 2026 사후 F1@10k {g("posthoc2026", "f1_10k")?.toFixed(3)}
        </span>
      )}
      <span className="ml-auto flex items-center gap-3 text-dim">
        <span>
          {BOARD.score.frozen}
          <Info term="frozen" />
        </span>
        <Link href={expert ? "/performance?view=expert" : "/performance"} className="underline" style={{ color: "var(--accent)" }}>
          {BOARD.score.detail}
        </Link>
      </span>
    </footer>
  );
}
