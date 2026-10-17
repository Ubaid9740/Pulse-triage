# field/: Field app (owner: A)

Flutter, Android only. Phones send straight to the server when they can reach it, and relay phone to
phone (Nearby Connections) only when they can't. System Design Part 4.

## Start (hour 0)

From the repo root, with Flutter and Android Studio installed:

```
flutter create --org com.pulsetriage --platforms android field
cd field
flutter pub add nearby_connections permission_handler sqflite path geolocator
flutter pub add flutter_tts qr_flutter mobile_scanner pinenacl uuid http connectivity_plus
flutter run
```

(`flutter create` into this folder keeps this README.) Copy `../shared/profiles/*.json` into
`assets/profiles/` and list them under `flutter: assets:` in `pubspec.yaml`.

## The contract

- Packet format, signing and sealing: `../shared/README.md`; the Python reference is
  `../server/app/devtools.py` (`phone_wire`).
- Add a test (`test/packet_test.dart`) that loads every file in `../shared/examples/`, builds a packet
  from it, and checks the fields match `../shared/schemas/`.
- Until signing and sealing are built, send `sig: ""`, `pubkey: ""` and `sealed: base64(payload JSON)`;
  the server accepts these while its development switches are off.
- Check your packets against a running server: they appear at `http://<laptop-ip>:8000/api/snapshot`.

Build order and prompts: System Design 14.5 (A) and Team Brief 4.10 (A1 to A5).
