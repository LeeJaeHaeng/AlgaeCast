import Link from "next/link";
import { Info } from "@/components/Info";
import { BOARD, COMBO, COMBO_ORDER, banner as bannerText, comboOf } from "@/lib/copy";
import { fmtDate, tierOf } from "@/lib/format";
import { CMP, NUMBERS } from "@/lib/numbers";
import type { ForecastLite, SiteStatus } from "@/lib/queries";

/** 상황 배너(48px): 색 = 가장 높은 조합, 문구 = §8.3 템플릿(조합별 "지점, 지점 라벨" 을 · 로 연결), 우측 = 조합별 개수 */
export function Banner({ status, nextRefresh }: { status: SiteStatus[]; nextRefresh: string }) {
  const byCombo = COMBO_ORDER.map((k) => ({
    combo: k,
    sites: status
      .filter((s) => comboOf(s.latest_alert_level, tierOf(s.tier)) === k)
      .sort((x, y) => (y.p_alert ?? 0) - (x.p_alert ?? 0))
      .map((s) => s.name),
  }));
  const text = bannerText(byCombo, nextRefresh);
  const top = byCombo.find((g) => g.sites.length)?.combo ?? "safe";
  const color = COMBO[top].color;
  return (
    <div className="flex min-h-12 items-center justify-between gap-4 border-b border-border px-4" style={{ background: `color-mix(in srgb, ${color} 18%, var(--bg))` }} role="status" aria-live="polite">
      <div className="flex min-w-0 items-center gap-3 truncate font-bold" style={{ fontSize: "var(--banner-font)", color }}>
        <span aria-hidden>{COMBO[top].icon}</span>
        <span className="truncate">{text}</span>
      </div>
      <div className="hidden shrink-0 items-center gap-4 text-base xl:flex">
        {byCombo.map((g) => (
          <Count key={g.combo} label={COMBO[g.combo].bannerWord} n={g.sites.length} color={COMBO[g.combo].color} icon={COMBO[g.combo].icon} />
        ))}
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

/** 성적표 띠(40px): 2020~2026 경계 사건 포착·중앙 리드타임·2026 사후 계산(블라인드 아님) — 제출·운영 모델 v2.1 */
export function ScoreStrip({ expert }: { expert: boolean }) {
  const { events: ev, y2026 } = NUMBERS; // 헤드라인 숫자는 numbers.ts(빌드 전 reports/eval 과 대조)
  const f2 = (v: number) => v.toFixed(2);
  return (
    <footer className="flex h-10 items-center gap-6 border-t border-border bg-panel px-4 text-sm" aria-label={BOARD.panels.score}>
      <span className="panel-title">{BOARD.panels.score}</span>
      <span>
        <b className="text-base">{BOARD.score.caught(ev.detected, ev.total)}</b>
        <span className="text-dim"> ({BOARD.score.lead(ev.medianLeadDays)} · 2020~2026년)</span>
        <Info term="leadTime" />
      </span>
      <span>
        {BOARD.score.year2026(y2026.detected, y2026.total)}{" "}
        <span className="text-dim">
          ({BOARD.score.lead(y2026.medianLeadDays)} · {BOARD.score.year2026Sub})
        </span>
      </span>
      {expert && (
        <span className="text-dim">{BOARD.score.expert(f2(CMP.h25v21.f1_10k), f2(CMP.h25b0.f1_10k), f2(CMP.p26v21.f1_10k), f2(CMP.p26b0.f1_10k))}</span>
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
