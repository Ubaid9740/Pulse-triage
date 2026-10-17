# server/: command server

FastAPI + SQLite, one process, runs on the command-post laptop with no internet.

## Run

From the repo root (Windows):

```
server\.venv\Scripts\activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir server
```

Keys are created in `server/keys/` on first start; the database is `server/pulsetriage.db`.
Copy `.env.example` to `.env` to change settings. So phones can reach the laptop, allow the port once
(administrator prompt):

```
netsh advfirewall firewall add rule name="PulseTriage 8000" dir=in action=allow protocol=TCP localport=8000
```

Optional public route for online phones away from the command post (laptop needs internet):
`cloudflared tunnel --url http://localhost:8000`, then set `PT_PUBLIC_URL` and restart.

## Test

```
cd server
python -m pytest
```

## Endpoints built so far

| Call | What it does |
| --- | --- |
| `GET /api/status` | Health; phones use it to decide online or offline |
| `GET /api/setup-qr`, `/api/setup-qr.png` | Server addresses, command post keys, server time |
| `GET /api/profiles` | Hazard profiles for the dashboard and phones |
| `POST /api/packets` | Upload up to 100 wire packets; returns accepted, duplicate, rejected (with reason) |
| `GET /api/outbound?since=&device=` | Alerts, jobs and revocations after a cursor |
| `GET /api/snapshot` | Everything the dashboard shows |
| `GET /api/cases/{id}` | One case with every merged report and its history (`case_detail.schema.json`) |
| `POST /api/cases/{id}/verify` `{"by"}` | Dispatcher confirmed it: confidence 1.0, status `verified` |
| `POST /api/cases/{id}/split` `{"report_id", "by"}` | Undo a wrong merge; the report starts its own case |
| `POST /api/devices/{id}/trust` `{"trusted", "by"}` | Known helper or team phone; its open cases are rescored |
| `POST /api/settings/hazard` `{"hazard", "by"}` | Change the active hazard profile |
| `POST /api/zones/import?by=` | Replace the zones with a GeoJSON file (`zones.schema.json`) |
| `GET /api/zones` | Every zone with its Silent Zone numbers (`zone.schema.json`) |
| `POST /api/zones/hard-hit` `{"zones", "hard_hit", "by"}` | Mark zones inside the hazard extent, or clear them |
| `GET /api/zones/{name}` | Zone card: the numbers, the outreach list, the zone task (`zone_card.schema.json`) |
| `POST /api/zones/{name}/task` `{"by"}` | "Send welfare-check team": one open zone task per zone |
| `POST /api/registry/import?by=` | Add or update registered people from CSV (body `text/csv`) |
| `GET /api/coverage` | Warning coverage per zone, alert timeouts, the outreach list (`coverage.schema.json`) |
| `POST /api/alerts` | Issue, update (`replaces`) or end (`replaces` + `cancel`) an alert; signs and queues it |
| `POST /api/alerts/preview` | The payload `POST /api/alerts` would send, for the composer; nothing is queued |
| `GET /api/alerts`, `/api/alerts/{id}` | Alerts with status, replies and coverage (`alert_summary.schema.json`) |
| `POST /api/announcement` `{"alert_id", "languages"}` | Loudspeaker and radio script, about 20 s (`announcement.schema.json`) |
| `GET /api/teams`, `POST /api/teams` | Teams (`team.schema.json`); add one or change its details, position, fuel |
| `POST /api/teams/{id}/status` `{"status", "reason", "by"}` | Set a status by hand, e.g. after a radio call |
| `GET /api/suggest?case_id=` | Best team, alternatives, trade-off, teams about to be free, place (`suggestion.schema.json`) |
| `GET /api/suggest/all` | Each unassigned case, down the ranked list, with its fastest free team (each team once) |
| `POST /api/assign` `{"case_id", "team_id", "place", "reassign", "eta_min"}` | Confirm a team: makes the job, signs it, queues it for the team's phone |
| `GET /api/shelters`, `POST /api/shelters` | Shelters and cooling centres; head count updates (`shelter.schema.json`) |
| `GET /api/supplies`, `POST /api/supplies` `{"item", "warn_at", "unit"}` | Stock, use and run-out per item (`supply.schema.json`); set the warning level |
| `POST /api/supplies/move` `{"kind", "item", "qty", "from", "to"}` | restock, load, unload, deliver, transfer or used |
| `GET /api/resources/summary` | Team counters and warnings (overdue, none free, low stock, nearly full) |
| `GET /api/devices` | Phones heard from, with trust, revocation and team |
| `POST /api/devices/{id}/revoke` `{"revoked", "reason", "by"}` | Refuse a phone (e.g. stolen) and send phones the signed list; `revoked: false` restores it |
| `GET /api/demo/packs`, `POST /api/demo/reset` `{"pack"}` | Demo packs in `scenario/packs/`; reset a running server to one |
| `GET /docs` | Interactive API docs |

Reject reasons: `invalid_wire`, `too_big`, `invalid_body`, `bad_signature`, `unsigned`, `not_allowed`,
`expired`, `revoked`, `pubkey_mismatch`, `rate_limited`, `cannot_unseal`, `bad_payload`, `invalid_payload`.

## Development switches

`PT_REQUIRE_SIGNATURES` and `PT_REQUIRE_SEALING` default to off, so the phone app can start with
unsigned, plain-base64 packets. Switch both on once the app signs and seals (build hours 28 to 33).

## Scripts

- `scripts/make_keys.py [--force]`: create or rotate the command post keys
- `scripts/send_example.py report report_heat [--unsigned] [--plain]`: send examples like a phone
- `scripts/reset_demo.py --pack flood` (server stopped) or `--pack heat --keep-server` (server
  running), `--list`: end the incident and load a pack (see below)
- `scripts/backup.py [--to E:\pulsetriage]`, `--list`, `--restore [FILE]` (server stopped): backups

## Demo reset, backups, revoking

A pack is `scenario/packs/<name>/`: `pack.json` (`{"hazard": "flood", "hard_hit": ["Ward 4"]}`),
`zones.geojson` (or `scenario/zones.geojson`), and optionally `registry.csv`, `shelters.json`
and `teams.json` (lists of `POST /api/shelters` and `POST /api/teams` bodies) and `supplies.json`
(`[{"item", "qty", "place", "warn_at", "unit"}]`). Every file is checked before anything is
cleared. A reset clears the incident (cases, reports, alerts, zones, registry, teams, jobs,
places, supplies, audit log) and keeps what phones rely on: the keys (no new setup QR), the
devices and their trust (revocations are lifted), the packets already seen (so a phone still
carrying rehearsal packets cannot bring them back), the outbound sequence and the alert and job
numbers. The old database is backed up first.

The scheduler backs up the database every 5 minutes to `backups/` (SQLite backup API) and keeps
the newest 24; `/api/status` shows `last_backup`. To take over on a second laptop: copy the
`keys/` folder and the newest backup, `backup.py --restore`, start the server, give it the same
IP on the router. `backup.py --restore` and `reset_demo.py` without `--keep-server` refuse while
a server answers on `PT_PORT`.

A revoked phone's packets are refused at once. Each revoke packet carries the full list
(`replace_key` "revoke"), so phones keep only the newest and stop relaying for those phones.

## How cases are built

Each report is stored, then joins the closest open case that is within 150 m (or has the same
landmark), within 3 hours, the same hazard (or "other"), within 2 people, and shares a condition or
a key word. Otherwise it starts a new case. The case is then rebuilt from all its reports and
rescored: points = time + can't-save-themselves + window + people, times trust
`0.6 + 0.4 x confidence`. Every part is one line of `reasons`. The scheduler rescores every 30 s, so
hours left and confidence change even without new reports. All numbers are in
`shared/constants.json` (System Design 9.1 to 9.4).

Worked examples, checked by the tests: house 14 from two phones = 69 points (confidence 0.75);
heatstroke from a trusted volunteer = 66 (0.8); the same volunteer before being trusted = 60.

## Silent Zones and warning coverage

Load the town first: `POST /api/zones/import` with `scenario/zones.geojson` (each feature needs
`name` and `population`), then `POST /api/registry/import` with the registry CSV
(`shared/examples/registry.csv` shows the columns; rows without `consent_at` are skipped). Every
report is placed in the zone its position falls in.

A zone is hard-hit when it is marked (`POST /api/zones/hard-hit`, by the dispatcher or the replay),
or, for heat (`"affected": "alert_zones"`), when an active heat alert covers it. A hard-hit zone is
Silent when it has under a quarter of the reports expected for its size (at least 8 expected;
the rate is the median reports per 100 people of the other hard-hit zones), or when under 25% of
its registered vulnerable people (at least 10) have confirmed. Ward 4 example: 2,000 people at a
median 1.2 per 100 = 24 expected, 2 received, 9 of 41 confirmed: Silent.

A registered person is confirmed by an alert reply, a welfare check, or a report that names them
(`registry_id`). When an alert is older than 30 min (emergency) or 2 h (warning), everyone in its
zones who has not confirmed since it was issued becomes an "unconfirmed" case at confidence 0.3.
A report naming that person joins the same case and its trust replaces the 0.3; a "safe" reply
or welfare check closes it. A zone task scores 60 points + 1 per registered person, capped at 90.

An update keeps the clock of the alert it replaces: for each zone, waiting and confirmations
count from the first alert in the chain that covered it.

## Alerts

`POST /api/alerts` with `hazard`, `severity` (`watch`, `warning`, `emergency`) and `zones` is
enough: the headline and three steps come from the hazard profile's template (send `fill` for
placeholders such as `{start}` and `{end}`, or write `headline` and `do_now` yourself), places
default to the nearest shelters with space (cooling centres for heat), and it is valid for 12 h.

```
{"hazard": "heat", "severity": "warning", "zones": ["Ward 4", "Old Market"],
 "fill": {"start": "12:00", "end": "17:00"}}
{"replaces": "A-0001", "severity": "emergency"}     update: anything left out is kept
{"replaces": "A-0002", "cancel": true}              all-clear, worded from common.json
```

Each alert is signed with the command post key and queued for `GET /api/outbound` at urgency 4,
with `replace_key` `alert:<first alert ID>` so relays keep only the newest version; the packet
expires with the alert. The scheduler marks alerts past `valid_until` as expired. The
announcement frame (intro, places, pass it on, repeat) is per language in `common.json`; if a
script runs past 20 s the closing repeat is left out.

## Teams, suggestions and supplies

A team comes from `POST /api/teams` (the scenario's teams) or from a phone's volunteer packet,
which links the phone to the team of that name or makes a new one. Pings and acks count only
from the phone linked to a team. What a team can do comes from its type and its crew's skills
(`constants.json` teams.capabilities_*); anyone can do a welfare check.

```
available -> assigned (POST /api/assign) -> en_route (ack) -> on_scene (ping within 100 m, or ack
"arrived") -> returning (ack "done" + outcome) -> available (ack "ready", or a ping back at base)
```

"Done" closes the case, adds the people to the place they were taken to, and takes the supplies
used off the team's load. "Can't reach" and "out of service" put the case back in the queue. A
late ack never moves a team backwards. The scheduler flags a team overdue at ETA + 50% of the
travel time (at least 10 min) and not heard from after 15 min without a ping while en route.

Suggestions use teams that are available, not low on fuel, can do everything the case needs, and
carry or can fetch from the command post the supplies the case needs (profile `supply_rules`;
items nobody has entered yet do not block). Travel = distance x 1.4 / speed: a boat 1.5 km away
takes about 13 min. The trade-off checks the top 10 cases: "Boat 2 is also best for case #1. If
it goes here, #1 waits about 7 more min (next best: Boat 3)". A team on scene for more than 10 of
its expected 20 minutes shows as soon free. A job goes only to the team's phone (`to_device`); a
team without a phone gets a "tell them by radio" warning.

Supplies sit at `command_post`, `shelter:<id>` and `team:<id>`. Left is the sum; the burn rate
is "used" over the last 3 hours.

## Code map

`app/main.py` routes · `config.py` settings · `db.py` schema and storage · `crypto.py` keys, signing,
sealing · `schemas.py` shared-schema validation · `profiles.py` profile rules · `ingest.py` the packet
pipeline · `merge.py` duplicate rules · `scoring.py` points, confidence, badges · `cases.py` attach,
rebuild, rescore, verify, split, trust · `zones.py` zone shapes, the Silent Zone test, zone tasks ·
`coverage.py` registry, confirmations, warning coverage, alert timeouts · `alerts.py` create, update,
cancel, expire and announce alerts · `teams.py` team tracker: setup, pings, acks, arrival,
outcome, overdue · `suggest.py` suggestions, trade-off, assign and job packets · `supplies.py`
shelters, stock, moves, burn rate · `scheduler.py` alert expiry, timeouts, rescoring, zones and
team checks every 30 s · `outbound.py` the queue to phones · `snapshot.py` the dashboard
snapshot · `packets.py` packet and geohash helpers · `devtools.py` phone-side packet builder
(reference for the app).

`devices.py` the phones and revoking · `backups.py` database copies and restore · `demo.py` the
reset per pack.

The server steps of System Design 14.5 (B1 to B7) are built. Still open: the AI reader
(`reader.py`), the call-taker intake and paste box, case overrides and weights, `scripts/purge.py`.
