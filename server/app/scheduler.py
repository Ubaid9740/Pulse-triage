"""Background jobs, every server.scheduler_s seconds (System Design 5.4).

Hours left shrink and confidence decays as time passes, so points must be recomputed even
when no new report arrives. Later steps add coverage timeouts, zones, team checks and supplies.
"""
from __future__ import annotations

import logging
import threading

from .cases import CaseBook

log = logging.getLogger("pulsetriage.scheduler")


class Scheduler:
    def __init__(self, cases: CaseBook, constants: dict):
        self.cases = cases
        self.interval_s = constants["server"]["scheduler_s"]
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> None:
        try:
            self.cases.rescore_all()
        except Exception:  # a bad row must not stop the loop; it is logged and retried next run
            log.exception("scheduler run failed")

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
