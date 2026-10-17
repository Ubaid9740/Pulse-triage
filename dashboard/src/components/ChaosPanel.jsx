import { useEffect, useState } from "react";
import { get, post } from "../api.js";
import Dialog from "./Dialog.jsx";

const PROBLEMS = [
  ["duplicate", "Duplicate", "A second phone reports the top case again", "It merges: a \"2 reports\" badge, more trust."],
  ["fake", "Fake report", "An unknown phone claims 50 people trapped at the stadium", "Low trust and a \"verify\" badge."],
  ["wrong_location", "Wrong location", "The top case's landmark, with GPS 2 km off", "A separate case with lower trust and \"check location\"."],
];

// Demo only (System Design 13.4): inject the problems a real incident brings and watch the
// dashboard handle them within one refresh.
export default function ChaosPanel({ refresh, onClose, onOpenCase }) {
  const [results, setResults] = useState([]);
  const [ai, setAi] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    get("/api/status").then((s) => setAi(s.ai)).catch(() => {});
  }, []);

  async function inject(kind, body) {
    setError(null);
    try {
      const out = await post(`/api/chaos/${kind}`, body);
      if (kind === "ai_down") setAi(out.ai);
      else setResults((r) => [{ kind, ...out }, ...r]);
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  const down = ai?.simulated_outage;
  return (
    <Dialog title="Chaos (demo only)" onClose={onClose}>
      <p className="muted">Bad data is normal in a disaster. Each button sends a real signed report from a new phone.</p>
      <div className="chaos-list">
        {PROBLEMS.map(([kind, title, what, expect]) => (
          <div key={kind} className="chaos-row">
            <div><b>{title}</b><br /><span>{what}</span><br /><span className="muted small-text">{expect}</span></div>
            <button onClick={() => inject(kind)}>Inject</button>
          </div>
        ))}
        <div className="chaos-row">
          <div><b>AI outage</b><br /><span>The AI reader acts as if the internet were cut</span><br />
            <span className="muted small-text">The offline banner shows; keyword rules carry on.
              {ai && !ai.enabled ? " (The AI reader is turned off on this server.)" : ""}</span></div>
          <button className={down ? "on" : ""} onClick={() => inject("ai_down", { on: !down })}>
            {down ? "End outage" : "Start outage"}
          </button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {results.length > 0 && (
        <ul className="chaos-results">
          {results.map((r) => (
            <li key={r.report_id}>
              {PROBLEMS.find((p) => p[0] === r.kind)[1]}:{" "}
              {r.merged ? `joined case #${r.case_id}` : `new case #${r.case_id}`}{" "}
              <button className="link" onClick={() => onOpenCase(r.case_id)}>Open</button>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}
