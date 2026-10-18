import { caseTitle, hhmm, hoursLeft, label, pointsTier } from "../format.js";
import Badge from "./Badge.jsx";
import Icon from "./Icon.jsx";

// The ranked list: highest points first, as the server sorts them.
export default function CaseList({ cases, onSelect }) {
  return (
    <section className="queue" aria-label="Ranked rescue cases">
      <header className="pane-head">
        <div>
          <h2>Rescue queue</h2>
          <p>{cases.length} open · ranked by priority points</p>
        </div>
        <span className="live-chip"><span className="pulse-dot" aria-hidden="true" />Auto-refresh</span>
      </header>
      {!cases.length ?
      <div className="empty">No open cases. New reports appear here within 2 seconds.</div> :

      <ol className="case-list">
          {cases.map((c, i) => {
          const tier = pointsTier(c.points);
          const urgent = c.hours_left !== null && c.hours_left !== undefined && c.hours_left < 1;
          return (
            <li key={c.id}>
                <button className={`case-row row-${tier}`} onClick={() => onSelect(c.id)}>
                  <span className="rank">{i + 1}</span>
                  <span className={`points tier-${tier}`} aria-label={`${c.points} points`}>{c.points}</span>
                  <span className="row-main">
                    <span className="row-top">
                      <span className="row-title">{caseTitle(c)}</span>
                      {c.badges.length > 0 &&
                    <span className="row-badges">{c.badges.map((b) => <Badge key={b} text={b} />)}</span>
                    }
                    </span>
                    <span className="row-sub">
                      <span className="meta-hazard">{label(c.hazard)}</span>
                      {c.landmark && c.zone && <span><Icon name="mapPin" size={12} />{c.zone}</span>}
                      <span><Icon name="users" size={12} />{c.people} {c.people === 1 ? "person" : "people"}</span>
                      {c.hours_left !== null &&
                    <span className={urgent ? "meta-urgent" : ""}><Icon name="clock" size={12} />{hoursLeft(c.hours_left)} left</span>
                    }
                      {c.window_closes_at && <span className="meta-urgent">window closes {hhmm(c.window_closes_at)}</span>}
                      {c.status !== "new" && <span className="meta-status">{label(c.status)}</span>}
                    </span>
                    {c.note && <span className="row-note">{c.note}</span>}
                  </span>
                </button>
              </li>);

        })}
        </ol>
      }
    </section>);

}