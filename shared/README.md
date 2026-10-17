# shared/: the contract

Everything the phone app, server and dashboard must agree on. Change nothing here without telling the team.

| Path | What |
| --- | --- |
| `constants.json` | Every tunable number (System Design, Appendix A) |
| `schemas/wire.schema.json` | What travels between phones and to the server |
| `schemas/body.schema.json` | The signed packet body |
| `schemas/payloads/<kind>.schema.json` | The payload inside each kind of packet |
| `schemas/case.schema.json`, `snapshot.schema.json` | What the dashboard reads from `GET /api/snapshot` |
| `schemas/case_detail.schema.json` | One case with its reports and history (`GET /api/cases/{id}`) |
| `schemas/zone.schema.json`, `zone_card.schema.json`, `coverage.schema.json` | Zones in the snapshot, the zone card, warning coverage |
| `schemas/zones.schema.json` | The zones file the scenario provides (`scenario/zones.geojson`) |
| `schemas/alert_summary.schema.json`, `announcement.schema.json` | Alerts in the snapshot and `GET /api/alerts`; the loudspeaker script |
| `schemas/setup_qr.schema.json` | What phones scan at setup |
| `schemas/profile.schema.json` | Hazard profile format |
| `profiles/*.json` | `common` plus one file per disaster: questions, rules, keywords, tips, alert templates |
| `examples/*.json` | One valid example per packet kind, plus a snapshot and a setup QR |
| `examples/zones.geojson`, `examples/registry.csv` | A three-zone town and a three-person registry, in the import formats |

## How a phone builds a packet

`server/app/devtools.py` (`phone_wire`) is the reference implementation.

1. Make the payload (`schemas/payloads/<kind>.schema.json`) and encode it as compact UTF-8 JSON.
2. Seal it: `base64(libsodium crypto_box_seal(payload, box_pk))`, where `box_pk` comes from the setup QR.
   While sealing is switched off in development, the server also accepts `base64(payload)`.
3. Make the body (`schemas/body.schema.json`): `v`, `id` (UUID v4), `kind`, `from_device`, `pubkey`,
   `created_at`, `expires_at` (+24 h), `max_hops` (12), `area` (5-letter geohash), `urgency`, `sealed`.
4. Encode the body as JSON text **once**. Sign the UTF-8 bytes of that text with the phone's Ed25519 key.
5. Send `{"body": <that text>, "sig": <base64 signature>, "hops": 0}`. Relays only ever change `hops`.
   While signatures are switched off in development, `sig` and `pubkey` may be empty.

Alerts, jobs and revocations are made only by the command post: readable `public` payload, signed with
`sign_pk` from the setup QR. Phones must ignore any that don't verify.

## Profile rule tokens

`x` yes/no answer is yes · `!x` it is no or missing · `x:a|b` answer is a or b (multi: contains a or b) ·
`cond:a|b` the person has condition a or b. A rule matches when all its tokens match; `[]` always matches.
Hours to critical = the smallest `hours` among matching rules in `common.json` and the hazard's profile
(24 if none). The server checks every token against real questions, options and conditions at start-up.

## Checks

`cd server` then `python -m pytest tests/test_contracts.py` validates every example, schema and profile.
The Flutter app should run the same check on `examples/` (see `field/README.md`).
