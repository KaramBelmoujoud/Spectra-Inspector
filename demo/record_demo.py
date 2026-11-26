"""Scripted, self-captioned demo of Spectra Inspector, recorded with ffmpeg.

    .venv\\Scripts\\python demo\\record_demo.py            record everything
    .venv\\Scripts\\python demo\\record_demo.py --dry      run without recording
    .venv\\Scripts\\python demo\\record_demo.py --only 2,3 run some chapters (dry)

The real Spectra main window runs in this process (so the script can find its
widgets); the mouse and keyboard are driven with real input (SetCursorPos /
SendInput) from a worker thread. Only windows opened by this script are shown
in the desktop tree, and a backdrop hides everything else on the screen.
"""
from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap, QLinearGradient  # noqa: E402
from PySide6.QtWidgets import (QApplication, QComboBox, QInputDialog, QLabel, QMessageBox,  # noqa: E402
                               QPlainTextEdit, QPushButton, QToolBar, QToolButton, QVBoxLayout, QWidget)

ARGS = sys.argv[1:]
DRY = "--dry" in ARGS or "--only" in ARGS
ONLY = set()
if "--only" in ARGS:
    ONLY = {int(x) for x in ARGS[ARGS.index("--only") + 1].split(",")}
# the secondary monitor (\\.\DISPLAY1: x=2560, y=365, 1920x1080, taskbar at the bottom)
MON_X, MON_Y = 2560, 365
SCREEN_W, SCREEN_H = 1920, 1032          # its work area (without the taskbar)
SPLIT = 1200                             # Spectra on the left, the target app on the right
CAPTION_H = 112                          # strip at the bottom for the captions
APP_H = SCREEN_H - CAPTION_H
SPECTRA_RECT = (MON_X, MON_Y, SPLIT, APP_H)
RIGHT = (MON_X + SPLIT, MON_Y, SCREEN_W - SPLIT, APP_H)
RIGHT_TOP = (MON_X + SPLIT + 40, MON_Y + 40, SCREEN_W - SPLIT - 80, 430)
RIGHT_BOTTOM = (MON_X + SPLIT, MON_Y + 470, SCREEN_W - SPLIT, 440)
OUT_DIR = os.path.join(HERE, "chapters")
os.makedirs(OUT_DIR, exist_ok=True)
RAW = os.path.join(OUT_DIR, "raw_capture.mp4")
# Everything shown on screen (file dialogs, Explorer windows, saved-file messages) uses this neutral folder,
# so the path of the project folder never appears in the video. It is created on start and removed at the end.
STAGE = os.environ.get("SPECTRA_DEMO_STAGE", r"C:\SpectraDemo")
STAGE_FILES = os.path.join(STAGE, "files")      # what the dialogs open and save into
STAGE_STORE = os.path.join(STAGE, "store")      # Explorer window 1
STAGE_SHOTS = os.path.join(STAGE, "screenshots")  # Explorer window 2
LOG = open(os.path.join(OUT_DIR, "record_log.txt"), "w", encoding="utf-8")


def log(*a):
    msg = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(msg, flush=True)
    LOG.write(msg + "\n"); LOG.flush()


app = QApplication(sys.argv)
from spectra.backends import cdp, win32  # noqa: E402
from spectra.gui.widgets import apply_dark_theme  # noqa: E402

# ----------------------------------------------------------------- only show our own windows
ALLOWED_HWNDS: set = set()
ALLOWED_PIDS: set = set()
_orig_desktop_windows = win32.desktop_windows


def _demo_desktop_windows():
    return [h for h in _orig_desktop_windows()
            if h in ALLOWED_HWNDS or win32.pid_tid(h)[0] in ALLOWED_PIDS]


win32.desktop_windows = _demo_desktop_windows

# the demo browser gets its own throw-away profile (never the one Spectra uses for you)
import tempfile  # noqa: E402
_orig_launch = cdp.launch_browser
DEMO_PROFILE = os.path.join(tempfile.gettempdir(), "spectra-demo-browser-profile")


def _demo_launch(exe, port=9222, url="about:blank", profile_dir=None, extra=None):
    return _orig_launch(exe, port, url, profile_dir=DEMO_PROFILE,
                        extra=(extra or []) + ["--hide-crash-restore-bubble", "--disable-session-crashed-bubble"])


cdp.launch_browser = _demo_launch

# file dialogs open in demo/chapters, so only a file name has to be typed on camera
from PySide6.QtWidgets import QFileDialog  # noqa: E402
_orig_save, _orig_open = QFileDialog.getSaveFileName, QFileDialog.getOpenFileName
QFileDialog.getSaveFileName = staticmethod(
    lambda parent=None, caption="", d="", flt="", *a, **k: _orig_save(parent, caption, os.path.join(STAGE_FILES, os.path.basename(d)), flt))
QFileDialog.getOpenFileName = staticmethod(
    lambda parent=None, caption="", d="", flt="", *a, **k: _orig_open(parent, caption, STAGE_FILES, flt))
from spectra.gui.main_window import MainWindow  # noqa: E402

u32 = ctypes.windll.user32
u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             wintypes.UINT]


# ----------------------------------------------------------------- GUI-thread bridge
class _Bridge(QObject):
    sig = Signal(object)

    def __init__(self):
        super().__init__()
        self.sig.connect(self._run, Qt.QueuedConnection)

    def _run(self, job):
        fn, box, ev = job
        try:
            box["r"] = fn()
        except Exception as e:  # noqa: BLE001
            box["e"] = e
        ev.set()


BRIDGE = _Bridge()


def gui(fn, timeout=20):
    if threading.current_thread() is threading.main_thread():
        return fn()
    box, ev = {}, threading.Event()
    BRIDGE.sig.emit((fn, box, ev))
    if not ev.wait(timeout):
        raise TimeoutError("GUI call timed out")
    if "e" in box:
        raise box["e"]
    return box.get("r")


def until(cond, timeout=8.0, step=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if cond():
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(step)
    return False


# ----------------------------------------------------------------- backdrop + captions
class Backdrop(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setGeometry(MON_X, MON_Y, SCREEN_W, SCREEN_H)

    def paintEvent(self, _):
        p = QPainter(self)
        g = QLinearGradient(0, 0, SCREEN_W, SCREEN_H)
        g.setColorAt(0, QColor(24, 28, 40)); g.setColorAt(1, QColor(40, 30, 52))
        p.fillRect(self.rect(), g)
        p.setPen(QColor(255, 255, 255, 28))
        p.setFont(QFont("Segoe UI", 48, QFont.Bold))
        p.drawText(self.rect().adjusted(0, 0, -60, -60), Qt.AlignRight | Qt.AlignBottom, "Spectra Inspector")


class Caption(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                         Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.title, self.text = "", ""
        self.resize(1560, 104)

    def say(self, title, text=""):
        self.title, self.text = title, text
        self.move(MON_X + (SCREEN_W - self.width()) // 2, MON_Y + SCREEN_H - self.height() - 16)
        self.show(); self.raise_(); self.update()

    def paintEvent(self, _):
        if not self.title:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(12, 14, 20, 225)); p.setPen(QColor(20, 184, 166))
        p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 16, 16)
        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("Segoe UI", 19, QFont.Bold))
        p.drawText(self.rect().adjusted(26, 10, -26, -54), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        p.setPen(QColor(205, 210, 222))
        p.setFont(QFont("Segoe UI", 13))
        p.drawText(self.rect().adjusted(26, 54, -26, -8), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self.text)


class CodePanel(QWidget):
    """Shows a Python snippet and the live output of running it in another process."""

    def __init__(self):
        super().__init__(None, Qt.Window | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Python - Spectra API")
        self.setStyleSheet("background:#11141b;color:#e6e6e6")
        lay = QVBoxLayout(self)
        self.code = QPlainTextEdit(readOnly=True)
        self.out = QPlainTextEdit(readOnly=True)
        for w_ in (self.code, self.out):
            w_.setFont(QFont("Cascadia Mono", 13))
        self.out.setStyleSheet("color:#8be28b")
        lay.addWidget(QLabel("script.py")); lay.addWidget(self.code, 3)
        lay.addWidget(QLabel("output")); lay.addWidget(self.out, 2)
        self.setGeometry(MON_X + 90, MON_Y + 260, 1000, 600)


backdrop, caption = None, None


def say(title, text="", hold=0.0):
    gui(lambda: caption.say(title, text))
    log("CAPTION:", title)
    if hold:
        time.sleep(hold)


# ----------------------------------------------------------------- real input
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(inp):
    u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def move(x, y, dur=0.55):
    x, y = int(x), int(y)
    sx, sy = win32.cursor_pos()
    n = max(1, int(dur / 0.008))
    for i in range(1, n + 1):
        t = i / n
        e = t * t * (3 - 2 * t)
        u32.SetCursorPos(int(sx + (x - sx) * e), int(sy + (y - sy) * e))
        time.sleep(0.008)
    u32.SetCursorPos(x, y)


def mouse(flag):
    inp = INPUT(type=0); inp.mi.dwFlags = flag; _send(inp)


def click(x=None, y=None, button="left", double=False, dur=0.55):
    if x is not None:
        move(x, y, dur)
        time.sleep(0.15)
    down, up = {"left": (0x2, 0x4), "right": (0x8, 0x10)}[button]
    for _ in range(2 if double else 1):
        mouse(down); time.sleep(0.05); mouse(up); time.sleep(0.07)
    time.sleep(0.12)


def wheel(amount):
    inp = INPUT(type=0); inp.mi.dwFlags = 0x0800; inp.mi.mouseData = ctypes.c_uint32(amount).value; _send(inp)


VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "enter": 0x0D, "esc": 0x1B, "tab": 0x09, "down": 0x28,
      "up": 0x26, "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23, "del": 0x2E, "back": 0x08,
      "f1": 0x70, "f3": 0x72, "f4": 0x73, "f5": 0x74, "a": 0x41, "s": 0x53, "o": 0x4F, "t": 0x54, "l": 0x4C,
      "1": 0x31, "2": 0x32, "space": 0x20}


def key(combo, pause=0.12):
    keys = [VK[k] for k in combo.split("+")]
    for k in keys:
        inp = INPUT(type=1); inp.ki.wVk = k; _send(inp); time.sleep(0.03)
    for k in reversed(keys):
        inp = INPUT(type=1); inp.ki.wVk = k; inp.ki.dwFlags = 2; _send(inp); time.sleep(0.03)
    time.sleep(pause)


def type_text(text, cps=22):
    from spectra.api import _send_unicode
    for ch in text:
        _send_unicode(ch)
        time.sleep(1.0 / cps)


# ----------------------------------------------------------------- Spectra widget geometry (GUI thread)
W: MainWindow = None


def center(widget):
    def f():
        p = widget.mapToGlobal(widget.rect().center())
        return p.x(), p.y()
    return gui(f)


def button(text):
    return gui(lambda: next(b for b in W.findChildren(QPushButton) if b.text() == text))


def action_pos(act):
    def f():
        tb = W.findChild(QToolBar)
        wd = tb.widgetForAction(act)
        p = wd.mapToGlobal(wd.rect().center())
        return p.x(), p.y()
    return gui(f)


def browsers_button_pos():
    def f():
        b = next(b for b in W.findChildren(QToolButton) if "Browsers" in b.text())
        p = b.mapToGlobal(b.rect().center())
        return p.x(), p.y()
    return gui(f)


def tab_pos(name):
    def f():
        bar = W.tabs.tabBar()
        i = next(i for i in range(bar.count()) if bar.tabText(i).replace("&&", "&").startswith(name))
        p = bar.mapToGlobal(bar.tabRect(i).center())
        return p.x(), p.y()
    return gui(f)


def step_pos(i, checkbox=False):
    def f():
        it = W.step_list.item(i)
        W.step_list.scrollToItem(it)
        r = W.step_list.visualItemRect(it)
        x = r.left() + 12 if checkbox else r.left() + min(260, r.width() // 2)
        p = W.step_list.viewport().mapToGlobal(QPoint(x, r.center().y()))
        return p.x(), p.y()
    return gui(f)


def attr_row(name):
    return gui(lambda: next((r for r in range(W.attr_table.rowCount())
                             if W.attr_table.item(r, 1) and W.attr_table.item(r, 1).text() == name), -1))


def attr_cell(row, col):
    def f():
        if col == 2:
            wd = W.attr_table.cellWidget(row, 2)
            p = wd.mapToGlobal(wd.rect().center())
            return p.x(), p.y()
        r = W.attr_table.visualItemRect(W.attr_table.item(row, col))
        x = r.left() + 14 if col == 0 else r.center().x()
        p = W.attr_table.viewport().mapToGlobal(QPoint(x, r.center().y()))
        return p.x(), p.y()
    return gui(f)


def combo_item_pos(row, text):
    def f():
        cb: QComboBox = W.attr_table.cellWidget(row, 2)
        i = cb.findText(text)
        v = cb.view()
        r = v.visualRect(v.model().index(i, 0))
        p = v.viewport().mapToGlobal(r.center())
        return p.x(), p.y()
    return gui(f)


def tree_item_pos(pred):
    def f():
        def walk(it):
            for i in range(it.childCount()):
                c = it.child(i)
                if pred(c.text(0)):
                    return c
                if c.isExpanded():
                    r = walk(c)
                    if r is not None:
                        return r
            return None
        for i in range(W.tree.topLevelItemCount()):
            top = W.tree.topLevelItem(i)
            if pred(top.text(0)):
                it = top
                break
            it = walk(top) if top.isExpanded() else None
            if it is not None:
                break
        else:
            return None
        W.tree.scrollToItem(it)
        r = W.tree.visualItemRect(it)
        p = W.tree.viewport().mapToGlobal(QPoint(r.left() + 60, r.center().y()))
        return p.x(), p.y(), (r.left() - 10)
    return gui(f)


def spectra_text():
    return gui(lambda: (W.elem_label.text(), W.selector_text(), W.valid_label.text()))


def settle(timeout=10):
    """Wait until the current selection, selector generation and validation are done."""
    until(lambda: gui(lambda: not W.picking and "Loading" not in W.elem_label.text()
                      and not W.valid_label.text().startswith(("Generating", "Validating"))), timeout)
    time.sleep(0.3)


def activate_spectra():
    gui(lambda: (W.showNormal() if W.isMinimized() else None, W.raise_(), W.activateWindow()))
    win32.bring_to_front(int(gui(lambda: int(W.winId()))))
    time.sleep(0.35)


def place(hwnd, rect):
    u32.ShowWindow(hwnd, 9)
    u32.SetWindowPos(hwnd, None, rect[0], rect[1], rect[2], rect[3], 0x0040 | 0x0004)


def rect_of(selector, timeout=8):
    def f():
        n = W.service.engine.find_first(selector, timeout)
        if n is None:
            return None
        if n.tech == "web":  # make sure it is visible before pointing at it
            from spectra.api import Element
            el = Element.__new__(Element)
            el.node = n
            el._web_call("function(){this.scrollIntoViewIfNeeded ? this.scrollIntoViewIfNeeded(true)"
                         " : this.scrollIntoView({block:'center'});}")
            time.sleep(0.4)
        return n.rect()
    r = W.driver.call(f, timeout + 5)
    if not r:
        raise LookupError(f"not found on screen: {selector}")
    return r


def mid(r, fx=0.5, fy=0.5):
    return int(r[0] + (r[2] - r[0]) * fx), int(r[1] + (r[3] - r[1]) * fy)


def pick(target_xy, hover_path=(), how="click", hold=0.8):
    """F3, hover along a path, then capture with a click (or Ctrl)."""
    activate_spectra()
    key("f3")
    until(lambda: gui(lambda: W.picking), 3)
    time.sleep(0.6)
    for xy in hover_path:
        move(*xy, dur=0.6)
        time.sleep(hold)
    move(*target_xy, dur=0.6)
    until(lambda: gui(lambda: W.hover_node is not None), 3)
    time.sleep(1.0)
    if how == "click":
        click()
    else:
        key("ctrl", pause=0.3)
    settle()


def set_attr_value(name, value):
    row = attr_row(name)
    if row < 0:
        log("attr not found", name)
        return
    click(*attr_cell(row, 3), double=True)
    time.sleep(0.3)
    key("ctrl+a")
    type_text(value)
    key("enter")


def set_attr_op(name, op):
    row = attr_row(name)
    if row < 0:
        return
    click(*attr_cell(row, 2))
    time.sleep(0.5)
    click(*combo_item_pos(row, op), dur=0.4)


def toggle_attr(name):
    row = attr_row(name)
    if row >= 0:
        click(*attr_cell(row, 0))


def show_validation(pause=2.2):
    settle()
    time.sleep(pause)


# ----------------------------------------------------------------- environment
STATE = {}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def new_windows(before, pred, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        found = [h for h in set(win32.top_windows()) - before if pred(h)]
        if found:
            return found
        time.sleep(0.25)
    return []


def open_charmap():
    p = subprocess.Popen(["charmap.exe"])
    hw = new_windows(set(), lambda h: win32.pid_tid(h)[0] == p.pid and win32.window_text(h) == "Character Map"
                     and win32.is_visible(h))
    if not hw:
        raise RuntimeError("Character Map did not open")
    hw = hw[0]
    STATE["app_hwnd"], STATE["app_pid"], STATE["app_proc"] = hw, p.pid, p
    ALLOWED_PIDS.add(p.pid)
    l, t, r, b = win32.window_rect(hw)
    u32.SetWindowPos(hw, None, MON_X + SPLIT + 100, MON_Y + 120, 0, 0, 0x0001 | 0x0004 | 0x0040)
    time.sleep(0.8)
    return hw


def app_sel(tail=""):
    return f'uia:Window[pid="{STATE["app_pid"]}"]' + (f" >> {tail}" if tail else "")


def open_explorer(path, rect):
    before = set(win32.top_windows())
    subprocess.Popen(["explorer.exe", path])
    hw = new_windows(before, lambda h: win32.class_name(h) == "CabinetWClass")
    if not hw:
        raise RuntimeError("Explorer did not open")
    hw = hw[0]
    STATE.setdefault("explorer_hwnds", []).append(hw)
    ALLOWED_HWNDS.add(hw)
    place(hw, rect)
    time.sleep(1.2)
    return hw


def web(sel_tail, title="Spectra Demo Store"):
    return f'web:tab[title="{title}"] >> {sel_tail}'


# ================================================================= chapters
def show_tab(host):
    """Bring a browser tab to the front (DevTools Target.activateTarget), as clicking its tab would."""
    win32.bring_to_front(STATE["chrome_hwnd"]); time.sleep(0.3)
    page = W.driver.call(lambda: next(p for p in W.service.web.pages() if p.host == host))
    W.driver.call(page.bring_to_front)
    time.sleep(1.5)


def ch1_intro():
    say("Spectra Inspector", "Inspect UI elements of Windows apps and web pages, and build selectors that find them again.", 4)
    say("1 · The layout", "Left: the live UI tree of the desktop, browsers and Java apps.")
    x, y = center(W.tree)
    move(x, y - 200); time.sleep(2.2)
    say("1 · The layout", "Centre: the element's ancestry and its attributes. Tick what the selector should use.")
    move(*center(W.step_list)); time.sleep(1.6)
    move(*center(W.attr_table)); time.sleep(1.8)
    say("1 · The layout", "The selector, validated live as you edit it.")
    move(*center(W.sel_text)); time.sleep(2.0)
    say("1 · The layout", "Right: every property of the selected element (UI Automation, MSAA, Win32, DOM).")
    move(*center(W.props)); time.sleep(2.2)
    say("1 · The layout", "Bottom: ready-to-use locators and code, a 'Try it' panel to act on the element, and the log.")
    for t in ("Try it", "Log", "Locators"):
        click(*tab_pos(t)); time.sleep(1.0)
    time.sleep(0.8)


def ch2_desktop():
    say("2 · Pick an element on screen", "Open a desktop app (Character Map), press F3 and hover: Spectra steps aside and frames the element under the mouse.")
    hw = open_charmap()
    time.sleep(0.8)
    edit = rect_of(app_sel('Edit[automationid="104"]'))
    path = [mid(rect_of(app_sel('ComboBox[automationid="105"]'))), mid(rect_of(app_sel('Pane[automationid="108"]')), 0.3, 0.3),
            mid(rect_of(app_sel('Pane[automationid="108"]')), 0.7, 0.6), mid(rect_of(app_sel('Button[name="Select"]'))),
            mid(rect_of(app_sel('CheckBox[automationid="119"]')))]
    say("2 · Pick an element on screen", "F3 ... hover over the font list, the character grid, the buttons ...")
    pick(mid(edit), hover_path=path)
    say("2 · Captured with a click", "The click never reaches the app. Spectra comes back with the element, its selector and its properties.", 3.5)
    say("2 · Properties", "Every UI Automation, pattern, MSAA and Win32 property. Filter them by typing.")
    move(*center(W.props)); wheel(-360); time.sleep(1.2); wheel(-720); time.sleep(1.2)
    click(*center(W.prop_filter)); type_text("Legacy"); time.sleep(2.5)
    key("ctrl+a"); key("back"); time.sleep(0.6)
    say("2 · The tree follows", "The UI tree expands to the captured element.")
    move(*center(W.tree)); time.sleep(2.5)
    say("2 · Ctrl also captures", "Pick the Copy button and press Ctrl instead of clicking: the button is not pressed.")
    pick(mid(rect_of(app_sel('Button[name="Copy"]'))), how="ctrl")
    time.sleep(2.5)


def ensure_app():
    if not STATE.get("app_pid"):
        open_charmap()


def ensure_browser():
    if not STATE.get("chrome_hwnd"):
        launch_browser_on_camera()


def ch3_editor():
    ensure_app()
    say("3 · The selector editor", "Pick the scroll bar's 'Line down' button: three ancestry levels, each one can become a step.")
    win32.bring_to_front(STATE["app_hwnd"]); time.sleep(0.4)
    pick(mid(rect_of(app_sel('Button[automationid="DownButton"]'))))
    time.sleep(1.5)
    say("3 · Edit an attribute with a wildcard", "Select the Window level and change its name to  Character*  (* and ? are wildcards).")
    click(*step_pos(0)); time.sleep(1.2)
    set_attr_value("name", "Character*")
    show_validation(2.5)
    say("3 · Choose how each attribute matches", "=  equals (with wildcards),  *=  contains,  ^=  starts with,  $=  ends with,  ~=  regular expression ...")
    set_attr_op("name", "~=")
    time.sleep(0.6)
    set_attr_value("name", "^Char.*Map$")
    show_validation(2.5)
    set_attr_op("name", "*=")
    set_attr_value("name", "Map")
    show_validation(2.0)
    say("3 · Tick and untick attributes", "Fewer attributes = a more robust selector. Live validation shows what still matches.")
    toggle_attr("class"); show_validation(1.6)
    toggle_attr("class"); show_validation(1.2)
    say("3 · Add or remove ancestry levels", "Ticking the middle level (the scroll bar) adds a step to the path.")
    n = gui(lambda: W.step_list.count())
    if n > 2:
        click(*step_pos(n - 2, checkbox=True)); show_validation(2.2)
        click(*step_pos(n - 2, checkbox=True)); show_validation(1.2)
    say("3 · Index", "When several elements match, :nth(N) picks one of them.")
    click(*step_pos(n - 1)); time.sleep(0.8)
    row = attr_row("automationid")
    if row >= 0:
        toggle_attr("automationid"); time.sleep(0.4)
    toggle_attr("name"); show_validation(2.0)
    sx, sy = center(W.nth_spin)
    wd = gui(lambda: W.nth_spin.width())
    for _ in range(3):
        click(sx + wd // 2 - 8, sy - 6, dur=0.3); time.sleep(0.5)
    show_validation(2.0)
    say("3 · Highlight matches", "Frames every element the selector finds.")
    click(*center(button("Highlight matches"))); time.sleep(2.8)
    say("3 · Mistakes are explained", "A broken selector is reported with the position of the error.")
    click(*center(W.sel_text)); key("ctrl+end"); type_text(" >> [", cps=12); show_validation(2.6)
    say("3 · Regenerate", "Rebuilds the shortest selector that finds exactly this element.")
    click(*center(button("Regenerate"))); show_validation(2.5)


def ch4_explorer():
    say("4 · File Explorer", "Two Explorer windows. Capture the file list in the first one.")
    hw1 = open_explorer(STAGE_STORE, (MON_X + SPLIT, MON_Y, SCREEN_W - SPLIT, 460))
    hw2 = open_explorer(STAGE_SHOTS, RIGHT_BOTTOM)
    win32.bring_to_front(hw1); time.sleep(0.8)
    lst = rect_of('uia:Window[class="CabinetWClass"][name^="store"] >> List[name="Items View"]')
    pick(mid(lst, 0.6, 0.85), hover_path=[mid(lst, 0.3, 0.1)])
    time.sleep(1.5)
    say("4 · Same element in several windows", "Make the window name a wildcard:  * - File Explorer  ...  now both lists match.")
    click(*step_pos(0)); time.sleep(0.8)
    set_attr_value("name", "* - File Explorer")
    show_validation(1.5)
    click(*center(button("Highlight matches"))); time.sleep(3.0)
    say("4 · Pick one again", "...  store*  narrows it back to a single window.")
    set_attr_value("name", "store*")
    show_validation(1.5)
    click(*center(button("Highlight matches"))); time.sleep(2.5)
    for h in (hw1, hw2):
        u32.PostMessageW(h, 0x0010, 0, 0)
    STATE["explorer_hwnds"] = []


def launch_browser_on_camera():
    say("5 · Web pages without a browser extension", "Browsers ▸ Launch Chrome: Spectra starts Chrome with its DevTools port open.")
    activate_spectra()
    before = set(win32.top_windows())
    click(*browsers_button_pos()); time.sleep(1.0)

    def item_pos():
        m = QApplication.activePopupWidget()
        act = next(a for a in m.actions() if a.text().startswith("Launch Chrome"))
        r = m.actionGeometry(act)
        p = m.mapToGlobal(r.center())
        return p.x(), p.y()
    try:
        move(*gui(item_pos), dur=0.5); time.sleep(0.6)
    except Exception:  # noqa: BLE001
        log("menu item position not found")

    def launch():  # same as clicking the menu item
        m = QApplication.activePopupWidget()
        if m is not None:
            m.close()
        W.launch_browser("Chrome", cdp.installed_browsers()["Chrome"])
    gui(launch)
    hws = new_windows(before, lambda h: win32.class_name(h) == "Chrome_WidgetWin_1" and win32.is_visible(h)
                      and win32.process_name(win32.pid_tid(h)[0]) == "chrome.exe"
                      and win32.window_text(h).strip() != "", 25)
    if not hws:
        raise RuntimeError("Chrome window did not appear")
    hw = hws[0]
    STATE["chrome_hwnd"] = hw
    STATE["chrome_pid"] = win32.pid_tid(hw)[0]
    ALLOWED_HWNDS.add(hw)
    place(hw, RIGHT)
    if not until(lambda: W.driver.call(lambda: bool(W.service.web.pages())), 20):
        raise RuntimeError("Spectra did not connect to the browser")
    STATE["port"] = W.driver.call(lambda: W.service.web.endpoints[0].port)
    time.sleep(1.5)
    say("5 · A page with many elements", "Open the demo store in a second tab.")
    win32.bring_to_front(hw); time.sleep(0.5)
    key("ctrl+t"); time.sleep(0.8)
    type_text(STATE["url"], cps=40); key("enter")
    until(lambda: W.driver.call(lambda: any(p.title == "Spectra Demo Store" for p in W.service.web.pages())), 15)
    time.sleep(1.5)
    activate_spectra()
    key("f5"); time.sleep(1.5)
    say("5 · The DOM in the tree", "Browsers ▸ tab ▸ the live DOM, including shadow roots and iframes.")
    pos = tree_item_pos(lambda t: t.startswith("Browsers"))
    if pos:
        click(pos[0], pos[1], double=True); time.sleep(1.2)
    pos = tree_item_pos(lambda t: "Spectra Demo Store" in t)
    if pos:
        click(pos[0], pos[1], double=True); time.sleep(1.5)
    pos = tree_item_pos(lambda t: t.startswith("html"))
    if pos:
        click(pos[0], pos[1], double=True); time.sleep(1.5)
    pos = tree_item_pos(lambda t: t.startswith("body"))
    if pos:
        click(pos[0], pos[1], double=True); time.sleep(2.0)


def ch5_browser():
    launch_browser_on_camera()
    say("5 · Pick inside the page", "F3 works in the browser too: Spectra reads the real DOM over DevTools.")
    nav = rect_of(web('a[href="#deals"]'))
    srch = rect_of(web('input[id="search"]'))
    card1 = rect_of(web('article[class="card"]:nth(1)'))
    add3 = rect_of(web('button[class="add"]:nth(3)'))
    pick(mid(add3), hover_path=[mid(nav), mid(srch), mid(card1, 0.5, 0.3)])
    say("5 · A selector for the 3rd 'Add to cart'", "Six identical buttons: Spectra adds :nth(3) automatically.", 3.0)
    say("5 · CSS, XPath, Playwright, Selenium", "Locators & code: CSS and XPath with their match counts, plus ready-to-paste snippets.")
    click(*tab_pos("Locators")); time.sleep(3.5)
    say("5 · Pick another product with the Index", "Change :nth to 5 ...")
    n = gui(lambda: W.step_list.count())
    click(*step_pos(n - 1)); time.sleep(0.6)
    click(*center(W.nth_spin), double=True); key("ctrl+a"); type_text("5"); key("tab")
    show_validation(1.0)
    click(*center(button("Highlight matches"))); time.sleep(2.5)
    say("5 · ... or all six", "Index 0 = no index: six matches, all framed.")
    click(*center(W.nth_spin), double=True); key("ctrl+a"); type_text("0"); key("tab")
    show_validation(1.0)
    click(*center(button("Highlight matches"))); time.sleep(3.0)
    say("5 · F4: the browser's own inspect mode", "Press F4, then click an element in the page.")
    activate_spectra()
    key("f4"); time.sleep(1.0)
    dlg = until(lambda: gui(lambda: isinstance(QApplication.activeModalWidget(), QInputDialog)), 3)
    if dlg:
        idx = gui(lambda: next(i for i, t in enumerate(QApplication.activeModalWidget().comboBoxItems())
                               if "Spectra Demo Store" in t))
        say("5 · F4: the browser's own inspect mode", "Choose the tab ...")
        time.sleep(1.2)
        for _ in range(idx):
            key("down", 0.3)
        time.sleep(0.6)
        key("enter")
    time.sleep(1.5)
    btn = rect_of(web('button[id="login-btn"]'))
    move(*mid(btn), dur=0.7); time.sleep(1.2)
    click()
    settle(); time.sleep(2.5)
    say("5 · Shadow DOM", "The coupon box is a web component. Its selector goes straight through the shadow root with >>.")
    apply_ = rect_of(web('promo-dialog >> button[id="apply"]'))
    pick(mid(apply_), hover_path=[mid(apply_, 0.2, -1.5)])
    time.sleep(3.0)
    say("5 · Iframes", "The newsletter form lives in an iframe: >> crosses into it as well.")
    sub = rect_of(web('iframe[id="newsletter"] >> button[id="subscribe"]'))
    pick(mid(sub))
    time.sleep(3.0)
    say("5 · Repair a broken selector", "Change the button id so it no longer matches ... then Repair… finds the element again.")
    click(*center(W.sel_text)); key("ctrl+a")
    type_text(web('iframe[id="newsletter"] >> button[id="subscribe-old"][type="submit"]'), cps=45)
    show_validation(2.0)
    click(*center(button("Repair…"))); time.sleep(1.0)
    if until(lambda: gui(lambda: isinstance(QApplication.activeModalWidget(), QMessageBox)), 2):
        time.sleep(1.5); key("enter")
    show_validation(3.0)


def ch6_tryit():
    ensure_browser(); ensure_app()
    win32.bring_to_front(STATE["chrome_hwnd"]); time.sleep(0.5)
    say("6 · Try it: act on the element", "Capture the search box, then Set value.")
    s = rect_of(web('input[id="search"]'))
    pick(mid(s))
    click(*tab_pos("Try it")); time.sleep(0.8)
    click(*center(W.value_edit)); key("ctrl+a"); type_text("headphones")
    click(*center(button("Set value"))); time.sleep(2.0)
    say("6 · Try it: Click", "Capture the Search button and click it from Spectra: the page reacts.")
    b = rect_of(web('button[id="search-btn"]'))
    pick(mid(b))
    click(*tab_pos("Try it")); time.sleep(0.5)
    click(*center(button("Click"))); time.sleep(2.5)
    say("6 · Fill a form", "Email field: Set value ...  then Click on 'Sign in'.")
    e = rect_of(web('input[id="email"]'))
    pick(mid(e))
    click(*tab_pos("Try it")); time.sleep(0.4)
    click(*center(W.value_edit)); key("ctrl+a"); type_text("ada@spectra.dev")
    click(*center(button("Set value"))); time.sleep(1.5)
    b = rect_of(web('button[id="login-btn"]'))
    pick(mid(b))
    click(*tab_pos("Try it")); time.sleep(0.4)
    click(*center(button("Click"))); time.sleep(2.5)
    say("6 · Screenshot of one element", "Capture a product card and save it as a PNG.")
    card = rect_of(web('article[class="card"]:nth(4)'))
    pick((card[0] + 5, (card[1] + card[3]) // 2))  # the card's padding, not its picture
    click(*tab_pos("Try it")); time.sleep(0.4)
    png_rel = f"product_card_{int(time.time())}.png"
    png = os.path.join(STAGE_FILES, png_rel)
    click(*center(button("Screenshot…"))); time.sleep(1.8)
    type_text(png_rel, cps=40); time.sleep(0.4); key("enter")
    until(lambda: os.path.exists(png), 6)
    time.sleep(0.8)

    def show_png():
        lab = QLabel()
        lab.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        pm = QPixmap(png)
        lab.setPixmap(pm)
        lab.setStyleSheet("background:#fff;border:3px solid #14b8a6")
        lab.adjustSize()
        lab.move(MON_X + 420, MON_Y + 360)
        lab.show()
        STATE["png_label"] = lab
    if os.path.exists(png):
        gui(show_png)
        say("6 · Screenshot of one element", f"Saved {os.path.basename(png)}", 3.0)
        gui(lambda: STATE["png_label"].close())
    say("6 · Desktop apps: Set value and Toggle", "Character Map: set the 'Characters to copy' box through UI Automation ...")
    win32.bring_to_front(STATE["app_hwnd"]); time.sleep(0.6)
    pick(mid(rect_of(app_sel('Edit[automationid="104"]'))))
    click(*tab_pos("Try it")); time.sleep(0.4)
    click(*center(W.value_edit)); key("ctrl+a"); type_text("Spectra ✓")
    click(*center(button("Set value"))); time.sleep(1.0)
    win32.bring_to_front(STATE["app_hwnd"]); time.sleep(2.2)
    say("6 · Desktop apps: Set value and Toggle", "... and toggle the 'Advanced view' check box: the dialog grows.")
    pick(mid(rect_of(app_sel('CheckBox[automationid="119"]'))))
    click(*tab_pos("Try it")); time.sleep(0.4)
    click(*center(button("Toggle"))); time.sleep(0.8)
    win32.bring_to_front(STATE["app_hwnd"]); time.sleep(2.5)
    activate_spectra()
    click(*center(button("Toggle"))); time.sleep(1.5)


def ch7_example():
    ensure_browser()
    say("7 · Any site: example.com", "Switch to the first tab and pick an element of a real public page.")
    show_tab("example.com")
    ex = 'web:tab[host="example.com"] >> '
    hover = []
    for tail in ("svg", "p:nth(1)", "p:nth(3)"):
        try:
            hover.append(mid(rect_of(ex + tail, 3)))
        except LookupError:
            pass
    try:
        target = mid(rect_of(ex + "a", 3))
    except LookupError:
        target = mid(rect_of(ex + "p:nth(2)", 3))
    pick(target, hover_path=hover)
    time.sleep(3.5)


def ch8_extras():
    ensure_browser()
    say("8 · Follow focus", "Turn on Follow focus, then Tab through the form: Spectra follows the keyboard focus.")
    show_tab("127.0.0.1")
    activate_spectra()
    click(*action_pos(W.focus_act)); time.sleep(0.6)
    e = rect_of(web('input[id="email"]'))
    click(*mid(e)); time.sleep(1.8)
    for _ in range(3):
        key("tab"); time.sleep(1.8)
    activate_spectra()
    click(*action_pos(W.focus_act)); time.sleep(0.8)
    say("8 · Raw view", "Shows every UI Automation element, not only the control view.")
    click(*action_pos(W.raw_act)); time.sleep(2.0)
    click(*action_pos(W.raw_act)); time.sleep(1.0)
    say("8 · Save and open selectors", "Ctrl+S saves the selector to a file, Ctrl+O loads and validates it.")
    sel_rel = f"add_to_cart_{int(time.time())}.sel"
    sel_file = os.path.join(STAGE_FILES, sel_rel)
    activate_spectra()
    key("ctrl+s"); time.sleep(1.5); type_text(sel_rel, cps=40); key("enter"); time.sleep(1.2)
    click(*center(W.sel_text)); key("ctrl+a"); key("del"); time.sleep(0.8)
    key("ctrl+o"); time.sleep(1.5); type_text(sel_rel, cps=40); key("enter")
    show_validation(2.0)
    say("8 · Syntax help (F1)", "The whole selector language on one page.")
    key("f1"); time.sleep(4.5); key("enter"); time.sleep(0.5)
    say("8 · The log", "Connections, warnings and errors are listed here.")
    click(*tab_pos("Log")); time.sleep(2.5)
    say("8 · Use selectors from Python", "The same selectors work in scripts: find an element and click it.")
    port = STATE["port"]
    script = (f"from spectra.api import Spectra\n\n"
              f"s = Spectra(browser_port={port})\n"
              f"buttons = s.find_all('web:tab[title=\"Spectra Demo Store\"] >> button[class=\"add\"]')\n"
              f"print(len(buttons), 'Add to cart buttons')\n"
              f"buttons[1].click()      # Nimbus Keyboard\n"
              f"buttons[5].click()      # Halo Webcam\n"
              f"cart = s.find('web:tab[title=\"Spectra Demo Store\"] >> span[id=\"cart\"]')\n"
              f"print('cart now shows:', cart.get('text'))\n")

    def open_panel():
        p = CodePanel(); p.code.setPlainText(script); p.show(); STATE["panel"] = p
    gui(open_panel)
    time.sleep(3.0)
    proc = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=60)
    out = (proc.stdout + proc.stderr).strip() or "(no output)"
    gui(lambda: STATE["panel"].out.setPlainText("> python script.py\n" + out))
    log("API demo output:", out)
    time.sleep(2.5)
    win32.bring_to_front(STATE["chrome_hwnd"]); time.sleep(3.0)
    gui(lambda: STATE["panel"].close())


def ch9_outro():
    activate_spectra()
    say("Spectra Inspector", "Desktop apps (UI Automation, MSAA, Win32) · web pages without an extension (DOM, shadow DOM, iframes) · "
        "Java apps · live selector editor with wildcards, regex and :nth · locators & code · try-it actions · Python API", 7)


CHAPTERS = [(1, "Intro and layout", ch1_intro), (2, "Pick on the desktop", ch2_desktop),
            (3, "Selector editor", ch3_editor), (4, "File Explorer and wildcards", ch4_explorer),
            (5, "Web pages: pick, F4, shadow DOM, iframes, repair", ch5_browser),
            (6, "Try it actions", ch6_tryit), (7, "example.com", ch7_example),
            (8, "Follow focus, raw view, files, help, Python API", ch8_extras), (9, "Outro", ch9_outro)]


# ================================================================= recording + run
def start_recorder():
    if DRY:
        return None
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "gdigrab", "-framerate", "30", "-offset_x", str(MON_X),
           "-offset_y", str(MON_Y), "-video_size", f"{SCREEN_W}x{SCREEN_H}", "-draw_mouse", "1", "-i", "desktop",
           "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p", RAW]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    time.sleep(1.5)
    return p


def stop_recorder(p):
    if p is None:
        return
    try:
        p.stdin.write(b"q"); p.stdin.flush()
        p.wait(30)
    except Exception:  # noqa: BLE001
        p.kill()


def scenario():
    marks = []
    rec = None
    failures = []
    try:
        time.sleep(2.0)
        rec = start_recorder()
        t0 = time.monotonic()
        for num, title, fn in CHAPTERS:
            if ONLY and num not in ONLY:
                continue
            marks.append((num, title, time.monotonic() - t0))
            log(f"=== chapter {num}: {title}")
            try:
                fn()
            except Exception:  # noqa: BLE001
                tb = traceback.format_exc()
                failures.append((num, tb))
                log(f"!!! chapter {num} failed:\n{tb}")
        marks.append((0, "end", time.monotonic() - t0))
    finally:
        stop_recorder(rec)
        with open(os.path.join(OUT_DIR, "marks.json"), "w") as f:
            json.dump({"marks": marks, "failures": failures}, f, indent=1)
        log("done; failures:", len(failures))
        BRIDGE.sig.emit((app.quit, {}, threading.Event()))  # quit on the GUI thread


def main():
    global W, backdrop, caption
    apply_dark_theme(app)
    import shutil
    shutil.rmtree(DEMO_PROFILE, ignore_errors=True)  # fresh throw-away browser profile every run
    setup_stage()
    port = free_port()
    STATE["http"] = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                                     cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    STATE["url"] = f"http://127.0.0.1:{port}/demo_shop.html"
    backdrop = Backdrop(); backdrop.show()
    caption = Caption()
    W = MainWindow()
    W.minimize_act.setChecked(True)
    W.live_check.setChecked(True)
    W.show()
    W.setGeometry(SPECTRA_RECT[0] + 8, SPECTRA_RECT[1] + 31, SPECTRA_RECT[2] - 16, SPECTRA_RECT[3] - 39)
    ALLOWED_HWNDS.add(int(W.winId()))
    from PySide6.QtWidgets import QDockWidget
    docks = {d.objectName(): d for d in W.findChildren(QDockWidget)}
    QTimer.singleShot(400, lambda: (W.resizeDocks([docks["tree_dock"], docks["props_dock"]], [220, 360], Qt.Horizontal),
                                    W.resizeDocks([docks["out_dock"]], [200], Qt.Vertical)))
    QTimer.singleShot(500, W.refresh_tree)
    u32.SetCursorPos(MON_X + SCREEN_W // 2, MON_Y + SCREEN_H // 2)  # start on the demo monitor
    threading.Thread(target=scenario, name="demo-scenario", daemon=True).start()
    try:
        app.exec()
    finally:
        cleanup()


def setup_stage():
    import shutil
    for d in (STAGE_FILES, STAGE_STORE, STAGE_SHOTS):
        os.makedirs(d, exist_ok=True)
    for name in ("demo_shop.html", "README_demo.md"):
        if os.path.exists(os.path.join(HERE, name)):
            shutil.copy(os.path.join(HERE, name), STAGE_STORE)
    for i, name in enumerate(("aurora.txt", "nimbus.txt", "comet.txt")):
        with open(os.path.join(STAGE_SHOTS, name), "w") as f:
            f.write(f"sample file {i + 1}\n")


def cleanup():
    log("cleanup")
    try:
        W.close()
    except Exception:  # noqa: BLE001
        pass
    for h in STATE.get("explorer_hwnds", []):
        u32.PostMessageW(h, 0x0010, 0, 0)
    if STATE.get("app_proc"):
        STATE["app_proc"].kill()
    if STATE.get("chrome_pid"):
        subprocess.call(["taskkill", "/F", "/T", "/PID", str(STATE["chrome_pid"])], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
    if STATE.get("http"):
        STATE["http"].kill()
    win32.remove_all_hooks()
    import shutil
    for name in os.listdir(STAGE_FILES) if os.path.isdir(STAGE_FILES) else []:
        try:  # keep what was saved on camera next to the recording
            shutil.copy(os.path.join(STAGE_FILES, name), OUT_DIR)
        except OSError:
            pass
    shutil.rmtree(STAGE, ignore_errors=True)


if __name__ == "__main__":
    main()
    os._exit(0)
