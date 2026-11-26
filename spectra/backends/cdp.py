"""Minimal, thread-safe Chrome DevTools Protocol client.

Works with any Chromium browser (Chrome, Edge, Brave, Opera, Electron apps,
WebView2 hosts) started with ``--remote-debugging-port``. No browser
extension is involved.
"""
from __future__ import annotations

import itertools
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import urllib.request
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Callable, Dict, List, Optional

import websocket  # websocket-client

_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class CdpError(RuntimeError):
    pass


def http_json(host: str, port: int, path: str, timeout: float = 2.0, method: str = "GET"):
    req = urllib.request.Request(f"http://{host}:{port}{path}", method=method)
    with _NO_PROXY.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "null")


def port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    """Quick TCP check. On Windows a refused connection to a closed local port
    only fails after ~2 s of retries, so a short timeout matters."""
    if host in ("127.0.0.1", "localhost", "::1"):
        timeout = min(timeout, 0.3)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe(host: str = "127.0.0.1", port: int = 9222, timeout: float = 0.6) -> Optional[dict]:
    """Return /json/version for a debugging endpoint, or None."""
    if not port_open(host, port, timeout):
        return None
    try:
        return http_json(host, port, "/json/version", timeout)
    except Exception:  # noqa: BLE001
        return None


def list_targets(host: str, port: int) -> List[dict]:
    return http_json(host, port, "/json/list") or []


class CdpConnection:
    """One websocket to one DevTools target."""

    def __init__(self, ws_url: str, timeout: float = 10.0):
        self.ws_url = ws_url
        self.timeout = timeout
        self._ids = itertools.count(1)
        self._pending: Dict[int, Future] = {}
        self._listeners: List[Callable[[str, dict], None]] = []
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self.ws = websocket.create_connection(
            ws_url, timeout=timeout, suppress_origin=True, enable_multithread=True,
            http_no_proxy=["127.0.0.1", "localhost", "::1"])
        self.ws.settimeout(None)
        self.closed = False
        self._reader = threading.Thread(target=self._read_loop, name="cdp-reader", daemon=True)
        self._reader.start()

    def on_event(self, fn: Callable[[str, dict], None]):
        self._listeners.append(fn)

    def _read_loop(self):
        while not self.closed:
            try:
                raw = self.ws.recv()
            except Exception:  # noqa: BLE001
                break
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if "id" in msg:
                with self._lock:
                    fut = self._pending.pop(msg["id"], None)
                if fut is not None:
                    if "error" in msg:
                        fut.set_exception(CdpError(msg["error"].get("message", str(msg["error"]))))
                    else:
                        fut.set_result(msg.get("result", {}))
            elif "method" in msg:
                for fn in list(self._listeners):
                    try:
                        fn(msg["method"], msg.get("params", {}))
                    except Exception:  # noqa: BLE001
                        pass
        self.closed = True
        with self._lock:
            pending, self._pending = self._pending, {}
        for fut in pending.values():
            if not fut.done():
                fut.set_exception(CdpError("connection closed"))

    def send(self, method: str, params: Optional[dict] = None, timeout: Optional[float] = None) -> dict:
        if self.closed:
            raise CdpError("connection closed")
        mid = next(self._ids)
        fut: Future = Future()
        with self._lock:
            self._pending[mid] = fut
        payload = json.dumps({"id": mid, "method": method, "params": params or {}})
        with self._send_lock:
            self.ws.send(payload)
        try:
            return fut.result(timeout or self.timeout)
        except (FutureTimeout, TimeoutError):
            with self._lock:
                self._pending.pop(mid, None)
            raise CdpError(f"{method} timed out") from None

    def evaluate(self, expression: str, timeout: Optional[float] = None):
        r = self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                            "awaitPromise": True}, timeout)
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            text = d.get("exception", {}).get("description") or d.get("text")
            raise CdpError(f"script error: {text}")
        return r.get("result", {}).get("value")

    def close(self):
        self.closed = True
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ launching

BROWSER_CANDIDATES = {
    "Chrome": [r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
               r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
               r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
               "google-chrome", "chromium", "chromium-browser"],
    "Edge": [r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
             r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe", "microsoft-edge"],
    "Brave": [r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
              r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe"],
}


def find_browser(name: str) -> Optional[str]:
    for cand in BROWSER_CANDIDATES.get(name, []):
        path = os.path.expandvars(cand)
        if os.path.isabs(path):
            if os.path.isfile(path):
                return path
        else:
            found = shutil.which(path)
            if found:
                return found
    return None


def installed_browsers() -> Dict[str, str]:
    return {n: p for n in BROWSER_CANDIDATES if (p := find_browser(n))}


def launch_browser(exe: str, port: int = 9222, url: str = "about:blank",
                   profile_dir: Optional[str] = None, extra: Optional[List[str]] = None) -> subprocess.Popen:
    """Start a browser with the debugging port open.

    Recent Chrome versions refuse remote debugging on the default profile, so a
    separate profile folder is used (it persists, so sign-ins are kept).
    """
    profile_dir = profile_dir or os.path.join(tempfile.gettempdir(), f"spectra-browser-profile-{port}")
    os.makedirs(profile_dir, exist_ok=True)
    args = [exe, f"--remote-debugging-port={port}", f"--user-data-dir={profile_dir}",
            "--no-first-run", "--no-default-browser-check", "--force-renderer-accessibility"]
    args += extra or []
    args.append(url)
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(args, creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
