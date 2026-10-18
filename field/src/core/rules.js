// The profile rules, as the server reads them (server/app/profiles.py). Used for the urgency hint
// that decides mesh send order, and to show the right questions. profiles = GET /api/profiles:
// { common: {...}, profiles: { flood: {...}, heat: {...}, ... } }.

function parseToken(text) {
  if (text.includes(":")) {
    const [key, rest] = text.split(/:(.*)/s);
    return { kind: key === "cond" ? "cond" : "in", key, values: rest.split("|").filter(Boolean) };
  }
  if (text.startsWith("!")) return { kind: "no", key: text.slice(1) };
  return { kind: "yes", key: text };
}

function tokenMatches(token, details, conditions) {
  if (token.kind === "cond") return token.values.some((v) => conditions.has(v));
  const value = details[token.key];
  if (token.kind === "yes") return value === true;
  if (token.kind === "no") return value !== true;
  if (Array.isArray(value)) return token.values.some((v) => value.includes(v));
  return token.values.includes(value);
}

export function ruleMatches(tokens, details, conditions) {
  const conds = new Set(conditions);
  return tokens.every((t) => tokenMatches(parseToken(t), details || {}, conds));
}

export function hoursToCritical(profiles, hazard, details, conditions) {
  const rules = [...(profiles?.common?.hours_rules || []), ...(profiles?.profiles?.[hazard]?.hours_rules || [])];
  let best = { hours: 24, text: null };
  for (const rule of rules) {
    if (rule.hours < best.hours && ruleMatches(rule.all, details, conditions)) best = { hours: rule.hours, text: rule.text };
  }
  return best;
}

// Mesh send order (Team Brief A2): under 1 h = 3, under 3 h = 2, any condition = 1, else 0.
export function urgencyHint(profiles, hazard, details, conditions) {
  const { hours } = hoursToCritical(profiles, hazard, details, conditions);
  if (hours < 1) return 3;
  if (hours < 3) return 2;
  return conditions.length ? 1 : 0;
}

export function questions(profiles, hazard) {
  return [...(profiles?.common?.questions || []), ...(profiles?.profiles?.[hazard]?.questions || [])];
}

export const label = (text) => (text || "").replaceAll("_", " ");
