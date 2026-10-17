"""SQLite storage: one file, WAL mode, one lock so every access is serialised.

JSON fields (conditions, details, reasons, ...) are stored as TEXT and parsed by callers.
Times are ISO 8601 UTC strings; coordinates are WGS84 decimal degrees.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS packets (
    id TEXT PRIMARY KEY, kind TEXT, from_device TEXT, created_at TEXT, received_at TEXT,
    hops INT, body TEXT, sig TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY, pubkey TEXT, role TEXT, trusted INT DEFAULT 0, revoked INT DEFAULT 0,
    first_seen TEXT, last_upload_at TEXT);
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY, packet_id TEXT, case_id INT, source TEXT, hazard TEXT, for_whom TEXT,
    people INT, conditions TEXT, details TEXT, note TEXT, lat REAL, lng REAL, accuracy_m REAL,
    landmark TEXT, device_id TEXT, reporter_role TEXT, reader TEXT, reader_conf REAL,
    created_at TEXT, received_at TEXT);
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY, hazard TEXT, zone TEXT, lat REAL, lng REAL, accuracy_m REAL,
    landmark TEXT, people INT, conditions TEXT, details TEXT, hours_at_report REAL,
    hours_text TEXT, hours_ref_at TEXT, reported_at TEXT, window_closes_at TEXT, points REAL, reasons TEXT,
    confidence REAL, needs TEXT, badges TEXT, status TEXT, team_id TEXT, shelter_id TEXT,
    source TEXT, reader TEXT, report_count INT, note TEXT, verified INT DEFAULT 0,
    last_update TEXT, override TEXT);
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY, hazard TEXT, severity TEXT, zones TEXT, body TEXT, issued_at TEXT,
    valid_until TEXT, replaces TEXT, packet_id TEXT);
CREATE TABLE IF NOT EXISTS alert_replies (
    id TEXT PRIMARY KEY, alert_id TEXT, device_id TEXT, registry_id TEXT, status TEXT,
    lat REAL, lng REAL, at TEXT);
CREATE TABLE IF NOT EXISTS registry (
    id TEXT PRIMARY KEY, name TEXT, zone TEXT, lat REAL, lng REAL, conditions TEXT,
    phone TEXT, consent_at TEXT, confirmed_at TEXT, confirmed_by TEXT);
CREATE TABLE IF NOT EXISTS zones (
    name TEXT PRIMARY KEY, polygon TEXT, population INT, hard_hit INT, expected REAL,
    actual INT, registered INT, confirmed INT, silent INT);
CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY, name TEXT, type TEXT, capabilities TEXT, device_id TEXT, status TEXT,
    status_since TEXT, case_id INT, eta TEXT, lat REAL, lng REAL, ping_at TEXT,
    battery INT, fuel TEXT, load TEXT, flags TEXT, speed_kmh REAL);
CREATE TABLE IF NOT EXISTS team_pings (
    id INTEGER PRIMARY KEY, team_id TEXT, lat REAL, lng REAL, accuracy_m REAL, at TEXT,
    status TEXT, battery INT, fuel TEXT);
CREATE TABLE IF NOT EXISTS team_status_log (
    id INTEGER PRIMARY KEY, team_id TEXT, status TEXT, at TEXT, by TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, case_id INT, team_id TEXT, created_at TEXT, eta TEXT, status TEXT,
    outcome TEXT, packet_id TEXT);
CREATE TABLE IF NOT EXISTS shelters (
    id TEXT PRIMARY KEY, name TEXT, type TEXT, lat REAL, lng REAL, capacity INT,
    occupancy INT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS supplies (
    item TEXT, unit TEXT, place TEXT, qty REAL, warn_at REAL, PRIMARY KEY (item, place));
CREATE TABLE IF NOT EXISTS supply_moves (
    id INTEGER PRIMARY KEY, item TEXT, from_place TEXT, to_place TEXT, qty REAL, at TEXT,
    by TEXT, reason TEXT, job_id TEXT);
CREATE TABLE IF NOT EXISTS outbound (
    seq INTEGER PRIMARY KEY, packet_id TEXT, wire TEXT, to_device TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY, at TEXT, actor TEXT, action TEXT, target TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS ix_packets_device ON packets(from_device, kind, received_at);
CREATE INDEX IF NOT EXISTS ix_reports_case ON reports(case_id);
CREATE INDEX IF NOT EXISTS ix_cases_open ON cases(status, points);
CREATE INDEX IF NOT EXISTS ix_pings_team ON team_pings(team_id, at);
CREATE INDEX IF NOT EXISTS ix_replies ON alert_replies(alert_id);
CREATE INDEX IF NOT EXISTS ix_registry ON registry(zone);
"""

# Columns added after the first release: (table, column, type). Applied to older database files.
MIGRATIONS = [
    ("cases", "hours_ref_at", "TEXT"),
    ("reports", "registry_id", "TEXT"),       # the report is about this registered person
    ("reports", "zone", "TEXT"),              # the zone its position is in
    ("zones", "marked_at", "TEXT"),           # marked hard-hit by the dispatcher or the replay
    ("zones", "hard_hit_since", "TEXT"),
    ("zones", "rate", "REAL"),                # reports per 100 people used for 'expected'
    ("zones", "quiet", "INT"),                # few reports for its size
    ("zones", "unheard", "INT"),              # low warning coverage
    ("zones", "silent_since", "TEXT"),
]
# Indexes on migrated columns, created after the migrations.
LATE_INDEXES = """
CREATE INDEX IF NOT EXISTS ix_reports_registry ON reports(registry_id);
CREATE INDEX IF NOT EXISTS ix_reports_zone ON reports(zone);
"""


def setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    """Read a setting inside an open connection (Database.get_setting takes the lock itself)."""
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return default if row is None else json.loads(row[0])


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)
            for table, column, kind in MIGRATIONS:
                have = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")}
                if column not in have:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
            self._conn.executescript(LATE_INDEXES)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def all(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def scalar(self, sql: str, params: tuple | dict = ()) -> Any:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            return row[0] if row else None

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Several reads under the lock, with no transaction and no revision bump."""
        with self._lock:
            yield self._conn

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """One transaction. Bumps the snapshot revision so the dashboard sees a change."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute(
                    "INSERT INTO settings(key, value) VALUES('rev', '1') "
                    "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1")
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def get_setting(self, key: str, default: Any = None) -> Any:
        value = self.scalar("SELECT value FROM settings WHERE key = ?", (key,))
        return default if value is None else json.loads(value)

    def set_setting(self, key: str, value: Any) -> None:
        with self.write() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)))

    def rev(self) -> int:
        value = self.scalar("SELECT value FROM settings WHERE key = 'rev'")
        return int(value) if value is not None else 0
