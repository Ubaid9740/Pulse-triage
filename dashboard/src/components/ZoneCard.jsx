import { useEffect, useState } from "react";
import { enc, get, post } from "../api.js";
import { label } from "../format.js";

// The zone card (Team Brief figure 7): the numbers, warning coverage, the outreach list and the
// "Send welfare-check team" zone task.
export default function ZoneCard({ name, rev, onClose, onOpenCase, refresh }) {
  const [card, setCard] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let live = true;
    get(`/api/zones/${enc(name)}`).then((d) => live && setCard(d)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [name, rev]);

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

  if (!card) return <div className="card">{error ? <p className="error">{error}</p> : "Loading…"}</div>;
  const z = card.zone;
  const coverage = z.coverage === null ? null : Math.round(z.coverage * 100);

  return (
    <div className="card">
      <div className="card-head">
        <button className="close" onClick={onClose} aria-label="Back to the list">←</button>
        <div className="card-title">
          <span className="muted">Zone · {z.population.toLocaleString()} people</span>
          <h2>{z.name}</h2>
        </div>
        {z.silent ? <span className="points big silent">SILENT</span>
                  : <span className="points big quiet">{z.hard_hit ? "hard-hit" : "calm"}</span>}
      </div>

      <ul className="lines">{card.lines.map((l) => <li key={l}>{l}</li>)}</ul>

      {coverage !== null && (
        <div className="coverage">
          <div className="bar"><span style={{ width: `${coverage}%` }} /></div>
          <span>Warning coverage {coverage}% ({z.confirmed} of {z.registered} registered confirmed)</span>
        </div>
      )}
      {error && <p className="error">{error}</p>}

      <div className="actions">
        {card.task.case_id
          ? <button onClick={() => onOpenCase(card.task.case_id)}>Open the zone task (#{card.task.case_id})</button>
          : <button className="primary" onClick={async () => {
              const out = await act(`/api/zones/${enc(z.name)}/task`);
              if (out) onOpenCase(out.case.id);
            }}>Send welfare-check team ({card.task.points} points)</button>}
        <button onClick={() => act("/api/zones/hard-hit", { zones: [z.name], hard_hit: !z.hard_hit })}>
          {z.hard_hit ? "Clear hard-hit" : "Mark hard-hit"}
        </button>
      </div>
      <p className="muted small-text">{card.task.reasons.map((r) => `${r.text} (+${r.points})`).join(" · ")}</p>

      <h3>Outreach list: {card.unconfirmed.length} not confirmed</h3>
      {card.unconfirmed.length === 0 ? <p className="muted">Everyone registered here is confirmed.</p> : (
        <table className="outreach">
          <thead><tr><th>Who</th><th>Needs</th><th>Phone</th></tr></thead>
          <tbody>
            {card.unconfirmed.map((p) => (
              <tr key={p.id} className={`prio-${p.priority}`}>
                <td>{p.name} <span className="muted">{p.id}</span></td>
                <td>{p.conditions.map(label).join(", ")}</td>
                <td>{p.phone || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
