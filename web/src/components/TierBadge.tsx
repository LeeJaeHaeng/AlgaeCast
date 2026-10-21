import { TIER_BG, TIER_LABEL, type Tier, tierOf } from "@/lib/format";

export function TierBadge({ tier, size = "md" }: { tier: string | null | undefined; size?: "sm" | "md" | "lg" }) {
  const t: Tier = tierOf(tier);
  const cls = size === "lg" ? "px-3 py-1 text-base" : size === "sm" ? "px-1.5 py-0.5 text-xs" : "px-2 py-0.5 text-sm";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border font-semibold ${TIER_BG[t]} ${cls}`} aria-label={`단계 ${TIER_LABEL[t]}`}>
      <span className="inline-block h-2 w-2 rounded-full" style={{ background: `var(--tier-${t})` }} aria-hidden />
      {TIER_LABEL[t]}
    </span>
  );
}
