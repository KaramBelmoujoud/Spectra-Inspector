"""'Copy element as JSON': one action that dogfoods ctx.add_action and ctx.run_in_ui."""
import json

from spectra.plugins import PluginInfo

PLUGIN = PluginInfo(
    id="copy_json_action", name="Copy element as JSON", version="1.0", author="Spectra Inspector contributors",
    description="Adds a 'Copy as JSON' action: technology, role, attributes, rectangle and selector of the "
                "selected element, copied to the clipboard.")


def element_json(node, selector: str) -> str:
    """Runs on the driver thread."""
    data = {
        "tech": node.tech,
        "role": node.role(),
        "label": node.label(),
        "attributes": dict(node.selector_attrs()),
        "rect": list(node.rect()) if node.rect() else None,
        "selector": selector,
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def copy_json(node, ctx):
    text = element_json(node, ctx.selector_text())

    def to_clipboard():
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(text)
    ctx.run_in_ui(to_clipboard)
    return f"Copied {len(text)} characters of JSON"


def register(ctx):
    ctx.add_action("Copy as JSON", copy_json, shortcut="Ctrl+Shift+J")
