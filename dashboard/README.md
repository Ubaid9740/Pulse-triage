# dashboard/: dispatcher dashboard (owner: C)

React + Vite + react-leaflet, plain CSS, built to static files that the server serves at `/`.

## Run

```
cd dashboard
npm install
npm run build        # writes dist/; the server then serves it at http://localhost:8000/
npm run dev          # while building: http://localhost:5173, API proxied to the server on :8000
```

To see data, run the server and `python server/scripts/send_example.py report report_heat`, or reset
to a scenario pack (`python server/scripts/reset_demo.py --pack flood`).

## What is built (System Design 6, Team Brief C1)

- **Polling**: `App.jsx` fetches `GET /api/snapshot` every 2 s into one state object; commands POST
  and refresh at once. A failed poll keeps the last snapshot and the top bar says "Server not reachable".
- **Top bar**: disaster selector (`POST /api/settings/hazard`), the AI offline banner, counters
  (cases, silent zones, teams free), the first warnings.
- **Map** (60%): zones outlined (solid when hard-hit), filled by warning coverage, red when silent;
  case pins red 70+, orange 40-69, yellow under 40, sized by people, dashed when a window closes
  soon; teams by type letter and status colour, grey when their position is over 10 min old, a line
  to their case and their last positions; places with head count / capacity. Click a pin or a zone.
- **Ranked list** (40%): rank, points, place, people, time left, badges.
- **Case card**: every reason with its points, subtotal, the trust line, override, total; badges,
  needs, reader; buttons Verified, Override (points or status, reason required), Suggest team (best,
  alternatives, trade-off, soon free, place; Assign), Split per report; history.
- **Zone card**: the explanation lines, coverage bar, "Send welfare-check team" (zone task), mark or
  clear hard-hit, and the outreach list (medical needs first, then people alone).
- **Bottom strip**: the active alert, replies, coverage and when unconfirmed people become cases.

Offline base map: put `town.pmtiles` in `public/tiles/` (the scenario provides it); the map uses it
through protomaps-leaflet if present, and shows the zones on a plain background if not. Nothing loads
from the internet.

## Next (System Design 14.5, C)

- C2: AlertComposer (templates, zones, places, phone preview, announcement), IntakeForm, PasteBox.
- C3: Teams and resources tab (counters, team table, status with a reason, supplies table and moves),
  WeightsPanel, ChaosPanel, SetupQR.
