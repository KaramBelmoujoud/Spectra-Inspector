"""Live UI Automation checks against Character Map (charmap.exe). Windows only.

Character Map is a classic Win32 app that ships with Windows: the process we
start owns its window, so the tests only ever touch (and close) that instance,
never windows the user already has open. The windows open without taking the
keyboard focus. Set SPECTRA_TEST_SCREEN="x,y" (the top-left corner of a monitor,
e.g. "2560,365") to open them on another monitor than the main one."""
import os
import shutil
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="needs Windows")


@pytest.fixture(scope="module")
def spectra():
    from spectra.api import Spectra
    s = Spectra()
    assert s.service.uia is not None, s.service.errors
    return s


SCREEN = tuple(int(v) for v in os.environ["SPECTRA_TEST_SCREEN"].split(",")) \
    if os.environ.get("SPECTRA_TEST_SCREEN") else (0, 0)


def start_charmap(offset=(100, 100)) -> subprocess.Popen:
    """Start Character Map without activating it, placed on SCREEN."""
    from spectra.backends import win32
    if not shutil.which("charmap.exe"):
        pytest.skip("charmap.exe is not available")
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 4  # SW_SHOWNOACTIVATE
    p = subprocess.Popen(["charmap.exe"], startupinfo=si)
    for _ in range(50):
        hws = [h for h in win32.top_windows() if win32.pid_tid(h)[0] == p.pid]
        if hws:
            # SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
            win32.user32.SetWindowPos(hws[0], None, SCREEN[0] + offset[0], SCREEN[1] + offset[1], 0, 0, 0x15)
            break
        time.sleep(0.1)
    return p


def raise_without_focus(hwnd: int):
    """Put a window on top of the others without taking the keyboard focus."""
    from spectra.backends import win32
    for z in (-1, -2):  # HWND_TOPMOST then HWND_NOTOPMOST: on top, but not "always on top"
        win32.user32.SetWindowPos(hwnd, win32.wintypes.HWND(z), 0, 0, 0, 0, 0x0013)  # NOSIZE | NOMOVE | NOACTIVATE


@pytest.fixture(scope="module")
def target():
    p = start_charmap()
    time.sleep(2.0)
    yield f'uia:Window[pid="{p.pid}"]'
    p.kill()


def test_desktop_has_windows(spectra):
    kids = spectra.driver.call(lambda: spectra.service.uia.root().children())
    assert len(kids) > 0


def test_find_and_generate(spectra, target):
    win = spectra.find(target, timeout=10)
    assert win.rect is not None
    edit = spectra.find(f"{target} >> Edit", timeout=5)
    assert edit.get("controlid") == "104"  # Win32 control id of the 'Characters to copy' box
    eng = spectra.service.engine
    sel, res = spectra.driver.call(lambda: eng.generate(edit.node))
    assert len(res.matches) == 1, sel.to_text()
    assert res.matches[0] == edit.node


def test_point_lookup(spectra, target):
    win = spectra.find(target, timeout=10)
    raise_without_focus(int(spectra.driver.call(win.node.hwnd)))
    time.sleep(0.5)
    l, t, r, b = win.rect
    node = spectra.driver.call(lambda: spectra.service.element_at((l + r) // 2, (t + b) // 2))
    assert node is not None
    props = spectra.driver.call(node.properties)
    assert any(k == "ProcessName" and v == "charmap.exe" for _, k, v in props)


def test_desktop_children_match_uia(spectra, target):
    """The fast HWND-based desktop listing must agree with UIA's own FindAll."""
    from spectra.backends import uia as U
    b = spectra.service.uia

    def both():
        arr = b.root().el.FindAllBuildCache(U.TreeScope_Children, b.view_condition, b.cache_request)
        old = [b.wrap(arr.GetElement(i)).key() for i in range(arr.Length)]
        new = [n.key() for n in b.desktop_children(b.view_condition)]
        return old, new
    old, new = spectra.driver.call(both)
    assert set(new) == set(old)


def test_new_window_found_after_tree_was_loaded(spectra):
    """Searching must not use a desktop child list cached before the window opened."""
    spectra.driver.call(lambda: spectra.service.uia.root().children())
    p = start_charmap(offset=(700, 100))  # classic Win32 app: the Popen pid owns the window
    try:
        el = spectra.find(f'uia:Window[pid="{p.pid}"]', timeout=15)
        assert el.node.process() == "charmap.exe"
    finally:
        p.kill()


def test_bulk_properties_match_single_reads(spectra, target):
    win = spectra.find(target, timeout=10)

    def both():
        n = win.node
        bulk = {k: v for _, k, v in n.properties()}
        n._load_all_props = lambda: False  # force the one-call-per-property path
        n.refresh()
        single = {k: v for _, k, v in n.properties()}
        return bulk, single
    bulk, single = spectra.driver.call(both)
    for k in ("Name", "ClassName", "ProcessId", "ProcessName", "ControlType"):
        assert bulk.get(k) == single.get(k), k
    assert len(bulk) >= len(single) - 3


def test_click_catcher_swallows_press_and_release():
    """The picker's mouse hook: a press outside Spectra is reported and swallowed,
    its release is swallowed too, other mouse messages pass through."""
    import ctypes
    from spectra.backends import win32
    clicks = []
    released = []
    cc = win32.ClickCatcher(lambda b, x, y: clicks.append((b, x, y)), on_released=lambda: released.append(1))
    passed = []
    win32.user32.CallNextHookEx = lambda *a: passed.append(a[2]) or 0  # don't touch the real hook chain
    try:
        hw = win32.desktop_windows()[0]
        l, t, r, b = win32.window_rect(hw)
        info = win32.MSLLHOOKSTRUCT()
        info.pt.x, info.pt.y = (l + r) // 2, (t + b) // 2
        lp = ctypes.addressof(info)
        assert cc._callback(0, win32.WM_LBUTTONDOWN, lp) == 1
        assert clicks == [("left", info.pt.x, info.pt.y)]
        assert cc.stop() is False  # button still held: keep the hook for its release
        assert cc._callback(0, win32.WM_LBUTTONUP, lp) == 1 and released == [1]
        cc._callback(0, 0x0200, lp)  # WM_MOUSEMOVE passes through
        cc._callback(0, win32.WM_LBUTTONDOWN, lp)  # stopped: no more captures
        assert passed == [0x0200, win32.WM_LBUTTONDOWN] and len(clicks) == 1
    finally:
        del win32.user32.CallNextHookEx  # back to the real function
        win32.user32.CallNextHookEx.argtypes = [win32.wintypes.HHOOK, ctypes.c_int, win32.wintypes.WPARAM,
                                                win32.wintypes.LPARAM]
        win32.user32.CallNextHookEx.restype = ctypes.c_ssize_t
        cc.uninstall()


def test_click_catcher_stays_alive_while_hooked():
    """Regression: The picker's mouse hook object was only referenced by a Qt timer
    (which holds bound methods weakly); garbage collection freed its ctypes
    callback while Windows still called it, crashing the app on the next click."""
    import gc
    import weakref
    from spectra.backends import win32
    cc = win32.ClickCatcher(lambda *a: None)
    try:
        assert cc.install()
        ref = weakref.ref(cc)
        del cc
        gc.collect()
        assert ref() is not None, "hooked catcher was garbage collected"
    finally:
        win32.remove_all_hooks()  # quickly: this thread doesn't pump messages
    gc.collect()
    assert ref() is None


# last: it leaves this process with Qt/overlay windows that nobody pumps, and a UIA
# desktop-wide FindAll would then wait on them
def test_highlighter_does_not_crash():
    from PySide6.QtWidgets import QApplication
    from spectra.gui.overlay import Highlighter
    app = QApplication.instance() or QApplication([])
    h = Highlighter()
    x, y = SCREEN
    h.show((x + 100, y + 100, x + 300, y + 200))
    app.processEvents()
    h.show_many([((x + 10, y + 10, x + 50, y + 50), (255, 0, 0)), ((x + 60, y + 60, x + 90, y + 90), (0, 0, 255))])
    app.processEvents()
    h.hide()
