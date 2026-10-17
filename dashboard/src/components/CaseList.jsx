import { caseTitle, hoursLeft, label, pointsColour } from "../format.js";

// The ranked list: highest points first, as the server sorts them.
export default function CaseList({ cases, onSelect }) {
  if (!cases.length) {
    return <div className="empty">No open cases. New reports appear here within 2 seconds.</div>;
  }
  return (
    <ol className="case-list">
      {cases.map((c, i) => (
        <li key={c.id}>
          <button className="case-row" onClick={() => onSelect(c.id)}>
            <span className="rank">#{i + 1}</span>
            <span className="points" style={{ background: pointsColour(c.points) }}>{c.points}</span>
            <span className="row-main">
              <span className="row-title">{caseTitle(c)}</span>
              <span className="row-sub">
                {label(c.hazard)} · {c.people} {c.people === 1 ? "person" : "people"}
                {c.hours_left !== null && <> · {hoursLeft(c.hours_left)} left</>}
                {c.status !== "new" && <> · {label(c.status)}</>}
              </span>
            </span>
            <span className="row-badges">
              {c.badges.map((b) => <span key={b} className={`badge badge-${b.replace(/\s/g, "-")}`}>{b}</span>)}
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}
