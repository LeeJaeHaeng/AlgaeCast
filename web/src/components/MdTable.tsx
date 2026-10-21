import type { MdTable as T } from "@/lib/reports";

export function MdTable({ table, caption, maxRows = 60, highlightFirstRow = false }: { table: T; caption?: string; maxRows?: number; highlightFirstRow?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="tbl">
        {caption && <caption className="pb-1 text-left text-sm font-semibold">{caption}</caption>}
        <thead>
          <tr>
            {table.header.map((h, i) => (
              <th key={i}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.slice(0, maxRows).map((r, i) => (
            <tr key={i} className={highlightFirstRow && i === 0 ? "bg-amber-50 font-semibold" : ""}>
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
