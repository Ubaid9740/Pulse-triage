# field/: Field app (owner: A)

React Native with Expo (SDK 58), Android first. We switched from Flutter so the app runs with only
Node installed: no Android SDK is needed to try it. Phones send straight to the command post when
they can reach it, and otherwise keep every message and pass it on to the next phone (System
Design Part 4).

## Run it on a phone (no Android SDK)

1. Install **Expo Go** from the Play Store on an Android phone on the same Wi-Fi as the laptop.
2. On the laptop:
   ```
   cd field
   npm install
   npx expo start
   ```
3. Scan the QR code that `expo start` prints with Expo Go. The app opens; edits reload live.
4. In the app, pick a role and scan the dashboard's **Phone setup** QR (or type the laptop's
   address, e.g. `http://192.168.1.20:8000`).

`npx expo start --web` previews the screens in a browser (development only: no camera, GPS or
secure key storage there).

## Screens (Team Brief 3.5)

| Screen | What it does | Sends |
| --- | --- | --- |
| Setup | Role (helper, volunteer, rescue team), name, skills, team type; scan the setup QR or type the address. Makes the phone's Ed25519 keys (kept in secure storage). | `volunteer` for teams |
| Home | Latest alert, the red "Report someone who needs help" button, jobs, status line (connected or not, messages waiting, last sync) | |
| Alert | Severity band, headline, 3 steps, places to go, Read aloud, I'm safe / I need help / I'm helping others, pass it on, safety tips. Only alerts signed by the command post are shown; new ones buzz. | `alert_reply` |
| Report | What's happening (preset from the alert), for whom, how many, conditions, the disaster's own questions (from the profiles), note, landmark, GPS. Saved at once, even with no signal. | `report` |
| Welfare check | Registry ID or place; Safe, Needs help, Not found | `welfare_check` |
| Jobs | The signed job for this phone: distance, ETA, conditions, first aid; On my way, Arrived (also automatic within 100 m), Done with the outcome, Can't reach; fuel, Ready, Out of service; position pings every 2 min on a job, 10 min idle (while the app is open) | `ack`, `team_ping` |
| Mesh and QR | What the phone carries; Show QR and Scan QR to pass messages phone to phone | |
| Settings | Device ID, servers, set up again | |

## How it works

`src/core/` is plain JavaScript shared by the app and the Node tests:

| File | What |
| --- | --- |
| `packet.js` | Wire packets exactly as the server checks them: Ed25519 signature of the body text, libsodium sealed box (X25519 + BLAKE2b nonce) of the payload, geohash, device ID |
| `rules.js` | The profile rules (hours to critical, urgency hint for send order, questions) |
| `store.js` | The packet store: keeps what this phone made until the server has it, drops expired relayed packets, newest per `replace_key`, capped |
| `mesh.js` | The phone-to-phone protocol (hello / have / want / packets / done, 30 KB batches), independent of the transport; QR encoding |
| `sync.js` | Server checks (online after 1 good check, offline after 2 bad), upload, then alerts and jobs after the cursor, verified against the command post key |
| `payloads.js` | One builder per packet kind, matching `shared/schemas/payloads/` |

`src/shell/AppState.js` holds the settings, keys, store and timers (sync every 10 s offline, 30 s
online). `src/profiles/` is a copy of `shared/profiles` (`npm run profiles` refreshes it).

## Tests

`npm test` runs the core against a real server with signatures and sealing required. From the
repo root, in one terminal:

```
PT_REQUIRE_SIGNATURES=1 PT_REQUIRE_SEALING=1 PT_AI=off PT_PORT=8011 server/.venv/Scripts/python.exe -m uvicorn app.main:app --port 8011 --app-dir server
```

then reset it to a pack (`python server/scripts/reset_demo.py --pack flood --keep-server --server http://127.0.0.1:8011`)
and run `npm test` in `field/`. It checks: geohash and rules match the server; sealed boxes and
signatures; a report goes straight in; an offline phone's report reaches the server through a
second phone (hops 1); signed alerts arrive and forged ones are dropped; an "I'm safe" reply; a
team phone joins, gets its signed job, goes on scene by ping and finishes with an outcome.

## Not done yet: automatic Bluetooth relay

Phone-to-phone relay without QR codes needs a native module (Nearby Connections, or BLE), which
Expo Go cannot load. The protocol is ready (`src/core/mesh.js`: give `MeshSession` a `send`
function and feed it the peer's messages); what is missing is the transport:

1. Add a Nearby Connections or BLE module and make a development build with EAS
   (`npx expo install expo-dev-client`, then `eas build --profile development --platform android`;
   EAS builds in the cloud, so no Android SDK is needed here, only a free Expo account).
2. Advertise and discover with service ID `pulsetriage`; on connect run `MeshSession.start()`, pass
   each received JSON message to `onMessage`, disconnect when `finished`.

Until then the QR hand-off on the Mesh and QR screen carries messages between phones, one signed
packet per code. A dev or release build that talks to `http://` addresses also needs cleartext
traffic allowed (expo-build-properties `android.usesCleartextTraffic`); Expo Go already allows it.
