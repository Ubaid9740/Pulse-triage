// Small display helpers shared by the components.

export function pointsColour(points) {
  if (points >= 70) return "var(--red)";
  if (points >= 40) return "var(--orange)";
  return "var(--yellow)";
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

export const TEAM_COLOURS = {
  available: "#2e9d5b",
  assigned: "#2f6fd6",
  en_route: "#2f6fd6",
  on_scene: "#7b4fd1",
  returning: "#5f7a8a",
  out_of_service: "#d64545",
};

export const TEAM_LETTER = { boat: "B", truck: "T", medic: "M", rescue: "R", fire: "F", welfare: "W", volunteer: "V" };
