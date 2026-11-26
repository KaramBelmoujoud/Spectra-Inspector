"""Data types of the plugin API (re-exported by :mod:`spectra.plugins`)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..core.node import Node
from ..core.selector import Selector


@dataclass(frozen=True)
class PluginInfo:
    """Describes a plugin. Put an instance in a module-level ``PLUGIN`` variable.

    ``id`` must be unique and stable (letters, digits, ``-``, ``_`` and ``.``); it names the
    plugin's settings file and its enabled state. ``api_version`` is the plugin API version the
    plugin was written for; only its major number has to match Spectra's.
    """
    id: str
    name: str
    version: str = "0.1"
    author: str = ""
    description: str = ""
    api_version: str = "1.0"
    homepage: str = ""


class Exporter:
    """Turns the selected element into code for another tool.

    Subclass it, set ``name`` and override :meth:`export`. The result is shown as a section of
    the *Locators & code* tab and can be copied from the *Export* menu.
    Both methods run on the driver thread, so they may read the node directly.
    """
    #: Section title, e.g. "Playwright (Python)".
    name: str = "Exporter"

    def applies_to(self, node: Node) -> bool:
        """Return False for elements this exporter can't handle (e.g. ``node.tech != "web"``)."""
        return True

    def export(self, node: Node, selector_text: str) -> str:
        """Return the code text for ``node``; ``selector_text`` is the generated Spectra selector."""
        raise NotImplementedError


class SelectorFormat:
    """Another way to write a selector, e.g. an XPath-like notation.

    ``from_selector`` is required; ``to_selector`` is optional (formats that can't be read back
    leave it returning None). Both run on the driver thread.
    """
    #: Shown as the section title and in the Export menu.
    name: str = "Format"

    def applies_to(self, node: Node) -> bool:
        return True

    def from_selector(self, selector: Selector, node: Node) -> str:
        raise NotImplementedError

    def to_selector(self, text: str) -> Optional[Selector]:
        return None
