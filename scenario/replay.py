"""Play a scenario pack into a running server (the same replay as the dashboard's Replay button).

    python scenario/replay.py --pack flood --speed 60          # reset to the pack, then play it
    python scenario/replay.py --pack heat --no-reset
    python scenario/replay.py --status
    python scenario/replay.py --stop

The server streams scenario/packs/<pack>/messages.json in itself (server/app/replay.py), so this
script only starts it and prints the scenario clock and the presenter's cues until the story ends
(Ctrl+C leaves it playing; --stop ends it). Build the packs first: python scenario/generate.py
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def call(server: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(server + path, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        sys.exit(f"{path}: {exc.code} {exc.read().decode(errors='replace')}")
    except urllib.error.URLError as exc:
        sys.exit(f"No server answers at {server} ({exc.reason}). Start it first.")


def line(s: dict) -> str:
    clock = s.get("scenario_time", "--:--")
    held = f", {s['held_replies']} replies waiting for an alert" if s.get("held_replies") else ""
    return f"[{clock}] {s.get('done', 0)}/{s.get('total', 0)} events{held}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Play a scenario pack into the server.")
    parser.add_argument("--pack", default="flood")
    parser.add_argument("--speed", type=float, help="scenario minutes per real minute (the pack's default if not given)")
    parser.add_argument("--no-reset", action="store_true", help="play on top of what the server has now")
    parser.add_argument("--server", default="http://localhost:8000")
    parser.add_argument("--status", action="store_true", help="show the replay's status and exit")
    parser.add_argument("--stop", action="store_true", help="stop the replay and exit")
    args = parser.parse_args()

    if args.stop:
        print(line(call(args.server, "/api/demo/replay/stop", {})), "stopped")
        return
    if args.status:
        print(json.dumps(call(args.server, "/api/demo/replay"), indent=1))
        return
    body = {"pack": args.pack, "reset": not args.no_reset}
    if args.speed:
        body["speed"] = args.speed
    s = call(args.server, "/api/demo/replay", body)
    print(f"Playing {s['pack']} at {s['speed']:g}x from {s['start']} ({s['total']} events). Ctrl+C leaves it playing.")
    seen = 0
    try:
        while True:
            time.sleep(2)
            s = call(args.server, "/api/demo/replay")
            cues = list(reversed(s.get("cues", [])))
            for c in cues[seen:] if len(cues) > seen else []:
                print(f"  {c['at']}  {c['text']}")
            seen = len(cues)
            for e in s.get("errors", [])[:1]:
                print("  error:", e)
            if s.get("story_done") or not s.get("running"):
                print(line(s), "- story done; teams keep moving until --stop" if s.get("running") else "- stopped")
                return
    except KeyboardInterrupt:
        print("\n" + line(s), "- still playing on the server")


if __name__ == "__main__":
    main()
