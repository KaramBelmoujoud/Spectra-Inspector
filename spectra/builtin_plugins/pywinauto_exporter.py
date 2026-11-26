"""pywinauto code for desktop (UI Automation) elements."""
from spectra.plugins import Exporter, PluginInfo

PLUGIN = PluginInfo(
    id="pywinauto_exporter", name="pywinauto exporter", version="1.0", author="Spectra Inspector contributors",
    description="pywinauto (UIA back end) code to find the selected desktop element.")


class Pywinauto(Exporter):
    name = "pywinauto (UIA backend)"

    def applies_to(self, node):
        return node.tech == "uia"

    def export(self, node, selector_text):
        chain = node.ancestry()
        top = chain[0]
        ta, na = top.selector_attrs(), node.selector_attrs()
        args_top = []
        if ta.get("name"):
            args_top.append(f"title={ta['name']!r}")
        if ta.get("class"):
            args_top.append(f"class_name={ta['class']!r}")
        args = []
        if na.get("automationid"):
            args.append(f"auto_id={na['automationid']!r}")
        if na.get("name"):
            args.append(f"title={na['name']!r}")
        args.append(f"control_type={node.role()!r}")
        return "\n".join([
            "from pywinauto import Desktop",
            f"win = Desktop(backend='uia').window({', '.join(args_top)})",
            f"el = win.child_window({', '.join(args)})" if node is not top else "el = win",
            "el.wait('exists', timeout=10)",
        ])


def register(ctx):
    ctx.add_exporter(Pywinauto)
