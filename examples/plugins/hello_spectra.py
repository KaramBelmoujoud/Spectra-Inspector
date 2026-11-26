"""A minimal Spectra Inspector plugin: one action and one panel.

Install it by copying this file into %APPDATA%\\Spectra\\plugins\\ (or use Plugins > Plugin Manager >
Install from file…), then tick it in the Plugin Manager.
"""
from spectra.plugins import PluginInfo

PLUGIN = PluginInfo(
    id="hello_spectra",
    name="Hello Spectra",
    version="1.0",
    author="Your name",
    description="Example plugin: a 'Say hello' action and a panel that follows the selected element.",
    api_version="1.0",
)


def say_hello(node, ctx):
    # Runs on the driver thread: the element can be used directly here.
    ctx.settings["greetings"] = ctx.settings.get("greetings", 0) + 1
    return f"Hello, {node.role()} \"{node.get('name') or node.label()}\"! (greeting #{ctx.settings['greetings']})"


def make_panel(ctx):
    # Runs on the UI thread: build Qt widgets here, never touch elements directly.
    from PySide6.QtWidgets import QLabel

    label = QLabel("Select an element…")
    label.setWordWrap(True)

    def on_selected(node):
        # Event callbacks run on the UI thread too; ask the driver thread for element data.
        ctx.run_in_driver(lambda: node.label(), lambda text: label.setText(f"Selected: {text}"))

    ctx.on("element_selected", on_selected)
    return label


def register(ctx):
    ctx.add_action("Say hello", say_hello)
    ctx.add_panel("Hello", make_panel)
    ctx.log("Hello Spectra is ready")


def unregister(ctx):
    # Optional: everything added through ctx is removed automatically.
    ctx.log("Goodbye")
