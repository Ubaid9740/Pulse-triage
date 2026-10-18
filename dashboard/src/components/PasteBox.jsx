import { useState } from "react";
import { post } from "../api.js";
import { label } from "../format.js";
import Dialog from "./Dialog.jsx";

// Paste a batch of forwarded messages (chat exports, texts, a shared sheet): each becomes a report,
// read by keywords at once and by the AI in the background. Chatter is skipped and listed.
export default function PasteBox({ snap, profiles, refresh, onClose, onOpenCase }) {
  const [text, setText] = useState("");
  const [hazard, setHazard] = useState("");
  const [out, setOut] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const hazards = profiles ? Object.keys(profiles.profiles).sort() : [];

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      setOut(await post("/api/paste", hazard ? { text, hazard } : { text }));
      refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog title="Paste forwarded messages" onClose={onClose} wide>
      {!out ?
      <form className="paste" onSubmit={submit}>
          <label className="wide">Messages
            <textarea rows="12" value={text} onChange={(e) => setText(e.target.value)} autoFocus
          placeholder={"[12/10, 14:03] Ana: Old man alone behind the green mosque, house 14, water at his waist\n" +
          "[12/10, 14:06] Bo: grandmother confused and very hot, no fan\n\n" +
          "Chat exports split on their headers, otherwise on blank lines, otherwise one message per line."} />
          </label>
          <div className="row">
            <label>If a message does not say which disaster
              <select value={hazard} onChange={(e) => setHazard(e.target.value)}>
                <option value="">use the newest alert, then {label(snap.hazard)}</option>
                {hazards.map((h) => <option key={h} value={h}>{profiles.profiles[h]?.label?.en || label(h)}</option>)}
              </select>
            </label>
          </div>
          {error && <p className="error" role="alert">{error}</p>}
          <div className="actions">
            <button type="submit" className="primary" disabled={!text.trim() || busy}>{busy ? "Reading…" : "Read the messages"}</button>
            <button type="button" onClick={onClose}>Cancel</button>
          </div>
        </form> :

      <div className="paste-result">
          <div className="result-summary">
            <span><b>{out.messages}</b> messages</span>
            <span className="rs-good"><b>{out.reports.filter((r) => !r.duplicate).length}</b> new reports</span>
            <span><b>{out.reports.filter((r) => r.duplicate).length}</b> already seen</span>
            <span><b>{out.skipped.length}</b> skipped</span>
          </div>
          <ul className="paste-list">
            {out.reports.map((r) =>
          <li key={r.report_id}>
                <div className="paste-item">
                  <span className="muted small-text">{label(r.read.hazard)} · {r.read.people} {r.read.people === 1 ? "person" : "people"}
                    {r.read.landmark ? ` · ${r.read.landmark}` : ""}{r.duplicate ? " · already seen" : ""}</span>
                  <span>{r.text}</span>
                </div>
                {r.case_id && <button className="small" onClick={() => onOpenCase(r.case_id)}>Case #{r.case_id}</button>}
              </li>
          )}
          </ul>
          {out.skipped.length > 0 &&
        <>
              <h3>Skipped (nothing to act on)</h3>
              <ul className="paste-list skipped">{out.skipped.map((s, i) => <li key={i} className="muted">{s.text}</li>)}</ul>
            </>
        }
          <div className="actions">
            <button onClick={() => {setOut(null);setText("");}}>Paste more</button>
            <button className="primary" onClick={onClose}>Done</button>
          </div>
        </div>
      }
    </Dialog>);

}