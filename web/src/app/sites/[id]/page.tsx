import { notFound } from "next/navigation";
import { Info } from "@/components/Info";
import { PageFrame } from "@/components/PageFrame";
import { RangeBar } from "@/components/control/SiteTile";
import { BigChart, EnvChart } from "@/components/site/SiteCharts";
import { BOARD, COMBO, GROUP_LABEL, OFFICIAL_LEVEL, REASON, REASON_WATER_UP_MILD, SITE, TERMS, TIER, TIER_EXPERT, comboOf, levelOfCells, reasonWaterDays, targetLabel, type FeatureGroup } from "@/lib/copy";
import { ALERT_LEVEL_LABEL, fmtCells, fmtCellsKo, fmtDate, fmtDateFull, fmtDateKo, pctInt, tierOf } from "@/lib/format";
import { getBloomEvents, getHydro, getLatestRun, getObservations, getPredictions, getShap, getSiteStatus, getSites, getWeather } from "@/lib/queries";

export const revalidate = 300;

export async function generateStaticParams() {
  return ["2011G26", "2011G56", "2020G33", "2022G05", "3008G30"].map((id) => ({ id }));
}

const GROUPS: FeatureGroup[] = ["ar", "water", "hydro", "weather", "forecast", "time_site"];

export default async function SitePage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<Record<string, string | undefined>> }) {
  const [{ id }, sp] = await Promise.all([params, searchParams]);
  const expert = sp.view === "expert";
  const [sites, status, run] = await Promise.all([getSites(), getSiteStatus(), getLatestRun()]);
  const site = sites.find((s) => s.site_id === id);
  if (!site) notFound();
  const st = status.find((s) => s.site_id === id);
  const [obs, preds, shap, events, hydro, weather] = await Promise.all([getObservations(id, 365), getPredictions(id, run?.run_id ?? null, 400), getShap(id, run?.run_id ?? null), getBloomEvents(id), getHydro(id, 180), getWeather(id, 180)]);
  const today = new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" });
  const fmt = expert ? fmtCells : fmtCellsKo;
  const t = tierOf(st?.tier);
  const combo = comboOf(st?.latest_alert_level, t);
  const c = COMBO[combo];
  const lvl = st?.latest_alert_level ?? 0;
  const p = pctInt(st?.p_alert);
  const tl = targetLabel(st?.target_date, today, st?.q50, st?.obs_cell_count, fmt);

  // 큰 차트: 1년 측정 + 지난 예상(회색) + 이번 예상(파란 점·띠)
  const latest = preds.at(-1);
  const pastByTarget = new Map(preds.filter((x) => x.target_date !== latest?.target_date).map((x) => [x.target_date, x.q50]));
  const pts = [...obs.map((o) => ({ date: o.obs_date, obs: o.cell_count, past_pred: pastByTarget.get(o.obs_date) ?? null })), ...(latest ? [{ date: latest.target_date, obs: null, q50: latest.q50, lo: latest.q10_cqr, hi: latest.q90_cqr }] : [])].sort((a, b) => a.date.localeCompare(b.date));

  // 왜 이렇게 예상했나: 그룹별 기여 합 → 상위 3개 → §8.1 템플릿
  const byGroup = new Map<FeatureGroup, number>();
  for (const s of shap) {
    const g = (GROUPS.includes(s.feature_group as FeatureGroup) ? s.feature_group : "time_site") as FeatureGroup;
    byGroup.set(g, (byGroup.get(g) ?? 0) + (s.shap_value ?? 0));
  }
  const hotDays = obs.filter((o) => o.obs_date >= new Date(Date.now() - 30 * 86_400_000).toISOString().slice(0, 10) && (o.water_temp ?? 0) >= 25).length;
  const reasons = [...byGroup.entries()]
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 3)
    .map(([g, v]) => ({ g, v, text: g === "water" && v >= 0 ? (hotDays > 0 ? `${REASON.water.up} ${reasonWaterDays(hotDays)}` : REASON_WATER_UP_MILD) : REASON[g][v >= 0 ? "up" : "down"] }));
  const total = [...byGroup.values()].reduce((a, b) => a + Math.abs(b), 0) || 1;

  // 지난 예상은 맞았나 (실측이 온 최근 10건)
  const verified = preds.filter((x) => x.obs_cell_count != null).slice(-10).reverse();
  const hits = verified.filter((x) => levelOfCells(x.q50) === levelOfCells(x.obs_cell_count)).length;

  const q50Over = (st?.q50 ?? 0) >= 10_000;
  const hiOver = (st?.q90_cqr ?? 0) >= 10_000;
  const plain = q50Over ? SITE.plain.whyOver(fmt(st?.q50), p) : hiOver ? SITE.plain.whyHighChance(fmt(st?.q50), p) : SITE.plain.whyLowChance(fmt(st?.q50), p);

  const wtData = obs.filter((o) => o.obs_date >= new Date(Date.now() - 180 * 86_400_000).toISOString().slice(0, 10)).map((o) => ({ date: o.obs_date, wt: o.water_temp }));
  const hydroData = hydro.map((h) => ({ date: h.obs_date, inflow: h.inflow_cms, outflow: h.outflow_cms, rain: h.rainfall_mm }));
  const wxData = weather.map((w) => ({ date: w.obs_date, ta: w.ta_mean, rn: w.rn_sum }));

  return (
    <PageFrame title="" expert={expert} back={{ href: "/", label: SITE.back }}>
      {/* 머리: 지점 · 조합 라벨 · 공식/AI · 날짜 */}
      <header className="panel flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3" style={combo === "enter" ? { boxShadow: `inset 0 0 0 1px ${c.color}` } : undefined}>
        <h1 className="text-3xl font-bold">{site.name}</h1>
        <span className="text-2xl font-bold" style={{ color: c.color }}>
          {c.icon} {c.label}
        </span>
        <Info text={c.tip} />
        <span className="rounded border px-2 py-0.5 text-sm" style={{ borderColor: OFFICIAL_LEVEL[lvl].color, color: OFFICIAL_LEVEL[lvl].color }}>
          {BOARD.tile.official} {OFFICIAL_LEVEL[lvl].label} <span className="opacity-70">({SITE.measuredBasis})</span>
        </span>
        <span className="rounded border px-2 py-0.5 text-sm" style={{ borderColor: TIER[t].color, color: TIER[t].color }}>
          {BOARD.tile.ai} {TIER[t].label}
          {expert && <span className="ml-1 opacity-70">{TIER_EXPERT[t]}</span>}
        </span>
        <span className="ml-auto text-sm text-dim">
          {site.basin} · {SITE.facility(site.facility_name ?? "–")} · {TERMS.baseDate.label} {fmtDateKo(st?.base_date)}
          <Info term="baseDate" /> · {BOARD.tile.measuredOn} {fmtDateKo(st?.latest_obs_date)}
        </span>
      </header>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        {/* 큰 차트 */}
        <section className="panel p-3">
          <div className="flex items-baseline justify-between">
            <h2 className="text-lg font-semibold">{SITE.chart.title}</h2>
            <span className="text-xs text-dim">{SITE.chart.legend}</span>
          </div>
          <BigChart points={pts} height={360} />
        </section>
        {/* 앞으로 7일 */}
        <section className="panel flex flex-col gap-3 p-4">
          <h2 className="text-lg font-semibold">{SITE.forecastBox}</h2>
          <div>
            <div className="flex items-center text-sm text-dim">
              {TERMS.q50.label}
              <Info term="q50" />
              <span className={`ml-2 ${tl.state === "verified" ? (tl.hit ? "text-[var(--safe)]" : "text-[var(--severe)]") : ""}`}>{tl.text}</span>
            </div>
            <div className="text-[44px] font-bold leading-none" style={{ color: c.color }}>
              {fmt(st?.q50)} <span className="text-base font-normal text-dim">{BOARD.unit.cells}</span>
            </div>
          </div>
          <div>
            <div className="flex items-center text-sm text-dim">
              {TERMS.range.label}
              <Info term="range" />
              <span className="ml-2 text-text">
                {fmt(st?.q10_cqr)} ~ {fmt(st?.q90_cqr)} {BOARD.unit.cells}
              </span>
            </div>
            <RangeBar q10={st?.q10_cqr ?? null} q50={st?.q50 ?? null} q90={st?.q90_cqr ?? null} color={c.color} height={14} />
          </div>
          <div>
            <div className="flex items-center text-sm text-dim">
              {TERMS.pAlert.label}
              <Info term="pAlert" />
            </div>
            <div className="flex items-center gap-3">
              <div className="relative h-3 flex-1 rounded-full bg-[var(--panel-border)]" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={p} aria-label={TERMS.pAlert.label}>
                <div className="h-full rounded-full" style={{ width: `${p}%`, background: c.color }} />
                <div className="absolute -top-1 h-5 w-0.5 bg-text/70" style={{ left: "52%" }} title={BOARD.basis.chance} aria-hidden />
              </div>
              <span className="text-4xl font-bold">{p}%</span>
            </div>
            {expert && <div className="text-xs text-dim">p_alert {(st?.p_alert ?? 0).toFixed(3)} · 운영점 0.52 · CQR q10 {fmtCells(st?.q10_cqr)} / q90 {fmtCells(st?.q90_cqr)}</div>}
          </div>
          <p className="text-base leading-relaxed">{plain}</p>
          <p className="text-sm leading-relaxed text-dim">
            {TERMS.frozen.label}
            <Info term="frozen" /> — {SITE.plain.frozen}
          </p>
        </section>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        {/* 왜 이렇게 예상했나 */}
        <section className="panel p-4">
          <h2 className="flex items-center text-lg font-semibold">
            {SITE.whyBox}
            <Info term="why" />
          </h2>
          <p className="mb-2 text-xs text-dim">{SITE.reasonsIntro}</p>
          <ol className="space-y-2">
            {reasons.map((r, i) => (
              <li key={r.g} className="flex items-start gap-2 text-base">
                <span className="mt-0.5 text-lg font-bold" style={{ color: r.v >= 0 ? "var(--alert)" : "var(--safe)" }}>
                  {["①", "②", "③"][i]}
                </span>
                <span>
                  <span className="font-semibold">{r.text}</span>
                  <span className="ml-2 text-xs text-dim">
                    {GROUP_LABEL[r.g]} · {r.v >= 0 ? "올림" : "내림"} {Math.round((Math.abs(r.v) / total) * 100)}%
                  </span>
                </span>
              </li>
            ))}
            {!reasons.length && <li className="text-sm text-dim">근거 자료가 아직 없습니다.</li>}
          </ol>
          {expert && shap.length > 0 && (
            <table className="tbl mt-3 text-xs">
              <thead>
                <tr>
                  <th>feature</th>
                  <th>group</th>
                  <th className="text-right">shap</th>
                  <th className="text-right">value</th>
                </tr>
              </thead>
              <tbody>
                {shap.map((s) => (
                  <tr key={s.feature_name}>
                    <td>{s.feature_name}</td>
                    <td>{s.feature_group}</td>
                    <td className="text-right">{(s.shap_value ?? 0).toFixed(3)}</td>
                    <td className="text-right">{s.feature_value?.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {/* 지난 녹조 발생 기록과 미리 알림 */}
        <section className="panel p-4">
          <h2 className="flex items-center text-lg font-semibold">
            {SITE.historyBox}
            <Info term="leadTime" />
          </h2>
          {events.length ? (
            <table className="tbl mt-2">
              <thead>
                <tr>
                  <th>{SITE.history.cols.first}</th>
                  <th>{SITE.history.cols.official}</th>
                  <th>{SITE.history.cols.watch}</th>
                  <th className="text-right">{SITE.history.cols.lead}</th>
                </tr>
              </thead>
              <tbody>
                {events.slice(0, 8).map((e) => (
                  <tr key={e.event_id}>
                    <td>
                      {fmtDateFull(e.first_exceed_date)}
                      {e.first_exceed_date >= "2026-01-01" && <span className="ml-1 text-[10px] text-dim">({SITE.history.posthoc})</span>}
                    </td>
                    <td>{fmtDateFull(e.official_alert_date)}</td>
                    <td>{e.first_watch_date ? fmtDateFull(e.first_watch_date) : "–"}</td>
                    <td className="text-right font-semibold" style={{ color: e.detected_watch ? "var(--safe)" : "var(--severe)" }}>
                      {e.detected_watch && e.lead_days_watch_e != null ? SITE.history.caught(e.lead_days_watch_e) : SITE.history.missed}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="mt-2 text-sm text-dim">{SITE.history.none}</p>
          )}
          <h3 className="mt-4 text-sm font-semibold text-dim">{SITE.verifyBox}</h3>
          <p className="text-base">{verified.length ? SITE.verifySummary(hits, verified.length) : "실측이 도착한 예상이 아직 없습니다."}</p>
          {expert && verified.length > 0 && (
            <table className="tbl mt-2 text-xs">
              <thead>
                <tr>
                  <th>{SITE.verifyCols.base}</th>
                  <th>{SITE.verifyCols.target}</th>
                  <th className="text-right">{SITE.verifyCols.pred}</th>
                  <th className="text-right">{SITE.verifyCols.actual}</th>
                  <th>{SITE.verifyCols.same}</th>
                </tr>
              </thead>
              <tbody>
                {verified.map((v) => (
                  <tr key={`${v.base_date}-${v.target_date}`}>
                    <td>{fmtDate(v.base_date)}</td>
                    <td>{fmtDate(v.target_date)}</td>
                    <td className="text-right">{fmtCells(v.q50)}</td>
                    <td className="text-right">{fmtCells(v.obs_cell_count)}</td>
                    <td>{levelOfCells(v.q50) === levelOfCells(v.obs_cell_count) ? "✓" : "✗"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {/* 권고 조치 */}
        <section className="panel p-4" style={{ borderColor: c.color }}>
          <h2 className="text-lg font-semibold">{SITE.recoBox}</h2>
          <p className="mt-1 text-lg font-semibold" style={{ color: c.color }}>
            {c.icon} {c.label}
          </p>
          <p className="mt-1 text-base leading-relaxed">{c.reco(site.name, p)}</p>
          <ul className="mt-3 space-y-1 text-base">
            {c.actions.map((a) => (
              <li key={a} className="flex items-start gap-2">
                <span style={{ color: c.color }}>▸</span>
                {a}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-dim">
            {BOARD.tile.official} {ALERT_LEVEL_LABEL[lvl]} ({SITE.measuredBasis}) 과 {BOARD.tile.ai} {TIER[t].label} 을 함께 본 판단입니다. 공식 발령을 대체하지 않습니다.
          </p>
        </section>
      </div>

      {/* 물·날씨 상황 */}
      <section className="panel p-4">
        <h2 className="text-lg font-semibold">{SITE.envBox}</h2>
        <div className="mt-2 grid gap-4 lg:grid-cols-3">
          <div>
            <div className="text-sm font-semibold">{SITE.tabs.water}</div>
            <div className="text-xs text-dim">{SITE.envNote.water}</div>
            <EnvChart data={wtData} keys={[{ k: "wt", label: "물 온도", color: "#38BDF8" }]} height={180} unit="℃" />
          </div>
          <div>
            <div className="text-sm font-semibold">{SITE.tabs.flow}</div>
            <div className="text-xs text-dim">{SITE.envNote.flow}</div>
            <EnvChart data={hydroData} keys={[{ k: "inflow", label: "들어오는 물", color: "#22C55E" }, { k: "outflow", label: "내보내는 물(방류)", color: "#F97316" }]} height={180} unit="㎥/s" />
          </div>
          <div>
            <div className="text-sm font-semibold">{SITE.tabs.weather}</div>
            <div className="text-xs text-dim">{SITE.envNote.weather}</div>
            <EnvChart data={wxData} keys={[{ k: "ta", label: "기온(℃)", color: "#FACC15" }, { k: "rn", label: "비(mm)", color: "#38BDF8" }]} height={180} />
          </div>
        </div>
      </section>
    </PageFrame>
  );
}
