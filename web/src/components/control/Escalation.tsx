"use client";

import { useEffect } from "react";

/** 새 상승(안전→주의, 주의→대응 등) 감지: 지난 방문의 단계와 비교해 해당 지점 타일을 깜빡인다 (data-site 속성) */
export function Escalation({ tiers }: { tiers: Record<string, "normal" | "watch" | "alert"> }) {
  useEffect(() => {
    const rank = { normal: 0, watch: 1, alert: 2 } as const;
    try {
      const prev = JSON.parse(localStorage.getItem("algaecast.tiers") ?? "{}") as Record<string, keyof typeof rank>;
      for (const [sid, t] of Object.entries(tiers)) {
        if (prev[sid] && rank[t] > rank[prev[sid]]) {
          document.querySelectorAll<HTMLElement>(`[data-site="${sid}"]`).forEach((el) => el.classList.add("blink"));
        }
      }
      localStorage.setItem("algaecast.tiers", JSON.stringify(tiers));
    } catch {}
  }, [tiers]);
  return null;
}
