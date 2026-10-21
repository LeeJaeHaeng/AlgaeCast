import type { MdTable as T } from "@/lib/reports";

export function MdTable({ table, caption, maxRows = 60, highlightFirstRow = false }: { table: T; caption?: string; maxRows?: number; highlightFirstRow?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="tbl text-xs">
        {caption && <caption className="pb-1 text-left text-sm font-semibold text-text">{caption}</caption>}
        <thead>
          <tr>
            {table.header.map((h, i) => (
              <th key={i}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.slice(0, maxRows).map((r, i) => (
            <tr key={i} className={highlightFirstRow && i === 0 ? "font-semibold" : ""} style={highlightFirstRow && i === 0 ? { background: "color-mix(in srgb, var(--accent) 12%, transparent)" } : undefined}>
              {r.map((c, j) => (
                <td key={j}>{c.replace(/\*\*/g, "").replace(/`/g, "")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
