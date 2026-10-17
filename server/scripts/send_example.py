"""Send shared example packets to a running server, signed and sealed like a phone would.

    python server/scripts/send_example.py report report_heat --server http://localhost:8000
    python server/scripts/send_example.py report --unsigned --plain   # development formats

Each run makes fresh packet IDs and times, so the server accepts them as new reports.
The fake phone's signing key is kept in server/keys/dev_phone.key.
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nacl.signing import SigningKey  # noqa: E402

from app.config import SHARED_DIR, Settings  # noqa: E402
from app.crypto import b64d, b64e  # noqa: E402
from app.devtools import load_example, phone_wire  # noqa: E402


def dev_key() -> SigningKey:
    path = Settings.from_env().keys_dir / "dev_phone.key"
    if path.exists():
        return SigningKey(b64d(path.read_text().strip()))
    key = SigningKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(b64e(bytes(key)))
    return key


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read())


def main() -> None:
    parser = argparse.ArgumentParser(description="Send example packets to the server.")
    parser.add_argument("examples", nargs="+", help="names in shared/examples, e.g. report report_heat")
    parser.add_argument("--server", default="http://localhost:8000")
    parser.add_argument("--device", default="dev_DEMO1")
    parser.add_argument("--unsigned", action="store_true", help="send without a signature")
    parser.add_argument("--plain", action="store_true", help="send the payload as plain base64, not sealed")
    args = parser.parse_args()

    box_pk = None if args.plain else get_json(f"{args.server}/api/setup-qr")["box_pk"]
    key = None if args.unsigned else dev_key()
    wires = []
    for name in args.examples:
        ex = load_example(SHARED_DIR, name)
        body = ex["body"]
        if body["kind"] in ("alert", "job", "revoke"):
            sys.exit(f"{name}: only the server makes {body['kind']} packets")
        wires.append(phone_wire(body["kind"], ex["payload"], device_id=args.device, signing_key=key,
                                box_pk=box_pk, urgency=body["urgency"], area=body["area"],
                                replace_key=body.get("replace_key")))
    req = urllib.request.Request(f"{args.server}/api/packets", data=json.dumps({"packets": wires}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(json.dumps(json.loads(resp.read()), indent=2))


if __name__ == "__main__":
    main()
