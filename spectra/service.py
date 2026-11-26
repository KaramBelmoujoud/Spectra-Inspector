"""Wires the back ends together and answers "what element is at this point?".

Everything here runs on the driver thread.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Dict, List, Optional, Tuple

from .backends.web import WebBackend, WebPage
from .core.engine import Engine
from .core.node import Backend, Node

IS_WIN = sys.platform == "win32"


class Service:
    def __init__(self):
        self.engine = Engine()
        self.web = WebBackend()
        self.engine.register(self.web)
        self.uia = None
        self.java = None
        self.errors: Dict[str, str] = {}
        self.own_pid = os.getpid()
        self.prefer_web = True
        self.prefer_java = True
        self.extra_backends: List[Backend] = []  # added by plugins (spectra.plugins ctx.add_backend)
        self._metrics: Dict[str, Tuple[float, dict]] = {}

    def init(self):
        if not IS_WIN:
            self.errors["uia"] = "UI Automation needs Windows"
            self.errors["java"] = "Java Access Bridge needs Windows"
            return
        from .backends import win32
        win32.enable_dpi_awareness()
        try:
            from .backends.uia import UiaBackend
            self.uia = UiaBackend()
            self.engine.register(self.uia)
        except Exception as e:  # noqa: BLE001
            self.errors["uia"] = f"{type(e).__name__}: {e}"
        try:
            from .backends.jab import JavaBackend
            jb = JavaBackend()
            ok, err = jb.available()
            if ok:
                self.java = jb
                self.engine.register(jb)
            else:
                self.errors["java"] = err
        except Exception as e:  # noqa: BLE001
            self.errors["java"] = f"{type(e).__name__}: {e}"
        self.web.screen_mapper = self.page_screen_origin

    # ------------------------------------------------------------ browser <-> screen
    def metrics(self, page: WebPage, max_age: float = 1.0) -> Optional[dict]:
        cached = self._metrics.get(page.target_id)
        if cached and time.monotonic() - cached[0] < max_age:
            return cached[1]
        try:
            m = page.page_metrics()
        except Exception:  # noqa: BLE001
            m = None
        self._metrics[page.target_id] = (time.monotonic(), m)
        return m

    @staticmethod
    def _viewport_matches(m: dict, title: str, rc) -> int:
        if not m or m.get("vis") != "visible":
            return -1
        dpr = float(m.get("dpr") or 1)
        w, h = rc[2] - rc[0], rc[3] - rc[1]
        if abs(m["iw"] * dpr - w) > 3 or abs(m["ih"] * dpr - h) > 3:
            return -1
        score = 1
        t = m.get("title") or ""
        if t and title.startswith(t):
            score += 2
        if m.get("focus"):
            score += 1
        return score

    def page_screen_origin(self, page: WebPage):
        if not IS_WIN:
            return None
        from .backends import win32
        m = self.metrics(page)
        if not m:
            return None
        best, best_score = None, 0
        for _top, _rw, title, rc in win32.chromium_viewports():
            s = self._viewport_matches(m, title, rc)
            if s > best_score:
                best, best_score = rc, s
        if best is None:
            return None
        return float(best[0]), float(best[1]), (best[2] - best[0]) / float(m["iw"] or 1)

    def web_node_at(self, x: int, y: int) -> Optional[Node]:
        from .backends import win32
        if not self.web.endpoints:
            return None
        rw = win32.render_widget_at(x, y)
        if not rw:
            return None
        rc = win32.client_rect_screen(rw)
        title = win32.window_text(win32.root_window(rw))
        best, best_score = None, 0
        for page in self.web.pages():
            s = self._viewport_matches(self.metrics(page), title, rc)
            if s > best_score:
                best, best_score = page, s
        if best is None:
            return None
        scale = (rc[2] - rc[0]) / float(self.metrics(best)["iw"] or 1)
        try:
            return best.node_at_css((x - rc[0]) / scale, (y - rc[1]) / scale)
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------ picking
    def element_at(self, x: int, y: int) -> Optional[Node]:
        if not IS_WIN:
            return None
        from .backends import win32
        hw = win32.window_from_point(x, y)
        if not hw:
            return None
        pid, _ = win32.pid_tid(hw)
        if pid == self.own_pid:
            return None
        proc = win32.process_name(pid)
        if self.prefer_web and proc in win32.BROWSER_PROCESSES:
            node = self.web_node_at(x, y)
            if node is not None:
                return node
        if self.prefer_java and self.java is not None:
            try:
                node = self.java.from_point(x, y)
                if node is not None:
                    return node
            except Exception:  # noqa: BLE001
                pass
        for backend in list(self.extra_backends):  # plugin back ends get a chance before UI Automation
            try:
                node = backend.from_point(x, y)
            except Exception:  # noqa: BLE001
                node = None
            if node is not None:
                return node
        if self.uia is not None:
            return self.uia.from_point(x, y)
        return None

    def roots(self):
        out = []
        if self.uia is not None:
            out.append(self.uia.root())
        out.append(self.web.root())
        if self.java is not None:
            out.append(self.java.root())
        out.extend(b.root() for b in self.extra_backends)
        return out
