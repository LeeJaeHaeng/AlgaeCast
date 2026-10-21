import { TIER } from "@/lib/copy";
import { tierOf } from "@/lib/format";

/** 단계 배지 (예상 단계: 안전/주의 관찰/대응 필요) */
export function TierBadge({ tier, size = "md" }: { tier: string | null | undefined; size?: "sm" | "md" | "lg" }) {
  const t = tierOf(tier);
  const sz = size === "lg" ? "px-3 py-1 text-base" : size === "sm" ? "px-1.5 py-0.5 text-xs" : "px-2 py-0.5 text-sm";
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border font-semibold ${sz}`} style={{ color: TIER[t].color, borderColor: TIER[t].color, background: `color-mix(in srgb, ${TIER[t].color} 15%, transparent)` }}>
      <span aria-hidden>{TIER[t].icon}</span>
      {TIER[t].label}
    </span>
  );
}
