import { Info } from "@/components/Info";
import { MdTable } from "@/components/MdTable";
import { PageFrame } from "@/components/PageFrame";
import { ABOUT, TERMS } from "@/lib/copy";
import { parseTables, readReport } from "@/lib/reports";

export const revalidate = 86400;

export default async function AboutPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const expert = sp.view === "expert";
  const frozenV2 = parseTables(readReport("FROZEN_v2.1.md") ?? "")[0];
  return (
    // .narrow-fit: 좁은 화면(≤767px) 가로 넘침 방지 규칙의 범위(globals.css), 768px 이상에는 적용되는 스타일 없음
    <PageFrame title={ABOUT.title} lead={ABOUT.lead} expert={expert} className="narrow-fit">
      <section className="panel p-4">
        <p className="text-lg leading-relaxed">{ABOUT.what}</p>
        <p className="mt-2 text-base font-semibold" style={{ color: "var(--watch)" }}>
          {ABOUT.notOfficial}
        </p>
      </section>

      {/* 작동 방식 4단계 */}
      <section className="panel p-4">
        <h2 className="text-xl font-semibold">작동 방식</h2>
        <ol className="mt-3 grid gap-3 md:grid-cols-4">
          {ABOUT.steps.map((s, i) => (
            <li key={s.n} className="relative rounded-xl border border-border p-4">
              <div className="text-3xl font-bold" style={{ color: "var(--accent)" }}>
                {s.n}
              </div>
              <div className="mt-1 text-lg font-semibold">{s.title}</div>
              <p className="mt-1 text-sm leading-relaxed text-dim">{s.body}</p>
              {i < ABOUT.steps.length - 1 && (
                <span className="absolute -right-3 top-1/2 hidden -translate-y-1/2 text-2xl text-dim md:block" aria-hidden>
                  →
                </span>
              )}
            </li>
          ))}
        </ol>
        <p className="mt-3 text-sm text-dim">
          {TERMS.frozen.label}
          <Info term="frozen" /> · {ABOUT.frozenLine}
        </p>
      </section>

      {/* 제출·운영 모델 v2.1 · 이력 v2·v1 */}
      <section className="panel p-4" style={{ borderColor: "var(--accent)" }}>
        <h2 className="text-xl font-semibold">{ABOUT.models.title}</h2>
        <p className="mt-1 text-sm leading-relaxed text-dim">{ABOUT.models.lead}</p>
        <p className="mt-1 text-sm leading-relaxed">{ABOUT.models.leak}</p>
        <div className="mt-2 overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                {ABOUT.models.cols.map((c, i) => (
                  <th key={i}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ABOUT.models.rows.map((r) => (
                <tr key={r[0]}>
                  <td className="font-semibold">{r[0]}</td>
                  <td className="font-semibold" style={{ color: "var(--accent)" }}>
                    {r[1]}
                  </td>
                  <td className="text-dim">{r[2]}</td>
                  <td className="text-dim">{r[3]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {expert && (
          <div className="mt-2 space-y-2">
            <p className="text-sm text-dim">{ABOUT.models.expert}</p>
            {frozenV2 && <MdTable table={frozenV2.table} caption={ABOUT.models.frozenTable} />}
          </div>
        )}
      </section>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        {/* 데이터 출처 */}
        <section className="panel p-4">
          <h2 className="text-xl font-semibold">{ABOUT.dataTitle}</h2>
          <table className="tbl mt-2">
            <thead>
              <tr>
                {ABOUT.dataCols.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ABOUT.data.map((r) => (
                <tr key={r[0]} className={r[1].includes("DataON") ? "font-semibold" : ""} style={r[1].includes("DataON") ? { background: "color-mix(in srgb, var(--accent) 12%, transparent)" } : undefined}>
                  {r.map((c, j) => (
                    <td key={j}>{c}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-sm text-dim">{ABOUT.aida}</p>
        </section>

        {/* 한계 */}
        <section className="panel p-4" style={{ borderColor: "var(--severe)" }}>
          <h2 className="text-xl font-semibold">{ABOUT.limitsTitle}</h2>
          <ul className="mt-2 space-y-2 text-base leading-relaxed">
            {ABOUT.limits.map((l) => (
              <li key={l} className="flex gap-2">
                <span style={{ color: "var(--severe)" }}>▸</span>
                <span>{l}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs font-semibold" style={{ color: "var(--watch)" }}>
            {ABOUT.limitsFootnote}
          </p>
        </section>
      </div>

      {/* 재현 */}
      <section className="panel p-4">
        <h2 className="text-xl font-semibold">{ABOUT.reproTitle}</h2>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-base leading-relaxed">
          {ABOUT.repro.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ol>
        {expert && <p className="mt-2 text-sm text-dim">{ABOUT.reproExpert}</p>}
      </section>
    </PageFrame>
  );
}
