"""Database backups (System Design 11.4). The server also makes one every 5 minutes.

    python server/scripts/backup.py                       # a backup now, into server/backups/
    python server/scripts/backup.py --to E:\\pulsetriage    # ... and a copy there (a USB stick)
    python server/scripts/backup.py --list
    python server/scripts/backup.py --restore [FILE]      # server stopped: put a backup in place (default: newest)

Taking over on a second laptop: copy the keys folder and the newest backup, run --restore,
start the server, and give the laptop the same IP address on the router.
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import timeutil  # noqa: E402
from app.backups import PREFIX, copy_database, restore_database  # noqa: E402
from app.config import Settings  # noqa: E402
from app.net import server_answers  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--to", type=Path, help="also copy the backup into this folder")
    parser.add_argument("--list", action="store_true", help="list the backups")
    parser.add_argument("--restore", nargs="?", const="newest", metavar="FILE", help="put a backup in place")
    parser.add_argument("--server", help="server URL to check (default http://127.0.0.1:<PT_PORT>)")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    folder = settings.backups_dir
    files = sorted(folder.glob(f"{PREFIX}*.db"), key=lambda p: p.name, reverse=True) if folder.exists() else []

    if args.list:
        for f in files:
            print(f"{f.name}  {f.stat().st_size // 1024} KB")
        print(f"{len(files)} backups in {folder}")
        return 0

    if args.restore:
        url = args.server or f"http://127.0.0.1:{settings.port}"
        if server_answers(url):
            print(f"The server at {url} is running. Stop it first.", file=sys.stderr)
            return 1
        source = files[0] if args.restore == "newest" and files else Path(args.restore)
        if args.restore == "newest" and not files:
            print(f"No backups in {folder}.", file=sys.stderr)
            return 1
        kept = restore_database(source, settings.db_path)
        print(f"Restored {source} to {settings.db_path}." + (f" The old database is kept as {kept.name}." if kept else ""))
        return 0

    if not settings.db_path.exists():
        print(f"No database at {settings.db_path}.", file=sys.stderr)
        return 1
    path = folder / f"{PREFIX}{timeutil.now().strftime('%Y%m%d-%H%M%S')}-manual.db"
    copy_database(settings.db_path, path)
    print(f"Backed up to {path}")
    if args.to:
        args.to.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, args.to / path.name)
        print(f"Copied to {args.to / path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
