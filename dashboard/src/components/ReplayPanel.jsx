import { useEffect, useState } from "react";
import { get, post } from "../api.js";
import { label } from "../format.js";
import Dialog from "./Dialog.jsx";

const SPEEDS = [30, 60, 90, 120, 300];

// The scenario replay (Team Brief 5.2): pick a pack and a speed, reset to it and play its story.
// While it plays, the scenario clock and the presenter's cues show here and in the bottom strip.
export default function ReplayPanel({ replay, refresh, onClose }) {
  const [packs, setPacks] = useState(null);
  const [pack, setPack] = useState(replay?.pack || "flood");
  const [speed, setSpeed] = useState(60);
  const [reset, setReset] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    get("/api/demo/packs").then((p) => {
      setPacks(p.packs);
      if (p.packs.length && !p.packs.includes(pack)) setPack(p.packs[0]);
    }).catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function start() {
    setError(null);
    setBusy(true);
    try {
      await post("/api/demo/replay", { pack, speed, reset });
      refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    try {
      await post("/api/demo/replay/stop");
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  const running = replay?.running;
  return (
    <Dialog title="Scenario replay" onClose={onClose}>
      {!running && (
        <>
          <p className="muted">A made-up disaster in Karachi, streamed in as real reports, texts and replies.
            {reset ? " The server is reset to the pack first: this incident's data is cleared (a backup is kept)." : ""}</p>
          <div className="row">
            <label>Pack
              <select value={pack} onChange={(e) => setPack(e.target.value)}>
                {(packs || []).map((p) => <option key={p} value={p}>{label(p)}</option>)}
              </select>
            </label>
            <label>Speed
              <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
                {SPEEDS.map((s) => <option key={s} value={s}>{s}x ({s === 60 ? "1 h of story per minute" : `${s} min per minute`})</option>)}
              </select>
            </label>
          </div>
          <label className="check"><input type="checkbox" checked={reset} onChange={(e) => setReset(e.target.checked)} />
            Reset to the pack first</label>
          <div className="actions">
            <button className="primary" onClick={start} disabled={busy || !packs?.length}>{busy ? "Starting…" : "Start"}</button>
            <button onClick={onClose}>Cancel</button>
          </div>
        </>
      )}
      {replay?.pack && (
        <div className="replay-status">
          <p>
            <b>{label(replay.pack)}</b> · {replay.speed}x ·{" "}
            {running ? <>scenario time <b className="clock">{replay.scenario_time}</b></> : "stopped"} ·{" "}
            {replay.done} of {replay.total} events{replay.story_done ? " (story done; teams still move)" : ""}
          </p>
          {replay.held_replies > 0 && (
            <p className="warn">{replay.held_replies} replies are waiting for an active alert: issue the warning.</p>
          )}
          {replay.cues?.length > 0 && (
            <ul className="cues">
              {replay.cues.map((c, i) => <li key={i} className={i === 0 ? "now" : ""}><span className="muted">{c.at}</span> {c.text}</li>)}
            </ul>
          )}
          {replay.errors?.length > 0 && <p className="error">{replay.errors[0]}</p>}
          {running && <div className="actions"><button onClick={stop}>Stop the replay</button></div>}
        </div>
      )}
      {error && <p className="error">{error}</p>}
    </Dialog>
  );
}
