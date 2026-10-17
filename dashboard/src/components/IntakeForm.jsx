import { useState } from "react";
import { post } from "../api.js";
import { label, pointsColour } from "../format.js";
import Dialog from "./Dialog.jsx";

// The call-taker's form (Team Brief 3.3): the same fields as the phone, built from the profile of
// the chosen disaster, plus a free-text note. Anything left out is read from the note.
export default function IntakeForm({ snap, profiles, refresh, onClose, onOpenCase }) {
  const [hazard, setHazard] = useState(snap.hazard);
  const [forWhom, setForWhom] = useState("other");
  const [people, setPeople] = useState("");
  const [conditions, setConditions] = useState([]);
  const [details, setDetails] = useState({});
  const [note, setNote] = useState("");
  const [landmark, setLandmark] = useState("");
  const [contact, setContact] = useState("");
  const [registryId, setRegistryId] = useState("");
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);

  if (!profiles) return <Dialog title="Intake" onClose={onClose}>Loading the profiles…</Dialog>;
  const hazards = Object.keys(profiles.profiles).sort();
  const questions = [...(profiles.common.questions || []), ...(profiles.profiles[hazard]?.questions || [])];

  function answer(id, value) {
    setDetails((old) => {
      const next = { ...old };
      if (value === undefined || value === "" || (Array.isArray(value) && !value.length)) delete next[id];
      else next[id] = value;
      return next;
    });
  }

  async function submit(e) {
    e.preventDefault();
    setError(null);
    const body = { hazard, for_whom: forWhom, conditions, details };
    if (people) body.people = Number(people);
    for (const [key, value] of [["note", note], ["landmark", landmark], ["contact", contact], ["registry_id", registryId]]) {
      if (value.trim()) body[key] = value.trim();
    }
    try {
      setDone(await post("/api/intake", body));
      refresh();
    } catch (err) {
      setError(err.message);
    }
  }

  if (done) {
    const c = done.case;
    return (
      <Dialog title="Intake" onClose={onClose}>
        <div className="intake-done">
          <span className="points big" style={{ background: pointsColour(c.points) }}>{c.points}</span>
          <div>
            <p><b>Case #{c.id}</b> · {c.landmark || c.zone || "no location"} · {c.people} {c.people === 1 ? "person" : "people"}</p>
            <p className="muted">{c.report_count > 1 ? `Joined an existing case (${c.report_count} reports). ` : ""}
              {c.reasons.filter((r) => r.kind !== "trust").map((r) => r.text).join(" · ")}</p>
          </div>
        </div>
        <div className="actions">
          <button className="primary" onClick={() => onOpenCase(c.id)}>Open the case</button>
          <button onClick={() => { setDone(null); setNote(""); setDetails({}); setConditions([]); setPeople(""); setLandmark(""); }}>
            Next call
          </button>
          <button onClick={onClose}>Close</button>
        </div>
      </Dialog>
    );
  }

  return (
    <Dialog title="Intake: a call, radio message or walk-in" onClose={onClose} wide>
      <form className="intake" onSubmit={submit}>
        <div className="row">
          <label>Disaster
            <select value={hazard} onChange={(e) => { setHazard(e.target.value); setDetails({}); }}>
              {hazards.map((h) => <option key={h} value={h}>{profiles.profiles[h]?.label?.en || label(h)}</option>)}
            </select>
          </label>
          <label>For whom
            <select value={forWhom} onChange={(e) => setForWhom(e.target.value)}>
              <option value="self">The caller</option>
              <option value="neighbour">A neighbour</option>
              <option value="other">Someone else</option>
            </select>
          </label>
          <label>How many people
            <input type="number" min="1" max="500" value={people} placeholder="from the note" onChange={(e) => setPeople(e.target.value)} />
          </label>
        </div>

        <fieldset>
          <legend>About them</legend>
          {profiles.common.conditions.map((c) => (
            <label key={c} className="check">
              <input type="checkbox" checked={conditions.includes(c)}
                     onChange={() => setConditions((old) => (old.includes(c) ? old.filter((x) => x !== c) : [...old, c]))} />
              {label(c)}
            </label>
          ))}
        </fieldset>

        <fieldset>
          <legend>{profiles.profiles[hazard]?.label?.en || label(hazard)} questions</legend>
          {questions.map((q) => (
            <div key={q.id} className="question">
              <span>{q.ask.en}</span>
              {q.type === "yesno" && (
                <span className="choices">
                  {[["yes", true], ["no", false], ["?", undefined]].map(([t, v]) => (
                    <label key={t} className="check">
                      <input type="radio" name={q.id} checked={details[q.id] === v} onChange={() => answer(q.id, v)} />{t}
                    </label>
                  ))}
                </span>
              )}
              {q.type === "choice" && (
                <select value={details[q.id] || ""} onChange={(e) => answer(q.id, e.target.value)}>
                  <option value="">?</option>
                  {q.options.map((o) => <option key={o} value={o}>{label(o)}</option>)}
                </select>
              )}
              {q.type === "multi" && (
                <span className="choices">
                  {q.options.map((o) => {
                    const picked = details[q.id] || [];
                    return (
                      <label key={o} className="check">
                        <input type="checkbox" checked={picked.includes(o)}
                               onChange={() => answer(q.id, picked.includes(o) ? picked.filter((x) => x !== o) : [...picked, o])} />
                        {label(o)}
                      </label>
                    );
                  })}
                </span>
              )}
            </div>
          ))}
        </fieldset>

        <label className="wide">What they said (read by keywords, then the AI, for anything not ticked above)
          <textarea rows="3" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)}
                    placeholder="e.g. Old man alone behind the green mosque, house 14, water at his waist and rising" />
        </label>
        <div className="row">
          <label>Landmark <input maxLength={200} value={landmark} onChange={(e) => setLandmark(e.target.value)} placeholder="from the note" /></label>
          <label>Caller's number <input maxLength={40} value={contact} onChange={(e) => setContact(e.target.value)} /></label>
          <label>Registry ID <input maxLength={40} value={registryId} onChange={(e) => setRegistryId(e.target.value)} placeholder="R-0007" /></label>
        </div>
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button type="submit" className="primary" disabled={!note.trim() && !conditions.length && !Object.keys(details).length}>
            Add the report
          </button>
          <button type="button" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </Dialog>
  );
}
