"""On-screen highlight rectangles.

On Windows the frames are native layered, click-through, top-most windows
placed in physical pixels, so they line up on mixed-DPI multi-monitor
setups. Elsewhere a Qt fallback is used (development only).
"""
from __future__ import annotations

import sys
from typing import List, Optional, Sequence, Tuple

Rect = Tuple[int, int, int, int]
PRIMARY = (20, 184, 166)     # the selected element (teal)
SECONDARY = (245, 158, 11)   # other matches (amber)
ANCHOR = (167, 139, 250)     # anchors (violet)


class _Win32Frames:
    THICK = 3

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ct, self.wt = ctypes, wintypes
        u, g, k = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32
        self.u, self.g = u, g
        LRESULT = ctypes.c_ssize_t
        self.WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.DefWindowProcW.restype = LRESULT
        u.CreateWindowExW.restype = wintypes.HWND
        u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wintypes.UINT]
        u.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.InvalidateRect.argtypes = [wintypes.HWND, wintypes.LPVOID, wintypes.BOOL]
        u.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
        u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        g.CreateSolidBrush.restype = wintypes.HBRUSH
        g.CreateSolidBrush.argtypes = [wintypes.COLORREF]
        g.DeleteObject.argtypes = [wintypes.HGDIOBJ]

        class PAINTSTRUCT(ctypes.Structure):
            _fields_ = [("hdc", wintypes.HDC), ("fErase", wintypes.BOOL), ("rcPaint", wintypes.RECT),
                        ("fRestore", wintypes.BOOL), ("fIncUpdate", wintypes.BOOL),
                        ("rgbReserved", ctypes.c_byte * 32)]
        self.PAINTSTRUCT = PAINTSTRUCT
        u.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
        u.BeginPaint.restype = wintypes.HDC
        u.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]

        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", self.WNDPROC),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
                        ("hIconSm", wintypes.HICON)]
        u.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
        k.GetModuleHandleW.restype = wintypes.HMODULE
        self.hinst = k.GetModuleHandleW(None)
        self.KEY = 0x00FF00FF  # magenta, made transparent
        self.key_brush = g.CreateSolidBrush(self.KEY)
        self.colors = {}
        self.brushes = {}
        self._proc = self.WNDPROC(self._wndproc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._proc
        wc.hInstance = self.hinst
        wc.lpszClassName = "SpectraHighlightFrame"
        u.RegisterClassExW(ctypes.byref(wc))
        self.pool: List[int] = []
        self.placed = {}
        self.shown = 0

    def _brush(self, rgb):
        cref = rgb[0] | (rgb[1] << 8) | (rgb[2] << 16)
        if cref not in self.brushes:
            self.brushes[cref] = self.g.CreateSolidBrush(cref)
        return self.brushes[cref]

    def _wndproc(self, hwnd, msg, wp, lp):
        WM_PAINT, WM_NCHITTEST, WM_ERASEBKGND = 0x000F, 0x0084, 0x0014
        if msg == WM_NCHITTEST:
            return -1  # HTTRANSPARENT
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_PAINT:
            ps = self.PAINTSTRUCT()
            hdc = self.u.BeginPaint(hwnd, self.ct.byref(ps))
            rc = self.wt.RECT()
            self.u.GetClientRect(hwnd, self.ct.byref(rc))
            self.u.FillRect(hdc, self.ct.byref(rc), self.key_brush)
            br = self._brush(self.colors.get(int(hwnd or 0), PRIMARY))
            t = self.THICK
            W, H = rc.right, rc.bottom
            for band in ((0, 0, W, t), (0, H - t, W, H), (0, 0, t, H), (W - t, 0, W, H)):
                r = self.wt.RECT(*band)
                self.u.FillRect(hdc, self.ct.byref(r), br)
            self.u.EndPaint(hwnd, self.ct.byref(ps))
            return 0
        return self.u.DefWindowProcW(hwnd, msg, wp, lp)

    def _new(self) -> int:
        WS_POPUP = 0x80000000
        EX = 0x00080000 | 0x00000020 | 0x00000008 | 0x00000080 | 0x08000000  # LAYERED|TRANSPARENT|TOPMOST|TOOLWINDOW|NOACTIVATE
        hwnd = self.u.CreateWindowExW(EX, "SpectraHighlightFrame", "", WS_POPUP, 0, 0, 10, 10,
                                      None, None, self.hinst, None)
        self.u.SetLayeredWindowAttributes(hwnd, self.KEY, 255, 0x1)  # LWA_COLORKEY
        return int(hwnd)

    def show(self, items: Sequence[Tuple[Rect, tuple]]):
        items = list(items)[:200]
        while len(self.pool) < len(items):
            self.pool.append(self._new())
        HWND_TOPMOST = self.wt.HWND(-1)
        SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0010, 0x0040
        pad = self.THICK
        for i, (hwnd, (r, color)) in enumerate(zip(self.pool, items)):
            if i < self.shown and self.placed.get(hwnd) == (tuple(r), color):
                continue  # already there: moving/repainting it again only flickers
            self.placed[hwnd] = (tuple(r), color)
            self.colors[hwnd] = color
            l, t, rr, b = r
            self.u.SetWindowPos(hwnd, HWND_TOPMOST, l - pad, t - pad, max(rr - l + 2 * pad, 2 * pad + 1),
                                max(b - t + 2 * pad, 2 * pad + 1), SWP_NOACTIVATE | SWP_SHOWWINDOW)
            self.u.InvalidateRect(hwnd, None, True)
        for hwnd in self.pool[len(items):self.shown]:
            self.u.ShowWindow(hwnd, 0)
        self.shown = len(items)

    def hide(self):
        for hwnd in self.pool[:self.shown]:
            self.u.ShowWindow(hwnd, 0)
        self.shown = 0


class _QtFrames:
    def __init__(self):
        self.frames = []

    def show(self, items):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QPainter, QPen
        from PySide6.QtWidgets import QWidget

        class Frame(QWidget):
            def __init__(self):
                super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                                 Qt.WindowTransparentForInput)
                self.setAttribute(Qt.WA_TranslucentBackground)
                self.setAttribute(Qt.WA_ShowWithoutActivating)
                self.color = QColor(*PRIMARY)

            def paintEvent(self, _):
                p = QPainter(self)
                p.setPen(QPen(self.color, 3))
                p.drawRect(self.rect().adjusted(1, 1, -2, -2))

        items = list(items)[:200]
        while len(self.frames) < len(items):
            self.frames.append(Frame())
        for f, (r, color) in zip(self.frames, items):
            f.color = QColor(*color)
            f.setGeometry(r[0] - 3, r[1] - 3, r[2] - r[0] + 6, r[3] - r[1] + 6)
            f.show()
            f.update()
        for f in self.frames[len(items):]:
            f.hide()

    def hide(self):
        for f in self.frames:
            f.hide()


class Highlighter:
    def __init__(self):
        self.impl = None
        if sys.platform == "win32":
            try:
                self.impl = _Win32Frames()
            except Exception:  # noqa: BLE001
                self.impl = None
        if self.impl is None:
            self.impl = _QtFrames()

    def show(self, rect: Optional[Rect], color=PRIMARY):
        if rect:
            self.impl.show([(rect, color)])
        else:
            self.impl.hide()

    def show_many(self, items: Sequence[Tuple[Rect, tuple]]):
        items = [(r, c) for r, c in items if r]
        if items:
            self.impl.show(items)
        else:
            self.impl.hide()

    def hide(self):
        self.impl.hide()
