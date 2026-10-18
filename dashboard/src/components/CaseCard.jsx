import { useEffect, useState } from "react";
import { get, post } from "../api.js";
import { caseTitle, hhmm, hoursLeft, label, pointsTier, TIER_LABEL } from "../format.js";
import Badge from "./Badge.jsx";
import Icon from "./Icon.jsx";

const READER = { form: "app form", keywords: "keyword rules", ai: "AI", system: "the server" };

// The explanation card: the real maths line by line, then the dispatcher's buttons.
export default function CaseCard({ caseId, rank, rev, onClose, refresh }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [mode, setMode] = useState(null); // "override" | "suggest"

  useEffect(() => {
    let live = true;
    get(`/api/cases/${caseId}`).then((d) => live && setDetail(d)).catch((e) => live && setError(e.message));
    return () => {live = false;};
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

  if (!detail) {
    return <div className="card card-loading">{error ? <p className="error">{error}</p> : <span className="muted">Loading case…</span>}</div>;
  }
  const c = detail.case;
  const parts = c.reasons.filter((r) => r.kind !== "trust" && r.kind !== "override");
  const trust = c.reasons.find((r) => r.kind === "trust");
  const override = c.reasons.find((r) => r.kind === "override");
  const subtotal = parts.reduce((s, r) => s + r.points, 0);
  const tier = pointsTier(c.points);

  return (
    <article className="card case-card" aria-label={`Case ${c.id}`}>
      <header className="card-head">
        <button className="icon-btn" onClick={onClose} aria-label="Back to the list"><Icon name="arrowLeft" size={18} /></button>
        <div className="card-title">
          <span className="eyebrow">Rank #{rank || "?"} · Case {c.id} · {label(c.hazard)}</span>
          <h2>{caseTitle(c)}</h2>
          {c.landmark && c.zone && <span className="card-sub"><Icon name="mapPin" size={13} />{c.zone}</span>}
        </div>
        <div className={`score tier-${tier}`}>
          <span className="score-num">{c.points}</span>
          <span className="score-label">{TIER_LABEL[tier]} priority</span>
        </div>
      </header>

      {c.badges.length > 0 && <div className="badge-row">{c.badges.map((b) => <Badge key={b} text={b} />)}</div>}

      <section className="card-section">
        <h3>Why this score</h3>
        <table className="reasons">
          <tbody>
            {parts.map((r, i) =>
            <tr key={i}><td>{r.text}</td><td className="num">+{r.points}</td></tr>
            )}
            {trust &&
            <>
                <tr className="sub"><td>Subtotal</td><td className="num">{subtotal}</td></tr>
                <tr className="trust"><td><span className="trust-tag">Confidence</span>{trust.text}</td><td className="num">×{trust.points.toFixed(2)}</td></tr>
              </>
            }
            {override && <tr className="override"><td><Icon name="pencil" size={13} />{override.text}</td><td className="num">{override.points}</td></tr>}
            <tr className="total"><td>Priority points</td><td className="num">{c.points}</td></tr>
          </tbody>
        </table>
      </section>

      <dl className="facts">
        <div><dt>People</dt><dd>{c.people} {c.people === 1 ? "person" : "people"}</dd></div>
        {c.hours_left !== null && <div><dt>Time left</dt><dd className={c.hours_left < 1 ? "urgent" : ""}>{hoursLeft(c.hours_left)} left</dd></div>}
        {c.needs.length > 0 && <div><dt>Needs</dt><dd>{c.needs.join(" + ")}</dd></div>}
        <div><dt>Reports</dt><dd>{detail.reports.length}</dd></div>
        <div><dt>Read by</dt><dd>{READER[c.reader] || c.reader}</dd></div>
        <div><dt>Status</dt><dd>{label(c.status)}{c.team_id ? ` (${c.team_id})` : ""}</dd></div>
      </dl>
      {c.note && <blockquote className="note">“{c.note}”</blockquote>}
      {error && <p className="error" role="alert">{error}</p>}

      <div className="actions card-actions">
        {!c.badges.includes("verified") &&
        <button className="btn btn-success" onClick={() => act(`/api/cases/${c.id}/verify`)}><Icon name="shieldCheck" />Verified</button>
        }
        <button className={`btn ${mode === "override" ? "on" : ""}`} aria-pressed={mode === "override"}
        onClick={() => setMode(mode === "override" ? null : "override")}><Icon name="pencil" />Override…</button>
        <button className={`btn btn-primary ${mode === "suggest" ? "on" : ""}`} aria-pressed={mode === "suggest"}
        onClick={() => setMode(mode === "suggest" ? null : "suggest")}><Icon name="navigation" />Suggest team</button>
      </div>
      {mode === "override" && <Override c={c} act={act} done={() => setMode(null)} />}
      {mode === "suggest" && <Suggest c={c} rev={rev} act={act} done={() => setMode(null)} />}

      <section className="card-section">
        <h3>{detail.reports.length} {detail.reports.length === 1 ? "report" : "reports"}{detail.reports.length > 1 ? " · merged" : ""}</h3>
        <ul className="reports">
          {detail.reports.map((r) =>
          <li key={r.id}>
              <div className="report-meta">
                <span>{hhmm(r.created_at)} · {label(r.source)} · {READER[r.reader] || r.reader}</span>
                {r.trusted && <span className="chip chip-success"><Icon name="check" size={11} />trusted phone</span>}
                {detail.reports.length > 1 &&
              <button className="btn btn-xs" onClick={() => act(`/api/cases/${c.id}/split`, { report_id: r.id })}>
                    <Icon name="split" size={13} />Split
                  </button>
              }
              </div>
              {r.note && <p className="report-note">“{r.note}”</p>}
            </li>
          )}
        </ul>
      </section>

      <section className="card-section">
        <h3>History</h3>
        <ul className="history">
          {detail.history.slice(-6).reverse().map((h, i) =>
          <li key={i}><span className="history-time">{hhmm(h.at)}</span><span>{label(h.action)} {h.detail ? `· ${h.detail}` : ""}</span></li>
          )}
        </ul>
      </section>
    </article>);

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
      <p className="panel-title">Override the rules</p>
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
      <div className="panel-actions">
        <button type="submit" className="primary" disabled={!reason.trim()}>Save override</button>
        {c.badges.includes("override") &&
        <button type="button" onClick={async () => (await act(`/api/cases/${c.id}/override`, { reason: reason || "Back to the rules" })) && done()}>
            Back to the rules
          </button>
        }
      </div>
    </form>);

}

function Suggest({ c, rev, act, done }) {
  const [s, setS] = useState(null);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  useEffect(() => {
    let live = true;
    get(`/api/suggest?case_id=${c.id}`).then((d) => live && setS(d)).catch((e) => live && setError(e.message));
    return () => {live = false;};
  }, [c.id, rev]);
  if (error) return <p className="error panel">{error}</p>;
  if (!s) return <div className="panel"><span className="muted">Finding a team…</span></div>;

  async function assign(teamId) {
    const out = await act("/api/assign", { case_id: c.id, team_id: teamId, place: s.place?.id || null, reassign: !!c.team_id });
    if (out) setResult(out);
  }

  if (result) {
    return (
      <div className="panel panel-success">
        <p><Icon name="check" size={15} /> <b>{result.job_id}</b> sent, ETA {hhmm(result.eta)} (about {result.travel_min} min).</p>
        {result.warnings.map((w) => <p key={w} className="warn">{w}</p>)}
        <div className="panel-actions"><button onClick={done}>OK</button></div>
      </div>);

  }
  const options = [s.best, ...s.alternatives].filter(Boolean);
  return (
    <div className="panel">
      <p className="panel-title">Suggested teams</p>
      {s.why_none && <p className="warn">No suggestion: {s.why_none}.</p>}
      {options.map((o, i) =>
      <div key={o.team_id} className={`option ${i === 0 ? "best" : ""}`}>
          <span className="option-main">
            <span className="option-name"><b>{o.name}</b>{i === 0 && s.best && <span className="chip chip-success">Best match</span>}</span>
            <span className="option-sub">about {o.travel_min} min ({o.distance_km} km)
              {o.fetch.length > 0 && <> · pick up {o.fetch.map(label).join(", ")} first</>}</span>
          </span>
          <button className={i === 0 ? "primary" : ""} onClick={() => assign(o.team_id)}>Assign</button>
        </div>
      )}
      {s.tradeoff && <p className="tradeoff"><Icon name="info" size={14} />{s.tradeoff}</p>}
      {s.soon_free.map((t) => <p key={t.team_id} className="muted small-text">{t.name} free in about {t.free_in_min} min</p>)}
      {s.place &&
      <p className="place-line"><Icon name="home" size={14} />Take people to: <b>{s.place.name}</b> ({s.place.space_left ?? "?"} places, {s.place.distance_km} km)</p>
      }
    </div>);

}