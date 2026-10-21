"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { BOARD, COMBO, COMBO_ORDER } from "@/lib/copy";

export type MapSite = { site_id: string; name: string; lat: number; lon: number; tier: string | null; q50: number | null; p_alert: number | null; latest_alert_level: number | null; latest_cell_count: number | null };

const MapInner = dynamic(() => import("./MapInner"), { ssr: false, loading: () => <div className="h-full w-full animate-pulse bg-panel" aria-hidden /> });

/** 중앙 지도: Esri Dark Gray Canvas(키 불필요) + 낙동강·금강 본류 물길(OSM 단순화) + 조합 라벨 마커. 발표모드에서는 밝은 타일 */
export function ControlMap({ sites, expert }: { sites: MapSite[]; expert: boolean }) {
  const [light, setLight] = useState(false);
  useEffect(() => {
    const read = () => setLight(document.documentElement.dataset.theme === "light");
    read();
    const mo = new MutationObserver(read);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => mo.disconnect();
  }, []);
  return (
    <div className="relative h-full w-full overflow-hidden rounded-xl" role="region" aria-label={`${BOARD.panels.map} — ${BOARD.mapLegend}`}>
      <MapInner sites={sites} expert={expert} light={light} />
      <div className="pointer-events-none absolute left-2 top-2 z-[400] rounded-md border border-border bg-panel/85 px-2 py-1 text-xs text-dim">
        <div className="flex flex-wrap gap-x-3 gap-y-0.5">
          {COMBO_ORDER.map((k) => (
            <span key={k} style={{ color: COMBO[k].color }}>
              {COMBO[k].icon} {COMBO[k].bannerWord}
            </span>
          ))}
        </div>
        <div>
          {BOARD.mapLegend} · {BOARD.mapPulse}
        </div>
      </div>
    </div>
  );
}
