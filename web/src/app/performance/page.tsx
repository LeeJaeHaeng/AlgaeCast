import { Info } from "@/components/Info";
import { MdTable } from "@/components/MdTable";
import { PageFrame } from "@/components/PageFrame";
import { Timeline } from "@/components/perf/Timeline";
import { PERF, TERMS, V2_NOTICE, n2 } from "@/lib/copy";
import { NUMBERS, V2CMP } from "@/lib/numbers";
import { getBloomEvents } from "@/lib/queries";
import { firstParagraphs, parseTables, readReport } from "@/lib/reports";

export const revalidate = 3600;

const f2 = (v: number | null | undefined) => (v == null ? "–" : v.toFixed(2));

function Section({ file, title, pick = [0], maxRows, notice }: { file: string; title: string; pick?: number[]; maxRows?: number; notice?: string }) {
  const md = readReport(file);
  if (!md) return null;
  const tables = parseTables(md);
  const paras = firstParagraphs(md, 3);
  return (
    <section className="panel space-y-2 p-4">
      <h3 className="font-semibold">{title}</h3>
      {notice && (
        <p className="text-xs font-semibold" style={{ color: "var(--watch)" }}>
          {notice}
        </p>
      )}
      {paras.map((p, i) => (
        <p key={i} className="text-xs text-dim">
          {p}
        </p>
      ))}
      {pick.map((i) => (tables[i] ? <MdTable key={i} table={tables[i].table} caption={tables[i].title} maxRows={maxRows} /> : null))}
      <p className="text-[11px] text-dim">출처 reports/eval/{file}</p>
    </section>
  );
}

function Big({ label, value, sub, tone, second }: { label: string; value: string; sub: string; tone?: string; second?: string }) {
  return (
    <div className="panel flex flex-col justify-between p-4">
      <div className="text-sm text-dim">{label}</div>
      <div className="my-1 text-[40px] font-bold leading-none" style={{ color: tone }}>
        {value}
      </div>
      {second && <div className="mb-1 text-xl font-bold leading-tight" style={{ color: "var(--accent)" }}>{second}</div>}
      <div className="text-sm text-dim">{sub}</div>
    </div>
  );
}

export default async function PerformancePage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const expert = sp.view === "expert";
  const events = await getBloomEvents();
  const allN = NUMBERS.events.total;
  const allHit = NUMBERS.events.detected;
  const onsetPct = Math.round((allHit / allN) * 100);
  const b0Hit = NUMBERS.events.persistenceDetected;
  const b0Pct = Math.round((b0Hit / allN) * 100);
  const bench = readReport("tbl_benchmark_nier.md");
  const benchN = Number(bench?.match(/n=(\d+)/)?.[1] ?? "0");

  return (
    <PageFrame title={PERF.title} lead={PERF.lead} expert={expert}>
      {/* 제출·운영 모델 = v2, 블라인드 검증 = v1 */}
      <p className="panel px-4 py-2 text-sm leading-relaxed" style={{ borderColor: "var(--accent)" }}>
        {PERF.models}
      </p>
      {/* 큰 숫자 4개 — 같은 크기, 약한 숫자도 그대로 */}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Big label={PERF.big.caught.label} value={`${allN}건 중 ${allHit}건`} sub={PERF.big.caught.sub(NUMBERS.events.medianLeadDays)} tone="var(--safe)" />
        <Big label={PERF.big.y2026.label} value={`${NUMBERS.y2026.total}건 중 ${NUMBERS.y2026.detected}건`} sub={PERF.big.y2026.sub(NUMBERS.y2026.medianLeadDays)} tone="var(--safe)" />
        <Big label={PERF.big.r2log.label} value={PERF.big.r2log.value(f2(NUMBERS.r2log.y2025), f2(NUMBERS.r2log.y2026))} second={PERF.big.v2line(f2(V2CMP.h25v2.r2log), f2(V2CMP.p26v2.r2log))} sub={PERF.big.r2log.sub} tone="var(--watch)" />
        <Big label={PERF.big.f1.label} value={`${f2(NUMBERS.f1_10k.y2025)} / ${f2(NUMBERS.f1_10k.y2026)}`} second={PERF.big.v2line(f2(V2CMP.h25v2.f1_10k), f2(V2CMP.p26v2.f1_10k))} sub={PERF.big.f1.sub(f2(NUMBERS.f1_10k.y2025), f2(NUMBERS.f1_10k.persistence2025), f2(NUMBERS.f1_10k.y2026), f2(NUMBERS.f1_10k.persistence2026))} tone="var(--watch)" />
      </div>
      <p className="text-xs text-dim">{PERF.basis}</p>
      <p className="text-xs font-semibold" style={{ color: "var(--watch)" }}>
        {PERF.v2Footnote}
      </p>

      <CompareV1V2 expert={expert} />

      <section className="panel p-4">
        <p className="text-xl font-semibold leading-relaxed">{PERF.sentence}</p>
        <h2 className="mt-4 flex items-center text-base font-semibold text-dim">
          {PERF.onset.title}
          <Info term="leadTime" />
        </h2>
        <div className="mt-2 space-y-2">
          <Bar label={PERF.onset.ours} pct={onsetPct} note={`${allHit}/${allN}건`} color="var(--safe)" />
          <Bar label={PERF.onset.persist} pct={b0Pct} note={`${b0Hit}/${allN}건 · ${PERF.onset.persistNote}`} color="var(--severe)" />
        </div>
      </section>

      <section className="panel p-4">
        <h2 className="text-lg font-semibold">{PERF.timeline.title}</h2>
        <Timeline events={events} />
      </section>

      <div className="grid gap-3 lg:grid-cols-2">
        <section className="panel p-4">
          <h2 className="text-lg font-semibold">{PERF.target.title}</h2>
          <ul className="mt-2 space-y-1 text-base">
            {PERF.target
              .rows(
                { r25: n2(NUMBERS.r2raw.y2025), r26: n2(NUMBERS.r2raw.y2026), n25: n2(NUMBERS.nseraw.y2025), n26: n2(NUMBERS.nseraw.y2026) },
                { r25: n2(V2CMP.h25v2.r2raw), r26: n2(V2CMP.p26v2.r2raw), n25: n2(V2CMP.h25v2.nseraw), n26: n2(V2CMP.p26v2.nseraw) },
              )
              .map((r) => (
              <li key={r} className="font-semibold" style={{ color: "var(--severe)" }}>
                {r}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-dim">{PERF.target.rowsNote(n2(V2CMP.h25v1.r2raw))}</p>
          <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm leading-relaxed">
            {PERF.target.why.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ol>
        </section>
        <section className="panel p-4">
          <h2 className="text-lg font-semibold">{PERF.mulmoa.title}</h2>
          <p className="mt-2 text-base leading-relaxed">{PERF.mulmoa.text(benchN)}</p>
          <p className="mt-3 text-sm text-dim">
            {TERMS.frozen.label}
            <Info term="frozen" /> · {TERMS.persistence.label}
            <Info term="persistence" />
          </p>
        </section>
      </div>

      {expert && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">{PERF.expertTitle}</h2>
          <Section file="tbl_holdout_2025_v2.md" title="2025 홀드아웃·CV — v2(제출·운영) vs v1(블라인드 검증), 같은 252행" pick={[0, 1]} />
          <Section file="tbl_holdout_2026_posthoc_v2.md" title="2026 사후 — v2 vs v1 (전체·지점별·리드타임·사건별·전환 분해)" pick={[0, 1, 2, 3, 4]} notice={V2_NOTICE} />
          <Section file="tbl_holdout_2025.md" title="2025 홀드아웃(v1 공개 256행) — 전 지표 + 부트스트랩 95% CI" pick={[0, 1]} />
          <Section file="tbl_holdout_2026_posthoc.md" title="2026 사후 검증(v1 블라인드) — 전체·지점별·전환 분해·리드타임" pick={[0, 1, 2, 3, 4]} />
          <Section file="tbl_transitions.md" title="상태 전환 구간 평가" pick={[0, 1]} maxRows={20} />
          <Section file="tbl_leadtime.md" title="리드타임 (2020~2025)" pick={[0, 1]} />
          <Section file="tbl_operating_points.md" title="운영점 (비용비 r)" pick={[0]} />
          <Section file="tbl_stat_tests.md" title="통계 검정 (Diebold-Mariano · Wilcoxon)" pick={[0]} />
          <Section file="tbl_cqr.md" title="분위 구간 보정 (CQR)" pick={[0]} />
          <Section file="tbl_ablation.md" title="피처 그룹 ablation" pick={[0]} />
          <Section file="tbl_sensitivity.md" title="2025 원단위 지표 민감도" pick={[0]} maxRows={12} />
          <Section file="tbl_by_site.md" title="지점별" pick={[0]} />
          <Section file="tbl_by_month.md" title="월별" pick={[0]} />
        </section>
      )}
    </PageFrame>
  );
}

type MetricRow = { key: keyof typeof PERF.compare.rows; v2: string; v1: string; b0: string };

function CompareTable({ title, rows, expert, notice }: { title: string; rows: MetricRow[]; expert: boolean; notice?: string }) {
  return (
    <div className="min-w-0">
      <h3 className="text-base font-semibold">{title}</h3>
      {notice && (
        <p className="mt-1 text-xs font-semibold" style={{ color: "var(--watch)" }}>
          ※ {notice}
        </p>
      )}
      <div className="mt-2 overflow-x-auto">
        <table className="tbl text-sm">
          <thead>
            <tr>
              {PERF.compare.cols.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const meta = PERF.compare.rows[r.key];
              return (
                <tr key={r.key}>
                  <td>
                    {meta.label}
                    {expert && <span className="ml-1 text-xs text-dim">({meta.expert})</span>}
                  </td>
                  <td className="text-right font-bold" style={{ color: "var(--accent)" }}>
                    {r.v2}
                  </td>
                  <td className="text-right">{r.v1}</td>
                  <td className="text-right text-dim">{r.b0}</td>
                  <td className="text-xs text-dim">{meta.better}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** v1(블라인드 검증)·v2(제출·운영) 나란히 — 점예측 지표만 다르고 감시·경보는 같다. 숫자는 numbers.ts V2CMP(빌드 전 원천 대조) */
function CompareV1V2({ expert }: { expert: boolean }) {
  const C = PERF.compare;
  const { h25v2, h25v1, h25b0, p26v2, p26v1, p26b0, p26point, p26watch, cvR2raw } = V2CMP;
  const metricRows = (a: typeof h25v2 | typeof p26v2, b: typeof h25v1 | typeof p26v1, c: typeof h25b0 | typeof p26b0): MetricRow[] =>
    [...(["r2log", "rmselog", "r2raw", "nseraw"] as const).map((k): MetricRow => ({ key: k, v2: n2(a[k]), v1: n2(b[k]), b0: n2(c[k]) })), { key: "f1", v2: n2(a.f1_10k), v1: n2(b.f1_10k), b0: n2(c.f1_10k) }];
  const rows26: MetricRow[] = [
    ...metricRows(p26v2, p26v1, p26b0),
    { key: "point", v2: C.count(p26point.v2, p26point.total), v1: C.count(p26point.v1, p26point.total), b0: C.count(p26point.persistence, p26point.total) },
    { key: "watch", v2: C.countLead(p26watch.v2, p26watch.total, p26watch.medianLeadV2), v1: C.countLead(p26watch.v1, p26watch.total, p26watch.medianLeadV1), b0: C.count(NUMBERS.y2026.persistenceDetected, NUMBERS.y2026.total) },
  ];
  return (
    <section className="panel space-y-3 p-4" aria-label={C.title}>
      <div>
        <h2 className="text-lg font-semibold">{C.title}</h2>
        <p className="text-sm text-dim">{C.lead}</p>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <CompareTable title={C.y2025(h25v2.n)} rows={metricRows(h25v2, h25v1, h25b0)} expert={expert} />
        <CompareTable title={C.y2026(p26v2.n)} rows={rows26} expert={expert} notice={V2_NOTICE} />
      </div>
      <ul className="space-y-1 text-sm leading-relaxed">
        <li style={{ color: "var(--safe)" }}>{C.common(NUMBERS.y2026.detected, NUMBERS.y2026.total, NUMBERS.y2026.medianLeadDays, NUMBERS.events.detected, NUMBERS.events.total, NUMBERS.events.medianLeadDays)}</li>
        <li>{C.good(p26point.v2, p26point.v1, p26point.total, n2(p26v2.f1_10k), n2(p26v1.f1_10k))}</li>
        <li style={{ color: "var(--severe)" }}>{C.weak(n2(p26v2.r2raw), n2(h25v2.f1_10k), n2(h25b0.f1_10k), n2(p26v2.f1_10k), n2(p26b0.f1_10k))}</li>
        <li className="text-dim">{C.cv(n2(cvR2raw.v2), n2(cvR2raw.v1), n2(cvR2raw.b0))}</li>
        <li className="text-dim">{C.note2025(n2(h25v1.r2raw), n2(NUMBERS.r2raw.y2025))}</li>
      </ul>
      <p className="text-[11px] text-dim">{C.source}</p>
    </section>
  );
}

function Bar({ label, pct, note, color }: { label: string; pct: number; note: string; color: string }) {
  return (
    <div className="grid grid-cols-[260px_minmax(0,1fr)_72px] items-center gap-3 text-base">
      <span>{label}</span>
      <div className="h-5 w-full rounded bg-[var(--panel-border)]">
        <div className="h-full rounded" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="text-right font-bold">{pct}%</span>
      <span className="col-span-3 -mt-1 text-xs text-dim">{note}</span>
    </div>
  );
}
