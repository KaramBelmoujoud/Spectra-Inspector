"""Thin ctypes helpers for Win32 (only imported on Windows)."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from functools import lru_cache
from typing import List, Optional, Tuple

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GA_PARENT, GA_ROOT, GA_ROOTOWNER = 1, 2, 3
GWL_STYLE, GWL_EXSTYLE = -16, -20
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wintypes.UINT]
user32.GetDlgCtrlID.argtypes = [wintypes.HWND]
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]

VK_CONTROL, VK_LCONTROL, VK_SHIFT, VK_ESCAPE, VK_F2 = 0x11, 0xA2, 0x10, 0x1B, 0x71
VK_LBUTTON, VK_MENU = 0x01, 0x12


def h(hwnd) -> int:
    return int(hwnd or 0)


def cursor_pos() -> Tuple[int, int]:
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def window_from_point(x: int, y: int) -> int:
    return h(user32.WindowFromPoint(wintypes.POINT(x, y)))


def root_window(hwnd: int) -> int:
    return h(user32.GetAncestor(hwnd, GA_ROOT))


def class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def window_text(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def pid_tid(hwnd: int) -> Tuple[int, int]:
    pid = wintypes.DWORD()
    tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value, tid


def window_rect(hwnd: int) -> Tuple[int, int, int, int]:
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def client_rect_screen(hwnd: int) -> Tuple[int, int, int, int]:
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, pt.x + r.right, pt.y + r.bottom


def is_visible(hwnd: int) -> bool:
    return bool(user32.IsWindowVisible(hwnd))


def styles(hwnd: int) -> Tuple[int, int]:
    return user32.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF, user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF


def control_id(hwnd: int) -> int:
    return user32.GetDlgCtrlID(hwnd)


def top_windows(visible_only: bool = True) -> List[int]:
    out: List[int] = []

    def cb(hwnd, _):
        if not visible_only or user32.IsWindowVisible(hwnd):
            out.append(h(hwnd))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
GW_OWNER = 4


def owner(hwnd: int) -> int:
    return h(user32.GetWindow(hwnd, GW_OWNER))


def is_cloaked(hwnd: int) -> bool:
    """True for windows DWM hides (other virtual desktops, suspended UWP frames...)."""
    v = wintypes.DWORD()
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 14, ctypes.byref(v), 4)  # DWMWA_CLOAKED
    except OSError:
        return False
    return bool(v.value)


def desktop_windows() -> List[int]:
    """Visible top-level windows that UI Automation shows directly under the
    desktop: windows owned by another visible window appear under their owner,
    and cloaked or empty windows are not shown."""
    out = []
    for hw in top_windows():
        ow = owner(hw)
        if ow and is_visible(ow):
            continue
        l, t, r, b = window_rect(hw)
        if r <= l or b <= t or is_cloaked(hw):
            continue
        if styles(hw)[1] & 0x80020 == 0x80020:  # WS_EX_LAYERED | WS_EX_TRANSPARENT: click-through overlay
            continue
        out.append(hw)
    return out


def child_windows(parent: int) -> List[int]:
    out: List[int] = []

    def cb(hwnd, _):
        out.append(h(hwnd))
        return True

    user32.EnumChildWindows(parent, WNDENUMPROC(cb), 0)
    return out


@lru_cache(maxsize=512)
def _process_path(pid: int) -> str:
    hp = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not hp:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(hp, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(hp)


def process_path(pid: int) -> str:
    return _process_path(int(pid)) if pid else ""


def process_name(pid: int) -> str:
    return os.path.basename(process_path(pid)).lower()


def bring_to_front(hwnd: int):
    if not hwnd:
        return
    user32.ShowWindow(hwnd, 9 if user32.IsIconic(hwnd) else 5)  # SW_RESTORE / SW_SHOW
    if user32.SetForegroundWindow(hwnd) and h(user32.GetForegroundWindow()) == hwnd:
        return
    # Windows refuses SetForegroundWindow from a background process; sharing the
    # input state with the current foreground thread lifts that restriction.
    fg = h(user32.GetForegroundWindow())
    fg_tid = pid_tid(fg)[1] if fg else 0
    me = kernel32.GetCurrentThreadId()
    attached = bool(fg_tid and fg_tid != me and user32.AttachThreadInput(me, fg_tid, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(me, fg_tid, False)


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


LowLevelMouseProc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, LowLevelMouseProc, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0201, 0x0202, 0x0204, 0x0205
_INSTALLED_HOOKS: set = set()  # ClickCatchers whose hook is live (keeps their callbacks alive)


def remove_all_hooks():
    for c in list(_INSTALLED_HOOKS):
        c.uninstall()


class ClickCatcher:
    """Global low-level mouse hook used while picking: left/right clicks
    outside our own windows are swallowed (the target app never sees them)
    and reported as on_click("left" | "right", x, y) on button press; the
    matching release is swallowed too, so the app gets no orphan button-up.

    Install it from a thread that runs a message loop (the GUI thread); the
    callback must return quickly, so it should only schedule work."""

    def __init__(self, on_click, on_released=None):
        self.on_click = on_click
        self.on_released = on_released  # called (inside the hook) after a swallowed release once stopped
        self.own_pid = os.getpid()
        self.armed = True
        self._swallow_up = None
        self._hook = None
        self._proc = LowLevelMouseProc(self._callback)  # keep a reference: the hook calls it

    def stop(self) -> bool:
        """Stop capturing. Returns True when the hook can be removed now; False
        while a button is still held, so its release can still be swallowed."""
        self.armed = False
        if self._swallow_up is None:
            self.uninstall()
            return True
        return False

    def install(self) -> bool:
        if self._hook is None:
            self._hook = user32.SetWindowsHookExW(14, self._proc, None, 0)  # WH_MOUSE_LL
            if self._hook:
                # Windows calls self._proc on every mouse event until the hook is removed. If this
                # object were garbage collected first, ctypes would free that callback and the next
                # mouse event would jump into freed memory and kill the process. Callers (e.g. Qt
                # timers, which only hold weak references to bound methods) can't be trusted to
                # keep it alive, so the module does.
                _INSTALLED_HOOKS.add(self)
        return bool(self._hook)

    def uninstall(self):
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
        _INSTALLED_HOOKS.discard(self)

    def _callback(self, code, wparam, lparam):
        try:
            if code == 0 and self.armed and wparam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN):
                info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                x, y = info.pt.x, info.pt.y
                hw = window_from_point(x, y)
                if not (hw and pid_tid(hw)[0] == self.own_pid):  # clicks on Spectra itself pass through
                    self._swallow_up = WM_LBUTTONUP if wparam == WM_LBUTTONDOWN else WM_RBUTTONUP
                    self.on_click("left" if wparam == WM_LBUTTONDOWN else "right", x, y)
                    return 1
            elif code == 0 and wparam == self._swallow_up:
                self._swallow_up = None
                if not self.armed and self.on_released:
                    self.on_released()
                return 1
        except Exception:  # noqa: BLE001 - an error must never leave the mouse dead
            pass
        return user32.CallNextHookEx(None, code, wparam, lparam)


def win32_properties(hwnd: int) -> List[Tuple[str, str, str]]:
    if not hwnd:
        return []
    pid, tid = pid_tid(hwnd)
    st, ex = styles(hwnd)
    root = root_window(hwnd)
    rows = [
        ("Win32", "hwnd", f"0x{hwnd:08X} ({hwnd})"),
        ("Win32", "class", class_name(hwnd)),
        ("Win32", "text", window_text(hwnd)),
        ("Win32", "control id", str(control_id(hwnd))),
        ("Win32", "style", f"0x{st:08X}"),
        ("Win32", "ex style", f"0x{ex:08X}"),
        ("Win32", "visible", str(is_visible(hwnd))),
        ("Win32", "window rect", ", ".join(map(str, window_rect(hwnd)))),
        ("Win32", "thread id", str(tid)),
        ("Win32", "process id", str(pid)),
        ("Win32", "process path", process_path(pid)),
        ("Win32", "top-level hwnd", f"0x{root:08X}"),
        ("Win32", "top-level class", class_name(root)),
    ]
    return rows


def enable_dpi_awareness():
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- browser glue

CHROME_TOP_CLASS = "Chrome_WidgetWin_1"
CHROME_RENDER_CLASS = "Chrome_RenderWidgetHostHWND"
BROWSER_PROCESSES = {"chrome.exe", "msedge.exe", "brave.exe", "opera.exe", "vivaldi.exe", "chromium.exe",
                     "msedgewebview2.exe"}


def render_widget_at(x: int, y: int) -> Optional[int]:
    """The Chromium page viewport window under the point, if any."""
    hw = window_from_point(x, y)
    cur = hw
    for _ in range(6):
        if not cur:
            break
        if class_name(cur) == CHROME_RENDER_CLASS:
            return cur
        cur = h(user32.GetParent(cur))
    root = root_window(hw) if hw else 0
    if root and class_name(root) == CHROME_TOP_CLASS:
        for c in child_windows(root):
            if class_name(c) == CHROME_RENDER_CLASS and is_visible(c):
                l, t, r, b = client_rect_screen(c)
                if l <= x < r and t <= y < b:
                    return c
    return None


def chromium_viewports() -> List[Tuple[int, int, str, Tuple[int, int, int, int]]]:
    """(top hwnd, render hwnd, top title, client rect) for visible Chromium viewports."""
    out = []
    for top in top_windows():
        if class_name(top) != CHROME_TOP_CLASS:
            continue
        title = window_text(top)
        for c in child_windows(top):
            if class_name(c) == CHROME_RENDER_CLASS and is_visible(c):
                rc = client_rect_screen(c)
                if rc[2] - rc[0] > 10 and rc[3] - rc[1] > 10:
                    out.append((top, c, title, rc))
    return out
