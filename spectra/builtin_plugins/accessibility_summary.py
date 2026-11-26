"""A small accessibility check shown in the Properties panel."""
from spectra.plugins import PluginInfo

PLUGIN = PluginInfo(
    id="accessibility_summary", name="Accessibility summary", version="1.0",
    author="Spectra Inspector contributors",
    description="Adds an 'Accessibility summary' group to the Properties panel: accessible name, role, "
                "keyboard focus, and warnings such as a button without a name.")

GROUP = "Accessibility summary"
UIA_INTERACTIVE = {"Button", "CheckBox", "ComboBox", "Edit", "Hyperlink", "ListItem", "MenuItem", "RadioButton",
                   "Slider", "Spinner", "SplitButton", "Tab", "TabItem", "TreeItem", "DataItem"}
WEB_INTERACTIVE = {"button", "a", "input", "select", "textarea", "summary"}
P_IS_KEYBOARD_FOCUSABLE, P_IS_ENABLED = 30009, 30010


def summarize(node):
    """(name, role, focusable, warnings) for UI Automation and web elements; None for others."""
    warnings = []
    if node.tech == "uia":
        name = node.get("name") or ""
        role = node.role()
        focusable = node.prop(P_IS_KEYBOARD_FOCUSABLE) if hasattr(node, "prop") else None
        if role in UIA_INTERACTIVE and not name.strip():
            warnings.append(f"{role} has no accessible name (Name is empty)")
        if role in UIA_INTERACTIVE and focusable is False and node.prop(P_IS_ENABLED):
            warnings.append(f"{role} can't be reached with the keyboard")
        return name, role, focusable, warnings
    if node.tech == "web":
        tag = (node.role() or "").lower()
        get = node.get
        name = (get("aria-label") or get("text") or get("title") or get("alt") or get("placeholder") or "").strip()
        role = get("role") or tag
        if tag in WEB_INTERACTIVE and tag != "input" and not name:
            warnings.append(f"<{tag}> has no accessible name (no text, aria-label or title)")
        if tag == "input" and (get("type") or "text") not in ("hidden", "submit", "button", "reset") \
                and not (name or get("id") or get("aria-labelledby")):
            warnings.append("<input> has no label, aria-label, placeholder or id for a <label for>")
        if tag == "img" and get("alt") is None:
            warnings.append("<img> has no alt attribute")
        focusable = tag in WEB_INTERACTIVE or (get("tabindex") not in (None, "-1"))
        return name, role, focusable, warnings
    return None


def provider(node):
    s = summarize(node)
    if s is None:
        return []
    name, role, focusable, warnings = s
    rows = [(GROUP, "accessible name", name or "(none)"), (GROUP, "role", role),
            (GROUP, "keyboard focusable", "unknown" if focusable is None else str(bool(focusable)))]
    rows += [(GROUP, "warning", w) for w in warnings] or [(GROUP, "warnings", "none")]
    return rows


def register(ctx):
    ctx.add_property_provider(provider)
