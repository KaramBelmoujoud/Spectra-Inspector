"""One background thread that owns every automation call.

UI Automation COM objects, tree walks and selector searches can block for a
long time when a target app hangs; running them here keeps the GUI
responsive. Requests with the same ``coalesce`` key replace older pending
ones (used for hover picking).
"""
from __future__ import annotations

import queue
import sys
import threading
import traceback
from typing import Callable, Optional


class Job:
    __slots__ = ("fn", "on_done", "on_error", "key", "cancelled")

    def __init__(self, fn, on_done, on_error, key):
        self.fn, self.on_done, self.on_error, self.key = fn, on_done, on_error, key
        self.cancelled = False


class Driver(threading.Thread):
    def __init__(self, init: Optional[Callable[[], None]] = None):
        super().__init__(name="spectra-driver", daemon=True)
        self._q: "queue.Queue[Job]" = queue.Queue()
        self._latest = {}
        self._lock = threading.Lock()
        self._init = init
        self.init_error: Optional[str] = None
        self.ready = threading.Event()

    def run(self):
        if sys.platform == "win32":
            sys.coinit_flags = 0  # COINIT_MULTITHREADED for comtypes imported on this thread
        if self._init:
            try:
                self._init()
            except Exception:  # noqa: BLE001
                self.init_error = traceback.format_exc()
        self.ready.set()
        while True:
            job = self._q.get()
            if job is None:
                return
            if job.cancelled:
                continue
            try:
                result = job.fn()
            except Exception as e:  # noqa: BLE001
                if job.on_error:
                    job.on_error(e, traceback.format_exc())
                continue
            if job.on_done and not job.cancelled:
                job.on_done(result)

    def submit(self, fn: Callable, on_done: Optional[Callable] = None, on_error: Optional[Callable] = None,
               coalesce: Optional[str] = None) -> Job:
        job = Job(fn, on_done, on_error, coalesce)
        if coalesce:
            with self._lock:
                old = self._latest.get(coalesce)
                if old is not None:
                    old.cancelled = True
                self._latest[coalesce] = job
        self._q.put(job)
        return job

    def call(self, fn: Callable, timeout: float = 30.0):
        """Run fn on the driver thread and wait for the result."""
        if threading.current_thread() is self:
            return fn()
        done = threading.Event()
        box = {}

        def ok(r):
            box["r"] = r
            done.set()

        def err(e, tb):
            box["e"] = e
            done.set()

        self.submit(fn, ok, err)
        if not done.wait(timeout):
            raise TimeoutError("driver call timed out")
        if "e" in box:
            raise box["e"]
        return box.get("r")

    def stop(self):
        self._q.put(None)
