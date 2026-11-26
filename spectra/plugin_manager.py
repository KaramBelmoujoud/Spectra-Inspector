"""Discovers, loads, enables and disables plugins.

Sources (in this order; the first plugin with a given id wins):

* built-in plugins shipped in ``spectra/builtin_plugins/``,
* the user plugins folder (``%APPDATA%\\Spectra\\plugins``): single ``.py`` files or packages,
* installed Python packages that declare an entry point in the ``spectra_inspector.plugins`` group.

Every call into plugin code is wrapped so that a broken plugin is reported (Log tab and the
Plugin Manager) but never takes the application down. The manager has no Qt dependency: the
application gives it a *host* object (see :class:`Host`) for everything UI-related.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import shutil
import sys
import threading
import traceback
import zipfile
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Callable, Dict, List, Optional, Tuple

from .plugins import API_VERSION
from .plugins.context import PluginContext
from .plugins.types import PluginInfo

ENTRY_POINT_GROUP = "spectra_inspector.plugins"
BUILTIN_PACKAGE = "spectra.builtin_plugins"
_ID_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")


def spectra_home() -> str:
    """Where Spectra keeps per-user data. ``SPECTRA_HOME`` overrides it (used by the tests)."""
    if os.environ.get("SPECTRA_HOME"):
        return os.environ["SPECTRA_HOME"]
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Spectra")


class Host:
    """What the plugin manager needs from the application. The GUI implements this; tests use a fake."""
    engine: Any = None

    def run_in_driver(self, fn, callback=None, timeout=30.0):
        result = fn()
        if callback:
            callback(result)
            return None
        return result

    def run_in_ui(self, fn, wait=False, timeout=30.0):
        return fn()

    def log(self, msg: str):
        print(msg)

    def current_node(self):
        return None

    def selector_text(self) -> str:
        return ""

    def set_selector_text(self, text: str, validate: bool = True):
        pass

    def highlight(self, node):
        pass

    def select(self, node):
        pass

    def plugins_changed(self, kind: str):
        """Called (UI thread) when the set of exporters, actions, panels... changes."""

    def add_panel(self, plugin_id: str, panel: dict):
        pass

    def remove_panel(self, plugin_id: str, panel: dict):
        pass

    def confirm_third_party(self, record: "PluginRecord") -> bool:
        """Ask the user before a non-built-in plugin is enabled for the first time."""
        return False


@dataclass
class PluginRecord:
    id: str
    source: str                         # "built-in", "folder" or "package"
    location: str                       # file, folder or "dist:name"
    module: Optional[ModuleType] = None
    info: Optional[PluginInfo] = None
    enabled: bool = False
    error: str = ""
    ctx: Optional[PluginContext] = None
    loader: Optional[Callable[[], ModuleType]] = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return self.info.name if self.info else self.id

    @property
    def builtin(self) -> bool:
        return self.source == "built-in"


class Registry:
    """Everything plugins have added, by kind, in registration order."""
    KINDS = ("backends", "exporters", "formats", "actions", "panels", "providers", "events")

    def __init__(self, manager: "PluginManager"):
        self._m = manager
        self._items: Dict[str, List[Tuple[str, Any]]] = {k: [] for k in self.KINDS}
        self._lock = threading.RLock()

    def add(self, kind: str, plugin_id: str, item: Any, what: str):
        from .plugins.context import Handle
        with self._lock:
            entry = (plugin_id, item)
            self._items[kind].append(entry)
        self._m._on_added(kind, plugin_id, item)

        def remove():
            with self._lock:
                if entry in self._items[kind]:
                    self._items[kind].remove(entry)
            self._m._on_removed(kind, plugin_id, item)
        return Handle(remove, what)

    def items(self, kind: str) -> List[Tuple[str, Any]]:
        with self._lock:
            return list(self._items[kind])

    def of(self, kind: str) -> List[Any]:
        return [item for _, item in self.items(kind)]


def _major(version: str) -> str:
    return str(version).split(".")[0].strip()


class PluginManager:
    def __init__(self, host: Optional[Host] = None, plugin_dir: Optional[str] = None,
                 include_builtin: bool = True, include_entry_points: bool = True):
        self.host = host or Host()
        self.home = spectra_home()
        self.plugin_dir = plugin_dir or os.path.join(self.home, "plugins")
        self.settings_dir = self.plugin_dir
        self.state_file = os.path.join(self.home, "plugins.json")
        self.include_builtin = include_builtin
        self.include_entry_points = include_entry_points
        self.records: Dict[str, PluginRecord] = {}
        self.registry = Registry(self)
        self._state = self._load_state()

    # ------------------------------------------------------------------ persisted state
    def _load_state(self) -> dict:
        try:
            with open(self.state_file, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("enabled", {})
                data.setdefault("trusted", [])
                return data
        except (OSError, ValueError):
            pass
        return {"enabled": {}, "trusted": []}

    def _save_state(self):
        try:
            os.makedirs(self.home, exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2)
        except OSError as e:
            self.host.log(f"Plugins: could not save {self.state_file}: {e}")

    def is_trusted(self, plugin_id: str) -> bool:
        return plugin_id in self._state["trusted"]

    def wants_enabled(self, rec: PluginRecord) -> bool:
        saved = self._state["enabled"].get(rec.id)
        if saved is not None:
            return bool(saved) and (rec.builtin or self.is_trusted(rec.id))
        return rec.builtin  # built-ins are on by default, third-party plugins off until the user agrees

    # ------------------------------------------------------------------ discovery
    def discover(self) -> List[PluginRecord]:
        """Find plugins (without running them) and import their modules to read ``PLUGIN``."""
        found: List[PluginRecord] = []
        if self.include_builtin:
            found += self._discover_builtin()
        found += self._discover_folder()
        if self.include_entry_points:
            found += self._discover_entry_points()
        for rec in found:
            if rec.id in self.records:
                old = self.records[rec.id]
                if old.location != rec.location and not old.error:
                    self.host.log(f"Plugins: {rec.location} also defines plugin id '{rec.id}'; "
                                  f"keeping the one from {old.location}")
                continue
            self.records[rec.id] = rec
            self._import(rec)
        return list(self.records.values())

    def _discover_builtin(self) -> List[PluginRecord]:
        import pkgutil
        try:
            pkg = importlib.import_module(BUILTIN_PACKAGE)
        except Exception:  # noqa: BLE001
            return []
        out = []
        for m in pkgutil.iter_modules(pkg.__path__):
            name = f"{BUILTIN_PACKAGE}.{m.name}"
            out.append(PluginRecord(id=m.name, source="built-in", location=name,
                                    loader=lambda n=name: importlib.import_module(n)))
        return out

    def _discover_folder(self) -> List[PluginRecord]:
        out = []
        if not os.path.isdir(self.plugin_dir):
            return out
        for entry in sorted(os.listdir(self.plugin_dir)):
            path = os.path.join(self.plugin_dir, entry)
            if entry.startswith(("_", ".")):
                continue
            if entry.endswith(".py") and os.path.isfile(path):
                stem = entry[:-3]
                out.append(PluginRecord(id=stem, source="folder", location=path,
                                        loader=lambda p=path, s=stem: _load_file(p, s)))
            elif os.path.isfile(os.path.join(path, "__init__.py")):
                out.append(PluginRecord(id=entry, source="folder", location=path,
                                        loader=lambda p=path, s=entry: _load_package(p, s)))
        return out

    def _discover_entry_points(self) -> List[PluginRecord]:
        from importlib import metadata
        out = []
        try:
            eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
        except TypeError:  # Python < 3.10 style; kept for safety
            eps = metadata.entry_points().get(ENTRY_POINT_GROUP, [])
        for ep in eps:
            dist = getattr(getattr(ep, "dist", None), "name", "") or ep.value
            out.append(PluginRecord(id=ep.name, source="package", location=f"{dist} ({ep.value})",
                                    loader=lambda e=ep: _load_entry_point(e)))
        return out

    def _import(self, rec: PluginRecord):
        rec.error = ""
        try:
            mod = rec.loader()
        except Exception:  # noqa: BLE001
            rec.error = "could not be imported:\n" + traceback.format_exc(limit=6)
            self.host.log(f"Plugin '{rec.id}' {rec.error}")
            return
        rec.module = mod
        info = getattr(mod, "PLUGIN", None)
        if not isinstance(info, PluginInfo):
            rec.error = "has no PLUGIN = PluginInfo(...) definition"
        elif not callable(getattr(mod, "register", None)):
            rec.error = "has no register(ctx) function"
        elif _major(info.api_version) != _major(API_VERSION):
            rec.error = (f"was written for plugin API {info.api_version}, but this Spectra provides API "
                         f"{API_VERSION}; it needs an update for {_major(API_VERSION)}.x")
        elif not info.id or set(info.id) - _ID_OK:
            rec.error = f"has an invalid id {info.id!r} (use letters, digits, '-', '_' and '.')"
        if isinstance(info, PluginInfo):
            rec.info = info
            if info.id and info.id != rec.id and not set(info.id) - _ID_OK:
                # the declared id is the real identity (file names may differ)
                self.records.pop(rec.id, None)
                rec.id = info.id
                self.records.setdefault(rec.id, rec)
        if rec.error:
            self.host.log(f"Plugin '{rec.id}' {rec.error}")

    # ------------------------------------------------------------------ enable / disable
    def start(self):
        """Discover plugins and enable those that should be on."""
        self.discover()
        for rec in list(self.records.values()):
            if not rec.error and self.wants_enabled(rec):
                self.enable(rec.id, remember=False)
            elif not rec.error and not rec.builtin and not self.is_trusted(rec.id):
                self.host.log(f"Plugins: found '{rec.name}' ({rec.source}); it stays off until you enable it in "
                              f"Plugins > Plugin Manager")

    def enable(self, plugin_id: str, remember: bool = True, confirmed: bool = False) -> bool:
        rec = self.records[plugin_id]
        if rec.enabled:
            return True
        if rec.error:
            return False
        if not rec.builtin and not self.is_trusted(rec.id):
            if not (confirmed or self.host.confirm_third_party(rec)):
                return False
            self._state["trusted"].append(rec.id)
        ctx = PluginContext(self, rec)
        rec.ctx = ctx
        try:
            rec.module.register(ctx)
        except Exception:  # noqa: BLE001
            rec.error = "failed in register():\n" + traceback.format_exc(limit=6)
            self.host.log(f"Plugin '{rec.id}' {rec.error}")
            ctx._cleanup()
            rec.ctx = None
            return False
        rec.enabled = True
        rec.error = ""
        if remember:
            self._state["enabled"][rec.id] = True
            self._save_state()
        return True

    def disable(self, plugin_id: str, remember: bool = True):
        rec = self.records[plugin_id]
        if rec.enabled and rec.ctx is not None:
            unreg = getattr(rec.module, "unregister", None)
            if callable(unreg):
                try:
                    unreg(rec.ctx)
                except Exception:  # noqa: BLE001
                    self.host.log(f"Plugin '{rec.id}' failed in unregister():\n" + traceback.format_exc(limit=4))
            rec.ctx._cleanup()
        rec.ctx = None
        rec.enabled = False
        if remember:
            self._state["enabled"][rec.id] = False
            self._save_state()

    def reload(self, plugin_id: str) -> bool:
        """Re-import a plugin's code (after editing it) and enable it again if it was on."""
        rec = self.records[plugin_id]
        was_on = rec.enabled
        self.disable(plugin_id, remember=False)
        if rec.module is not None and rec.source != "folder":
            rec.loader = (lambda m=rec.module: importlib.reload(m))  # folder plugins are re-read from disk
        self._import(rec)
        rec = self.records.get(rec.id, rec)
        if was_on and not rec.error:
            return self.enable(rec.id, remember=False)
        return not rec.error

    def stop(self):
        for rec in list(self.records.values()):
            if rec.enabled:
                self.disable(rec.id, remember=False)

    # ------------------------------------------------------------------ installing
    def install_file(self, path: str) -> List[str]:
        """Copy a plugin (.py file, or a .zip holding a .py file or a package) into the plugins folder.
        Returns the new plugin ids (not enabled; the user enables them)."""
        os.makedirs(self.plugin_dir, exist_ok=True)
        before = set(self.records)
        if path.lower().endswith(".py"):
            shutil.copy(path, os.path.join(self.plugin_dir, os.path.basename(path)))
        elif path.lower().endswith(".zip"):
            with zipfile.ZipFile(path) as z:
                for name in z.namelist():
                    target = os.path.realpath(os.path.join(self.plugin_dir, name))
                    if not target.startswith(os.path.realpath(self.plugin_dir) + os.sep):
                        raise ValueError(f"unsafe path in zip: {name}")
                z.extractall(self.plugin_dir)
        else:
            raise ValueError("choose a .py file or a .zip archive")
        self.discover()
        return [pid for pid in self.records if pid not in before]

    # ------------------------------------------------------------------ used by the application
    def emit(self, event: str, *args):
        """Call every subscriber of ``event`` (UI thread); errors are logged, never raised."""
        for pid, (ev, cb) in self.registry.items("events"):
            if ev != event:
                continue
            try:
                cb(*args)
            except Exception:  # noqa: BLE001
                self.host.log(f"Plugin '{pid}' failed handling {event}:\n" + traceback.format_exc(limit=4))

    def exporters_for(self, node) -> List[Tuple[str, Any]]:
        out = []
        for pid, ex in self.registry.items("exporters"):
            try:
                if ex.applies_to(node):
                    out.append((pid, ex))
            except Exception:  # noqa: BLE001
                pass
        return out

    def formats_for(self, node) -> List[Tuple[str, Any]]:
        out = []
        for pid, fm in self.registry.items("formats"):
            try:
                if fm.applies_to(node):
                    out.append((pid, fm))
            except Exception:  # noqa: BLE001
                pass
        return out

    def export_sections(self, node, selector) -> List[Tuple[str, str]]:
        """(title, text) for every exporter and format that applies to ``node`` (driver thread)."""
        text = selector.to_text()
        out = []
        for pid, fm in self.formats_for(node):
            try:
                out.append((fm.name, fm.from_selector(selector, node)))
            except Exception as e:  # noqa: BLE001
                out.append((fm.name, f"(plugin '{pid}' failed: {e})"))
        for pid, ex in self.exporters_for(node):
            try:
                out.append((ex.name, ex.export(node, text)))
            except Exception as e:  # noqa: BLE001
                out.append((ex.name, f"(plugin '{pid}' failed: {e})"))
        return out

    def extra_properties(self, node) -> List[Tuple[str, str, str]]:
        rows: List[Tuple[str, str, str]] = []
        for pid, provider in self.registry.items("providers"):
            try:
                for row in provider(node) or []:
                    g, k, v = row
                    rows.append((str(g), str(k), str(v)))
            except Exception as e:  # noqa: BLE001
                rows.append(("Plugin errors", pid, f"{type(e).__name__}: {e}"))
        return rows

    def run_action(self, action: dict, node) -> Optional[str]:
        """Run a plugin action on the driver thread. Returns a status message."""
        check = action.get("applies_to")
        if check is not None and not check(node):
            return f"{action['name']} is not available for this element"
        r = action["callback"](node, action["ctx"])
        return r if isinstance(r, str) else f"{action['name']}: done"

    # registry hooks
    def _on_added(self, kind: str, plugin_id: str, item: Any):
        if kind == "backends":
            from .core.selector import register_tech
            register_tech(item.tech)
            self.host.engine.register(item)
            svc = getattr(self.host, "service", None)
            if svc is not None and hasattr(svc, "extra_backends"):
                svc.extra_backends.append(item)
        elif kind == "panels":
            self.host.add_panel(plugin_id, item)
        self.host.plugins_changed(kind)

    def _on_removed(self, kind: str, plugin_id: str, item: Any):
        if kind == "backends":
            eng = self.host.engine
            if eng.backends.get(item.tech) is item:
                del eng.backends[item.tech]
            svc = getattr(self.host, "service", None)
            if svc is not None and item in getattr(svc, "extra_backends", []):
                svc.extra_backends.remove(item)
        elif kind == "panels":
            self.host.remove_panel(plugin_id, item)
        self.host.plugins_changed(kind)


# ---------------------------------------------------------------------- module loading
def _user_namespace():
    """Folder plugins are imported as spectra_user_plugins.<name>, so they never clash with other modules."""
    if "spectra_user_plugins" not in sys.modules:
        ns = ModuleType("spectra_user_plugins")
        ns.__path__ = []
        sys.modules["spectra_user_plugins"] = ns


def _load_file(path: str, stem: str) -> ModuleType:
    _user_namespace()
    name = f"spectra_user_plugins.{stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


def _load_package(path: str, stem: str) -> ModuleType:
    _user_namespace()
    name = f"spectra_user_plugins.{stem}"
    spec = importlib.util.spec_from_file_location(name, os.path.join(path, "__init__.py"),
                                                  submodule_search_locations=[path])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


def _load_entry_point(ep) -> ModuleType:
    # the entry point names the plugin module (or any object with PLUGIN and register attributes)
    return ep.load()
