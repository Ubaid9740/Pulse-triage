import { TEAM_COLOURS } from "../format.js";

// Compact map key. Collapsible so it never hides the map on small screens.
export default function MapLegend({ snap }) {
  const silent = snap.zones.filter((z) => z.silent).length;
  return (
    <details className="map-legend" open>
      <summary>Map key</summary>
      <div className="legend-grid">
        <div className="legend-group">
          <h4>Case priority</h4>
          <ul>
            <li><i className="lg-dot tier-high" />70+ points</li>
            <li><i className="lg-dot tier-medium" />40–69 points</li>
            <li><i className="lg-dot tier-low" />Under 40</li>
            <li><i className="lg-dot lg-dashed" />Window closing</li>
          </ul>
        </div>
        <div className="legend-group">
          <h4>Zone · warning coverage</h4>
          <ul>
            <li><i className="lg-zone lg-silent" /><b className="lg-silent-text">Silent Zone{silent ? ` (${silent})` : ""}</b></li>
            <li><i className="lg-zone lg-cov-low" />Under 50%</li>
            <li><i className="lg-zone lg-cov-mid" />50–80%</li>
            <li><i className="lg-zone lg-cov-high" />80%+</li>
            <li><i className="lg-zone lg-hard" />Hard-hit (solid edge)</li>
          </ul>
        </div>
        <div className="legend-group">
          <h4>Places · teams</h4>
          <ul>
            <li><i className="place-icon place-shelter">S</i>Shelter</li>
            <li><i className="place-icon place-cooling">C</i>Cooling centre</li>
            <li><i className="place-icon place-hospital">H</i>Hospital</li>
            <li className="lg-teams">
              <i className="lg-team" style={{ background: TEAM_COLOURS.available }} title="Available">B</i>
              <i className="lg-team" style={{ background: TEAM_COLOURS.en_route }} title="En route">B</i>
              <i className="lg-team" style={{ background: TEAM_COLOURS.on_scene }} title="On scene">B</i>
              <i className="lg-team" style={{ background: TEAM_COLOURS.out_of_service }} title="Out of service">B</i>
              Team: free · en route · on scene · out
            </li>
          </ul>
        </div>
      </div>
    </details>);

}