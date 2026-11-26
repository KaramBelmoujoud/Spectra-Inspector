"""The public plugin API of Spectra Inspector.

This package is the only thing a plugin should import from Spectra. Everything
here follows the plugin API version in :data:`API_VERSION`: additions bump the
minor number, incompatible changes bump the major number, and Spectra refuses
to load a plugin built for another major version.

A plugin is a Python module (a single ``.py`` file or a package) that defines::

    from spectra.plugins import PluginInfo

    PLUGIN = PluginInfo(id="hello", name="Hello", version="1.0", author="You",
                        description="Says hello")

    def register(ctx):          # called when the plugin is enabled
        ctx.add_action("Say hello", lambda node, ctx: f"Hello {node.label()}")

    def unregister(ctx):        # optional; everything added through ctx is removed anyway
        pass

See docs/plugins.md for the full guide.
"""
from __future__ import annotations

from ..core.node import Backend, Node
from ..core.selector import Filter, Selector, Step, parse
from .context import EVENTS, Handle, PluginContext, PluginSettings
from .types import Exporter, PluginInfo, SelectorFormat

API_VERSION = "1.0"

__all__ = [
    "API_VERSION", "PluginInfo", "PluginContext", "PluginSettings", "Handle", "EVENTS",
    "Exporter", "SelectorFormat", "Node", "Backend", "Selector", "Step", "Filter", "parse",
]
