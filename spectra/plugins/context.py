"""PluginContext: what a plugin receives in ``register(ctx)``."""
from __future__ import annotations

import json
import os
import threading
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Sequence, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from ..core.engine import Engine
    from ..core.node import Backend, Node
    from ..plugin_manager import PluginManager, PluginRecord
    from .types import Exporter, SelectorFormat

#: Events a plugin can subscribe to with ``ctx.on(event, callback)``. Callbacks run on the UI thread.
EVENTS = {
    "app_started": "callback()  - Spectra finished starting (back ends are ready)",
    "app_closing": "callback()  - the main window is closing",
    "element_selected": "callback(node)  - an element was selected (picked, clicked in the tree, ...)",
    "selector_validated": "callback(selector_text, result)  - a selector was generated or validated; "
                          "result.matches, result.error, result.elapsed_ms",
    "pick_started": "callback()  - on-screen picking (F3) started",
    "pick_finished": "callback(node_or_None)  - picking ended with a captured element, or None if cancelled",
}

PropertyRow = Tuple[str, str, str]


class Handle:
    """Returned by every ``ctx.add_*`` / ``ctx.on`` call. ``handle.remove()`` undoes that one registration;
    everything is removed automatically when the plugin is disabled."""

    def __init__(self, remove: Callable[[], None], what: str):
        self._remove, self.what, self.active = remove, what, True

    def remove(self):
        if self.active:
            self.active = False
            self._remove()

    def __repr__(self):
        return f"<Handle {self.what}{'' if self.active else ' (removed)'}>"


class PluginSettings(dict):
    """A dict that is saved as JSON whenever it changes (``%APPDATA%/Spectra/plugins/<id>.json``).

    Values must be JSON-serialisable. Use it like a normal dict; call ``save()`` after mutating a
    nested value in place."""

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self._lock = threading.RLock()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                super().update(data)
        except (OSError, ValueError):
            pass

    def save(self):
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(dict(self), f, indent=2)
            os.replace(tmp, self.path)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.save()

    def __delitem__(self, key):
        super().__delitem__(key)
        self.save()

    def update(self, *a, **kw):  # noqa: D102
        super().update(*a, **kw)
        self.save()

    def pop(self, *a):  # noqa: D102
        r = super().pop(*a)
        self.save()
        return r

    def setdefault(self, key, default=None):  # noqa: D102
        if key not in self:
            self[key] = default
        return self[key]


class PluginContext:
    """The plugin's handle on Spectra. One instance per enabled plugin.

    Threading: element objects (``Node``) and back ends must only be used on the *driver thread*.
    Exporters, selector formats, property providers and action callbacks are already called there.
    Event callbacks and panel factories run on the *UI thread*; use :meth:`run_in_driver` from them.
    """

    def __init__(self, manager: "PluginManager", record: "PluginRecord"):
        self._manager = manager
        self._record = record
        self._handles: List[Handle] = []
        self._settings: Optional[PluginSettings] = None

    # ------------------------------------------------------------------ identity
    @property
    def plugin_id(self) -> str:
        return self._record.id

    @property
    def info(self):
        return self._record.info

    # ------------------------------------------------------------------ registrations
    def _track(self, handle: Handle) -> Handle:
        self._handles.append(handle)
        return handle

    def add_backend(self, backend: "Backend") -> Handle:
        """Make a new UI technology inspectable. Pass a ``Backend`` subclass or instance; it is
        registered with the search engine under ``backend.tech`` (the selector prefix)."""
        if isinstance(backend, type):
            backend = backend()
        return self._track(self._manager.registry.add("backends", self.plugin_id, backend,
                                                      f"backend {backend.tech}"))

    def add_exporter(self, exporter: "Exporter") -> Handle:
        """Add a code exporter (an ``Exporter`` subclass or instance)."""
        if isinstance(exporter, type):
            exporter = exporter()
        return self._track(self._manager.registry.add("exporters", self.plugin_id, exporter,
                                                      f"exporter {exporter.name}"))

    def add_selector_format(self, fmt: "SelectorFormat") -> Handle:
        """Add another selector notation (a ``SelectorFormat`` subclass or instance)."""
        if isinstance(fmt, type):
            fmt = fmt()
        return self._track(self._manager.registry.add("formats", self.plugin_id, fmt, f"format {fmt.name}"))

    def add_action(self, name: str, callback: Callable[["Node", "PluginContext"], Any],
                   applies_to: Optional[Callable[["Node"], bool]] = None,
                   shortcut: Optional[str] = None) -> Handle:
        """Add a button to the *Try it* tab and the element context menu.

        ``callback(node, ctx)`` runs on the driver thread with the selected element; a returned string is
        shown in the status bar. ``applies_to(node)`` (driver thread) can refuse elements.
        ``shortcut`` is a Qt key sequence such as ``"Ctrl+Shift+J"``."""
        action = {"name": name, "callback": callback, "applies_to": applies_to, "shortcut": shortcut, "ctx": self}
        return self._track(self._manager.registry.add("actions", self.plugin_id, action, f"action {name}"))

    def add_panel(self, title: str, widget_factory: Callable[["PluginContext"], Any]) -> Handle:
        """Add a dockable panel. ``widget_factory(ctx)`` returns a QWidget (UI thread). The panel is listed
        in the *View* menu and removed when the plugin is disabled."""
        panel = {"title": title, "factory": widget_factory, "ctx": self}
        return self._track(self._manager.registry.add("panels", self.plugin_id, panel, f"panel {title}"))

    def add_property_provider(self, provider: Callable[["Node"], Sequence[Tuple[str, str, str]]]) -> Handle:
        """Add rows to the *Properties* panel. ``provider(node)`` runs on the driver thread and returns
        ``[(group, name, value), ...]``."""
        return self._track(self._manager.registry.add("providers", self.plugin_id, provider, "property provider"))

    def on(self, event: str, callback: Callable[..., Any]) -> Handle:
        """Subscribe to an event (see :data:`EVENTS`). Callbacks run on the UI thread."""
        if event not in EVENTS:
            raise ValueError(f"unknown event {event!r}; known events: {', '.join(EVENTS)}")
        return self._track(self._manager.registry.add("events", self.plugin_id, (event, callback), f"event {event}"))

    # ------------------------------------------------------------------ helpers
    @property
    def engine(self) -> "Engine":
        """The selector engine: ``engine.find_all(selector)``, ``engine.generate(node)`` (driver thread)."""
        return self._manager.host.engine

    def run_in_driver(self, fn: Callable[[], Any], callback: Optional[Callable[[Any], None]] = None,
                      timeout: float = 30.0):
        """Run ``fn`` on the driver thread (where elements may be used).

        With ``callback`` the call returns at once and ``callback(result)`` runs later on the UI thread.
        Without it the call waits and returns the result; don't wait like that from the UI thread
        (UI Automation may need the UI thread to answer for Spectra's own windows), pass a callback."""
        return self._manager.host.run_in_driver(fn, callback, timeout)

    def run_in_ui(self, fn: Callable[[], Any], wait: bool = False, timeout: float = 30.0):
        """Run ``fn`` on the UI thread. With ``wait=True`` the call blocks and returns its result."""
        return self._manager.host.run_in_ui(fn, wait, timeout)

    def log(self, msg: str):
        """Write a line to the *Log* tab (any thread)."""
        self._manager.host.log(f"[{self.plugin_id}] {msg}")

    @property
    def settings(self) -> PluginSettings:
        """Persistent per-plugin settings (a JSON-backed dict)."""
        if self._settings is None:
            self._settings = PluginSettings(os.path.join(self._manager.settings_dir, f"{self.plugin_id}.json"))
        return self._settings

    def current_node(self) -> Optional["Node"]:
        """The selected element, or None."""
        return self._manager.host.current_node()

    def selector_text(self) -> str:
        """The text in the selector editor (any thread)."""
        return self._manager.host.selector_text()

    def set_selector_text(self, text: str, validate: bool = True):
        """Replace the selector editor's text (any thread)."""
        self._manager.host.set_selector_text(text, validate)

    def highlight(self, node: "Node"):
        """Frame an element on screen (any thread)."""
        self._manager.host.highlight(node)

    def select(self, node: "Node"):
        """Make ``node`` the selected element, as if it had been picked (any thread)."""
        self._manager.host.select(node)

    # ------------------------------------------------------------------ internal
    def _cleanup(self):
        for h in reversed(self._handles):
            try:
                h.remove()
            except Exception:  # noqa: BLE001
                pass
        self._handles.clear()

    @property
    def handles(self) -> List[Handle]:
        return [h for h in self._handles if h.active]

