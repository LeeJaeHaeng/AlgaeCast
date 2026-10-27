import type { LogItem } from "@/components/control/EventLog";
import { BOARD, TIER, officialLabel } from "@/lib/copy";
import { fmtCellsKo, tierOf } from "@/lib/format";

/** v_event_log 행 → 표시용 (서버에서 호출) */
export function toLogItems(rows: { event_time: string; kind: "tier_change" | "observation" | "run"; site_id: string | null; site_name: string | null; tier_from: string | null; tier_to: string | null; cell_count: number | null; alert_level: number | null; p_alert: number | null; q50: number | null; status: string | null }[]): LogItem[] {
  return rows.map((r, i) => {
    const id = `${r.kind}-${r.site_id ?? "sys"}-${r.event_time}-${i}`;
    if (r.kind === "tier_change") {
      const to = tierOf(r.tier_to);
      const from = r.tier_from ? TIER[tierOf(r.tier_from)].label : null;
      return { id, time: r.event_time, kind: r.kind, tone: to, dateOnly: true, text: BOARD.log.tierChange(r.site_name ?? "", from, `${TIER[to].icon} ${TIER[to].label}`), expertNote: r.p_alert != null ? `(p_alert ${r.p_alert.toFixed(2)}, q50 ${Math.round(r.q50 ?? 0).toLocaleString()})` : undefined };
    }
    if (r.kind === "observation") {
      const lvl = r.alert_level ?? 0;
      // 공식 발령 문구는 officialLabel(접두어 + 접두어 뒤 라벨: "공식 발령 없음"·"공식 발령 관심") — 예전 '공식 발령 ' + "발령 없음" 조합의 단어 중복 방지
      return { id, time: r.event_time, kind: r.kind, tone: "info", dateOnly: true, text: BOARD.log.observation(r.site_name ?? "", `${fmtCellsKo(r.cell_count)} ${BOARD.unit.cells}`, officialLabel(lvl)) };
    }
    const ok = r.status === "success";
    return { id, time: r.event_time, kind: r.kind, tone: ok ? "normal" : "fail", text: ok ? BOARD.log.runOk : BOARD.log.runFail };
  });
}
