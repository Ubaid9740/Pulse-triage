import { useEffect, useRef, useState } from "react";
import { get, post } from "../api.js";
import { label } from "../format.js";
import Icon from "./Icon.jsx";

const TEXT = {
  cannot_walk: "Cannot walk or leave",
  elderly: "Elderly",
  child: "Child or infant",
  alone: "Alone",
  window: "Window closing (road floods, light fades)",
  person: "Points per person",
  people_max: "Most points for people"
};
const MAX = 50;

// A slider per weight (Team Brief 3.6) so a local authority can tune the rules. Each change is
// saved after a short pause; the server rescores every open case and the list below re-ranks.
export default function WeightsPanel({ refresh, onClose }) {
  const [weights, setWeights] = useState(null);
  const [defaults, setDefaults] = useState({});
  const [note, setNote] = useState(null);
  const [error, setError] = useState(null);
  const pending = useRef({});
  const timer = useRef(null);

  useEffect(() => {
    get("/api/settings/weights").then((w) => {setWeights(w.weights);setDefaults(w.defaults);}).catch((e) => setError(e.message));
    return () => clearTimeout(timer.current);
  }, []);

  async function save(body) {
    try {
      const out = await post("/api/settings/weights", body);
      setWeights(out.weights);
      setNote(`${out.cases_rescored} open case${out.cases_rescored === 1 ? "" : "s"} re-ranked`);
      setError(null);
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  function change(key, value) {
    setWeights((w) => ({ ...w, [key]: value }));
    pending.current = { ...pending.current, [key]: value };
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const weightsNow = pending.current;
      pending.current = {};
      save({ weights: weightsNow });
    }, 300);
  }

  const changed = weights && Object.keys(defaults).some((k) => weights[k] !== defaults[k]);
  return (
    <section className="weights" aria-label="Scoring weights">
      <div className="weights-head">
        <h2><Icon name="sliders" size={15} />Weights</h2>
        <button className="icon-btn" onClick={onClose} aria-label="Close weights"><Icon name="x" size={16} /></button>
      </div>
      <p className="muted small-text">Points each rule adds before the trust multiplier. Changes apply to every open case.</p>
      {!weights && !error && <p className="muted">Loading…</p>}
      {weights && Object.keys(defaults).map((key) =>
      <label key={key} className="slider">
          <span>{TEXT[key] || label(key)}</span>
          <input type="range" min="0" max={MAX} step="1" value={weights[key]} onChange={(e) => change(key, Number(e.target.value))} />
          <b className={weights[key] !== defaults[key] ? "changed" : ""}>{weights[key]}</b>
        </label>
      )}
      <div className="weights-foot">
        <button disabled={!changed} onClick={() => {clearTimeout(timer.current);pending.current = {};save({ reset: true });}}>
          Back to defaults
        </button>
        {note && <span className="ok small-text">{note}</span>}
        {error && <span className="error">{error}</span>}
      </div>
    </section>);

}