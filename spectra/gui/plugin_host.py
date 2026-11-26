"""Connects the plugin manager to the main window (the manager itself knows nothing about Qt)."""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget, QLabel, QMessageBox

from ..plugin_manager import Host, PluginRecord

if TYPE_CHECKING:  # pragma: no cover
    from .main_window import MainWindow

SECURITY_WARNING = ("Plugins run arbitrary Python code with your permissions: they can read your files, "
                    "control your applications and use the network. Only install and enable plugins you trust.")


class GuiHost(Host):
    def __init__(self, window: "MainWindow"):
        self.w = window
        self.service = window.service
        self.engine = window.service.engine
        self._docks: Dict[int, QDockWidget] = {}
        self._ui_thread = threading.current_thread()

    # ------------------------------------------------------------------ threads
    def _on_ui(self) -> bool:
        return threading.current_thread() is self._ui_thread

    def run_in_driver(self, fn, callback=None, timeout=30.0):
        drv = self.w.driver
        if callback is not None:
            drv.submit(fn, self.w.ui.wrap(callback),
                       lambda e, tb: self.log(f"Plugin code failed on the driver thread:\n{tb}"))
            return None
        if threading.current_thread() is drv:
            return fn()
        return drv.call(fn, timeout)

    def run_in_ui(self, fn, wait=False, timeout=30.0):
        if self._on_ui():
            return fn()
        if not wait:
            self.w.ui.post(fn)
            return None
        box, done = {}, threading.Event()

        def call():
            try:
                box["r"] = fn()
            except Exception as e:  # noqa: BLE001
                box["e"] = e
            done.set()
        self.w.ui.post(call)
        if not done.wait(timeout):
            raise TimeoutError("UI call timed out")
        if "e" in box:
            raise box["e"]
        return box.get("r")

    # ------------------------------------------------------------------ app state
    def log(self, msg: str):
        self.run_in_ui(lambda: self.w.log(msg))

    def current_node(self):
        return self.w.current

    def selector_text(self) -> str:
        return self.run_in_ui(self.w.selector_text, wait=True)

    def set_selector_text(self, text: str, validate: bool = True):
        def apply():
            self.w.sel_text.setPlainText(text)
            if validate:
                self.w.validate(highlight=False)
        self.run_in_ui(apply)

    def highlight(self, node):
        self.w.driver.submit(node.rect, self.w.ui.wrap(self.w._show_rect))

    def select(self, node):
        self.run_in_ui(lambda: self.w.select_node(node))

    def plugins_changed(self, kind: str):
        self.run_in_ui(lambda: self.w._plugins_changed(kind))

    # ------------------------------------------------------------------ panels
    def add_panel(self, plugin_id: str, panel: dict):
        def make():
            dock = QDockWidget(panel["title"], self.w, objectName=f"plugin:{plugin_id}:{panel['title']}")
            try:
                widget = panel["factory"](panel["ctx"])
            except Exception as e:  # noqa: BLE001
                widget = QLabel(f"The panel of plugin '{plugin_id}' failed to start:\n{type(e).__name__}: {e}")
                widget.setWordWrap(True)
                self.w.log(f"Plugin '{plugin_id}': panel '{panel['title']}' failed: {e}")
            dock.setWidget(widget)
            self.w.addDockWidget(Qt.BottomDockWidgetArea, dock)
            out = self.w.findChild(QDockWidget, "out_dock")
            if out is not None:
                self.w.tabifyDockWidget(out, dock)
                out.raise_()
            self._docks[id(panel)] = dock
            self.w._rebuild_view_menu()
        self.run_in_ui(make)

    def remove_panel(self, plugin_id: str, panel: dict):
        def drop():
            dock = self._docks.pop(id(panel), None)
            if dock is not None:
                self.w.removeDockWidget(dock)
                dock.deleteLater()
                self.w._rebuild_view_menu()
        self.run_in_ui(drop)

    def panel_dock(self, panel: dict):
        return self._docks.get(id(panel))

    # ------------------------------------------------------------------ trust
    def confirm_third_party(self, record: PluginRecord) -> bool:
        info = record.info
        text = (f"Enable the plugin \"{record.name}\"" + (f" {info.version}" if info else "") +
                (f" by {info.author}" if info and info.author else "") + f"?\n\nSource: {record.location}\n\n"
                + SECURITY_WARNING)
        r = QMessageBox.warning(self.w, "Enable a third-party plugin", text,
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return r == QMessageBox.Yes
