import { useEffect, useState } from "react";
import { get, post } from "../api.js";
import { caseTitle, hhmm, hoursLeft, label, pointsColour } from "../format.js";

const READER = { form: "app form", keywords: "keyword rules", ai: "AI", system: "the server" };

// The explanation card: the real maths line by line, then the dispatcher's buttons.
export default function CaseCard({ caseId, rank, rev, onClose, refresh }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [mode, setMode] = useState(null); // "override" | "suggest"

  useEffect(() => {
    let live = true;
    get(`/api/cases/${caseId}`).then((d) => live && setDetail(d)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [caseId, rev]);

  async function act(path, body) {
    setError(null);
    try {
      const out = await post(path, body);
      refresh();
      return out;
    } catch (e) {
      setError(e.message);
      return null;
    }
  }

  if (!detail) return <div className="card">{error ? <p className="error">{error}</p> : "Loading…"}</div>;
  const c = detail.case;
  const parts = c.reasons.filter((r) => r.kind !== "trust" && r.kind !== "override");
  const trust = c.reasons.find((r) => r.kind === "trust");
  const override = c.reasons.find((r) => r.kind === "override");
  const subtotal = parts.reduce((s, r) => s + r.points, 0);

  return (
    <div className="card">
      <div className="card-head">
        <button className="close" onClick={onClose} aria-label="Back to the list">←</button>
        <div className="card-title">
          <span className="muted">#{rank || "?"} · {label(c.hazard)}</span>
          <h2>{caseTitle(c)}</h2>
        </div>
        <span className="points big" style={{ background: pointsColour(c.points) }}>{c.points}</span>
      </div>

      <table className="reasons">
        <tbody>
          {parts.map((r, i) => (
            <tr key={i}><td>{r.text}</td><td className="num">+{r.points}</td></tr>
          ))}
          {trust && (
            <>
              <tr className="sub"><td>Subtotal</td><td className="num">{subtotal}</td></tr>
              <tr><td>{trust.text}</td><td className="num">×{trust.points.toFixed(2)}</td></tr>
            </>
          )}
          {override && <tr className="override"><td>{override.text}</td><td className="num">{override.points}</td></tr>}
          <tr className="total"><td>Priority points</td><td className="num">{c.points}</td></tr>
        </tbody>
      </table>

      <div className="facts">
        {c.badges.map((b) => <span key={b} className={`badge badge-${b.replace(/\s/g, "-")}`}>{b}</span>)}
        <span>{c.people} {c.people === 1 ? "person" : "people"}</span>
        {c.hours_left !== null && <span>{hoursLeft(c.hours_left)} left</span>}
        {c.needs.length > 0 && <span>Needs: {c.needs.join(" + ")}</span>}
        <span>Read by: {READER[c.reader] || c.reader}</span>
        <span>Status: {label(c.status)}{c.team_id ? ` (${c.team_id})` : ""}</span>
      </div>
      {c.note && <p className="note">“{c.note}”</p>}
      {error && <p className="error">{error}</p>}

      <div className="actions">
        {!c.badges.includes("verified") && <button onClick={() => act(`/api/cases/${c.id}/verify`)}>Verified</button>}
        <button className={mode === "override" ? "on" : ""} onClick={() => setMode(mode === "override" ? null : "override")}>Override…</button>
        <button className={mode === "suggest" ? "on" : ""} onClick={() => setMode(mode === "suggest" ? null : "suggest")}>Suggest team</button>
      </div>
      {mode === "override" && <Override c={c} act={act} done={() => setMode(null)} />}
      {mode === "suggest" && <Suggest c={c} rev={rev} act={act} done={() => setMode(null)} />}

      <h3>{detail.reports.length} {detail.reports.length === 1 ? "report" : "reports"}</h3>
      <ul className="reports">
        {detail.reports.map((r) => (
          <li key={r.id}>
            <span className="muted">{hhmm(r.created_at)} · {label(r.source)} · {READER[r.reader] || r.reader}
              {r.trusted ? " · trusted phone" : ""}</span>
            {r.note && <span> “{r.note}”</span>}
            {detail.reports.length > 1 && (
              <button className="small" onClick={() => act(`/api/cases/${c.id}/split`, { report_id: r.id })}>Split</button>
            )}
          </li>
        ))}
      </ul>

      <h3>History</h3>
      <ul className="history">
        {detail.history.slice(-6).reverse().map((h, i) => (
          <li key={i}><span className="muted">{hhmm(h.at)}</span> {label(h.action)} {h.detail ? `· ${h.detail}` : ""}</li>
        ))}
      </ul>
    </div>
  );
}

function Override({ c, act, done }) {
  const [points, setPoints] = useState(String(c.points));
  const [status, setStatus] = useState("");
  const [reason, setReason] = useState("");
  async function submit(e) {
    e.preventDefault();
    const body = { reason };
    if (status) body.status = status;
    if (points !== "" && Number(points) !== c.points) body.points = Number(points);
    if (await act(`/api/cases/${c.id}/override`, body)) done();
  }
  return (
    <form className="panel" onSubmit={submit}>
      <label>Points <input type="number" min="0" max="500" value={points} onChange={(e) => setPoints(e.target.value)} /></label>
      <label>Status
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">(keep {label(c.status)})</option>
          <option value="verified">verified</option>
          <option value="new">new</option>
          <option value="closed">closed (false alarm, duplicate)</option>
          <option value="done">done</option>
        </select>
      </label>
      <label className="wide">Reason (required, logged)
        <input value={reason} required onChange={(e) => setReason(e.target.value)} placeholder="e.g. Doctor confirmed oxygen nearly out" />
      </label>
      <button type="submit" disabled={!reason.trim()}>Save override</button>
      {c.badges.includes("override") && (
        <button type="button" onClick={async () => (await act(`/api/cases/${c.id}/override`, { reason: reason || "Back to the rules" })) && done()}>
          Back to the rules
        </button>
      )}
    </form>
  );
}

function Suggest({ c, rev, act, done }) {
  const [s, setS] = useState(null);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  useEffect(() => {
    let live = true;
    get(`/api/suggest?case_id=${c.id}`).then((d) => live && setS(d)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [c.id, rev]);
  if (error) return <p className="error panel">{error}</p>;
  if (!s) return <div className="panel">Finding a team…</div>;

  async function assign(teamId) {
    const out = await act("/api/assign", { case_id: c.id, team_id: teamId, place: s.place?.id || null, reassign: !!c.team_id });
    if (out) setResult(out);
  }

  if (result) {
    return (
      <div className="panel">
        <p><b>{result.job_id}</b> sent, ETA {hhmm(result.eta)} (about {result.travel_min} min).</p>
        {result.warnings.map((w) => <p key={w} className="warn">{w}</p>)}
        <button onClick={done}>OK</button>
      </div>
    );
  }
  const options = [s.best, ...s.alternatives].filter(Boolean);
  return (
    <div className="panel">
      {s.why_none && <p className="warn">No suggestion: {s.why_none}.</p>}
      {options.map((o, i) => (
        <div key={o.team_id} className={`option ${i === 0 ? "best" : ""}`}>
          <span><b>{o.name}</b> · about {o.travel_min} min ({o.distance_km} km)
            {o.fetch.length > 0 && <> · pick up {o.fetch.map(label).join(", ")} first</>}</span>
          <button onClick={() => assign(o.team_id)}>Assign</button>
        </div>
      ))}
      {s.tradeoff && <p className="tradeoff">{s.tradeoff}</p>}
      {s.soon_free.map((t) => <p key={t.team_id} className="muted">{t.name} free in about {t.free_in_min} min</p>)}
      {s.place && <p>Take people to: <b>{s.place.name}</b> ({s.place.space_left ?? "?"} places, {s.place.distance_km} km)</p>}
    </div>
  );
}
