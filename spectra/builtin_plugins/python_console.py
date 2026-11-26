"""A dockable Python console for trying selectors and automation from inside Spectra.

The code runs on the driver thread (where elements may be used), with stdout and stderr captured.
Pre-loaded names: ``spectra`` (the plugin API), ``ctx``, ``engine``, ``node`` (the selected element),
``find(selector)``, ``find_all(selector)``, ``highlight(node)`` and ``select(node)``.
"""
from __future__ import annotations

import ast
import contextlib
import io
import sys
import traceback

import spectra.plugins as spectra_api
from spectra.plugins import PluginInfo

PLUGIN = PluginInfo(
    id="python_console", name="Python console", version="1.0", author="Spectra Inspector contributors",
    description="A dockable Python console (View > Python console) with find(), find_all(), highlight() and "
                "the selected element pre-loaded.")

EXAMPLES = {
    "Selected element: label and attributes": "node.label(), node.selector_attrs()",
    "Find all desktop windows": "for w in find_all('uia:Window'):\n    print(w.label())",
    "Highlight the first match": "el = find('uia:Window')\nhighlight(el)\nel.label()",
    "Element properties (first 10)": "for group, name, value in node.properties()[:10]:\n"
                                     "    print(f'{group:20} {name:28} {value}')",
    "Generate a selector for the selected element": "sel, res = engine.generate(node)\nprint(sel.to_text())\nlen(res.matches)",
    "Buttons in the selected element's window": "win = node.ancestry()[0]\n"
                                                "for b in find_all(f'uia:Window[hwnd=\"{win.get('hwnd')}\"] >> Button')[:20]:\n"
                                                "    print(b.label())",
}


class ConsoleSession:
    """The console without any UI: keeps a namespace and runs code in it. ``run`` must be called on the
    driver thread (``ctx.run_in_driver``)."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.ns = {
            "spectra": spectra_api,
            "ctx": ctx,
            "engine": ctx.engine,
            "find": self.find,
            "find_all": self.find_all,
            "highlight": ctx.highlight,
            "select": ctx.select,
            "__name__": "__spectra_console__",
        }

    def find(self, selector: str, timeout: float = 5.0):
        """The first element that matches ``selector``, or None."""
        res = self.ctx.engine.find_all(selector, timeout)
        if res.error:
            raise ValueError(res.error)
        return res.matches[0] if res.matches else None

    def find_all(self, selector: str, timeout: float = 10.0):
        res = self.ctx.engine.find_all(selector, timeout)
        if res.error:
            raise ValueError(res.error)
        return res.matches

    def run(self, code: str) -> str:
        """Run ``code``; returns everything it printed, plus the value of a final expression (like a REPL)."""
        self.ns["node"] = self.ctx.current_node()
        out = io.StringIO()
        try:
            tree = ast.parse(code, "<console>", "exec")
        except SyntaxError:
            return traceback.format_exc(limit=0)
        last = None
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            last = ast.Expression(tree.body.pop().value)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                if tree.body:
                    exec(compile(tree, "<console>", "exec"), self.ns)  # noqa: S102 - it's a console
                if last is not None:
                    value = eval(compile(last, "<console>", "eval"), self.ns)  # noqa: S307
                    if value is not None:
                        self.ns["_"] = value
                        print(repr(value), file=out)
        except Exception:  # noqa: BLE001
            te = traceback.TracebackException(*sys.exc_info())
            # show only the user's own frames (and library frames below them), not this method
            frames = list(te.stack)
            first = next((i for i, fr in enumerate(frames) if fr.filename == "<console>"), 0)
            te.stack = traceback.StackSummary.from_list(frames[first:])
            out.write("".join(te.format()))
        return out.getvalue()


def make_panel(ctx):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QKeySequence, QShortcut
    from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSplitter,
                                   QVBoxLayout, QWidget)

    session = ConsoleSession(ctx)
    history, pos = [], [0]
    mono = QFont("Cascadia Mono", 10)
    mono.setStyleHint(QFont.Monospace)

    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(4, 4, 4, 4)
    top = QHBoxLayout()
    examples = QComboBox()
    examples.addItem("Examples…")
    examples.addItems(list(EXAMPLES))
    run_btn = QPushButton("Run  (Ctrl+Enter)", objectName="primary")
    clear_btn = QPushButton("Clear output")
    top.addWidget(examples, 1)
    top.addWidget(run_btn)
    top.addWidget(clear_btn)
    lay.addLayout(top)
    split = QSplitter(Qt.Vertical)
    editor = QPlainTextEdit()
    editor.setFont(mono)
    editor.setPlaceholderText("find('uia:Window').label()      # Ctrl+Enter runs, Ctrl+Up/Down browse history")
    output = QPlainTextEdit(readOnly=True)
    output.setFont(mono)
    split.addWidget(editor)
    split.addWidget(output)
    split.setSizes([120, 200])
    lay.addWidget(split, 1)
    hint = QLabel("Names: node, find(), find_all(), highlight(), select(), engine, ctx, spectra. "
                  "Code runs on the automation thread.")
    hint.setStyleSheet("color: #8a8d94;")
    lay.addWidget(hint)

    def run():
        code = editor.toPlainText().strip()
        if not code:
            return
        if not history or history[-1] != code:
            history.append(code)
        pos[0] = len(history)
        output.appendPlainText(">>> " + code.replace("\n", "\n... "))
        run_btn.setEnabled(False)

        def done(text):
            if text:
                output.appendPlainText(text.rstrip("\n"))
            run_btn.setEnabled(True)
        ctx.run_in_driver(lambda: session.run(code), done)

    def browse(step):
        if not history:
            return
        pos[0] = max(0, min(len(history), pos[0] + step))
        editor.setPlainText(history[pos[0]] if pos[0] < len(history) else "")

    def pick_example(i):
        if i > 0:
            editor.setPlainText(EXAMPLES[examples.itemText(i)])
            examples.setCurrentIndex(0)
            editor.setFocus()

    run_btn.clicked.connect(run)
    clear_btn.clicked.connect(output.clear)
    examples.activated.connect(pick_example)
    for keys, fn in (("Ctrl+Return", run), ("Ctrl+Enter", run), ("Ctrl+Up", lambda: browse(-1)),
                     ("Ctrl+Down", lambda: browse(1))):
        sc = QShortcut(QKeySequence(keys), editor)
        sc.setContext(Qt.WidgetShortcut)
        sc.activated.connect(fn)
    w.session = session  # for tests and debugging
    return w


def register(ctx):
    ctx.add_panel("Python console", make_panel)
