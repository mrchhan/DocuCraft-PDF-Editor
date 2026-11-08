"""Background jobs: heavy work runs on a thread pool; callbacks are delivered on the GUI thread."""
from __future__ import annotations

import traceback
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from core.errors import DocuCraftError, OperationCancelled
from core.pdf_organizer import CancelToken
from services.logging_service import get_logger

log = get_logger("jobs")


class JobSignals(QObject):
    progress = Signal(int, str)
    finished = Signal(object)
    failed = Signal(object)
    cancelled = Signal()
    done = Signal()


class Job(QRunnable):
    """`fn(progress, cancel)` -> result. `progress(pct, msg)`; `cancel()` -> bool."""

    def __init__(self, name: str, fn: Callable):
        super().__init__()
        self.name, self.fn, self.token = name, fn, CancelToken()
        self.signals = JobSignals()
        self.setAutoDelete(False)

    def cancel(self) -> None:
        self.token.cancel()

    def run(self) -> None:
        try:
            result = self.fn(lambda pct, msg="": self.signals.progress.emit(int(pct), str(msg)), self.token.cancelled)
            self.signals.finished.emit(result)
        except OperationCancelled:
            self.signals.cancelled.emit()
        except BaseException as exc:                      # never let a worker thread die silently
            if isinstance(exc, DocuCraftError):
                log.warning("Job '%s' failed: %s %s", self.name, exc.user_message, exc.detail)
            else:
                log.error("Job '%s' crashed:\n%s", self.name, traceback.format_exc())
            self.signals.failed.emit(exc)
        finally:
            self.signals.done.emit()


class _Relay(QObject):
    """Lives on the GUI thread so that callbacks run there (queued connections)."""

    def __init__(self, on_progress, on_finished, on_failed, on_cancelled, on_done, owner):
        super().__init__()
        self._cb, self._owner = (on_progress, on_finished, on_failed, on_cancelled, on_done), owner

    @Slot(int, str)
    def progress(self, pct, msg):
        self._cb[0] and self._cb[0](pct, msg)

    @Slot(object)
    def finished(self, r):
        self._cb[1] and self._cb[1](r)

    @Slot(object)
    def failed(self, e):
        self._cb[2] and self._cb[2](e)

    @Slot()
    def cancelled(self):
        self._cb[3] and self._cb[3]()

    @Slot()
    def done(self):
        self._cb[4] and self._cb[4]()
        self._owner._release(self)


class JobManager(QObject):
    jobsChanged = Signal(int)                            # number of active jobs

    def __init__(self, max_jobs: int = 2):
        super().__init__()
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(max(1, max_jobs))
        self._jobs: dict[_Relay, Job] = {}

    def set_max_jobs(self, n: int) -> None:
        self.pool.setMaxThreadCount(max(1, n))

    @property
    def active_count(self) -> int:
        return len(self._jobs)

    def submit(self, name: str, fn: Callable, *, on_progress=None, on_finished=None, on_failed=None,
               on_cancelled=None, on_done=None) -> Job:
        job = Job(name, fn)
        relay = _Relay(on_progress, on_finished, on_failed, on_cancelled, on_done, self)
        s = job.signals
        s.progress.connect(relay.progress); s.finished.connect(relay.finished); s.failed.connect(relay.failed)
        s.cancelled.connect(relay.cancelled); s.done.connect(relay.done)
        self._jobs[relay] = job
        self.jobsChanged.emit(len(self._jobs))
        self.pool.start(job)
        return job

    def _release(self, relay: _Relay) -> None:
        self._jobs.pop(relay, None)
        self.jobsChanged.emit(len(self._jobs))

    def cancel_all(self) -> None:
        for j in list(self._jobs.values()):
            j.cancel()

    def wait(self, ms: int = 30000) -> bool:
        return self.pool.waitForDone(ms)
