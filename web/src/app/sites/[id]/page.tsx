import { notFound } from "next/navigation";
import { ForecastChart, Gauge, ShapBars, SimpleLines } from "@/components/Charts";
import { TierBadge } from "@/components/TierBadge";
import { ALERT_LEVEL_LABEL, TIER_ACTION, fmtCells, fmtDateFull, fmtPct, tierOf } from "@/lib/format";
import { getBloomEvents, getHydro, getLatestRun, getObservations, getPredictions, getShap, getSiteStatus, getSites, getWeather } from "@/lib/queries";

export const revalidate = 1800;

const FEATURE_KO: Record<string, string> = {
  cell_log_t0: "최근 측정 세포수", cell_max_4w: "최근 4주 최대 세포수", cell_log_lag1w: "1주 전 세포수", cell_log_lag3w: "3주 전 세포수", cell_slope_3: "최근 3회 증가 기울기",
  consecutive_over_1k: "관심 기준 연속 초과 횟수", chla_lag1w: "1주 전 클로로필-a", wtemp_ma14: "14일 평균 수온", wtemp_minus_site_thresh: "지점 관심 임계 대비 수온", wtemp_diff7: "7일 수온 변화",
  ph_t0: "pH", ta_degree_days20: "30일 적산 기온", rn_sum30: "30일 누적 강수", hm_mean7: "7일 평균 습도", ws_mean7: "7일 평균 풍속", season_day: "조류 시즌 경과일", horizon_days: "예측 선행일",
  weir_outflow_t0: "보 방류량", weir_outflow_ma7: "보 7일 평균 방류량", weir_storage_rate_t0: "보 저수율", weir_residence_proxy: "보 체류시간 대리", inflow_t0: "상류 댐 유입량", outflow_t0: "상류 댐 방류량",
  outflow_change7: "상류 댐 방류 7일 변화", storage_rate_t0: "상류 댐 저수율", level_cont_t0: "연속 수위 편차", level_cont_diff7: "연속 수위 7일 변화", dominant_genus: "우점속", facility_type: "시설 유형", basin: "수계",
};
const GROUP_KO: Record<string, string> = { ar: "최근 남조류 추세", water: "수온·수질", hydro: "수문(보·댐)", weather: "기상", forecast: "예보", time_site: "계절·지점" };

export async function generateStaticParams() {
  return ["2011G26", "2011G56", "2020G33", "2022G05", "3008G30"].map((id) => ({ id }));
}

export default async function SitePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [sites, status, run] = await Promise.all([getSites(), getSiteStatus(), getLatestRun()]);
  const site = sites.find((s) => s.site_id === id);
  if (!site) notFound();
  const st = status.find((s) => s.site_id === id);
  const [obs, preds, shap, events, hydro, weather] = await Promise.all([
    getObservations(id, 180),
    getPredictions(id, run?.run_id ?? null, 400),
    getShap(id, run?.run_id ?? null),
    getBloomEvents(id),
    getHydro(id, 180),
    getWeather(id, 180),
  ]);
  const since = new Date();
  since.setDate(since.getDate() - 180);
  const pastPreds = preds.filter((p) => p.obs_cell_count != null && new Date(p.target_date) >= since);
  const latest = preds.at(-1);
  const pts = [
    ...obs.map((o) => ({ date: o.obs_date, obs: o.cell_count, past_pred: pastPreds.find((p) => p.target_date === o.obs_date)?.q50 ?? null })),
    ...(latest ? [{ date: latest.target_date, obs: null, q50: latest.q50, lo: latest.q10_cqr, hi: latest.q90_cqr }] : []),
  ];
  const op = (latest?.operating_point ?? st?.operating_point ?? {}) as { threshold?: number };
  const thr = typeof op.threshold === "number" ? op.threshold : 0.52;
  const shapItems = shap.slice(0, 5).map((s) => ({ label: `${GROUP_KO[s.feature_group ?? ""] ?? s.feature_group} · ${FEATURE_KO[s.feature_name] ?? s.feature_name}`, value: s.shap_value ?? 0, group: s.feature_group ?? "" }));
  const verify = preds.filter((p) => p.obs_cell_count != null).slice(-20).reverse();
  const hydroData = hydro.map((h) => ({ date: h.obs_date, inflow: h.inflow_cms, outflow: h.outflow_cms, rain: h.rainfall_mm, storage: h.storage_rate, level: h.weir_level }));
  const wxData = weather.map((w) => ({ date: w.obs_date, ta: w.ta_mean, rn: w.rn_sum }));
  const wtData = obs.map((o) => ({ date: o.obs_date, wt: o.water_temp }));
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">{site.name}</h1>
        <span className="text-sm text-slate-500">
          {site.basin} · {site.facility_name}
        </span>
        <TierBadge tier={st?.tier} size="lg" />
        <span className="text-xs text-slate-500">base_date {fmtDateFull(st?.base_date)} → 예측일 {fmtDateFull(st?.target_date)}</span>
      </header>

      <section className="card">
        <h2 className="font-semibold">관측 180일 + 7일 예측 (log 축, 80% 구간은 CQR 보정)</h2>
        <ForecastChart points={pts} />
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        <div className="card">
          <h2 className="font-semibold">경계(≥10,000) 초과 확률</h2>
          <Gauge p={st?.p_alert ?? null} threshold={thr} />
          <div className="mt-2 text-xs text-slate-500">
            감시 규칙: CQR q90 {fmtCells(st?.q90_cqr)} {(st?.q90_cqr ?? 0) >= 10000 ? "≥" : "<"} 10,000 · 최근 관측 단계 {ALERT_LEVEL_LABEL[st?.latest_alert_level ?? 0]}
          </div>
        </div>
        <div className="card md:col-span-2">
          <h2 className="font-semibold">권고 (우선순위 {st?.priority_rank ?? "–"})</h2>
          <div className="mt-1 text-lg font-semibold">{TIER_ACTION[tierOf(st?.tier)]}</div>
          <p className="mt-1 text-sm text-slate-700">{st?.rationale_ko ?? "근거 문장 없음"}</p>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="card">
          <h2 className="font-semibold">예측 근거 (SHAP 상위 5, 회귀 C1)</h2>
          {shapItems.length ? <ShapBars items={shapItems} /> : <p className="text-sm text-slate-500">자료 없음</p>}
          <p className="text-xs text-slate-500">막대 방향 ▲ 상승 요인 / ▼ 하락 요인, 툴팁에 기여 %</p>
        </div>
        <div className="card">
          <h2 className="font-semibold">과거 경계 사건 타임라인</h2>
          <table className="tbl mt-2">
            <thead>
              <tr>
                <th>첫 초과일</th>
                <th>공식 발령</th>
                <th>첫 감시</th>
                <th>첫 경보</th>
                <th>리드(감시/경보, 일)</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.event_id}>
                  <td>{fmtDateFull(e.first_exceed_date)}</td>
                  <td>{fmtDateFull(e.official_alert_date)}</td>
                  <td>{e.first_watch_date ? fmtDateFull(e.first_watch_date) : "미포착"}</td>
                  <td>{e.first_alert_date ? fmtDateFull(e.first_alert_date) : "미포착"}</td>
                  <td>
                    {e.lead_days_watch_e ?? "–"} / {e.lead_days_alert_e ?? "–"}
                    {e.first_exceed_date >= "2026-01-01" ? <span className="ml-1 text-[10px] text-slate-400">(사후)</span> : null}
                  </td>
                </tr>
              ))}
              {!events.length && (
                <tr>
                  <td colSpan={5} className="text-slate-500">
                    2020년 이후 경계 사건 없음
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <h2 className="font-semibold">수문·기상 보조 자료 (최근 180일)</h2>
        <div className="mt-2 grid gap-4 md:grid-cols-3">
          <div>
            <div className="text-sm text-slate-600">수온 (℃, 측정일)</div>
            <SimpleLines data={wtData} keys={[{ k: "wt", label: "수온", color: "#0284c7" }]} height={180} />
          </div>
          <div>
            <div className="text-sm text-slate-600">{site.facility_type === "dam" ? "댐" : "보"} 유입·방류 (㎥/s)</div>
            <SimpleLines data={hydroData} keys={[{ k: "inflow", label: "유입", color: "#16a34a" }, { k: "outflow", label: "방류", color: "#dc2626" }]} height={180} />
          </div>
          <div>
            <div className="text-sm text-slate-600">기온 (℃) · 강수 (mm)</div>
            <SimpleLines data={wxData} keys={[{ k: "ta", label: "기온", color: "#f59e0b" }, { k: "rn", label: "강수", color: "#2563eb" }]} height={180} />
          </div>
        </div>
      </section>

      <section className="card">
        <h2 className="font-semibold">사후 검증 (실측이 도착한 최근 20건)</h2>
        <table className="tbl mt-2">
          <thead>
            <tr>
              <th>base</th>
              <th>예측일</th>
              <th>예측 q50</th>
              <th>80% 구간</th>
              <th>실측</th>
              <th>log 오차</th>
              <th>단계</th>
              <th>경계 적중</th>
            </tr>
          </thead>
          <tbody>
            {verify.map((p) => {
              const err = p.obs_cell_count != null && p.q50 != null ? Math.log10(p.obs_cell_count + 1) - Math.log10(p.q50 + 1) : null;
              const hit = p.obs_cell_count != null ? ((p.obs_cell_count >= 10000) === (tierOf(p.tier) !== "normal") ? "○" : "×") : "–";
              return (
                <tr key={`${p.base_date}-${p.target_date}`}>
                  <td>{fmtDateFull(p.base_date)}</td>
                  <td>{fmtDateFull(p.target_date)}</td>
                  <td>{fmtCells(p.q50)}</td>
                  <td>
                    {fmtCells(p.q10_cqr)} ~ {fmtCells(p.q90_cqr)}
                  </td>
                  <td>{fmtCells(p.obs_cell_count)}</td>
                  <td>{err == null ? "–" : err.toFixed(2)}</td>
                  <td>
                    <TierBadge tier={p.tier} size="sm" />
                  </td>
                  <td>{hit}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="mt-1 text-xs text-slate-500">경계 적중: 실측 ≥10,000 여부와 감시/경보 점등 여부의 일치. 확률 {fmtPct(st?.p_alert)} 는 +4~+10일 창 기준 분류기.</p>
      </section>
    </div>
  );
}
