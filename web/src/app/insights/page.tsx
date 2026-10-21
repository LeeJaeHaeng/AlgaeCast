import Image from "next/image";
import { MdTable } from "@/components/MdTable";
import { parseTables, readReport } from "@/lib/reports";
import { getBloomEvents, leadSummary } from "@/lib/queries";
import { fmtDateFull } from "@/lib/format";

export const revalidate = 3600;

export default async function InsightsPage() {
  const events = await getBloomEvents();
  const lead = leadSummary(events);
  const onset = readReport("tbl_onset_trend.md");
  const onsetTables = onset ? parseTables(onset) : [];
  const cases = events.filter((e) => e.detected_watch && e.first_exceed_date < "2026-01-01").slice(0, 8);
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">인사이트</h1>

      <section className="card">
        <h2 className="font-semibold">2026년 이례적 조기 발령 vs 장기 추세 비유의</h2>
        <p className="mt-1 text-sm text-slate-600">
          2026년 강정·고령은 5월 18일에 관심 단계가 발령돼 평년보다 약 2개월 빨랐습니다. 그러나 지점 평균을 제거한 2016~2026 잔차의 Mann-Kendall 검정은 유의하지 않습니다(Sen −1.0일/년, p=0.64). 첫 발령일은 해마다 크게 달라지므로 고정 달력 대신 예측 기반 탄력 운영이 필요합니다.
        </p>
        <Image src="/reports/fig_onset_trend.png" alt="연도·지점별 첫 관심/경계 발령일(DOY)" width={1400} height={450} className="mt-2 h-auto w-full rounded border" />
        {onsetTables[0] && <MdTable table={onsetTables[0].table} caption="첫 발령일 추세 검정 (Mann-Kendall, Sen's slope; 음수 = 조기화)" />}
      </section>

      <section className="card">
        <h2 className="font-semibold">리드타임 — 공식 경계 발령 {lead.prior.n}건 중 {lead.prior.detected}건을 중앙 {lead.prior.median}일 앞서 감시 단계로 포착</h2>
        <p className="text-xs text-slate-500">첫 경계 초과 측정일 기준. 발령일 기준 중앙 21일. 2026 사후 검증: {lead.posthoc.detected}/{lead.posthoc.n}, 중앙 {lead.posthoc.median ?? "–"}일(동결 모델).</p>
        <table className="tbl mt-2">
          <thead>
            <tr>
              <th>지점</th>
              <th>첫 초과일</th>
              <th>공식 발령</th>
              <th>첫 감시 점등</th>
              <th>리드(일)</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((e) => (
              <tr key={e.event_id}>
                <td>{e.site_id}</td>
                <td>{fmtDateFull(e.first_exceed_date)}</td>
                <td>{fmtDateFull(e.official_alert_date)}</td>
                <td>{fmtDateFull(e.first_watch_date)}</td>
                <td>{e.lead_days_watch_e}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h2 className="font-semibold">지점별 수온 반응 — 같은 수온, 다른 지점</h2>
        <p className="mt-1 text-sm text-slate-600">관심(1,000 cells/mL)에 도달하는 수온: 해평 25.5℃, 강정·고령 23.7℃, 칠서 22.9℃, 물금·매리 22.2℃, 회남 20.0℃ (LOESS, Kruskal-Wallis p=7e-37). 지점별 임계를 피처로 사용합니다.</p>
        <Image src="/reports/fig_site_response.png" alt="지점별 세포수–수온 LOESS" width={1350} height={900} className="mt-2 h-auto w-full max-w-3xl rounded border" />
      </section>

      <section className="card">
        <h2 className="font-semibold">변수별 선행 시차 (lag 상관)</h2>
        <Image src="/reports/fig_lag_corr.png" alt="lag Spearman 히트맵" width={2000} height={900} className="mt-2 h-auto w-full rounded border" />
        <p className="text-xs text-slate-500">기온은 14~30일 lag 에서도 상관이 유지돼 누적 열량(적산온도) 피처의 근거가 됩니다.</p>
      </section>
    </div>
  );
}
