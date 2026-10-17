# dashboard/: dispatcher dashboard (owner: C)

React + Vite + react-leaflet, plain CSS, built to static files that the server serves at `/`.

## Run

```
cd dashboard
npm install
npm run build        # writes dist/; the server then serves it at http://localhost:8000/
npm run dev          # while building: http://localhost:5173, API proxied to the server on :8000
```

To see data: with the server running, `python server/scripts/reset_demo.py --pack flood --keep-server`
(the Karachi flood pack) then `python scenario/demo_reports.py` (15 reports from phones).

## What is built (System Design 6, Team Brief C1 and C2)

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
- **New alert** (top bar): a new alert, an update or an all-clear for an active one; disaster,
  severity, valid until, zones (hard-hit ticked), template placeholders such as start and end,
  places (or the nearest with space). Headline and steps are filled by `POST /api/alerts/preview`,
  so the phone preview beside the form is exactly what phones get; the text stays editable. After
  sending, "Generate announcement script" shows the loudspeaker text and its length.
- **Intake**: the report form built from the chosen disaster's questions in the profiles, the
  conditions, a free-text note (read for anything not ticked), landmark, caller's number, registry
  ID; shows the case it made or joined and opens it.
- **Paste**: a box for forwarded messages and an optional disaster for unclear ones; lists the
  reports made (with their case), the ones already seen and the chatter skipped.

Base map: if `public/tiles/town.pmtiles` exists (the scenario provides it), the map uses it through
protomaps-leaflet and nothing loads from the internet. Without it, the map shows OpenStreetMap's
street tiles (online, no key; the credit stays in the corner, as their tile policy asks). With
neither (no file, no internet) the zones and pins sit on a plain background and everything still works.
For a Karachi map that works offline, cut `town.pmtiles` from a Protomaps build (`pmtiles extract`
with `--bbox=66.9,24.75,67.3,25.05`).

## Next (System Design 14.5, C)

- C3: Teams and resources tab (counters, team table, status with a reason, supplies table and moves),
  WeightsPanel, ChaosPanel, SetupQR.
