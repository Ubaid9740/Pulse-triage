"""Background jobs, every server.scheduler_s seconds (System Design 5.4).

Hours left shrink and confidence decays as time passes, so points must be recomputed even
when no new report arrives. Each run: alerts past valid_until end, coverage timeouts
(unconfirmed registered people become cases), rescoring, then zones (hard-hit by alerts,
expected vs actual, the Silent flag), team checks (overdue, not heard from), and a database
backup every server.backup_minutes, and the AI health check every ai.health_check_s.
"""
from __future__ import annotations

import logging
import threading

from .ai_reader import AIReader
from .alerts import AlertBook
from .backups import Backups
from .cases import CaseBook
from .coverage import Coverage
from .teams import TeamBook
from .zones import ZoneBook

log = logging.getLogger("pulsetriage.scheduler")


class Scheduler:
    def __init__(self, cases: CaseBook, coverage: Coverage, zones: ZoneBook, alerts: AlertBook, teams: TeamBook,
                 backups: Backups, ai: AIReader, constants: dict):
        self.jobs = [("alerts", alerts.expire), ("coverage timeouts", coverage.timeouts),
                     ("rescore", cases.rescore_all), ("zones", zones.update), ("teams", teams.checks),
                     ("backup", backups.run), ("ai health", ai.check)]
        self.interval_s = constants["server"]["scheduler_s"]
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> None:
        for name, job in self.jobs:
            try:
                job()
            except Exception:  # one failing job must not stop the others; it is logged and retried next run
                log.exception("scheduler job %r failed", name)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        self.run_once()
        while not self._stop.wait(self.interval_s):
            self.run_once()
