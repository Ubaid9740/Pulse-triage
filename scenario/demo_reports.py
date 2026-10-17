"""Send a pack's demo reports to a running server, signed and sealed like phones would.

    python server/scripts/reset_demo.py --pack flood --keep-server
    python scenario/demo_reports.py --pack flood --server http://localhost:8000

Reads scenario/packs/<pack>/reports.json: a list of report payloads (as in
shared/examples/report.json) plus "device" (the phone that sent it) and "minutes_ago" (when).
Each phone keeps the same key from run to run, so the server knows it after the first time.
Run it after a reset: run twice and every report arrives again as a new one.
"""
import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from nacl.signing import SigningKey  # noqa: E402

from app import timeutil  # noqa: E402
from app.devtools import phone_wire  # noqa: E402
from app.packets import geohash  # noqa: E402


def call(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a pack's demo reports.")
    parser.add_argument("--pack", default="flood")
    parser.add_argument("--server", default="http://localhost:8000")
    args = parser.parse_args()

    pack = ROOT / "scenario" / "packs" / args.pack
    hazard = json.loads((pack / "pack.json").read_text(encoding="utf-8"))["hazard"]
    reports = json.loads((pack / "reports.json").read_text(encoding="utf-8"))
    box_pk = call(f"{args.server}/api/setup-qr")["box_pk"]
    now = timeutil.now()
    wires = []
    for r in sorted(reports, key=lambda r: -r["minutes_ago"]):
        payload = {"hazard": hazard, "reporter_role": "helper", "gps_accuracy_m": 20, "contact": "",
                   **{k: v for k, v in r.items() if k not in ("device", "minutes_ago")}}
        # A demo key per phone, the same every run (never use this for a real phone).
        key = SigningKey(hashlib.sha256(f"pulsetriage-demo:{r['device']}".encode()).digest())
        urgency = 3 if payload["details"].get("trapped") or payload["details"].get("water") in ("chest", "roof") else 2
        wires.append(phone_wire("report", payload, device_id=r["device"], signing_key=key, box_pk=box_pk,
                                urgency=urgency, area=geohash(payload["lat"], payload["lng"], 5),
                                created=now - timedelta(minutes=r["minutes_ago"])))
    out = call(f"{args.server}/api/packets", {"packets": wires})
    results = out.get("results", out)
    print(f"sent {len(wires)} reports from {pack.name}:", json.dumps(results)[:400])


if __name__ == "__main__":
    main()
