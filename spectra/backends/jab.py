"""Java back end through the Java Access Bridge (Swing, AWT and JavaFX-with-JAB apps).

Requirements: a Java runtime with the Access Bridge enabled
(run ``jabswitch -enable`` once, then restart the Java app), and
``WindowsAccessBridge-64.dll`` reachable (it ships in every JRE/JDK ``bin`` folder;
Spectra looks in JAVA_HOME, PATH and System32).

The bridge talks to JVMs with window messages, so every call runs on one
dedicated thread that pumps messages.
"""
from __future__ import annotations

import ctypes
import glob
import os
import queue
import threading
import time
from concurrent.futures import Future
from ctypes import wintypes
from typing import Dict, List, Optional

from ..core.node import Backend, Node
from . import win32

JOBJECT64 = ctypes.c_int64
VMID = ctypes.c_long
MAX_STRING = 1024
SHORT_STRING = 256


class AccessibleContextInfo(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_wchar * MAX_STRING),
        ("description", ctypes.c_wchar * MAX_STRING),
        ("role", ctypes.c_wchar * SHORT_STRING),
        ("role_en_US", ctypes.c_wchar * SHORT_STRING),
        ("states", ctypes.c_wchar * SHORT_STRING),
        ("states_en_US", ctypes.c_wchar * SHORT_STRING),
        ("indexInParent", ctypes.c_int32),
        ("childrenCount", ctypes.c_int32),
        ("x", ctypes.c_int32),
        ("y", ctypes.c_int32),
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("accessibleComponent", wintypes.BOOL),
        ("accessibleAction", wintypes.BOOL),
        ("accessibleSelection", wintypes.BOOL),
        ("accessibleText", wintypes.BOOL),
        ("accessibleInterfaces", wintypes.BOOL),
    ]


def _find_dll() -> Optional[str]:
    names = ["WindowsAccessBridge-64.dll"] if ctypes.sizeof(ctypes.c_void_p) == 8 else \
        ["WindowsAccessBridge-32.dll", "WindowsAccessBridge.dll"]
    dirs = []
    if os.environ.get("JAVA_HOME"):
        dirs += [os.path.join(os.environ["JAVA_HOME"], "bin"), os.path.join(os.environ["JAVA_HOME"], "jre", "bin")]
    dirs += os.environ.get("PATH", "").split(os.pathsep)
    dirs.append(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32"))
    for pattern in (r"%ProgramFiles%\Java\*\bin", r"%ProgramFiles%\Eclipse Adoptium\*\bin",
                    r"%ProgramFiles%\Microsoft\jdk*\bin", r"%ProgramFiles%\Zulu\*\bin",
                    r"%ProgramFiles%\Amazon Corretto\*\bin"):
        dirs += glob.glob(os.path.expandvars(pattern))
    for d in dirs:
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    return None


class JabThread:
    """Owns the bridge DLL; runs every call on one message-pumping thread."""

    def __init__(self):
        self.dll = None
        self.error = ""
        self._q: "queue.Queue" = queue.Queue()
        self._ready = threading.Event()
        self._t = threading.Thread(target=self._run, name="java-access-bridge", daemon=True)
        self._t.start()
        self._ready.wait(5)

    def _run(self):
        path = _find_dll()
        if not path:
            self.error = "WindowsAccessBridge DLL not found (install a JRE/JDK and run 'jabswitch -enable')"
            self._ready.set()
            return
        try:
            dll = ctypes.CDLL(path)
            self._declare(dll)
            dll.Windows_run()
            self.dll = dll
        except OSError as e:
            self.error = f"could not load {path}: {e}"
            self._ready.set()
            return
        msg = wintypes.MSG()
        user32 = ctypes.windll.user32
        # give JVMs a moment to announce themselves
        pumped = 0
        while True:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            if not self._ready.is_set():
                pumped += 1
                if pumped > 20:
                    self._ready.set()
            try:
                fn, fut = self._q.get(timeout=0.02)
            except queue.Empty:
                continue
            try:
                fut.set_result(fn(self.dll))
            except Exception as e:  # noqa: BLE001
                fut.set_exception(e)

    @staticmethod
    def _declare(d):
        d.Windows_run.restype = None
        d.isJavaWindow.argtypes = [wintypes.HWND]
        d.isJavaWindow.restype = wintypes.BOOL
        d.getAccessibleContextFromHWND.argtypes = [wintypes.HWND, ctypes.POINTER(VMID), ctypes.POINTER(JOBJECT64)]
        d.getAccessibleContextFromHWND.restype = wintypes.BOOL
        d.getAccessibleContextInfo.argtypes = [VMID, JOBJECT64, ctypes.POINTER(AccessibleContextInfo)]
        d.getAccessibleContextInfo.restype = wintypes.BOOL
        d.getAccessibleChildFromContext.argtypes = [VMID, JOBJECT64, ctypes.c_int32]
        d.getAccessibleChildFromContext.restype = JOBJECT64
        d.getAccessibleParentFromContext.argtypes = [VMID, JOBJECT64]
        d.getAccessibleParentFromContext.restype = JOBJECT64
        d.getAccessibleContextAt.argtypes = [VMID, JOBJECT64, ctypes.c_int32, ctypes.c_int32,
                                             ctypes.POINTER(JOBJECT64)]
        d.getAccessibleContextAt.restype = wintypes.BOOL
        d.releaseJavaObject.argtypes = [VMID, JOBJECT64]
        d.releaseJavaObject.restype = None
        d.getHWNDFromAccessibleContext.argtypes = [VMID, JOBJECT64]
        d.getHWNDFromAccessibleContext.restype = wintypes.HWND
        d.isSameObject.argtypes = [VMID, JOBJECT64, JOBJECT64]
        d.isSameObject.restype = wintypes.BOOL
        d.getVirtualAccessibleName.argtypes = [VMID, JOBJECT64, ctypes.c_wchar_p, ctypes.c_int]
        d.getVirtualAccessibleName.restype = wintypes.BOOL
        d.getCurrentAccessibleValueFromContext.argtypes = [VMID, JOBJECT64, ctypes.c_wchar_p, ctypes.c_short]
        d.getCurrentAccessibleValueFromContext.restype = wintypes.BOOL

    def call(self, fn, timeout: float = 10.0):
        if self.dll is None:
            raise RuntimeError(self.error or "Java Access Bridge is not available")
        if threading.current_thread() is self._t:
            return fn(self.dll)
        fut: Future = Future()
        self._q.put((fn, fut))
        return fut.result(timeout)


class JavaNode(Node):
    tech = "java"

    def __init__(self, backend: "JavaBackend", vm: int, ac: int, parent: Optional[Node], path: tuple,
                 hwnd: int = 0):
        self.backend, self.vm, self.ac, self._parent, self.path, self.hwnd = backend, vm, ac, parent, path, hwnd
        self._info: Optional[dict] = None
        self._kids: Optional[List[JavaNode]] = None

    def __del__(self):
        try:
            if self.backend.bridge.dll is not None:
                vm, ac = self.vm, self.ac
                self.backend.bridge._q.put((lambda d: d.releaseJavaObject(vm, ac), Future()))
        except Exception:  # noqa: BLE001
            pass

    def info(self) -> dict:
        if self._info is None:
            def fn(d):
                ci = AccessibleContextInfo()
                if not d.getAccessibleContextInfo(self.vm, self.ac, ctypes.byref(ci)):
                    return {}
                vn = ctypes.create_unicode_buffer(MAX_STRING)
                vname = vn.value if d.getVirtualAccessibleName(self.vm, self.ac, vn, MAX_STRING) else ""
                val = ctypes.create_unicode_buffer(MAX_STRING)
                value = val.value if d.getCurrentAccessibleValueFromContext(self.vm, self.ac, val, MAX_STRING) else ""
                return {"name": ci.name, "description": ci.description, "role": ci.role_en_US,
                        "role_localized": ci.role, "states": ci.states_en_US, "index": ci.indexInParent,
                        "childcount": ci.childrenCount, "x": ci.x, "y": ci.y, "w": ci.width, "h": ci.height,
                        "virtualname": vname, "value": value,
                        "interfaces": ", ".join(k for k in ("Component", "Action", "Selection", "Text")
                                                if getattr(ci, "accessible" + k))}
            self._info = self.backend.bridge.call(fn)
        return self._info

    def key(self):
        return (self.vm, self.top_hwnd(), self.path)

    def top_hwnd(self) -> int:
        n = self
        while isinstance(n, JavaNode) and not n.hwnd and n._parent is not None:
            n = n._parent
        return n.hwnd if isinstance(n, JavaNode) else 0

    def role(self):
        return (self.info().get("role") or "unknown").replace(" ", "-")

    def selector_attrs(self):
        i = self.info()
        out = {}
        for k in ("name", "description", "virtualname", "states", "value"):
            if i.get(k):
                out[k] = i[k]
        out["index"] = str(i.get("index", ""))
        if self.hwnd:
            out["process"] = win32.process_name(win32.pid_tid(self.hwnd)[0])
        return out

    def suggested_attrs(self, is_top=False):
        a = self.selector_attrs()
        if is_top:
            return [k for k in ("process", "name") if a.get(k)]
        return ["name"] if a.get("name") else (["virtualname"] if a.get("virtualname") else [])

    def properties(self):
        i = self.info()
        rows = [("Java", k, str(v)) for k, v in i.items()]
        if self.hwnd:
            rows += win32.win32_properties(self.hwnd)
        return rows

    def rect(self):
        i = self.info()
        if not i or i.get("w", 0) <= 0 or i.get("h", 0) <= 0:
            return None
        return i["x"], i["y"], i["x"] + i["w"], i["y"] + i["h"]

    def children(self):
        if self._kids is None:
            n = min(int(self.info().get("childcount") or 0), 5000)

            def fn(d):
                return [d.getAccessibleChildFromContext(self.vm, self.ac, k) for k in range(n)]
            acs = self.backend.bridge.call(fn) if n > 0 else []
            self._kids = [JavaNode(self.backend, self.vm, ac, self, self.path + (k,))
                          for k, ac in enumerate(acs) if ac]
        return self._kids

    def parent(self):
        return self._parent


class JavaRoot(Node):
    tech = "java"

    def __init__(self, backend):
        self.backend = backend

    def key(self):
        return ("root",)

    def role(self):
        return "java-root"

    def label(self):
        return "Java applications (Access Bridge)"

    def children(self):
        return self.backend.top_nodes()

    def parent(self):
        return None


class JavaBackend(Backend):
    tech = "java"
    title = "Java applications"

    def __init__(self):
        self.bridge = JabThread()
        self._root = JavaRoot(self)
        self._not_java: Dict[int, float] = {}

    def available(self):
        return (self.bridge.dll is not None, self.bridge.error)

    def root(self):
        return self._root

    def _top_for_hwnd(self, d, hwnd: int) -> Optional[JavaNode]:
        if not d.isJavaWindow(hwnd):
            return None
        vm, ac = VMID(), JOBJECT64()
        if not d.getAccessibleContextFromHWND(hwnd, ctypes.byref(vm), ctypes.byref(ac)):
            return None
        return JavaNode(self, vm.value, ac.value, self._root, (), hwnd=hwnd)

    def top_nodes(self) -> List[JavaNode]:
        if self.bridge.dll is None:
            return []
        hwnds = win32.top_windows()
        return [n for n in self.bridge.call(lambda d: [self._top_for_hwnd(d, hw) for hw in hwnds]) if n]

    def from_point(self, x, y):
        if self.bridge.dll is None:
            return None
        top_hwnd = win32.root_window(win32.window_from_point(x, y))
        # hovering calls this every few ms: remember windows that are not Java
        # for a while instead of asking the bridge thread each time
        now = time.monotonic()
        not_java_until = self._not_java.get(top_hwnd)
        if not_java_until is not None and now < not_java_until:
            return None

        def fn(d):
            top = self._top_for_hwnd(d, top_hwnd)
            if top is None:
                if len(self._not_java) > 500:
                    self._not_java.clear()
                self._not_java[top_hwnd] = now + 3.0
                return None
            ac = JOBJECT64()
            if not d.getAccessibleContextAt(top.vm, top.ac, x, y, ctypes.byref(ac)) or not ac.value:
                return top
            # rebuild the index path from the top down
            chain = [ac.value]
            cur = ac.value
            for _ in range(200):
                p = d.getAccessibleParentFromContext(top.vm, cur)
                if not p or d.isSameObject(top.vm, p, top.ac):
                    break
                chain.append(p)
                cur = p
            chain.reverse()
            node = top
            for obj in chain:
                ci = AccessibleContextInfo()
                d.getAccessibleContextInfo(top.vm, obj, ctypes.byref(ci))
                node = JavaNode(self, top.vm, obj, node, node.path + (ci.indexInParent,))
            return node
        return self.bridge.call(fn)
