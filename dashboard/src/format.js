// Small display helpers shared by the components.

// Priority tiers: 70+ red, 40–69 orange, under 40 yellow (thresholds unchanged).
export function pointsTier(points) {
  if (points >= 70) return "high";
  if (points >= 40) return "medium";
  return "low";
}

export const TIER_LABEL = { high: "High", medium: "Medium", low: "Low" };

// Hex values (not CSS variables) so Leaflet's SVG attributes render them.
export function pointsColour(points) {
  if (points >= 70) return "#D92D20";
  if (points >= 40) return "#EF7B1A";
  return "#F4C534";
}

export function pointsStroke(points) {
  if (points >= 70) return "#8F1A12";
  if (points >= 40) return "#9A4A06";
  return "#7A5A00";
}

export function hhmm(iso) {
  if (!iso) return "?";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function hoursLeft(h) {
  if (h === null || h === undefined) return "";
  if (h <= 0) return "now";
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  return `${Number(h.toFixed(1))} h`;
}

export const label = (text) => (text || "").replaceAll("_", " ");

export function caseTitle(c) {
  const where = c.landmark || c.zone || "no location";
  return `${where}`;
}

// Visual tone for a case badge, so the same badge always looks the same everywhere.
export function badgeTone(badge) {
  const b = (badge || "").toLowerCase();
  if (b.startsWith("verify") || b === "zone task") return "critical";
  if (b === "verified") return "success";
  if (b === "override") return "override";
  if (b.includes("re-check") || b.includes("check location") || b.includes("stale")) return "warning";
  if (/report/.test(b)) return "info";
  if (b.includes("unconfirmed")) return "strong";
  return "neutral";
}

export const TEAM_COLOURS = {
  available: "#157A44",
  assigned: "#1D4AB8",
  en_route: "#1D4AB8",
  on_scene: "#6D3FC8",
  returning: "#5B6B7A",
  out_of_service: "#B42318"
};

export const TEAM_LETTER = { boat: "B", truck: "T", medic: "M", rescue: "R", fire: "F", welfare: "W", volunteer: "V" };

// Places on the map: shelters, cooling centres and hospitals each get their own marker.
export function placeKind(type) {
  const t = (type || "").toLowerCase();
  if (t.includes("cool")) return "cooling";
  if (t.includes("hosp") || t.includes("clinic")) return "hospital";
  if (t.includes("shelter")) return "shelter";
  return "other";
}

export const PLACE_LETTER = { shelter: "S", cooling: "C", hospital: "H", other: "P" };