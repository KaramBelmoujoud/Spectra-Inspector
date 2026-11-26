"""Plugins > Plugin Manager…"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from .plugin_host import SECURITY_WARNING

if TYPE_CHECKING:  # pragma: no cover
    from ..plugin_manager import PluginManager


class PluginManagerDialog(QDialog):
    COLS = ("On", "Plugin", "Version", "Author", "Source", "Status")

    def __init__(self, manager: "PluginManager", parent=None):
        super().__init__(parent)
        self.m = manager
        self.setWindowTitle("Plugin Manager")
        self.resize(980, 560)
        lay = QVBoxLayout(self)
        warn = QLabel("⚠  " + SECURITY_WARNING)
        warn.setWordWrap(True)
        warn.setStyleSheet("background:#3b2f10; color:#fcd34d; padding:8px; border-radius:4px; font-weight:bold;")
        lay.addWidget(warn)

        split = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_item)
        self.table.currentCellChanged.connect(lambda *_: self._show_details())
        split.addWidget(self.table)
        self.details = QPlainTextEdit(readOnly=True)
        split.addWidget(self.details)
        split.setSizes([360, 140])
        lay.addWidget(split, 1)

        row = QHBoxLayout()
        for text, fn in (("Reload", self._reload), ("Install from file…", self._install),
                         ("Open plugins folder", self._open_folder), ("Rescan", self._rescan)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        docs = QLabel('<a href="https://github.com/KaramBelmoujoud/Spectra-Inspector/blob/main/docs/plugins.md">'
                      "Writing plugins</a>")
        docs.setOpenExternalLinks(True)
        row.addWidget(docs)
        close = QPushButton("Close", objectName="primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self._filling = False
        self.refresh()

    # ------------------------------------------------------------------
    def _records(self):
        return sorted(self.m.records.values(), key=lambda r: (not r.builtin, r.name.lower()))

    def refresh(self):
        self._filling = True
        recs = self._records()
        cur = self._selected_id()
        self.table.setRowCount(len(recs))
        for r, rec in enumerate(recs):
            on = QTableWidgetItem()
            on.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            on.setCheckState(Qt.Checked if rec.enabled else Qt.Unchecked)
            on.setData(Qt.UserRole, rec.id)
            if rec.error and not rec.enabled:
                on.setFlags(on.flags() & ~Qt.ItemIsUserCheckable)
            self.table.setItem(r, 0, on)
            info = rec.info
            status = "error: " + rec.error.splitlines()[0] if rec.error else ("enabled" if rec.enabled else "off")
            for c, text in enumerate((rec.name, info.version if info else "", info.author if info else "",
                                      rec.source, status), start=1):
                it = QTableWidgetItem(text)
                it.setData(Qt.UserRole, rec.id)
                if rec.error:
                    it.setForeground(Qt.red)
                self.table.setItem(r, c, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self._filling = False
        if cur:
            for r in range(self.table.rowCount()):
                if self.table.item(r, 0).data(Qt.UserRole) == cur:
                    self.table.selectRow(r)
        self._show_details()

    def _selected_id(self):
        r = self.table.currentRow()
        if r < 0 or self.table.item(r, 0) is None:
            return None
        return self.table.item(r, 0).data(Qt.UserRole)

    def _show_details(self):
        pid = self._selected_id()
        rec = self.m.records.get(pid) if pid else None
        if rec is None:
            self.details.setPlainText("")
            return
        info = rec.info
        lines = [f"{rec.name}  ({rec.id})"]
        if info:
            lines += [info.description, "", f"Version {info.version}" + (f" · by {info.author}" if info.author else "")
                      + f" · plugin API {info.api_version}"]
            if info.homepage:
                lines.append(info.homepage)
        lines.append(f"Source: {rec.source} · {rec.location}")
        if rec.ctx is not None:
            lines.append("Adds: " + (", ".join(h.what for h in rec.ctx.handles) or "nothing yet"))
        if rec.error:
            lines += ["", "Error:", rec.error]
        self.details.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------
    def _on_item(self, item):
        if self._filling or item.column() != 0:
            return
        pid = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            ok = self.m.enable(pid)
            if not ok and self.m.records[pid].error:
                QMessageBox.warning(self, "Plugin Manager", f"Could not enable the plugin:\n\n{self.m.records[pid].error}")
        else:
            self.m.disable(pid)
        self.refresh()

    def _reload(self):
        pid = self._selected_id()
        if pid:
            self.m.reload(pid)
            self.refresh()

    def _rescan(self):
        self.m.discover()
        self.refresh()

    def _install(self):
        path, _ = QFileDialog.getOpenFileName(self, "Install a plugin", "", "Plugins (*.py *.zip)")
        if not path:
            return
        if QMessageBox.warning(self, "Install a plugin", SECURITY_WARNING + "\n\nInstall " + os.path.basename(path) + "?",
                               QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            new = self.m.install_file(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Install a plugin", f"Could not install it: {e}")
            return
        self.refresh()
        QMessageBox.information(self, "Install a plugin",
                                ("Installed: " + ", ".join(new) + ". Tick it in the list to enable it.") if new
                                else "Copied, but no new plugin was found in it (it may replace one with the same id; "
                                     "use Reload).")

    def _open_folder(self):
        os.makedirs(self.m.plugin_dir, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.m.plugin_dir))
