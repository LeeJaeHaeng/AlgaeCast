import { Info } from "@/components/Info";
import { MdTable } from "@/components/MdTable";
import { PageFrame } from "@/components/PageFrame";
import { Timeline } from "@/components/perf/Timeline";
import { PERF, TERMS } from "@/lib/copy";
import { getBloomEvents, getMetrics } from "@/lib/queries";
import { firstParagraphs, parseTables, readReport } from "@/lib/reports";

export const revalidate = 3600;

/** reports/eval 표에서 특정 행(첫 칸 prefix)·열(헤더 이름) 값을 읽는다 — "0.727 [0.62, 0.82]" 는 앞 숫자만 */
function cell(file: string, rowPrefix: string, col: string, tableIdx = 0): number | null {
  const md = readReport(file);
  if (!md) return null;
  const t = parseTables(md)[tableIdx]?.table;
  if (!t) return null;
  const j = t.header.indexOf(col);
  const row = t.rows.find((r) => r[0].replace(/\*\*/g, "").startsWith(rowPrefix));
  if (j < 0 || !row) return null;
  const m = row[j].match(/-?\d+(\.\d+)?/);
  return m ? Number(m[0]) : null;
}
const f2 = (v: number | null | undefined) => (v == null ? "–" : v.toFixed(2));

function Section({ file, title, pick = [0], maxRows }: { file: string; title: string; pick?: number[]; maxRows?: number }) {
  const md = readReport(file);
  if (!md) return null;
  const tables = parseTables(md);
  const paras = firstParagraphs(md, 3);
  return (
    <section className="panel space-y-2 p-4">
      <h3 className="font-semibold">{title}</h3>
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

function Big({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: string }) {
  return (
    <div className="panel flex flex-col justify-between p-4">
      <div className="text-sm text-dim">{label}</div>
      <div className="my-1 text-[40px] font-bold leading-none" style={{ color: tone }}>
        {value}
      </div>
      <div className="text-sm text-dim">{sub}</div>
    </div>
  );
}

export default async function PerformancePage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const expert = sp.view === "expert";
  const [metrics, events] = await Promise.all([getMetrics(), getBloomEvents()]);
  const g = (split: string, m: string) => metrics.find((x) => x.split === split && x.site_id == null && x.metric === m)?.value ?? null;
  const ev25 = g("holdout2025", "leadtime_events") ?? 0;
  const det25 = g("holdout2025", "leadtime_detected_watch") ?? 0;
  const ev26 = g("posthoc2026", "leadtime_events") ?? 0;
  const det26 = g("posthoc2026", "leadtime_detected_watch") ?? 0;
  const med25 = g("holdout2025", "leadtime_median_days_watch_E") ?? 0;
  const med26 = g("posthoc2026", "leadtime_median_days_watch_E") ?? 0;
  const r2log25 = g("holdout2025", "r2_log");
  const r2log26 = g("posthoc2026", "r2_log");
  const f125 = g("holdout2025", "f1_10k");
  const f126 = g("posthoc2026", "f1_10k");
  const b025 = cell("tbl_holdout_2025.md", "B0", "f1_10k");
  const b026 = cell("tbl_holdout_2026_posthoc.md", "B0", "f1_10k");
  const r2raw25 = g("holdout2025", "r2_raw");
  const r2raw26 = g("posthoc2026", "r2_raw");
  const nse25 = g("holdout2025", "nse_raw");
  const nse26 = g("posthoc2026", "nse_raw");
  const allN = events.length || ev25 + ev26;
  const allHit = events.length ? events.filter((e) => e.detected_watch).length : det25 + det26;
  const onsetPct = allN ? Math.round((allHit / allN) * 100) : 0;
  const bench = readReport("tbl_benchmark_nier.md");
  const benchN = Number(bench?.match(/n=(\d+)/)?.[1] ?? "0");

  return (
    <PageFrame title={PERF.title} lead={PERF.lead} expert={expert}>
      {/* 큰 숫자 4개 — 같은 크기, 약한 숫자도 그대로 */}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Big label={PERF.big.caught.label} value={`${allN}건 중 ${allHit}건`} sub={PERF.big.caught.sub(med25)} tone="var(--safe)" />
        <Big label={PERF.big.y2026.label} value={`${ev26}건 중 ${det26}건`} sub={PERF.big.y2026.sub(med26)} tone="var(--safe)" />
        <Big label={PERF.big.r2log.label} value={PERF.big.r2log.value(f2(r2log25), f2(r2log26))} sub={PERF.big.r2log.sub} tone="var(--watch)" />
        <Big label={PERF.big.f1.label} value={`${f2(f125)} / ${f2(f126)}`} sub={PERF.big.f1.sub(f2(f125), f2(b025), f2(f126), f2(b026))} tone="var(--watch)" />
      </div>
      <p className="text-xs text-dim">{PERF.basis}</p>

      <section className="panel p-4">
        <p className="text-xl font-semibold leading-relaxed">{PERF.sentence}</p>
        <h2 className="mt-4 flex items-center text-base font-semibold text-dim">
          {PERF.onset.title}
          <Info term="leadTime" />
        </h2>
        <div className="mt-2 space-y-2">
          <Bar label={PERF.onset.ours} pct={onsetPct} note={`${allHit}/${allN}건`} color="var(--safe)" />
          <Bar label={PERF.onset.persist} pct={0} note={`0/${allN}건 · ${PERF.onset.persistNote}`} color="var(--severe)" />
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
            {PERF.target.rows(f2(r2raw25), f2(r2raw26), f2(nse25), f2(nse26)).map((r) => (
              <li key={r} className="font-semibold" style={{ color: "var(--severe)" }}>
                {r}
              </li>
            ))}
          </ul>
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
          <Section file="tbl_holdout_2025.md" title="2025 홀드아웃 — 전 지표 + 부트스트랩 95% CI" pick={[0, 1]} />
          <Section file="tbl_holdout_2026_posthoc.md" title="2026 사후 검증 — 전체·지점별·전환 분해·리드타임" pick={[0, 1, 2, 3, 4]} />
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
