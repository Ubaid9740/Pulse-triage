import { hhmm, label } from "../format.js";
import Icon from "./Icon.jsx";

// The active alert, its replies and the warning coverage of its zones; during a replay, the
// scenario clock and the latest cue for the presenter.
export default function BottomStrip({ snap, replay }) {
  const alert = snap.alerts.find((a) => a.status === "active") || snap.alerts[0];
  const cue = replay?.running && replay.cues?.[0];
  const cueBox = cue && <span className="cue-now"><Icon name="play" size={12} /><b>{replay.scenario_time}</b> {cue.text}</span>;
  if (!alert) {
    return (
      <footer className="bottom" aria-label="Active alert">
        <span className="bottom-label">Active alert</span>
        <span className="muted">No active alert</span>
        {cueBox}
      </footer>);

  }
  const cov = alert.coverage;
  const pct = cov && cov.coverage !== null ? Math.round(cov.coverage * 100) : null;
  const sev = alert.cancel ? "clear" : alert.severity;
  return (
    <footer className="bottom" aria-label="Active alert">
      <span className="bottom-label">{alert.status === "active" ? "Active alert" : "Last alert"}</span>
      <b className={`alert-tag sev-${sev}`}>
        <Icon name={alert.cancel ? "check" : "bell"} size={13} />
        {alert.cancel ? "ALL CLEAR" : `${label(alert.hazard)} ${alert.severity}`.toUpperCase()}
      </b>
      <span className="bottom-item"><Icon name="mapPin" size={13} />{alert.zones.join(", ")}</span>
      <span className="bottom-item"><Icon name="clock" size={13} />issued {hhmm(alert.issued_at)}</span>
      <span className="bottom-item"><Icon name="message" size={13} />{alert.replies.total} replies</span>
      {pct !== null &&
      <span className={`bottom-cov ${pct < 50 ? "is-low" : ""}`}>
          <span>coverage of registered people</span>
          <span className="mini-bar" aria-hidden="true"><i style={{ width: `${pct}%` }} /></span>
          <b>{pct}%</b>
          <span className="muted">({cov.confirmed} of {cov.registered})</span>
        </span>
      }
      {alert.timeout_at && <span className="bottom-item bottom-timeout">unconfirmed become cases at {hhmm(alert.timeout_at)}</span>}
      {cueBox}
    </footer>);

}