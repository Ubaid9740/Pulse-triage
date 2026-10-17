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
| `GET /docs` | Interactive API docs |

Reject reasons: `invalid_wire`, `too_big`, `invalid_body`, `bad_signature`, `unsigned`, `not_allowed`,
`expired`, `revoked`, `pubkey_mismatch`, `rate_limited`, `cannot_unseal`, `bad_payload`, `invalid_payload`.

## Development switches

`PT_REQUIRE_SIGNATURES` and `PT_REQUIRE_SEALING` default to off, so the phone app can start with
unsigned, plain-base64 packets. Switch both on once the app signs and seals (build hours 28 to 33).

## Scripts

- `scripts/make_keys.py [--force]`: create or rotate the command post keys
- `scripts/send_example.py report report_heat [--unsigned] [--plain]`: send examples like a phone

## Code map

`app/main.py` routes · `config.py` settings · `db.py` schema and storage · `crypto.py` keys, signing,
sealing · `schemas.py` shared-schema validation · `profiles.py` profile rules · `ingest.py` the packet
pipeline · `outbound.py` the queue to phones · `snapshot.py` the dashboard snapshot · `packets.py` packet
and geohash helpers · `devtools.py` phone-side packet builder (reference for the app).

Next: `merge.py`, `scoring.py`, `zones.py`, `coverage.py`, `alerts.py`, `suggest.py`, `teams.py`,
`supplies.py`, `scheduler.py` (System Design 14.5).
