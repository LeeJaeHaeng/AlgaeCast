import Image from "next/image";
import { MdTable } from "@/components/MdTable";
import { PageFrame } from "@/components/PageFrame";
import { INSIGHTS } from "@/lib/copy";
import { fmtCellsKo } from "@/lib/format";
import { parseTables, readReport } from "@/lib/reports";

export const revalidate = 3600;

export default async function InsightsPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const expert = sp.view === "expert";
  const onset = parseTables(readReport("tbl_onset_trend.md") ?? "");
  const surgeMd = readReport("tbl_bloom_events.md") ?? "";
  const surge = parseTables(surgeMd)[0]?.table;
  const rows = surge?.rows ?? [];
  const col = (name: string) => surge?.header.findIndex((h) => h.startsWith(name)) ?? -1;
  const num = (r: string[], c: number) => Number(r[c]);
  const med = (xs: number[]) => {
    const s = xs.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
    return s.length ? s[Math.floor((s.length - 1) / 2)] : NaN;
  };
  const cTemp = col("선행7일 평균기온");
  const cRain = col("선행7일 강수합");
  const tempMed = med(rows.map((r) => num(r, cTemp)));
  const rainMed = med(rows.map((r) => num(r, cRain)));
  const top = [...rows].sort((a, b) => num(b, col("배수")) - num(a, col("배수"))).slice(0, 8);
  const maxT = 27;
  return (
    <PageFrame title={INSIGHTS.title} lead={INSIGHTS.lead} expert={expert}>
      {/* ① 조기 발생 vs 장기 추세 */}
      <section className="panel grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div>
          <h2 className="text-xl font-semibold">{INSIGHTS.early.title}</h2>
          <p className="mt-2 text-base leading-relaxed">{INSIGHTS.early.body}</p>
          {expert && <p className="mt-2 text-sm text-dim">{INSIGHTS.early.expert}</p>}
          {expert && onset[0] && <MdTable table={onset[0].table} caption="첫 발령일 추세 검정 (Mann-Kendall, Sen's slope; 음수 = 조기화)" />}
        </div>
        <figure>
          <Image src="/reports/fig_onset_trend.png" alt={INSIGHTS.early.fig} width={1400} height={450} className="h-auto w-full rounded-lg border border-border bg-white" />
          <figcaption className="mt-1 text-xs text-dim">{INSIGHTS.early.fig}</figcaption>
        </figure>
      </section>

      {/* ② 물 온도 */}
      <section className="panel grid gap-4 p-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div>
          <h2 className="text-xl font-semibold">{INSIGHTS.temp.title}</h2>
          <p className="mt-2 text-base leading-relaxed">{INSIGHTS.temp.body}</p>
          {expert && <p className="mt-2 text-sm text-dim">{INSIGHTS.temp.expert}</p>}
        </div>
        <div>
          <div className="text-sm text-dim">{INSIGHTS.temp.unit}</div>
          <ul className="mt-2 space-y-2">
            {INSIGHTS.temp.rows.map(([name, t]) => (
              <li key={name} className="grid grid-cols-[90px_minmax(0,1fr)_56px] items-center gap-2 text-base">
                <span className="font-semibold">{name}</span>
                <div className="h-4 rounded bg-[var(--panel-border)]">
                  <div className="h-full rounded" style={{ width: `${((t - 15) / (maxT - 15)) * 100}%`, background: "linear-gradient(90deg, var(--accent), var(--alert))" }} />
                </div>
                <span className="text-right font-bold">{t.toFixed(1)}℃</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ③ 지점별 차이 */}
      <section className="panel grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div>
          <h2 className="text-xl font-semibold">{INSIGHTS.sites.title}</h2>
          <p className="mt-2 text-base leading-relaxed">{INSIGHTS.sites.body}</p>
        </div>
        <figure>
          <Image src="/reports/fig_site_response.png" alt={INSIGHTS.sites.fig} width={1350} height={900} className="h-auto w-full rounded-lg border border-border bg-white" />
          <figcaption className="mt-1 text-xs text-dim">{INSIGHTS.sites.fig}</figcaption>
        </figure>
      </section>

      {/* ④ 급증 */}
      <section className="panel p-4">
        <h2 className="text-xl font-semibold">{INSIGHTS.surge.title}</h2>
        <p className="mt-2 text-base leading-relaxed">{INSIGHTS.surge.body(rows.length, Number.isFinite(tempMed) ? tempMed.toFixed(1) : "–", Number.isFinite(rainMed) ? rainMed.toFixed(0) : "–")}</p>
        {surge && (
          <table className="tbl mt-3">
            <thead>
              <tr>
                {INSIGHTS.surge.cols.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {top.map((r, i) => (
                <tr key={i}>
                  <td>{r[0]}</td>
                  <td>{r[1]}</td>
                  <td>{r[2]}</td>
                  <td className="text-right">{fmtCellsKo(num(r, col("이전 세포수")))} 개/mL</td>
                  <td className="text-right font-semibold">{fmtCellsKo(num(r, col("급증 세포수")))} 개/mL</td>
                  <td className="text-right">{Math.round(num(r, col("배수"))).toLocaleString()}배</td>
                  <td className="text-right">{num(r, cTemp).toFixed(1)}℃</td>
                  <td className="text-right">{num(r, cRain).toFixed(0)}mm</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <p className="text-xs text-dim">{INSIGHTS.source}</p>
    </PageFrame>
  );
}
