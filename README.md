# PulseTriage

Disaster warning and triage for any disaster type, built to keep working with no internet.
CODE//CONNECT'26, Problem 01. Design: `System Design.pdf` and `PulseTriage-Team-Brief.pdf` (one folder up).

| Folder | What | Owner |
| --- | --- | --- |
| `shared/` | The contract: formats (JSON Schemas), examples, hazard profiles, constants | Everyone |
| `server/` | Command server: FastAPI + SQLite on the command-post laptop | B |
| `dashboard/` | Dispatcher dashboard: React + Vite + Leaflet | C |
| `field/` | Field app: Flutter, Android only | A |
| `scenario/` | Demo packs, replay, simulation | D |

## Quick start (server)

Windows, from this folder:

```
python -m venv server\.venv
server\.venv\Scripts\activate
pip install -r server\requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir server
```

Open http://localhost:8000. Then, in a second terminal (venv active), send example reports like a phone would:

```
python server\scripts\send_example.py report report_heat
```

They appear at http://localhost:8000/api/snapshot. Tests: `cd server` then `python -m pytest`.

## Ground rules

- `shared/` is sacred. Change it only after telling the whole team; then run the server tests and the Flutter contract test.
- Never hard-code a disaster. If code says "water" or "heat", it belongs in `shared/profiles/`.
- Every number lives in `shared/constants.json`.
- `main` always runs. Commit small, clear changes; tag versions that demo well (`git tag demo-v1`).
- Never commit `server/keys/`, `.env`, databases or build folders (see `.gitignore`).

## Status

Built: shared formats, examples, profiles (common, flood, heat, earthquake), server skeleton
(packet ingest with signatures and sealing, outbound queue, snapshot, setup QR) and the server core:
duplicate reports merge into cases, every case has priority points with readable reasons and a
confidence score, the scheduler rescores as time passes, and the dispatcher can verify, split and
trust. Zones, the opt-in registry, warning coverage and Silent Zones: unconfirmed registered people
become cases after an alert's timeout, and a quiet hard-hit zone turns red with a zone task.
Alerts: issued from templates, updated, ended with an all-clear, signed and queued for phones,
with a loudspeaker script. Teams: setup from the phone, pings and acks, automatic arrival,
outcome, overdue flags; suggestions with the trade-off; assign with a signed job for the team's
phone; shelters and supplies with burn rate and low-stock warnings.

Operations: revoking a stolen phone, backups every 5 minutes with restore, and a demo reset per
scenario pack that keeps phones working.

Intake form, paste box with the offline keyword reader, overrides with a reason, and tunable
weights.

Still open on the server: the AI reader and the data purge script.
