"""Delete the incident's personal data, keeping anonymous counts (System Design 10.4).

    python server/scripts/purge.py                  # dry run: what would go, and the counts kept
    python server/scripts/purge.py --yes            # do it (server stopped)
    python server/scripts/purge.py --yes --keep-backups

Writes server/after_action/after-action-<time>.json first (counts only), then deletes reports,
cases, the registry, replies, pings, jobs, raw packets, devices, supply moves, the audit log and
the AI cache, clears team positions and phones, vacuums the database, and deletes the backups
(they hold the same data). This cannot be undone.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import SERVER_DIR, Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.net import server_answers  # noqa: E402
from app.purge import after_action, planned, purge  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="really delete (without it, a dry run)")
    parser.add_argument("--keep-backups", action="store_true", help="do not delete the backups")
    parser.add_argument("--report-dir", type=Path, default=SERVER_DIR / "after_action")
    parser.add_argument("--server", help="server URL to check (default http://127.0.0.1:<PT_PORT>)")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    url = args.server or f"http://127.0.0.1:{settings.port}"
    if not settings.db_path.exists():
        print(f"No database at {settings.db_path}.", file=sys.stderr)
        return 1
    if server_answers(url):
        print(f"The server at {url} is running. Stop it first.", file=sys.stderr)
        return 1
    db = Database(settings.db_path)
    try:
        if not args.yes:
            print("Dry run. Rows that would be deleted:")
            print(json.dumps(planned(db), indent=2))
            print("Counts that would be kept:")
            print(json.dumps(after_action(db), indent=2))
            backups = list(settings.backups_dir.glob("*.db")) if settings.backups_dir.exists() else []
            print(f"{len(backups)} backups would be {'kept' if args.keep_backups else 'deleted'}. "
                  "Run again with --yes to purge.")
            return 0
        out = purge(db, args.report_dir, None if args.keep_backups else settings.backups_dir)
    finally:
        db.close()
    print(json.dumps(out, indent=2))
    print(f"Purged. Anonymous counts kept in {out['after_action']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
