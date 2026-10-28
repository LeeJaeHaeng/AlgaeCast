import { notFound } from "next/navigation";
import { Info } from "@/components/Info";
import { PageFrame } from "@/components/PageFrame";
import { ReplayBand, ReplayNotice } from "@/components/control/ReplayBand";
import { RangeBar } from "@/components/control/SiteTile";
import { BigChart, EnvChart, type SeriesPoint } from "@/components/site/SiteCharts";
import { BOARD, COMBO, GROUP_LABEL, OFFICIAL_LEVEL, REASON, REASON_WATER_UP_MILD, REPLAY, SITE, TERMS, TIER, TIER_EXPERT, UPSTREAM_PREFIX, comboOf, explainForecast, levelOfCells, outOfRange, outOfRangeTip, reasonWaterDays, targetLabel, type FeatureGroup } from "@/lib/copy";
import { addDays, fmtCells, fmtCellsKo, fmtDate, fmtDateFull, fmtDateKo, pctInt, tierOf } from "@/lib/format";
import { getBloomEvents, getHydro, getLatestRun, getObservations, getObservationsAfter, getPredictions, getReplayBounds, getReplayRun, getShap, getSiteStatus, getSites, getWeather, type Observation, type Shap } from "@/lib/queries";
import { addDaysISO, buildStatusAsOf, eventsAsOf, fillActualAsOf, mergeSameDate, obsAsOf, predsAsOf, replayMinOf, replayQuery, replayState, type Replay } from "@/lib/replay";
import { OP_PCT } from "@/lib/numbers";

export const revalidate = 300;

export async function generateStaticParams() {
  return ["2011G26", "2011G56", "2020G33", "2022G05", "3008G30"].map((id) => ({ id }));
}

const GROUPS: FeatureGroup[] = ["ar", "water", "hydro", "weather", "forecast", "time_site", "upstream"];

export default async function SitePage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<Record<string, string | undefined>> }) {
  const [{ id }, sp] = await Promise.all([params, searchParams]);
  const expert = sp.view === "expert";
  // 다시 보기(?asof=YYYY-MM-DD): 그날까지의 관측·그날 기준 예측만(쿼리 단계에서 거름). 틀리거나 범위 밖이면 현재 화면 + 한 줄 안내
  const wantsReplay = sp.asof !== undefined && sp.asof !== "";
  // 다시 보기는 고정한 run(REPLAY_RUN_ID, 없으면 최신 run)의 지난 예상값을 쓴다. 날짜가 틀려 현재 화면을 보일 때는 최신 run
  const [sites, status0, latestRun, replayRun] = await Promise.all([getSites(), wantsReplay ? Promise.resolve(null) : getSiteStatus(), getLatestRun(), wantsReplay ? getReplayRun() : Promise.resolve(null)]);
  const bounds = wantsReplay ? await getReplayBounds(replayRun?.run_id ?? null) : null;
  const rstate = bounds ? replayState(sp.asof, bounds) : "none";
  const replay: Replay | null = bounds && rstate === "ok" ? { asof: sp.asof as string, after: sp.after === "1" } : null;
  const run = replay ? replayRun : latestRun;
  const notice = bounds && (rstate === "bad" || rstate === "range") ? REPLAY.notice(replayMinOf(bounds), bounds.max ?? "–") : null;
  const asof = replay?.asof;
  const site = sites.find((s) => s.site_id === id);
  if (!site) notFound();
  const status = status0 ?? (replay ? [] : await getSiteStatus());
  const [obs, predsQ, shap0, eventsQ, hydro, weather] = await Promise.all([getObservations(id, 365, asof), getPredictions(id, run?.run_id ?? null, 400, asof), replay ? Promise.resolve([] as Shap[]) : getShap(id, run?.run_id ?? null), getBloomEvents(id, asof), getHydro(id, 180, asof), getWeather(id, 180, asof)]);
  // 다시 보기: 예측 행의 실측은 목표일 ≤ asof 만(비어 있으면 그날까지의 목표일 관측으로 채움), 사건은 공식 발령일 ≤ asof 만, 지점 상태는 그날 기준으로 다시 만든다
  const preds = replay ? fillActualAsOf(predsAsOf(predsQ, replay.asof), obs, replay.asof) : predsQ;
  const events = replay ? eventsAsOf(eventsQ, replay.asof) : eventsQ;
  const st = replay
    ? buildStatusAsOf(
        [site],
        preds.map((p) => ({ ...p, site_id: id })),
        obsAsOf(obs, replay.asof).map((o) => ({ site_id: id, obs_date: o.obs_date, cell_count: o.cell_count, alert_level: o.alert_level, water_temp: o.water_temp })),
        replay.asof,
      )[0]
    : status.find((s) => s.site_id === id);
  const shap = replay ? await getShap(id, run?.run_id ?? null, st?.base_date ?? null) : shap0;
  const afterObs: Observation[] = replay?.after ? await getObservationsAfter(id, replay.asof) : [];
  const today = replay ? replay.asof : new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" });
  const rq = replay ? replayQuery({ replay, expert }) : undefined;
  const fmt = expert ? fmtCells : fmtCellsKo;
  const t = tierOf(st?.tier);
  const combo = comboOf(st?.latest_alert_level, t);
  const c = COMBO[combo];
  const lvl = st?.latest_alert_level ?? 0;
  const p = pctInt(st?.p_alert);
  // 예상값 = T24 한 값 예측(pred_cell_count). q50(T24 분위 중앙값)은 전문가 보기에만
  const point = st?.pred_cell_count ?? null;
  const tl = targetLabel(st?.target_date, today, point, st?.obs_cell_count, fmt);
  const oor = outOfRange(point, st?.q10_cqr, st?.q90_cqr);

  // 큰 차트: 1년 측정 + 지난 예상값(회색) + 이번 예상값(파란 점·띠)
  const latest = preds.at(-1);
  const pastByTarget = new Map(preds.filter((x) => x.target_date !== latest?.target_date).map((x) => [x.target_date, x.pred_cell_count]));
  // 다시 보기: 범위 띠의 앞뒤 2일 여백 점은 차트(BigChart bandPad)가 브라우저에서 만든다 — 서버가 보내는 자료에는 목표일 하나만(그날 뒤 날짜를 싣지 않음)
  const pts0 = [...obs.map((o) => ({ date: o.obs_date, obs: o.cell_count, past_pred: pastByTarget.get(o.obs_date) ?? null })), ...(latest ? (replay ? [0] : [-2, 0, 2]).map((d) => ({ date: addDays(latest.target_date, d).toISOString().slice(0, 10), obs: null, pred: d === 0 ? latest.pred_cell_count : null, lo: latest.q10_cqr, hi: latest.q90_cqr })) : [])].sort((a, b) => a.date.localeCompare(b.date));
  // 다시 보기: 그날 세로선 자리(그날 측정이 없으면 빈 점) + '그 뒤 실제로는' 실측(asof 뒤 21일, 켰을 때만)
  const pts: SeriesPoint[] = replay ? [...pts0] : pts0;
  if (replay) {
    if (!pts.some((p) => p.date === replay.asof)) pts.push({ date: replay.asof, obs: null, past_pred: null });
    // 값이 없는 측정 행(세포수 비어 있음)은 그릴 것이 없어 싣지 않는다(그날 뒤 날짜만 담긴 빈 점을 보내지 않게)
    for (const a of afterObs.filter((x) => x.cell_count != null)) {
      const i = pts.findIndex((p) => p.date === a.obs_date);
      if (i >= 0) pts[i] = { ...pts[i], actual: a.cell_count };
      else pts.push({ date: a.obs_date, past_pred: null, actual: a.cell_count });
    }
    // 같은 날짜 점 합치기(목표일 ≤ 그날이고 그 날 측정이 있으면 날짜가 겹쳐 그날 세로선이 사라지던 문제)
    pts.splice(0, pts.length, ...mergeSameDate(pts));
  }

  // 왜 이렇게 예상했나: 그룹별 기여 합 → 상위 3개 → §8.1 템플릿
  const byGroup = new Map<FeatureGroup, number>();
  for (const s of shap) {
    // v2 상류 피처(up1_*)는 DB 그룹이 "etc" → 이름 접두어로 상류 그룹에 묶는다(그 밖의 미분류는 계절·지점 특성)
    const g = (s.feature_name.startsWith(UPSTREAM_PREFIX) ? "upstream" : GROUPS.includes(s.feature_group as FeatureGroup) ? s.feature_group : "time_site") as FeatureGroup;
    byGroup.set(g, (byGroup.get(g) ?? 0) + (s.shap_value ?? 0));
  }
  const d30 = replay ? addDaysISO(replay.asof, -30) : new Date(Date.now() - 30 * 86_400_000).toISOString().slice(0, 10);
  const hotDays = obs.filter((o) => o.obs_date >= d30 && (o.water_temp ?? 0) >= 25).length;
  const reasons = [...byGroup.entries()]
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 3)
    .map(([g, v]) => ({ g, v, text: g === "water" && v >= 0 ? (hotDays > 0 ? `${REASON.water.up} ${reasonWaterDays(hotDays)}` : REASON_WATER_UP_MILD) : REASON[g][v >= 0 ? "up" : "down"] }));
  const total = [...byGroup.values()].reduce((a, b) => a + Math.abs(b), 0) || 1;

  // 지난 예상은 맞았나 (실측이 온 최근 10건)
  const verified = preds.filter((x) => x.obs_cell_count != null).slice(-10).reverse();
  const hits = verified.filter((x) => levelOfCells(x.pred_cell_count) === levelOfCells(x.obs_cell_count)).length;

  const plain = explainForecast(point, st?.q90_cqr, p, fmt);

  const d180 = replay ? addDaysISO(replay.asof, -180) : new Date(Date.now() - 180 * 86_400_000).toISOString().slice(0, 10);
  const wtData = obs.filter((o) => o.obs_date >= d180).map((o) => ({ date: o.obs_date, wt: o.water_temp }));
  const hydroData = hydro.map((h) => ({ date: h.obs_date, inflow: h.inflow_cms, outflow: h.outflow_cms, rain: h.rainfall_mm }));
  const wxData = weather.map((w) => ({ date: w.obs_date, ta: w.ta_mean, rn: w.rn_sum }));

  return (
    // 글꼴 폴백 크기 보정(globals.css .fit-fallback-font): Pretendard 교체 때 아래 묶음이 밀리던 CLS 방지
    // .site-detail: 좁은 화면(≤767px) 가로 넘침 방지 규칙의 범위(globals.css), 768px 이상에는 적용되는 스타일 없음
    <PageFrame
      title=""
      expert={expert}
      back={{ href: "/", label: SITE.back }}
      className="fit-fallback-font site-detail"
      {...(replay ? { top: <ReplayBand replay={replay} path={`/sites/${id}`} expert={expert} />, homeQuery: rq, expertHref: `/sites/${id}${replayQuery({ replay, expert: !expert })}` } : notice ? { top: <ReplayNotice text={notice} /> } : {})}
    >
      {/* 머리: 지점 · 조합 라벨 · 공식/AI · 날짜 */}
      <header className="panel flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3" style={combo === "enter" ? { boxShadow: `inset 0 0 0 1px ${c.color}` } : undefined}>
        <h1 className="text-3xl font-bold">{site.name}</h1>
        <span className="text-2xl font-bold" style={{ color: c.color }}>
          {c.icon} {c.label}
        </span>
        <Info text={c.tip} />
        {/* '공식 발령' + 접두어 뒤 라벨(after) — 글자 마디를 전과 같게 두어(픽셀 동일) 0단계만 "공식 발령 없음"으로 바뀐다 */}
        <span className="rounded border px-2 py-0.5 text-sm" style={{ borderColor: OFFICIAL_LEVEL[lvl].color, color: OFFICIAL_LEVEL[lvl].color }}>
          {BOARD.tile.official} {OFFICIAL_LEVEL[lvl].after} <span className="opacity-70">({SITE.measuredBasis})</span>
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
            <span className="text-xs text-dim">
              {SITE.chart.legend} · 회색 작은 점 = {SITE.chartLow}
              {replay?.after && <span style={{ color: "var(--after)" }}> · {REPLAY.legendAfter}</span>}
            </span>
          </div>
          <BigChart points={pts} height={360} {...(replay ? { asof: replay.asof, bandPad: 2 } : {})} />
        </section>
        {/* 앞으로 7일 — data-replay-forecast(다시 보기에서만): 예측 목표일이 글자로 보이는 유일한 구역(scripts/check_asof.mjs 가 구역별로 검사) */}
        <section className="panel flex flex-col gap-3 p-4" data-replay-forecast={replay?.asof}>
          <h2 className="text-lg font-semibold">{SITE.forecastBox}</h2>
          <div>
            <div className="flex items-center text-sm text-dim">
              {TERMS.point.label}
              <Info term="point" />
              <span className={`ml-2 ${tl.state === "verified" ? (tl.hit ? "text-[var(--safe)]" : "text-[var(--severe)]") : ""}`}>{tl.text}</span>
            </div>
            <div className="text-[44px] font-bold leading-none" style={{ color: c.color }} data-point>
              {fmt(point)} <span className="text-base font-normal text-dim">{BOARD.unit.cells}</span>
              {oor && (
                <span className="ml-1 align-middle text-sm font-normal text-dim" data-out-of-range={oor}>
                  {BOARD.tile.outOfRange}
                  <Info text={outOfRangeTip(oor, fmt(st?.q10_cqr), fmt(st?.q90_cqr))} />
                </span>
              )}
            </div>
            {expert && st?.q50 != null && (
              <div className="mt-1 text-sm text-dim" data-q50>
                {TERMS.q50.label} <span className="font-semibold text-text">{fmtCells(st.q50)}</span> {BOARD.unit.cells}
                <Info term="q50" />
              </div>
            )}
          </div>
          <div>
            <div className="flex items-center text-sm text-dim">
              {TERMS.range.label}
              <Info term="range" />
              <span className="ml-2 text-text">
                {fmt(st?.q10_cqr)} ~ {fmt(st?.q90_cqr)} {BOARD.unit.cells}
              </span>
            </div>
            <RangeBar q10={st?.q10_cqr ?? null} point={point} q90={st?.q90_cqr ?? null} color={c.color} height={14} />
          </div>
          <div>
            <div className="flex items-center text-sm text-dim">
              {TERMS.pAlert.label}
              <Info term="pAlert" />
            </div>
            <div className="flex items-center gap-3">
              <div className="relative h-3 flex-1 rounded-full bg-[var(--panel-border)]" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={p} aria-label={TERMS.pAlert.label}>
                <div className="h-full rounded-full" style={{ width: `${p}%`, background: c.color }} />
                <div className="absolute -top-1 h-5 w-0.5 bg-text/70" style={{ left: `${OP_PCT}%` }} title={BOARD.basis.chance} aria-hidden />
              </div>
              <span className="text-4xl font-bold">{p}%</span>
            </div>
            {expert && <div className="text-xs text-dim">p_alert {(st?.p_alert ?? 0).toFixed(3)} · 운영점 {(OP_PCT / 100).toFixed(2)} · CQR q10 {fmtCells(st?.q10_cqr)} / q90 {fmtCells(st?.q90_cqr)}</div>}
          </div>
          <p className="text-base leading-relaxed">{plain}</p>
          <p className="text-sm leading-relaxed text-dim">
            {SITE.plain.frozen}
            <Info term="frozen" />
          </p>
          {expert && <p className="text-xs leading-relaxed text-dim">{SITE.plain.frozenExpert}</p>}
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
                <span className="min-w-0 flex-1">
                  <span className="font-semibold">{r.text}</span>
                  <span className="ml-2 text-xs text-dim">
                    {GROUP_LABEL[r.g]} · {r.v >= 0 ? "올림" : "내림"} {Math.round((Math.abs(r.v) / total) * 100)}%
                  </span>
                  <span className="mt-1 block h-2 w-full rounded-full bg-[var(--panel-border)]" aria-hidden>
                    <span className="block h-full rounded-full" style={{ width: `${Math.round((Math.abs(r.v) / total) * 100)}%`, background: r.v >= 0 ? "var(--alert)" : "var(--safe)" }} />
                  </span>
                </span>
              </li>
            ))}
            {!reasons.length && <li className="text-sm text-dim">{replay ? REPLAY.noShap : "근거 자료가 아직 없습니다."}</li>}
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

        {/* 지난 녹조 발생 기록과 미리 알림 — data-replay-history(다시 보기에서만): 이 구역의 날짜는 모두 그날 이하여야 한다(scripts/check_asof.mjs) */}
        <section className="panel p-4" data-replay-history={replay?.asof}>
          <h2 className="flex items-center text-lg font-semibold">
            {SITE.historyBox}
            <Info term="leadTime" />
          </h2>
          {events.length > 0 && <p className="mt-1 text-base font-semibold">{SITE.eventSummary(events.length, events.filter((e) => e.detected_watch).length)}</p>}
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
                {events.map((e) => (
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
                    <td className="text-right">{fmtCells(v.pred_cell_count)}</td>
                    <td className="text-right">{fmtCells(v.obs_cell_count)}</td>
                    <td>{levelOfCells(v.pred_cell_count) === levelOfCells(v.obs_cell_count) ? "✓" : "✗"}</td>
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
          <p className="mt-3 text-sm text-dim">
            {BOARD.tile.official} {OFFICIAL_LEVEL[lvl].after} ({SITE.measuredBasis}) 과 {BOARD.tile.ai} {TIER[t].label} 을 함께 본 판단입니다. 공식 발령을 대체하지 않습니다.
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
            {/* Y축 칸 72px: 눈금 "1350㎥/s"(12px 글자 폭 54px)가 기본 44px 칸에서 왼쪽으로 18px 잘리던 것 — 다섯 자리(1만㎥/s 이상)까지 들어감 */}
            <EnvChart data={hydroData} keys={[{ k: "inflow", label: "들어오는 물", color: "#22C55E" }, { k: "outflow", label: "내보내는 물(방류)", color: "#F97316" }]} height={180} unit="㎥/s" yWidth={72} />
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
