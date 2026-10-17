import { useEffect, useMemo, useState } from "react";
import { post } from "../api.js";
import { label } from "../format.js";
import Dialog from "./Dialog.jsx";

const SEVERITIES = [["watch", "Watch: be ready"], ["warning", "Warning: act today"], ["emergency", "Emergency: act now"]];
const BAND = { watch: "#e9c53b", warning: "#e8892b", emergency: "#d64545" };

function localInput(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// New alert (Team Brief 3.2 step 1): the template for the disaster and severity is filled in by
// the server's preview, so what you see is what phones get; the text stays editable. Then send it
// signed into the mesh, and generate the loudspeaker script.
export default function AlertComposer({ snap, profiles, refresh, onClose }) {
  const active = snap.alerts.filter((a) => a.status === "active");
  const [mode, setMode] = useState("new");          // "new", "update:<id>" or "clear:<id>"
  const [hazard, setHazard] = useState(snap.hazard);
  const [severity, setSeverity] = useState("warning");
  const [zones, setZones] = useState(snap.zones.filter((z) => z.hard_hit).map((z) => z.name));
  const [places, setPlaces] = useState([]);         // empty: the server picks the nearest with space
  const [fill, setFill] = useState({});
  const [validUntil, setValidUntil] = useState(localInput(new Date(Date.now() + 12 * 3600 * 1000)));
  const [headline, setHeadline] = useState("");
  const [steps, setSteps] = useState(["", "", ""]);
  const [edited, setEdited] = useState(false);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const [sent, setSent] = useState(null);
  const [scripts, setScripts] = useState(null);

  const [kind, target] = mode.includes(":") ? mode.split(":") : [mode, null];
  const clearing = kind === "clear";
  const hazards = profiles ? Object.keys(profiles.profiles).sort() : [snap.hazard];
  const template = profiles?.profiles[hazard]?.alert_templates?.[severity]?.en;
  const placeholders = useMemo(() => {
    const text = template ? [template.headline, ...template.do_now].join(" ") : "";
    return [...new Set([...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).filter((p) => p !== "zones"))];
  }, [template]);

  function body() {
    if (clearing) return { replaces: target, cancel: true };
    const b = { hazard, severity, zones, fill, valid_until: new Date(validUntil).toISOString() };
    if (places.length) b.places = places;
    if (kind === "update") b.replaces = target;
    if (edited) {
      b.headline = { en: headline };
      b.do_now = { en: steps.map((s) => s.trim()).filter(Boolean) };
    }
    return b;
  }

  // Ask the server for the filled-in payload whenever a choice changes.
  useEffect(() => {
    if (sent || (!clearing && !zones.length)) return;
    const missing = clearing || edited ? [] : placeholders.filter((p) => !(fill[p] || "").trim());
    if (missing.length) {
      setPreview(null);
      setError(`Fill in ${missing.map(label).join(" and ")} to see the alert`);
      setHeadline("");
      setSteps(["", "", ""]);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const p = await post("/api/alerts/preview", body());
        setPreview(p);
        setError(null);
        if (!edited) {
          setHeadline(p.headline.en);
          setSteps([...p.do_now.en, "", "", ""].slice(0, 3));
        }
      } catch (e) {
        setPreview(null);
        setError(e.message);
        if (!edited) {                          // never show text that no longer matches the choices
          setHeadline("");
          setSteps(["", "", ""]);
        }
      }
    }, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, hazard, severity, zones, places, fill, validUntil, edited, sent]);

  async function send() {
    setError(null);
    try {
      const out = await post("/api/alerts", body());
      setSent(out);
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  async function announce() {
    try {
      setScripts((await post("/api/announcement", { alert_id: sent.alert_id })).scripts);
    } catch (e) {
      setError(e.message);
    }
  }

  // Functional updates, so quick changes in a row never overwrite each other.
  const toggle = (setList, value) =>
    setList((list) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]));
  const shown = preview || {};
  const shownPlaces = shown.places || [];

  return (
    <Dialog title="New alert" onClose={onClose} wide>
      <div className="composer">
        <div className="composer-form">
          {sent ? (
            <div className="sent">
              <p><b>{sent.alert_id}</b> signed and queued for phones (outbound #{sent.outbound_seq}).</p>
              <p className="muted">It goes out to online phones at once and through the mesh to the rest.</p>
              <div className="actions">
                <button className="primary" onClick={announce}>Generate announcement script</button>
                <button onClick={onClose}>Done</button>
              </div>
              {scripts && scripts.map((s) => (
                <div key={s.language} className="script">
                  <span className="muted">{s.language} · about {s.seconds} s read aloud</span>
                  <p>{s.text}</p>
                </div>
              ))}
            </div>
          ) : (
            <>
              {active.length > 0 && (
                <label>What to send
                  <select value={mode} onChange={(e) => { setMode(e.target.value); setEdited(false); }}>
                    <option value="new">A new alert</option>
                    {active.map((a) => <option key={`u${a.id}`} value={`update:${a.id}`}>Update {a.id} ({label(a.hazard)} {a.severity})</option>)}
                    {active.map((a) => <option key={`c${a.id}`} value={`clear:${a.id}`}>All-clear for {a.id}</option>)}
                  </select>
                </label>
              )}
              {!clearing && (
                <>
                  <div className="row">
                    <label>Disaster
                      <select value={hazard} onChange={(e) => { setHazard(e.target.value); setEdited(false); }}>
                        {hazards.map((h) => <option key={h} value={h}>{profiles?.profiles[h]?.label?.en || label(h)}</option>)}
                      </select>
                    </label>
                    <label>Severity
                      <select value={severity} onChange={(e) => { setSeverity(e.target.value); setEdited(false); }}>
                        {SEVERITIES.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                      </select>
                    </label>
                    <label>Valid until
                      <input type="datetime-local" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} />
                    </label>
                  </div>
                  <fieldset>
                    <legend>Zones</legend>
                    {snap.zones.map((z) => (
                      <label key={z.name} className="check">
                        <input type="checkbox" checked={zones.includes(z.name)} onChange={() => toggle(setZones, z.name)} />
                        {z.name}{z.silent ? " (silent)" : z.hard_hit ? " (hard-hit)" : ""}
                      </label>
                    ))}
                    {!snap.zones.length && <span className="error">No zones loaded on the server yet.</span>}
                  </fieldset>
                  {placeholders.length > 0 && (
                    <div className="row">
                      {placeholders.map((p) => (
                        <label key={p}>{label(p)}
                          <input value={fill[p] || ""} placeholder={p === "start" ? "12:00" : p === "end" ? "17:00" : ""}
                                 onChange={(e) => { const v = e.target.value; setFill((f) => ({ ...f, [p]: v })); }} />
                        </label>
                      ))}
                    </div>
                  )}
                  <fieldset>
                    <legend>Places to go {places.length ? "" : "(automatic: nearest with space)"}</legend>
                    {snap.shelters.map((s) => (
                      <label key={s.id} className="check">
                        <input type="checkbox" checked={places.includes(s.id)} onChange={() => toggle(setPlaces, s.id)} />
                        {s.name} <span className="muted">{s.space_left ?? "?"} free</span>
                      </label>
                    ))}
                    {!snap.shelters.length && <span className="muted">No places entered yet.</span>}
                  </fieldset>
                  <label className="wide">Headline
                    <input value={headline} maxLength={120} onChange={(e) => { setHeadline(e.target.value); setEdited(true); }} />
                  </label>
                  {steps.map((s, i) => (
                    <label key={i} className="wide">Step {i + 1}
                      <input value={s} maxLength={140}
                             onChange={(e) => { const v = e.target.value; setSteps((old) => old.map((x, j) => (j === i ? v : x))); setEdited(true); }} />
                    </label>
                  ))}
                  {edited && <button className="link" onClick={() => setEdited(false)}>Back to the template text</button>}
                </>
              )}
              {error && <p className="error">{error}</p>}
              <div className="actions">
                <button className="primary" onClick={send} disabled={!preview}>
                  {clearing ? "Send all-clear" : kind === "update" ? "Send update" : "Sign and send"}
                </button>
                <button onClick={onClose}>Cancel</button>
              </div>
            </>
          )}
        </div>

        <div className="phone" aria-label="Phone preview">
          <div className="phone-band" style={{ background: shown.cancel ? "#2e9d5b" : BAND[shown.severity || severity] }}>
            {shown.cancel ? "ALL CLEAR" : `${label(shown.hazard || hazard)} ${shown.severity || severity}`.toUpperCase()}
          </div>
          <div className="phone-body">
            {!preview && error && <p className="phone-missing">{error}</p>}
            <p className="phone-headline">{edited || !preview ? headline || "…" : shown.headline?.en}</p>
            <ol>{(edited || !preview ? steps : shown.do_now?.en || []).filter(Boolean).map((s, i) => <li key={i}>{s}</li>)}</ol>
            {shownPlaces.length > 0 && (
              <div className="phone-place"><span className="muted">GO TO</span><br />
                {shownPlaces.map((p) => <span key={p.id}>{p.name}{p.space_left !== null ? ` · space for ${p.space_left}` : ""}<br /></span>)}
              </div>
            )}
            <div className="phone-buttons"><span>I'm safe</span><span className="need">I need help</span><span>I'm helping others</span></div>
            <p className="phone-sig">Signed by the command post</p>
          </div>
        </div>
      </div>
    </Dialog>
  );
}
