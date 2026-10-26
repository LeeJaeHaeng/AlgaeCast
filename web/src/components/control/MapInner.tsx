"use client";

import L from "leaflet";
import { useEffect, useMemo, useState } from "react";
import { GeoJSON, MapContainer, Marker, Popup, TileLayer, Tooltip, useMap } from "react-leaflet";
import type { FeatureCollection } from "geojson";
import { APP, BOARD, COMBO, OFFICIAL_LEVEL, TIER, comboOf } from "@/lib/copy";
import { fmtCellsKo, pctInt, tierOf } from "@/lib/format";
import type { MapSite } from "./ControlMap";

const OFFICIAL_HEX: Record<number, string> = { 0: "#8A9BB8", 1: "#FACC15", 2: "#F97316", 3: "#EF4444" };
const TILES = {
  dark: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
  light: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
};

/** 5개 지점 bbox 에 20% 패딩으로 맞춤 */
function FitBounds({ sites }: { sites: MapSite[] }) {
  const map = useMap();
  useEffect(() => {
    if (!sites.length) return;
    const b = L.latLngBounds(sites.map((s) => [s.lat, s.lon] as [number, number]));
    map.fitBounds(b.pad(0.2), { animate: false });
    const onResize = () => map.fitBounds(b.pad(0.2), { animate: false });
    map.on("resize", onResize);
    return () => {
      map.off("resize", onResize);
    };
  }, [map, sites]);
  return null;
}

export default function MapInner({ sites, expert, light, linkQuery }: { sites: MapSite[]; expert: boolean; light: boolean; linkQuery?: string }) {
  const [rivers, setRivers] = useState<FeatureCollection | null>(null);
  useEffect(() => {
    fetch("/rivers.geojson")
      .then((r) => (r.ok ? r.json() : null))
      .then((g) => setRivers(g))
      .catch(() => setRivers(null));
  }, []);
  const riverStyle = useMemo(() => ({ color: light ? "#0369a1" : "#38BDF8", weight: 2.5, opacity: 0.75 }), [light]);
  return (
    <MapContainer center={[35.9, 128.2]} zoom={8} zoomControl={false} scrollWheelZoom={false} attributionControl style={{ height: "100%", width: "100%" }}>
      <TileLayer attribution={`${APP.mapAttribution} · ${BOARD.mapRivers}`} url={light ? TILES.light : TILES.dark} maxZoom={16} />
      {rivers && <GeoJSON key={light ? "l" : "d"} data={rivers} style={riverStyle} interactive={false} />}
      <FitBounds sites={sites} />
      {sites.map((s) => {
        const t = tierOf(s.tier);
        const lvl = s.latest_alert_level ?? 0;
        const combo = comboOf(lvl, t);
        const c = COMBO[combo];
        const html = `<div class="relative" style="width:28px;height:28px"><div class="${combo === "enter" ? "pulse" : ""} absolute inset-0 rounded-full" style="background:${c.hex};border:3px solid ${OFFICIAL_HEX[lvl]};box-shadow:0 0 10px ${c.hex}"></div></div>`;
        const icon = L.divIcon({ html, className: "", iconSize: [28, 28], iconAnchor: [14, 14] });
        return (
          <Marker key={s.site_id} position={[s.lat, s.lon]} icon={icon} alt={`${s.name} ${c.label}`} title={`${s.name} ${c.label}`} keyboard={false}>
            <Tooltip permanent direction="right" offset={[16, 0]} className="!border-0 !bg-transparent !shadow-none !text-current" opacity={1}>
              <span className="rounded bg-panel/90 px-1.5 py-0.5 text-sm font-semibold" style={{ color: c.hex }}>
                {c.icon} {s.name} <span className="font-normal">{c.bannerWord}</span>
              </span>
            </Tooltip>
            <Popup>
              <div className="text-sm">
                <div className="font-bold">
                  {s.name} <span style={{ color: c.hex }}>{c.label}</span>
                </div>
                <div>
                  {BOARD.tile.now} {fmtCellsKo(s.latest_cell_count)} {BOARD.unit.cells} · {BOARD.tile.official} {OFFICIAL_LEVEL[lvl].label} · {BOARD.tile.ai} {TIER[t].label}
                </div>
                <div>
                  {BOARD.tile.next} {fmtCellsKo(s.point)} {BOARD.unit.cells} · {BOARD.tile.chance} {pctInt(s.p_alert)}%
                </div>
                <a className="underline" style={{ color: "var(--accent)" }} href={`/sites/${s.site_id}${linkQuery ?? (expert ? "?view=expert" : "")}`}>
                  지점 상세 보기
                </a>
              </div>
            </Popup>
          </Marker>
        );
      })}
    </MapContainer>
  );
}
