import { hhmm, label } from "../format.js";

// The active alert, its replies and the warning coverage of its zones; during a replay, the
// scenario clock and the latest cue for the presenter.
export default function BottomStrip({ snap, replay }) {
  const alert = snap.alerts.find((a) => a.status === "active") || snap.alerts[0];
  const cue = replay?.running && replay.cues?.[0];
  const cueBox = cue && <span className="cue-now"><b>{replay.scenario_time}</b> {cue.text}</span>;
  if (!alert) return <footer className="bottom">{cueBox}No active alert</footer>;
  const cov = alert.coverage;
  return (
    <footer className="bottom">
      {cueBox}
      <b>{alert.cancel ? "ALL CLEAR" : `${label(alert.hazard)} ${alert.severity}`.toUpperCase()}</b>
      <span>{alert.zones.join(", ")}</span>
      <span>issued {hhmm(alert.issued_at)}</span>
      <span>{alert.replies.total} replies</span>
      {cov && cov.coverage !== null && (
        <span>coverage of registered people: <b>{Math.round(cov.coverage * 100)}%</b> ({cov.confirmed} of {cov.registered})</span>
      )}
      {alert.timeout_at && <span>unconfirmed become cases at {hhmm(alert.timeout_at)}</span>}
    </footer>
  );
}
