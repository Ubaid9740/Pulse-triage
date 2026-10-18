import { useEffect, useState } from "react";
import { enc, get, post } from "../api.js";
import { label } from "../format.js";
import Icon from "./Icon.jsx";

// The zone card (Team Brief figure 7): the numbers, warning coverage, the outreach list and the
// "Send welfare-check team" zone task.
export default function ZoneCard({ name, rev, onClose, onOpenCase, refresh }) {
  const [card, setCard] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let live = true;
    get(`/api/zones/${enc(name)}`).then((d) => live && setCard(d)).catch((e) => live && setError(e.message));
    return () => {live = false;};
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

  if (!card) {
    return <div className="card card-loading">{error ? <p className="error">{error}</p> : <span className="muted">Loading zone…</span>}</div>;
  }
  const z = card.zone;
  const coverage = z.coverage === null ? null : Math.round(z.coverage * 100);
  const covLevel = coverage === null ? "" : coverage < 50 ? "low" : coverage < 80 ? "mid" : "high";

  return (
    <article className={`card zone-card ${z.silent ? "is-silent" : ""}`} aria-label={`Zone ${z.name}`}>
      {z.silent &&
      <div className="silent-band" role="status">
          <Icon name="silent" size={16} />
          <b>Silent Zone</b>
          <span>Fewer replies than expected for a hard-hit area</span>
        </div>
      }
      <header className="card-head">
        <button className="icon-btn" onClick={onClose} aria-label="Back to the list"><Icon name="arrowLeft" size={18} /></button>
        <div className="card-title">
          <span className="eyebrow">Zone · {z.population.toLocaleString()} people</span>
          <h2>{z.name}</h2>
        </div>
        {z.silent ? <span className="zone-state state-silent"><Icon name="silent" size={14} />SILENT</span> :
        <span className={`zone-state ${z.hard_hit ? "state-hard" : ""}`}>{z.hard_hit ? "hard-hit" : "calm"}</span>}
      </header>

      {coverage !== null &&
      <div className={`coverage cov-${covLevel}`}>
          <div className="coverage-top">
            <span>Warning coverage</span>
            <b>{coverage}%</b>
          </div>
          <div className="bar" role="progressbar" aria-valuenow={coverage} aria-valuemin={0} aria-valuemax={100}
        aria-label="Warning coverage"><span style={{ width: `${coverage}%` }} /></div>
          <span className="coverage-sub">
            {z.confirmed} of {z.registered} registered confirmed
            {covLevel === "low" && <b className="cov-flag"><Icon name="alert" size={12} />Low coverage</b>}
          </span>
        </div>
      }

      <ul className="lines">{card.lines.map((l) => <li key={l}>{l}</li>)}</ul>
      {error && <p className="error" role="alert">{error}</p>}

      <div className="actions card-actions">
        {card.task.case_id ?
        <button className="btn" onClick={() => onOpenCase(card.task.case_id)}><Icon name="fileText" />Open the zone task (#{card.task.case_id})</button> :
        <button className="btn btn-danger" onClick={async () => {
          const out = await act(`/api/zones/${enc(z.name)}/task`);
          if (out) onOpenCase(out.case.id);
        }}><Icon name="heart" />Send welfare-check team ({card.task.points} points)</button>}
        <button className="btn" onClick={() => act("/api/zones/hard-hit", { zones: [z.name], hard_hit: !z.hard_hit })}>
          {z.hard_hit ? "Clear hard-hit" : "Mark hard-hit"}
        </button>
      </div>
      <p className="task-reasons">{card.task.reasons.map((r) => `${r.text} (+${r.points})`).join(" · ")}</p>

      <section className="card-section">
        <h3>Outreach list · {card.unconfirmed.length} not confirmed</h3>
        {card.unconfirmed.length === 0 ? <p className="muted">Everyone registered here is confirmed.</p> :
        <table className="outreach">
            <thead><tr><th>Who</th><th>Needs</th><th>Phone</th></tr></thead>
            <tbody>
              {card.unconfirmed.map((p) =>
            <tr key={p.id} className={`prio-${p.priority}`}>
                  <td><b>{p.name}</b> <span className="muted">{p.id}</span></td>
                  <td>{p.conditions.map(label).join(", ")}</td>
                  <td className="mono">{p.phone || "—"}</td>
                </tr>
            )}
            </tbody>
          </table>
        }
      </section>
    </article>);

}