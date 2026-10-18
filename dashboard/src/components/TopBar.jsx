import { useState } from "react";
import { post } from "../api.js";
import { label } from "../format.js";
import Icon from "./Icon.jsx";

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
      <div className="topbar-main">
        <div className="brand">
          <span className="brand-mark"><Icon name="activity" size={18} /></span>
          <span className="brand-text"><b>PulseTriage</b><span>Command</span></span>
        </div>

        <label className="hazard">
          <span className="hazard-label">Disaster</span>
          <select value={snap.hazard} onChange={(e) => switchHazard(e.target.value)}>
            {hazards.map((h) =>
            <option key={h} value={h}>{profiles?.profiles[h]?.label?.en || label(h)}</option>
            )}
          </select>
        </label>

        <div className="conn" role="status">
          {offline ?
          <span className="status status-offline"><Icon name="wifiOff" size={14} />Server not reachable: showing the last update</span> :

          <span className="status status-online"><span className="pulse-dot" aria-hidden="true" />Live</span>
          }
          {!offline && snap.status.banner &&
          <span className="status status-fallback"><Icon name="type" size={14} />{snap.status.banner}</span>
          }
        </div>

        {warnings.length > 0 ?
        <div className="warnings" title={warnings.join("\n")}>
            <Icon name="alert" size={14} />
            <span>{warnings.slice(0, 2).join(" · ")}{warnings.length > 2 ? ` · +${warnings.length - 2} more` : ""}</span>
          </div> :
        <div className="warnings-spacer" />}

        <div className="counters">
          <span className="counter-item"><b>{snap.summary.open_cases}</b><span>open cases</span></span>
          <span className={`counter-item ${silent ? "warn" : ""}`}>
            {silent > 0 && <Icon name="silent" size={14} />}<b>{silent}</b><span>silent zones</span>
          </span>
          <span className="counter-item"><b>{teams.available ?? 0}</b><span>teams free</span></span>
        </div>
      </div>

      <nav className="toolbar" aria-label="Dashboard actions">
        <div className="tool-group">
          <button className="btn btn-primary" onClick={() => onOpen("alert")}><Icon name="megaphone" />New alert</button>
          <button className="btn" onClick={() => onOpen("intake")}><Icon name="phone" />Intake</button>
          <button className="btn" onClick={() => onOpen("paste")}><Icon name="clipboard" />Paste</button>
        </div>
        <span className="tool-sep" aria-hidden="true" />
        <div className="tool-group">
          <button className={`btn ${view === "teams" ? "on" : ""}`} aria-pressed={view === "teams"} onClick={() => onOpen("teams")}>
            <Icon name={view === "teams" ? "map" : "users"} />{view === "teams" ? "Back to map" : "Teams"}
          </button>
          <button className={`btn ${weightsOpen ? "on" : ""}`} aria-pressed={weightsOpen} onClick={() => onOpen("weights")}>
            <Icon name="sliders" />Weights
          </button>
        </div>
        {error && <span className="toolbar-error" role="alert"><Icon name="alert" size={14} />{error}</span>}
        <div className="tool-group tool-demo">
          <span className="tool-label">Demo</span>
          <button className={`btn btn-quiet ${replay?.running ? "on" : ""}`} onClick={() => onOpen("replay")}>
            <Icon name="play" />{replay?.running ? `Replay ${replay.scenario_time}` : "Replay"}
          </button>
          <button className="btn btn-quiet" onClick={() => onOpen("chaos")}><Icon name="zap" />Chaos</button>
          <button className="btn btn-quiet" onClick={() => onOpen("setup")}><Icon name="qr" />Phone setup</button>
        </div>
      </nav>
    </header>);

}