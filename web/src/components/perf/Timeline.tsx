import { PERF } from "@/lib/copy";
import { fmtDateFull } from "@/lib/format";
import type { BloomEvent } from "@/lib/queries";

const SITE_NAME: Record<string, string> = { "2011G26": "해평", "2011G56": "강정·고령", "2020G33": "칠서", "2022G05": "물금·매리", "3008G30": "회남" };
const ORDER = ["2011G26", "2011G56", "2020G33", "2022G05", "3008G30"];

/** 경계 사건 시간표(서버 SVG): 지점별 가로줄, 사건마다 처음 알린 날 → 실제 초과일 선, 놓친 사건 빨간 점, 올해 사건 테두리 */
export function Timeline({ events }: { events: BloomEvent[] }) {
  const W = 1800;
  const LANE = 44;
  const PAD_L = 110;
  const PAD_T = 28;
  const years = [2020, 2021, 2022, 2023, 2024, 2025, 2026];
  const t0 = new Date("2020-01-01").getTime();
  const t1 = new Date("2027-01-01").getTime();
  const x = (d: string) => PAD_L + ((new Date(d).getTime() - t0) / (t1 - t0)) * (W - PAD_L - 20);
  const H = PAD_T + LANE * ORDER.length + 10;
  return (
    <figure className="w-full overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={PERF.timeline.title}>
        {years.map((y) => (
          <g key={y}>
            <line x1={x(`${y}-01-01`)} x2={x(`${y}-01-01`)} y1={PAD_T - 6} y2={H - 6} stroke="var(--panel-border)" />
            <text x={x(`${y}-01-01`) + 6} y={14} fontSize={13} fill="var(--text-dim)">
              {y}년{y === 2026 ? ` (${PERF.timeline.posthoc})` : ""}
            </text>
          </g>
        ))}
        {ORDER.map((sid, i) => {
          const cy = PAD_T + LANE * i + LANE / 2;
          return (
            <g key={sid}>
              <text x={8} y={cy + 5} fontSize={15} fontWeight={700} fill="var(--text)">
                {SITE_NAME[sid]}
              </text>
              <line x1={PAD_L} x2={W - 20} y1={cy} y2={cy} stroke="var(--panel-border)" strokeDasharray="2 4" />
              {events
                .filter((e) => e.site_id === sid)
                .map((e) => {
                  const xe = x(e.first_exceed_date);
                  const post = e.first_exceed_date >= "2026-01-01";
                  const ok = e.detected_watch && e.first_watch_date;
                  const xw = ok ? x(e.first_watch_date!) : xe;
                  const col = ok ? "var(--safe)" : "var(--severe)";
                  const title = `${SITE_NAME[sid]} · ${fmtDateFull(e.first_exceed_date)} 1만 초과${ok ? ` · ${e.lead_days_watch_e}일 앞서 알림 (${fmtDateFull(e.first_watch_date)})` : ` · ${PERF.timeline.missed}`}`;
                  return (
                    <g key={e.event_id}>
                      <title>{title}</title>
                      {ok && <line x1={xw} x2={xe} y1={cy} y2={cy} stroke={col} strokeWidth={4} strokeLinecap="round" />}
                      {ok && <circle cx={xw} cy={cy} r={3.5} fill={col} />}
                      <circle cx={xe} cy={cy} r={post ? 7 : 6} fill={ok ? "var(--text)" : col} stroke={post ? "var(--accent)" : "var(--bg)"} strokeWidth={post ? 3 : 1.5} />
                      {ok && (
                        <text x={xe} y={cy - 11} fontSize={11} textAnchor="middle" fill="var(--text-dim)">
                          {e.lead_days_watch_e}일
                        </text>
                      )}
                    </g>
                  );
                })}
            </g>
          );
        })}
      </svg>
      <figcaption className="mt-1 text-xs text-dim">{PERF.timeline.legend}</figcaption>
    </figure>
  );
}
