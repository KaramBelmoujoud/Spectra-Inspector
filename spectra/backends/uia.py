"""Microsoft UI Automation back end (UIA3 over COM via comtypes).

Covers Win32, WinForms, WPF, UWP/WinUI, Qt, Electron/Chromium accessibility
trees, Office and anything else that exposes UIA or MSAA (MSAA data is shown
through the LegacyIAccessible pattern).

All calls must happen on the driver thread (see spectra.driver), which runs
COM in the multi-threaded apartment.
"""
from __future__ import annotations

import re
import threading
from typing import Dict, List, Optional

import comtypes
import comtypes.client

from ..core.node import Backend, Node
from . import win32

UIA = None
_automation = None
_lock = threading.Lock()

PROP_NAMES: Dict[int, str] = {}
CONTROL_TYPES: Dict[int, str] = {}
CONTROL_TYPE_IDS: Dict[str, int] = {}
PATTERN_NAMES: Dict[int, str] = {}

TreeScope_Element = 1
TreeScope_Children = 2
TreeScope_Descendants = 4
PropertyConditionFlags_IgnoreCase = 1

P_RUNTIME_ID = 30000
P_RECT = 30001
P_PID = 30002
P_CONTROL_TYPE = 30003
P_LOCALIZED_TYPE = 30004
P_NAME = 30005
P_AUTOMATION_ID = 30011
P_CLASS = 30012
P_HELP = 30013
P_HWND = 30020
P_OFFSCREEN = 30022
P_FRAMEWORK = 30024
P_ARIA_ROLE = 30101
P_VALUE = 30045
CACHED = (P_RUNTIME_ID, P_RECT, P_PID, P_CONTROL_TYPE, P_NAME, P_AUTOMATION_ID, P_CLASS, P_HWND,
          P_FRAMEWORK, P_LOCALIZED_TYPE)

ATTR_TO_PROP = {"name": P_NAME, "automationid": P_AUTOMATION_ID, "class": P_CLASS, "framework": P_FRAMEWORK}


def automation():
    global UIA, _automation
    with _lock:
        if _automation is None:
            try:
                comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            except OSError:
                pass  # already initialised on this thread
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as mod
            UIA = mod
            _automation = comtypes.client.CreateObject(mod.CUIAutomation, interface=mod.IUIAutomation)
            for name in dir(mod):
                v = getattr(mod, name)
                if not isinstance(v, int):
                    continue
                m = re.fullmatch(r"UIA_(\w+)PropertyId", name)
                if m:
                    PROP_NAMES[v] = m.group(1)
                m = re.fullmatch(r"UIA_(\w+)ControlTypeId", name)
                if m:
                    CONTROL_TYPES[v] = m.group(1)
                    CONTROL_TYPE_IDS[m.group(1).lower()] = v
                m = re.fullmatch(r"UIA_(\w+)PatternId", name)
                if m:
                    PATTERN_NAMES[v] = m.group(1)
        return _automation


def _clean(v):
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (tuple, list)):
        return tuple(v)
    s = str(v)
    if "POINTER" in s or "IUnknown" in s:
        return None
    return s


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, tuple):
        return "(" + ", ".join(_fmt(x) for x in v) + ")"
    return str(v)


class UiaNode(Node):
    tech = "uia"

    def __init__(self, backend: "UiaBackend", el, parent: Optional["UiaNode"] = None,
                 is_root: bool = False, cached: bool = False):
        self.backend = backend
        self.el = el
        self._parent = parent
        self._is_root = is_root
        self._cached = cached
        self._props: Dict[int, object] = {}
        self._kids: Optional[List[UiaNode]] = None
        self._attrs: Optional[dict] = None
        self._key = None

    # --- raw properties --------------------------------------------------------
    def prop(self, pid: int, fresh: bool = False):
        if not fresh and pid in self._props:
            return self._props[pid]
        v = None
        try:
            if self._cached and not fresh and pid in CACHED:
                v = self.el.GetCachedPropertyValue(pid)
            else:
                v = self.el.GetCurrentPropertyValue(pid)
        except Exception:  # noqa: BLE001 - element vanished or property unsupported
            v = None
        v = _clean(v)
        self._props[pid] = v
        return v

    def key(self):
        if self._key is None:
            rid = self.prop(P_RUNTIME_ID)
            self._key = tuple(rid) if rid else ("hwnd", self.prop(P_HWND), self.prop(P_NAME))
        return self._key

    def is_root(self):
        return self._is_root

    def role(self):
        if self._is_root:
            return "Desktop"
        ct = self.prop(P_CONTROL_TYPE)
        return CONTROL_TYPES.get(ct, str(ct)) if ct else "Unknown"

    def hwnd(self) -> int:
        return int(self.prop(P_HWND) or 0)

    def process(self) -> str:
        return win32.process_name(self.prop(P_PID) or 0)

    def selector_attrs(self):
        if self._attrs is None:
            a = {}
            for k, pid in (("name", P_NAME), ("automationid", P_AUTOMATION_ID), ("class", P_CLASS)):
                v = self.prop(pid)
                if v:
                    a[k] = str(v)
            a["process"] = self.process()
            fw = self.prop(P_FRAMEWORK)
            if fw:
                a["framework"] = str(fw)
            lt = self.prop(P_LOCALIZED_TYPE)
            if lt:
                a["type"] = str(lt)
            hw = self.hwnd()
            if hw:
                a["hwnd"] = str(hw)
                cid = win32.control_id(hw)
                if cid:
                    a["controlid"] = str(cid)
            self._attrs = a
        return self._attrs

    def get(self, name):
        if name in ("helptext", "help"):
            return _str(self.prop(P_HELP))
        if name == "ariarole":
            return _str(self.prop(P_ARIA_ROLE))
        if name == "value":
            return _str(self.prop(P_VALUE, fresh=True))
        if name == "pid":
            return _str(self.prop(P_PID))
        return self.selector_attrs().get(name)

    def suggested_attrs(self, is_top=False):
        a = self.selector_attrs()
        if is_top:
            out = ["process"]
            if a.get("class"):
                out.append("class")
            if a.get("name") and len(a["name"]) <= 120:
                out.append("name")
            return out
        out = []
        aid = a.get("automationid", "")
        if aid and not re.search(r"[0-9a-f]{8}-|\d{6,}", aid, re.I):
            out.append("automationid")
        if a.get("name") and len(a["name"]) <= 100:
            out.append("name")
        if not out and a.get("class"):
            out.append("class")
        return out

    def label(self):
        if self._is_root:
            return "Desktop (UI Automation)"
        name = self.prop(P_NAME) or ""
        aid = self.prop(P_AUTOMATION_ID) or ""
        out = self.role()
        if name:
            out += f'  "{str(name)[:60]}"'
        if aid:
            out += f"  #{aid}"
        if self._parent is not None and self._parent._is_root:
            out += f"   [{self.process()}]"
        return out

    def rect(self):
        r = self.prop(P_RECT, fresh=True)
        if not r or len(r) != 4:
            return None
        l, t, w, h = r
        if w <= 0 or h <= 0:
            return None
        return int(l), int(t), int(l + w), int(t + h)

    def _load_all_props(self) -> bool:
        """Fetch every property in one cross-process round trip."""
        cr, pids = self.backend.all_props_request()
        if cr is None:
            return False
        try:
            el = self.el.BuildUpdatedCache(cr)
        except Exception:  # noqa: BLE001
            return False
        for pid in pids:
            try:
                v = el.GetCachedPropertyValue(pid)
            except Exception:  # noqa: BLE001
                v = None
            self._props[pid] = _clean(v)
        return True

    def properties(self):
        rows = []
        bulk = self._load_all_props()
        for pid in sorted(PROP_NAMES):
            v = self.prop(pid, fresh=not bulk)
            if v is None or v == "" or v == ():
                continue
            name = PROP_NAMES[pid]
            if name.startswith("Is") and name.endswith("PatternAvailable"):
                if v:
                    rows.append(("Patterns", name[2:-len("PatternAvailable")], "available"))
                continue
            if name.startswith("LegacyIAccessible"):
                rows.append(("MSAA (LegacyIAccessible)", name[len("LegacyIAccessible"):], _fmt(v)))
                continue
            if pid == P_CONTROL_TYPE:
                v = f"{CONTROL_TYPES.get(v, v)} ({v})"
            group = "UI Automation"
            for prefix in ("Value", "RangeValue", "Toggle", "ExpandCollapse", "SelectionItem", "Selection",
                           "Window", "Transform", "Scroll", "Grid", "Table", "Dock", "Annotation", "Styles",
                           "Drag", "DropTarget", "Spreadsheet"):
                if name.startswith(prefix) and name != prefix and pid not in (P_VALUE,):
                    group = f"Pattern: {prefix}"
                    break
            if pid == P_VALUE:
                group = "Pattern: Value"
            rows.append((group, name, _fmt(v)))
        pid_ = self.prop(P_PID)
        if pid_:
            rows.append(("UI Automation", "ProcessName", self.process()))
            rows.append(("UI Automation", "ProcessPath", win32.process_path(pid_)))
        rows.extend(win32.win32_properties(self.hwnd()))
        return rows

    # --- tree ---------------------------------------------------------------------
    def children(self):
        if self._kids is None:
            self._kids = self.backend.children_of(self)
        return self._kids

    def refresh(self):
        self._kids = None
        self._props.clear()
        self._attrs = None

    def parent(self):
        if self._is_root:
            return None
        if self._parent is None:
            self._parent = self.backend.parent_of(self)
        return self._parent

    def find(self, step, deep, budget):
        # query live rather than using the cached child list, so windows opened
        # after the tree was first expanded are still found
        return self.backend.find_descendants(self, step, deep)


def _str(v):
    return None if v is None else str(v)


class UiaBackend(Backend):
    tech = "uia"
    title = "Desktop (UI Automation)"

    def __init__(self, raw_view: bool = False):
        self.raw_view = raw_view
        self.a = automation()
        self._root = UiaNode(self, self.a.GetRootElement(), is_root=True)
        self.cache_request = self.a.CreateCacheRequest()
        for pid in CACHED:
            try:
                self.cache_request.AddProperty(pid)
            except Exception:  # noqa: BLE001
                pass
        self._all_cr = None
        self.set_view(raw_view)

    def all_props_request(self):
        """A cache request holding every known property (built once)."""
        if self._all_cr is None:
            cr, pids = None, []
            try:
                cr = self.a.CreateCacheRequest()
                cr.TreeFilter = self.a.CreateTrueCondition()
                for pid in sorted(PROP_NAMES):
                    try:
                        cr.AddProperty(pid)
                        pids.append(pid)
                    except Exception:  # noqa: BLE001 - not supported on this Windows version
                        pass
            except Exception:  # noqa: BLE001
                cr = None
            self._all_cr = (cr, pids)
        return self._all_cr

    def set_view(self, raw: bool):
        self.raw_view = raw
        self.view_condition = self.a.RawViewCondition if raw else self.a.ControlViewCondition
        self.walker = self.a.RawViewWalker if raw else self.a.ControlViewWalker
        try:
            self.cache_request.TreeFilter = self.view_condition
        except Exception:  # noqa: BLE001
            pass
        self._root = UiaNode(self, self.a.GetRootElement(), is_root=True)

    def root(self):
        return self._root

    def wrap(self, el, parent=None, cached=False) -> UiaNode:
        return UiaNode(self, el, parent, cached=cached)

    def desktop_children(self, cond, parent: Optional[UiaNode] = None) -> List[UiaNode]:
        """Children of the desktop, built from the visible top-level windows.

        UIA's own FindAll on the desktop also probes every hidden top-level
        window (hundreds of them), which takes ~0.5 s; this takes a few ms
        per visible window."""
        out = []
        for hw in win32.desktop_windows():
            try:
                el = self.a.ElementFromHandle(hw)
                hit = el.FindFirstBuildCache(TreeScope_Element, cond, self.cache_request) if el else None
            except Exception:  # noqa: BLE001 - window closed meanwhile
                continue
            if hit:
                out.append(self.wrap(hit, parent or self._root, cached=True))
        return out

    def children_of(self, node: UiaNode) -> List[UiaNode]:
        if node._is_root:
            return self.desktop_children(self.view_condition, node)
        try:
            arr = node.el.FindAllBuildCache(TreeScope_Children, self.view_condition, self.cache_request)
            return [self.wrap(arr.GetElement(i), node, cached=True) for i in range(arr.Length)] if arr else []
        except Exception:  # noqa: BLE001
            pass
        out = []
        try:
            child = self.walker.GetFirstChildElement(node.el)
            while child and len(out) < 20000:
                out.append(self.wrap(child, node))
                child = self.walker.GetNextSiblingElement(child)
        except Exception:  # noqa: BLE001
            pass
        return out

    def parent_of(self, node: UiaNode) -> Optional[UiaNode]:
        try:
            p = self.walker.GetParentElement(node.el)
        except Exception:  # noqa: BLE001
            return self._root
        if not p:
            return self._root
        try:
            if self.a.CompareElements(p, self._root.el):
                return self._root
        except Exception:  # noqa: BLE001
            pass
        return self.wrap(p)

    def _condition_for(self, step):
        conds = [self.view_condition]
        if step.role != "*":
            ct = CONTROL_TYPE_IDS.get(step.role.lower())
            if ct is not None:
                conds.append(self.a.CreatePropertyCondition(P_CONTROL_TYPE, ct))
        for f in step.filters:
            pid = ATTR_TO_PROP.get(f.name)
            if pid and f.op == "=" and f.literal is not None:  # wildcards are matched in Python
                flags = PropertyConditionFlags_IgnoreCase if f.case_insensitive else 0
                conds.append(self.a.CreatePropertyConditionEx(pid, f.literal, flags))
        cond = conds[0]
        for c in conds[1:]:
            cond = self.a.CreateAndCondition(cond, c)
        return cond

    def find_descendants(self, node: UiaNode, step, deep: bool = True) -> Optional[List[UiaNode]]:
        scope = TreeScope_Descendants if deep else TreeScope_Children
        if node._is_root and not deep:
            try:
                return self.desktop_children(self._condition_for(step), node)
            except Exception:  # noqa: BLE001
                return None
        try:
            arr = node.el.FindAllBuildCache(scope, self._condition_for(step), self.cache_request)
        except Exception:  # noqa: BLE001
            return None
        if not arr:
            return []
        parent = None if deep else node
        return [self.wrap(arr.GetElement(i), parent, cached=True) for i in range(arr.Length)]

    def from_point(self, x, y):
        from comtypes.gen.UIAutomationClient import tagPOINT
        try:
            el = self.a.ElementFromPoint(tagPOINT(x, y))
        except Exception:  # noqa: BLE001
            return None
        return self.wrap(el) if el else None

    def focused(self):
        try:
            el = self.a.GetFocusedElement()
        except Exception:  # noqa: BLE001
            return None
        return self.wrap(el) if el else None

    def from_hwnd(self, hwnd: int):
        try:
            return self.wrap(self.a.ElementFromHandle(hwnd))
        except Exception:  # noqa: BLE001
            return None

    # --- actions (for trying an element out) -------------------------------------------
    def _pattern(self, node: UiaNode, name: str):
        pid = getattr(UIA, f"UIA_{name}PatternId")
        iface = getattr(UIA, f"IUIAutomation{name}Pattern")
        pat = node.el.GetCurrentPattern(pid)
        if not pat:
            raise RuntimeError(f"{name} pattern is not supported by this element")
        return pat.QueryInterface(iface)

    def action(self, node: UiaNode, action: str, arg: str = ""):
        if action == "Focus":
            node.el.SetFocus()
        elif action == "Invoke":
            self._pattern(node, "Invoke").Invoke()
        elif action == "Toggle":
            self._pattern(node, "Toggle").Toggle()
        elif action == "Expand":
            self._pattern(node, "ExpandCollapse").Expand()
        elif action == "Collapse":
            self._pattern(node, "ExpandCollapse").Collapse()
        elif action == "Select":
            self._pattern(node, "SelectionItem").Select()
        elif action == "Set value":
            self._pattern(node, "Value").SetValue(arg)
        elif action == "Scroll into view":
            self._pattern(node, "ScrollItem").ScrollIntoView()
        else:
            raise ValueError(action)
