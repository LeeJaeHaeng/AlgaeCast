import Link from "next/link";
import { KpiTile } from "@/components/KpiTile";
import { SiteMap } from "@/components/SiteMap";
import { Sparkline } from "@/components/Charts";
import { TierBadge } from "@/components/TierBadge";
import { TIER_ACTION, fmtCells, fmtDate, fmtDateFull, fmtPct, tierOf } from "@/lib/format";
import { getBloomEvents, getLatestRun, getObservations, getPredictions, getSiteStatus, getSites, leadSummary } from "@/lib/queries";
import { frozenCommit } from "@/lib/reports";

export const revalidate = 1800;

export default async function Home() {
  const [status, sites, run, events] = await Promise.all([getSiteStatus(), getSites(), getLatestRun(), getBloomEvents()]);
  const lead = leadSummary(events);
  const order = { alert: 0, watch: 1, normal: 2 } as const;
  const ranked = [...status].sort((a, b) => order[tierOf(a.tier)] - order[tierOf(b.tier)] || (b.p_alert ?? 0) - (a.p_alert ?? 0));
  const nAlert = status.filter((s) => tierOf(s.tier) === "alert").length;
  const nWatch = status.filter((s) => tierOf(s.tier) === "watch").length;
  const latestBase = status.map((s) => s.base_date).filter(Boolean).sort().at(-1);
  const hp = run?.hyperparams as { registry?: Record<string, string> } | null;
  const frozen = frozenCommit();
  const cards = await Promise.all(
    sites.map(async (s) => {
      const [obs, preds] = await Promise.all([getObservations(s.site_id, 180), getPredictions(s.site_id, run?.run_id ?? null, 30)]);
      const st = status.find((x) => x.site_id === s.site_id);
      const pts = obs.map((o) => ({ date: o.obs_date, obs: o.cell_count }));
      const last = preds.at(-1);
      if (last) pts.push({ date: last.target_date, obs: null, q50: last.q50 } as never);
      return { s, st, pts };
    }),
  );
  return (
    <div className="space-y-6">
      <section className="card border-sky-200 bg-sky-50">
        <h1 className="text-xl font-bold">공식 경계 발령 20건 중 18건(90%)을 첫 경계 초과 측정 기준 중앙 14일 앞서 감시 단계로 포착</h1>
        <p className="mt-1 text-sm text-slate-600">
          2020~2025 검증 기준(지속성 베이스라인 1건, 5%). 2026 사후 검증(모델 동결 후, 선택·튜닝 미사용): 경계 사건 {lead.posthoc.n}건 중 감시 {lead.posthoc.detected}건 사전 포착, 중앙 리드 {lead.posthoc.median ?? "–"}일. 발령일 기준 리드는 각각 21일·31일.
        </p>
        <p className="mt-1 text-xs text-slate-500">
          최근 갱신 {run ? new Date(run.run_at).toLocaleString("ko-KR") : "–"} · 모델 {run?.model_name} {hp?.registry?.regression ?? ""} · 동결 커밋 {frozen || "–"} · 최신 base_date {latestBase ? fmtDateFull(latestBase) : "–"}
        </p>
      </section>

      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiTile label="경보 지점" value={`${nAlert}`} sub="녹조제거설비 선제 배치 권고" tone={nAlert ? "alert" : "default"} />
        <KpiTile label="감시 지점" value={`${nWatch}`} sub="모니터링 강화·설비 준비 점검" tone={nWatch ? "watch" : "default"} />
        <KpiTile label="리드타임 실적 (2020~25)" value={`${lead.prior.detected}/${lead.prior.n}`} sub={`중앙 ${lead.prior.median ?? "–"}일 (감시 단계)`} tone="good" />
        <KpiTile label="2026 사후 검증" value={`${lead.posthoc.detected}/${lead.posthoc.n}`} sub={`중앙 ${lead.posthoc.median ?? "–"}일 · 동결 모델`} />
      </section>

      <section className="grid gap-4 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <SiteMap sites={status.map((s) => ({ site_id: s.site_id, name: s.name, lat: sites.find((x) => x.site_id === s.site_id)?.lat ?? 36, lon: sites.find((x) => x.site_id === s.site_id)?.lon ?? 128, tier: s.tier, q50: s.q50, p_alert: s.p_alert }))} />
          <p className="mt-1 text-xs text-slate-500">마커 색: 회색 정상 · 앰버 감시 · 빨강 경보. 클릭하면 상세로 이동합니다.</p>
        </div>
        <div className="card lg:col-span-2">
          <h2 className="font-semibold">설비 배치 우선순위 (경보 → 감시, 경보 확률 순)</h2>
          <table className="tbl mt-2">
            <thead>
              <tr>
                <th>순위</th>
                <th>지점</th>
                <th>단계</th>
                <th>경보 확률</th>
                <th>q50</th>
                <th>권고</th>
              </tr>
            </thead>
            <tbody>
              {ranked.map((s, i) => (
                <tr key={s.site_id}>
                  <td>{i + 1}</td>
                  <td>
                    <Link className="text-sky-700 underline" href={`/sites/${s.site_id}`}>
                      {s.name}
                    </Link>
                  </td>
                  <td>
                    <TierBadge tier={s.tier} size="sm" />
                  </td>
                  <td>{fmtPct(s.p_alert)}</td>
                  <td>{fmtCells(s.q50)}</td>
                  <td className="text-xs">{TIER_ACTION[tierOf(s.tier)]}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-slate-500">가중치를 곱하지 않습니다. 취수량 반영 토글은 5지점 취수 시설용량의 공식 출처가 모두 확인될 때 제공(강정·고령 미확인).</p>
        </div>
      </section>

      <section className="grid gap-3 md:grid-cols-2 lg:grid-cols-5">
        {cards.map(({ s, st, pts }) => (
          <Link key={s.site_id} href={`/sites/${s.site_id}`} className="card block hover:border-sky-300">
            <div className="flex items-center justify-between">
              <div className="font-semibold">{s.name}</div>
              <TierBadge tier={st?.tier} size="sm" />
            </div>
            <div className="text-xs text-slate-500">
              최근 관측 {fmtCells(st?.latest_cell_count)} ({fmtDate(st?.latest_obs_date)}) · 7일 후 q50 {fmtCells(st?.q50)}
            </div>
            <Sparkline points={pts} />
            <div className="text-[11px] text-slate-400">최근 180일 · 빨간 점 = 7일 예측 · 점선 = 경계 10,000</div>
          </Link>
        ))}
      </section>
    </div>
  );
}
