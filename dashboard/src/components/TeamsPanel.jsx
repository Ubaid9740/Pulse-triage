import { useState } from "react";
import { enc, post } from "../api.js";
import { hhmm, label, TEAM_COLOURS } from "../format.js";

const STATUSES = ["available", "assigned", "en_route", "on_scene", "returning", "out_of_service"];
// What the dispatcher may set by hand (a job is given with Assign on the case card).
const SETTABLE = ["available", "en_route", "on_scene", "returning", "out_of_service"];
const NEED_LABELS = { boat: "Boats", truck: "Trucks", medic: "Medics", rescue: "Rescue", fire: "Fire", evac: "Evacuation" };
const MOVES = {
  restock: { from: null, to: "default", text: "Restock (arrived at)" },
  load: { from: "default", to: "team", text: "Load onto a team" },
  unload: { from: "team", to: "default", text: "Unload from a team" },
  deliver: { from: "default", to: "shelter", text: "Deliver to a place" },
  used: { from: "default", text: "Used" },
  transfer: { from: "any", to: "any", text: "Transfer" },
};

// The Teams and resources view (Team Brief 3.7, C3): counters, warnings, every team's status and
// last position, supplies left and how fast they go, and the places' head counts.
export default function TeamsPanel({ snap, profiles, refresh, onOpenCase }) {
  const summary = snap.summary.teams || {};
  const warnings = snap.summary.warnings || [];
  return (
    <div className="resources">
      {warnings.length > 0 && <div className="res-warnings">{warnings.map((w) => <span key={w}>{w}</span>)}</div>}
      <div className="res-counters">
        {STATUSES.map((s) => (
          <span key={s} className="counter"><i style={{ background: TEAM_COLOURS[s] }} />{label(s)} <b>{summary[s] ?? 0}</b></span>
        ))}
        {Object.entries(summary.by_capability || {}).map(([need, c]) => (
          <span key={need} className={`counter need ${c.free === 0 ? "none" : ""}`}>
            {NEED_LABELS[need] || label(need)}: <b>{c.free}</b> of {c.total} free
          </span>
        ))}
      </div>
      <TeamTable snap={snap} refresh={refresh} onOpenCase={onOpenCase} />
      <SupplyTable snap={snap} profiles={profiles} refresh={refresh} />
      <PlaceTable snap={snap} />
    </div>
  );
}

function TeamTable({ snap, refresh, onOpenCase }) {
  const [editing, setEditing] = useState(null);       // team id
  const cases = Object.fromEntries(snap.cases.map((c) => [c.id, c]));
  return (
    <section>
      <h2>Teams</h2>
      <div className="table-wrap">
        <table className="res-table">
          <thead>
            <tr><th>Team</th><th>Type</th><th>Status</th><th>Job</th><th>ETA / arrived</th><th>Last seen</th>
              <th>Battery</th><th>Fuel</th><th>Carrying</th><th /></tr>
          </thead>
          <tbody>
            {snap.teams.map((t) => {
              const job = t.case_id ? cases[t.case_id] : null;
              const flagged = t.flags.length > 0;
              return [
                <tr key={t.id} className={flagged ? "flagged" : ""}>
                  <td><b>{t.name}</b></td>
                  <td>{label(t.type)}</td>
                  <td>
                    <span className="status-dot" style={{ background: TEAM_COLOURS[t.status] }} />
                    {label(t.status)}
                    {t.flags.map((f) => <span key={f} className="badge badge-verify">{label(f)}</span>)}
                    {t.status_reason && <div className="muted small-text">{t.status_reason}</div>}
                  </td>
                  <td>{t.case_id ? <button className="link" onClick={() => onOpenCase(t.case_id)}>
                    #{t.case_id} {job ? job.landmark || job.zone || "" : ""}</button> : ""}</td>
                  <td>{t.arrived_at ? `arrived ${hhmm(t.arrived_at)}` : t.eta ? `ETA ${hhmm(t.eta)}` : ""}
                    {t.distance_to_case_m !== null && !t.arrived_at
                      ? <div className="muted small-text">{(t.distance_to_case_m / 1000).toFixed(1)} km away</div> : null}</td>
                  <td className={t.stale ? "muted" : ""}>{t.ping_at ? `as of ${hhmm(t.ping_at)}` : "no ping yet"}
                    {t.ping_received_at && t.ping_received_at !== t.ping_at
                      ? <div className="muted small-text">received {hhmm(t.ping_received_at)}</div> : null}</td>
                  <td>{t.battery !== null ? `${t.battery}%` : ""}</td>
                  <td className={t.fuel === "low" ? "low" : ""}>{t.fuel || ""}</td>
                  <td className="small-text">{Object.entries(t.load).map(([i, q]) => `${q} ${label(i)}`).join(", ")}</td>
                  <td><button className="small" onClick={() => setEditing(editing === t.id ? null : t.id)}>Status</button></td>
                </tr>,
                editing === t.id && (
                  <tr key={`${t.id}-edit`} className="edit-row">
                    <td colSpan={10}>
                      <StatusForm team={t} onDone={() => { setEditing(null); refresh(); }} />
                    </td>
                  </tr>
                ),
              ];
            })}
          </tbody>
        </table>
        {!snap.teams.length && <p className="empty">No teams yet.</p>}
      </div>
    </section>
  );
}

// Set a status by hand, e.g. after a radio call. Out of service needs a reason.
function StatusForm({ team, onDone }) {
  const [status, setStatus] = useState(team.status === "out_of_service" ? "available" : "out_of_service");
  const [reason, setReason] = useState("");
  const [error, setError] = useState(null);
  const options = SETTABLE.filter((s) => s !== team.status && (team.case_id || !["en_route", "on_scene"].includes(s)));
  async function save(e) {
    e.preventDefault();
    setError(null);
    try {
      await post(`/api/teams/${enc(team.id)}/status`, { status, reason: reason.trim() || null });
      onDone();
    } catch (err) {
      setError(err.message);
    }
  }
  return (
    <form className="inline-form" onSubmit={save}>
      <label>{team.name} is now
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          {options.map((s) => <option key={s} value={s}>{label(s)}</option>)}
        </select>
      </label>
      <label className="grow">Reason {status === "out_of_service" ? "(needed)" : "(optional)"}
        <input value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)}
               placeholder={status === "out_of_service" ? "engine fault, refuelling, crew resting" : "radio call"} />
      </label>
      <button type="submit" className="primary" disabled={status === "out_of_service" && !reason.trim()}>Set</button>
      {team.case_id && ["available", "out_of_service"].includes(status) &&
        <span className="warn small-text">This cancels its job on case #{team.case_id}.</span>}
      {error && <span className="error">{error}</span>}
    </form>
  );
}

function SupplyTable({ snap, profiles, refresh }) {
  const [moving, setMoving] = useState(false);
  return (
    <section>
      <h2>Supplies <button className="small" onClick={() => setMoving(!moving)}>{moving ? "Close" : "Move stock"}</button></h2>
      {moving && <MoveForm snap={snap} profiles={profiles} onDone={refresh} />}
      <div className="table-wrap">
        <table className="res-table num-table">
          <thead>
            <tr><th>Supply</th><th>Command post</th><th>Places</th><th>On teams</th><th>Used today</th>
              <th>Left</th><th>Runs out in</th></tr>
          </thead>
          <tbody>
            {snap.supplies.map((s) => (
              <tr key={s.item} className={s.low ? "flagged" : ""}>
                <td><b>{label(s.item)}</b> {s.unit !== "pcs" ? <span className="muted">({s.unit})</span> : null}</td>
                <td>{fmt(s.command_post)}</td>
                <td>{fmt(s.shelters)}</td>
                <td>{fmt(s.teams)}</td>
                <td>{fmt(s.used_today)}</td>
                <td><b>{fmt(s.left)}</b>{s.low && <span className="badge badge-verify">LOW</span>}
                  {s.warn_at !== null && <div className="muted small-text">warn at {fmt(s.warn_at)}</div>}</td>
                <td>{s.runs_out_in_hours !== null ? `about ${roundHours(s.runs_out_in_hours)}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!snap.supplies.length && <p className="empty">No supplies entered yet. Use "Move stock" and Restock.</p>}
      </div>
    </section>
  );
}

// Restock, load, unload, deliver, use or transfer (POST /api/supplies/move). Places are the
// command post, a place (shelter, cooling centre, hospital) or a team.
function MoveForm({ snap, profiles, onDone }) {
  const known = snap.supplies.map((s) => s.item);
  const suggested = profiles?.profiles[snap.hazard]?.supplies || [];
  const items = [...new Set([...known, ...suggested])].sort();
  const [kind, setKind] = useState("restock");
  const [item, setItem] = useState(items[0] || "");
  const [qty, setQty] = useState("");
  const [from, setFrom] = useState("command_post");
  const [to, setTo] = useState("command_post");
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  const rule = MOVES[kind];
  const places = (side) => {
    const all = [["command_post", "Command post"],
      ...snap.shelters.map((s) => [`shelter:${s.id}`, s.name]),
      ...snap.teams.map((t) => [`team:${t.id}`, t.name])];
    if (side === "team") return all.filter(([p]) => p.startsWith("team:"));
    if (side === "shelter") return all.filter(([p]) => p.startsWith("shelter:"));
    return all;
  };
  const pick = (side, value) => { const list = places(side); return list.some(([p]) => p === value) ? value : list[0]?.[0] || ""; };
  const fromValue = rule.from ? pick(rule.from, from) : null;
  const toValue = rule.to ? pick(rule.to, to) : null;

  async function save(e) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    const body = { kind, item, qty: Number(qty) };
    if (fromValue) body.from = fromValue;
    if (toValue) body.to = toValue;
    try {
      await post("/api/supplies/move", body);
      setMessage(`${MOVES[kind].text}: ${qty} ${label(item)}`);
      setQty("");
      onDone();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <form className="inline-form panel" onSubmit={save}>
      <label>Move
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {Object.entries(MOVES).map(([k, m]) => <option key={k} value={k}>{m.text}</option>)}
        </select>
      </label>
      <label>Supply
        <input list="supply-items" value={item} onChange={(e) => setItem(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"))} />
        <datalist id="supply-items">{items.map((i) => <option key={i} value={i}>{label(i)}</option>)}</datalist>
      </label>
      <label>How many
        <input type="number" min="0" step="any" value={qty} onChange={(e) => setQty(e.target.value)} />
      </label>
      {rule.from && (
        <label>From
          <select value={fromValue} onChange={(e) => setFrom(e.target.value)}>
            {places(rule.from).map(([p, n]) => <option key={p} value={p}>{n}</option>)}
          </select>
        </label>
      )}
      {rule.to && (
        <label>To
          <select value={toValue} onChange={(e) => setTo(e.target.value)}>
            {places(rule.to).map(([p, n]) => <option key={p} value={p}>{n}</option>)}
          </select>
        </label>
      )}
      <button type="submit" className="primary" disabled={!item || !(Number(qty) > 0)}>Save</button>
      {message && <span className="ok">{message}</span>}
      {error && <span className="error">{error}</span>}
    </form>
  );
}

function PlaceTable({ snap }) {
  return (
    <section>
      <h2>Places</h2>
      <div className="table-wrap">
        <table className="res-table num-table">
          <thead><tr><th>Place</th><th>Type</th><th>People</th><th>Capacity</th><th>Space left</th><th>Updated</th></tr></thead>
          <tbody>
            {snap.shelters.map((s) => (
              <tr key={s.id} className={s.nearly_full ? "flagged" : ""}>
                <td><b>{s.name}</b>{s.nearly_full && s.next ? <div className="muted small-text">nearly full; next: {s.next.name}</div> : null}</td>
                <td>{label(s.type)}</td>
                <td>{s.occupancy}</td>
                <td>{s.capacity ?? ""}</td>
                <td>{s.space_left ?? ""}{s.nearly_full && <span className="badge badge-verify">nearly full</span>}</td>
                <td className="muted">{hhmm(s.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!snap.shelters.length && <p className="empty">No places entered yet.</p>}
      </div>
    </section>
  );
}

const fmt = (n) => (n === null || n === undefined ? "" : Number(n).toLocaleString(undefined, { maximumFractionDigits: 1 }));
const roundHours = (h) => (h < 1 ? `${Math.max(1, Math.round(h * 60))} min` : `${Math.round(h)} h`);
