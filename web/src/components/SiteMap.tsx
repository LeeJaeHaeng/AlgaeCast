"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import { TIER_COLOR, TIER_LABEL, fmtCells, fmtPct, tierOf } from "@/lib/format";

export type MapSite = { site_id: string; name: string; lat: number; lon: number; tier: string | null; q50: number | null; p_alert: number | null };

const MapContainer = dynamic(() => import("react-leaflet").then((m) => m.MapContainer), { ssr: false });
const TileLayer = dynamic(() => import("react-leaflet").then((m) => m.TileLayer), { ssr: false });
const CircleMarker = dynamic(() => import("react-leaflet").then((m) => m.CircleMarker), { ssr: false });
const Popup = dynamic(() => import("react-leaflet").then((m) => m.Popup), { ssr: false });

export function SiteMap({ sites }: { sites: MapSite[] }) {
  const center = useMemo<[number, number]>(() => [35.9, 128.3], []);
  return (
    <div className="h-[360px] w-full overflow-hidden rounded-xl border border-slate-200" role="region" aria-label="지점 지도 (마커 색 = 단계)">
      <MapContainer center={center} zoom={7} scrollWheelZoom={false} style={{ height: "100%", width: "100%" }}>
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {sites.map((s) => {
          const t = tierOf(s.tier);
          return (
            <CircleMarker key={s.site_id} center={[s.lat, s.lon]} radius={12} pathOptions={{ color: "#fff", weight: 2, fillColor: TIER_COLOR[t], fillOpacity: 0.95 }}>
              <Popup>
                <div className="text-sm">
                  <div className="font-bold">
                    {s.name} <span style={{ color: TIER_COLOR[t] }}>[{TIER_LABEL[t]}]</span>
                  </div>
                  <div>q50 {fmtCells(s.q50)} cells/mL · 경보 확률 {fmtPct(s.p_alert)}</div>
                  <a className="text-sky-700 underline" href={`/sites/${s.site_id}`}>
                    상세 보기 →
                  </a>
                </div>
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </div>
  );
}
