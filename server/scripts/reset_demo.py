"""Reset the server to a demo pack (System Design 14.8).

    python server/scripts/reset_demo.py --pack flood                  # server stopped
    python server/scripts/reset_demo.py --pack heat --keep-server     # server running: through its API
    python server/scripts/reset_demo.py --list

Packs are folders in scenario/packs/ (see app/demo.py for the files). The keys, devices and
seen packets are kept, so phones carry on without a new setup QR. The old database is backed up.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.net import server_answers  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", help="pack name, e.g. flood or heat")
    parser.add_argument("--keep-server", action="store_true", help="reset a running server through its API")
    parser.add_argument("--list", action="store_true", help="list the packs")
    parser.add_argument("--server", help="server URL (default http://127.0.0.1:<PT_PORT>)")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    url = (args.server or f"http://127.0.0.1:{settings.port}").rstrip("/")

    if args.list:
        folder = settings.scenario_dir / "packs"
        packs = sorted(p.name for p in folder.iterdir() if (p / "pack.json").exists()) if folder.exists() else []
        print("\n".join(packs) if packs else f"No packs in {folder}")
        return 0
    if not args.pack:
        parser.error("--pack is needed (or --list)")

    if args.keep_server:
        if not server_answers(url):
            print(f"No server answers at {url}. Start it, or leave out --keep-server.", file=sys.stderr)
            return 1
        req = urllib.request.Request(f"{url}/api/demo/reset", method="POST",
                                     data=json.dumps({"pack": args.pack, "by": "reset_demo"}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                out = json.loads(resp.read())
        except urllib.error.HTTPError as err:
            print(f"Reset refused: {json.loads(err.read()).get('detail')}", file=sys.stderr)
            return 1
    else:
        if server_answers(url):
            print(f"The server at {url} is running. Stop it first, or use --keep-server.", file=sys.stderr)
            return 1
        from app.main import create_app        # imported here: it is slow and not needed for --keep-server
        ctx = create_app(settings).state.ctx
        try:
            out = ctx.demo.reset(args.pack, "reset_demo")
        except (ValueError, LookupError) as exc:
            print(f"Reset refused: {exc}", file=sys.stderr)
            return 1
        finally:
            ctx.db.close()
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
