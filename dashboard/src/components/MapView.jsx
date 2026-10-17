import { useEffect, useMemo, useRef } from "react";
import L from "leaflet";
import { CircleMarker, GeoJSON, MapContainer, Marker, Polyline, Tooltip, useMap } from "react-leaflet";
import { caseTitle, hhmm, hoursLeft, pointsColour, TEAM_COLOURS, TEAM_LETTER } from "../format.js";

const TILES = "/tiles/town.pmtiles";
// Online street map: OpenStreetMap's own tiles (no key; light use with the credit shown), faded in
// styles.css so the zones and pins stand out on a projector.
const ONLINE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ONLINE_CREDIT = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const KARACHI = [24.88, 67.07];

// Zones: outline, fill by warning coverage, red when silent. Cases: pins by points, sized by
// people. Teams: icon by type, colour by status, grey when stale, a line to the case and the
// last positions. Places: head count over capacity (System Design 6.3).
export default function MapView({ snap, selected, onSelect }) {
  const cases = snap.cases.filter((c) => c.lat !== null && c.lng !== null);
  const caseById = useMemo(() => Object.fromEntries(snap.cases.map((c) => [c.id, c])), [snap.cases]);
  const zonesDoc = useMemo(() => ({
    type: "FeatureCollection",
    features: snap.zones.map((z) => ({ type: "Feature", properties: z, geometry: z.polygon })),
  }), [snap.zones]);
  const zonesKey = snap.zones.map((z) => `${z.name}:${z.silent}:${z.coverage}:${z.hard_hit}`).join("|")
    + (selected?.kind === "zone" ? `#${selected.name}` : "");

  return (
    <MapContainer center={KARACHI} zoom={12} className="map" zoomControl={true}>
      <BaseMap />
      <FitOnce snap={snap} />
      <GeoJSON key={zonesKey} data={zonesDoc} style={(f) => zoneStyle(f.properties, selected)}
               onEachFeature={(f, layer) => {
                 layer.on("click", () => onSelect({ kind: "zone", name: f.properties.name }));
                 layer.bindTooltip(zoneTip(f.properties), { sticky: true, className: "zone-tip" });
               }} />
      {snap.shelters.filter((s) => s.lat !== null).map((s) => (
        <CircleMarker key={`s-${s.id}`} center={[s.lat, s.lng]} radius={7}
                      pathOptions={{ color: "#1d7a45", fillColor: "#2e9d5b", fillOpacity: 0.9, weight: 2 }}>
          <Tooltip permanent direction="right" offset={[8, 0]} className="place-tip">
            {s.name} {s.occupancy}/{s.capacity ?? "?"}{s.nearly_full ? " nearly full" : ""}
          </Tooltip>
        </CircleMarker>
      ))}
      {snap.teams.filter((t) => t.lat !== null).map((t) => <Team key={`t-${t.id}`} team={t} target={caseById[t.case_id]} />)}
      {cases.map((c) => {
        const isSelected = selected?.kind === "case" && selected.id === c.id;
        return (
          <CircleMarker key={`c-${c.id}`} center={[c.lat, c.lng]} radius={8 + Math.min(c.people, 10) * 1.2}
                        eventHandlers={{ click: () => onSelect({ kind: "case", id: c.id }) }}
                        pathOptions={{ color: isSelected ? "#111" : "#fff", weight: isSelected ? 4 : 2,
                                       fillColor: pointsColour(c.points), fillOpacity: 0.95,
                                       dashArray: c.window_closes_at ? "4 3" : null }}>
            <Tooltip direction="top" offset={[0, -8]}>
              <b>{c.points}</b> {caseTitle(c)} · {c.people} {c.people === 1 ? "person" : "people"}
              {c.hours_left !== null && <> · {hoursLeft(c.hours_left)} left</>}
              {c.window_closes_at && <> · window closes {hhmm(c.window_closes_at)}</>}
            </Tooltip>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}

function zoneStyle(z, selected) {
  const picked = selected?.kind === "zone" && selected.name === z.name;
  if (z.silent) {
    return { color: "#b42318", weight: picked ? 5 : 3, fillColor: "#e5484d", fillOpacity: 0.35 };
  }
  const fill = z.coverage === null ? "#9aa5b1" : coverageColour(z.coverage);
  return { color: z.hard_hit ? "#8a4b08" : "#56606b", weight: picked ? 4 : z.hard_hit ? 2.5 : 1.5,
           dashArray: z.hard_hit ? null : "6 4", fillColor: fill, fillOpacity: 0.18 };
}

function coverageColour(c) {
  // red (0) to amber to green (1)
  const r = c < 0.5 ? 220 : Math.round(220 - (c - 0.5) * 2 * 170);
  const g = c < 0.5 ? Math.round(80 + c * 2 * 100) : 180;
  return `rgb(${r}, ${g}, 70)`;
}

function zoneTip(z) {
  const cov = z.coverage === null ? "" : ` · coverage ${Math.round(z.coverage * 100)}%`;
  return `<b>${z.name}</b>${z.silent ? " · SILENT" : ""}${cov}`;
}

function Team({ team, target }) {
  const colour = team.stale ? "#9aa5b1" : TEAM_COLOURS[team.status] || "#555";
  const icon = L.divIcon({
    className: "team-icon",
    html: `<span style="background:${colour}">${TEAM_LETTER[team.type] || "?"}</span>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
  const trail = team.trail.map((p) => [p.lat, p.lng]);
  return (
    <>
      {trail.length > 1 && <Polyline positions={trail} pathOptions={{ color: colour, weight: 2, opacity: 0.5, dashArray: "2 5" }} />}
      {target && target.lat !== null && (
        <Polyline positions={[[team.lat, team.lng], [target.lat, target.lng]]} pathOptions={{ color: colour, weight: 2 }} />
      )}
      <Marker position={[team.lat, team.lng]} icon={icon}>
        <Tooltip direction="top" offset={[0, -12]}>
          <b>{team.name}</b> · {team.status.replace("_", " ")}
          {team.flags.length > 0 && <> · {team.flags.join(", ").replaceAll("_", " ")}</>}
          {team.eta && team.status !== "on_scene" && <> · ETA {hhmm(team.eta)}</>}
          {" · as of "}{hhmm(team.ping_at)}
        </Tooltip>
      </Marker>
    </>
  );
}

// Fit the map to the town once, when there is something to show.
function FitOnce({ snap }) {
  const map = useMap();
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    map.invalidateSize();
    const size = map.getSize();
    if (!size.x || !size.y) return;                       // not laid out yet: try on the next snapshot
    const bounds = L.latLngBounds([]);
    snap.zones.forEach((z) => bounds.extend(L.geoJSON(z.polygon).getBounds()));
    snap.cases.forEach((c) => c.lat !== null && bounds.extend([c.lat, c.lng]));
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [30, 30] });
      done.current = true;
    }
  }, [snap, map]);
  return null;
}

// The base map: the offline file (dashboard/public/tiles/town.pmtiles) if the scenario provides one,
// otherwise the online street map. Without either (offline, no file) the shapes sit on grey.
function BaseMap() {
  const map = useMap();
  useEffect(() => {
    let layer = null;
    let gone = false;
    fetch(TILES, { method: "HEAD" })
      .then(async (res) => {
        // Missing file: 404 from the server, or the dev server's HTML fallback page.
        const offline = res.ok && !(res.headers.get("content-type") || "").includes("html");
        if (gone) return;
        if (offline) {
          const { leafletLayer } = await import("protomaps-leaflet");
          if (gone) return;
          layer = leafletLayer({ url: TILES, flavor: "light", lang: "en", attribution: "&copy; OpenStreetMap contributors" });
        } else {
          layer = L.tileLayer(ONLINE, { attribution: ONLINE_CREDIT, maxZoom: 19, className: "street-tiles" });
        }
        layer.addTo(map);
      })
      .catch(() => {});
    return () => {
      gone = true;
      if (layer) map.removeLayer(layer);
    };
  }, [map]);
  return null;
}
