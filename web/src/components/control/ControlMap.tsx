"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { APP, BOARD, OFFICIAL_LEVEL, TIER } from "@/lib/copy";
import { TIER_HEX, fmtCellsKo, pctInt, tierOf } from "@/lib/format";

export type MapSite = { site_id: string; name: string; lat: number; lon: number; tier: string | null; q50: number | null; p_alert: number | null; latest_alert_level: number | null; latest_cell_count: number | null };

const MapContainer = dynamic(() => import("react-leaflet").then((m) => m.MapContainer), { ssr: false });
const TileLayer = dynamic(() => import("react-leaflet").then((m) => m.TileLayer), { ssr: false });
const Marker = dynamic(() => import("react-leaflet").then((m) => m.Marker), { ssr: false });
const Popup = dynamic(() => import("react-leaflet").then((m) => m.Popup), { ssr: false });
const Tooltip = dynamic(() => import("react-leaflet").then((m) => m.Tooltip), { ssr: false });

const OFFICIAL_HEX: Record<number, string> = { 0: "#8A9BB8", 1: "#FACC15", 2: "#F97316", 3: "#EF4444" };

/** 중앙 지도: CartoDB Dark Matter, 마커 색 = 예상 단계, 테두리 = 공식 발령, 대응 필요는 맥박(감소 모션 설정 존중) */
export function ControlMap({ sites, expert }: { sites: MapSite[]; expert: boolean }) {
  const [light, setLight] = useState(false);
  useEffect(() => {
    const read = () => setLight(document.documentElement.dataset.theme === "light");
    read();
    const mo = new MutationObserver(read);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => mo.disconnect();
  }, []);
  const center = useMemo<[number, number]>(() => [35.95, 128.25], []);
  const [L, setL] = useState<typeof import("leaflet") | null>(null);
  useEffect(() => {
    import("leaflet").then((m) => setL(m));
  }, []);
  const tiles = light
    ? "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
    : "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}";
  return (
    <div className="relative h-full w-full overflow-hidden rounded-xl" role="region" aria-label={`${BOARD.panels.map} — ${BOARD.mapLegend}`}>
      <MapContainer center={center} zoom={8} zoomControl={false} scrollWheelZoom={false} attributionControl style={{ height: "100%", width: "100%" }}>
        <TileLayer attribution={APP.mapAttribution} url={tiles} maxZoom={16} />
        {L &&
          sites.map((s) => {
            const t = tierOf(s.tier);
            const lvl = s.latest_alert_level ?? 0;
            const html = `<div class="relative" style="width:28px;height:28px"><div class="${t === "alert" ? "pulse" : ""} absolute inset-0 rounded-full" style="background:${TIER_HEX[t]};border:3px solid ${OFFICIAL_HEX[lvl]};box-shadow:0 0 10px ${TIER_HEX[t]}"></div></div>`;
            const icon = L.divIcon({ html, className: "", iconSize: [28, 28], iconAnchor: [14, 14] });
            return (
              <Marker key={s.site_id} position={[s.lat, s.lon]} icon={icon} alt={`${s.name} ${TIER[t].label}`}>
                <Tooltip permanent direction="right" offset={[16, 0]} className="!border-0 !bg-transparent !shadow-none !text-current" opacity={1}>
                  <span className="rounded bg-panel/90 px-1.5 py-0.5 text-sm font-semibold" style={{ color: TIER_HEX[t] }}>
                    {TIER[t].icon} {s.name}
                  </span>
                </Tooltip>
                <Popup>
                  <div className="text-sm">
                    <div className="font-bold">
                      {s.name} <span style={{ color: TIER_HEX[t] }}>{TIER[t].label}</span>
                    </div>
                    <div>
                      {BOARD.tile.now} {fmtCellsKo(s.latest_cell_count)} {BOARD.unit.cells} · {BOARD.tile.official} {OFFICIAL_LEVEL[lvl].label}
                    </div>
                    <div>
                      {BOARD.tile.next} {fmtCellsKo(s.q50)} {BOARD.unit.cells} · {BOARD.tile.chance} {pctInt(s.p_alert)}%
                    </div>
                    <a className="underline" style={{ color: "var(--accent)" }} href={`/sites/${s.site_id}${expert ? "?view=expert" : ""}`}>
                      지점 상세 보기
                    </a>
                  </div>
                </Popup>
              </Marker>
            );
          })}
      </MapContainer>
      <div className="pointer-events-none absolute left-2 top-2 z-[400] rounded-md border border-border bg-panel/85 px-2 py-1 text-xs text-dim">
        {BOARD.mapLegend} · {BOARD.mapPulse}
      </div>
    </div>
  );
}
