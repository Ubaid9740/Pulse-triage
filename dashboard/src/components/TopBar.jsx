import { useState } from "react";
import { post } from "../api.js";
import { label } from "../format.js";

// Active disaster (switches the profile), the offline banner, counters and the warnings.
export default function TopBar({ snap, offline, profiles, refresh, onOpen, view, weightsOpen, replay }) {
  const [error, setError] = useState(null);
  const hazards = profiles ? Object.keys(profiles.profiles).sort() : [snap.hazard];
  const teams = snap.summary.teams || {};
  const silent = snap.zones.filter((z) => z.silent).length;
  const warnings = snap.summary.warnings || [];

  async function switchHazard(hazard) {
    setError(null);
    try {
      await post("/api/settings/hazard", { hazard });
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <header className="topbar">
      <div className="brand">PulseTriage</div>
      <label className="hazard">
        <span className="sr-only">Disaster</span>
        <select value={snap.hazard} onChange={(e) => switchHazard(e.target.value)}>
          {hazards.map((h) => (
            <option key={h} value={h}>{profiles?.profiles[h]?.label?.en || label(h)}</option>
          ))}
        </select>
      </label>
      {offline && <span className="banner banner-red">Server not reachable: showing the last update</span>}
      {!offline && snap.status.banner && <span className="banner">{snap.status.banner}</span>}
      <div className="tools">
        <button onClick={() => onOpen("alert")}>New alert</button>
        <button onClick={() => onOpen("intake")}>Intake</button>
        <button onClick={() => onOpen("paste")}>Paste</button>
        <button className={view === "teams" ? "on" : ""} onClick={() => onOpen("teams")}>
          {view === "teams" ? "Back to map" : "Teams"}
        </button>
        <button className={weightsOpen ? "on" : ""} onClick={() => onOpen("weights")}>Weights</button>
        <button className={replay?.running ? "on" : ""} onClick={() => onOpen("replay")}>
          {replay?.running ? `Replay ${replay.scenario_time}` : "Replay"}
        </button>
        <button onClick={() => onOpen("chaos")}>Chaos</button>
        <button onClick={() => onOpen("setup")}>Phone setup</button>
      </div>
      <div className="counters">
        <span><b>{snap.summary.open_cases}</b> cases</span>
        <span className={silent ? "warn" : ""}><b>{silent}</b> silent zones</span>
        <span><b>{teams.available ?? 0}</b> teams free</span>
      </div>
      {error && <span className="banner banner-red">{error}</span>}
      {warnings.length > 0 && (
        <div className="warnings" title={warnings.join("\n")}>
          {warnings.slice(0, 2).join(" · ")}{warnings.length > 2 ? ` · +${warnings.length - 2} more` : ""}
        </div>
      )}
    </header>
  );
}
