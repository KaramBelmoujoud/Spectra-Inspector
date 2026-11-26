"""Last-resort error reporting.

Under pythonw (run.bat) there is no console, so an unhandled exception or a
native crash would otherwise vanish without a trace. Everything goes to
%LOCALAPPDATA%\\Spectra\\spectra.log, and Python errors also to the Log tab
(through ``sink``) instead of being lost.
"""
from __future__ import annotations

import faulthandler
import os
import sys
import threading
import time
import traceback
from typing import Callable, Optional

sink: Optional[Callable[[str], None]] = None  # set by the main window: shows text in the Log tab
_file = None


def log_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Spectra", "spectra.log")


def write(text: str):
    line = time.strftime("%Y-%m-%d %H:%M:%S  ") + text.rstrip() + "\n"
    if _file is not None:
        try:
            _file.write(line)
            _file.flush()
        except Exception:  # noqa: BLE001
            pass
    if sink is not None:
        try:
            sink(text.rstrip())
        except Exception:  # noqa: BLE001
            pass


def _excepthook(etype, value, tb):
    write("Unhandled error:\n" + "".join(traceback.format_exception(etype, value, tb)))


def _thread_excepthook(args):
    name = args.thread.name if args.thread else "?"
    write(f"Unhandled error in thread {name}:\n" +
          "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))


def install():
    global _file
    try:
        path = log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > 2_000_000:
            os.replace(path, path + ".old")
        _file = open(path, "a", encoding="utf-8", buffering=1)
        _file.write(f"\n===== Spectra started {time.strftime('%Y-%m-%d %H:%M:%S')} (pid {os.getpid()}) =====\n")
        faulthandler.enable(_file, all_threads=True)  # native crashes leave a Python stack here
    except OSError:
        _file = None
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
