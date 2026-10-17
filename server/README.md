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
| `GET /docs` | Interactive API docs |

Reject reasons: `invalid_wire`, `too_big`, `invalid_body`, `bad_signature`, `unsigned`, `not_allowed`,
`expired`, `revoked`, `pubkey_mismatch`, `rate_limited`, `cannot_unseal`, `bad_payload`, `invalid_payload`.

## Development switches

`PT_REQUIRE_SIGNATURES` and `PT_REQUIRE_SEALING` default to off, so the phone app can start with
unsigned, plain-base64 packets. Switch both on once the app signs and seals (build hours 28 to 33).

## Scripts

- `scripts/make_keys.py [--force]`: create or rotate the command post keys
- `scripts/send_example.py report report_heat [--unsigned] [--plain]`: send examples like a phone

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

## Code map

`app/main.py` routes · `config.py` settings · `db.py` schema and storage · `crypto.py` keys, signing,
sealing · `schemas.py` shared-schema validation · `profiles.py` profile rules · `ingest.py` the packet
pipeline · `merge.py` duplicate rules · `scoring.py` points, confidence, badges · `cases.py` attach,
rebuild, rescore, verify, split, trust · `scheduler.py` background rescoring · `outbound.py` the queue
to phones · `snapshot.py` the dashboard snapshot · `packets.py` packet and geohash helpers ·
`devtools.py` phone-side packet builder (reference for the app).

Next: `zones.py`, `coverage.py`, `alerts.py`, `suggest.py`, `teams.py`, `supplies.py`
(System Design 14.5).
