export function KpiTile({ label, value, sub, tone = "default" }: { label: string; value: string; sub?: string; tone?: "default" | "alert" | "watch" | "good" }) {
  const ring = tone === "alert" ? "border-red-300" : tone === "watch" ? "border-amber-300" : tone === "good" ? "border-emerald-300" : "border-slate-200";
  return (
    <div className={`card ${ring}`}>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-bold tabular-nums">{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}
