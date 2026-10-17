"""Database backups (System Design 11.4).

The scheduler copies the database every server.backup_minutes to backups/ with the SQLite
backup API (a consistent copy, safe while the server runs) and keeps the newest
server.backups_kept. scripts/backup.py makes one on demand, copies it to a USB stick, or puts
one back in place. A second laptop with the same keys can take over: restore the newest
backup, start the server, give it the same IP address on the router.
"""
from __future__ import annotations

import shutil
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import timeutil
from .db import Database

PREFIX = "pulsetriage-"


def copy_database(src: Path, dest: Path) -> None:
    """Copy a database file that may be in use, without writing to it."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"{src.resolve().as_uri()}?mode=ro", uri=True)
    target = sqlite3.connect(dest)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def restore_database(backup: Path, db_path: Path) -> Path | None:
    """Put a backup in place of the database (the server must be stopped). The current database
    is kept next to it as *.replaced.db first. Returns that file, if there was one."""
    if not backup.exists():
        raise FileNotFoundError(backup)
    kept = None
    if db_path.exists():
        kept = db_path.with_name(f"{db_path.stem}-{timeutil.now().strftime('%Y%m%d-%H%M%S')}.replaced.db")
        copy_database(db_path, kept)
    for extra in (db_path, db_path.with_name(db_path.name + "-wal"), db_path.with_name(db_path.name + "-shm")):
        extra.unlink(missing_ok=True)
    shutil.copyfile(backup, db_path)
    return kept


class Backups:
    def __init__(self, db: Database, folder: Path, constants: dict):
        self.db = db
        self.folder = Path(folder)
        self.every = timedelta(minutes=constants["server"]["backup_minutes"])
        self.kept = constants["server"]["backups_kept"]
        self._lock = threading.Lock()
        self._last: datetime | None = None

    def run(self, now: datetime | None = None) -> Path | None:
        """The scheduler job: a backup when the last one is older than server.backup_minutes."""
        now = now or timeutil.now()
        if self._last is not None and now - self._last < self.every:
            return None
        return self.make(now)

    def make(self, now: datetime | None = None, label: str = "") -> Path:
        now = now or timeutil.now()
        with self._lock:
            name = f"{PREFIX}{now.strftime('%Y%m%d-%H%M%S')}{'-' + label if label else ''}.db"
            path = self.folder / name
            self.db.backup_to(path)
            self._last = now
            for old in self.files()[self.kept:]:
                old.unlink(missing_ok=True)
        return path

    def files(self) -> list[Path]:
        """Newest first."""
        if not self.folder.exists():
            return []
        return sorted(self.folder.glob(f"{PREFIX}*.db"), key=lambda p: p.name, reverse=True)

    def latest(self) -> str | None:
        """When the newest backup was made (from its name), for /api/status."""
        files = self.files()
        if not files:
            return None
        stamp = files[0].name[len(PREFIX):len(PREFIX) + 15]
        return timeutil.iso(datetime.strptime(stamp, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc))
