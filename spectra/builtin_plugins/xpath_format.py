"""An XPath-like notation for UI Automation selectors (output only)."""
from spectra.plugins import PluginInfo, SelectorFormat

PLUGIN = PluginInfo(
    id="xpath_format", name="XPath-like format (UIA)", version="1.0", author="Spectra Inspector contributors",
    description="Shows desktop selectors as /Window[@Name='...']//Edit[@AutomationId='...'].")

ATTRS = {"name": "Name", "automationid": "AutomationId", "class": "ClassName", "process": "ProcessName",
         "framework": "FrameworkId", "type": "LocalizedControlType", "controlid": "ControlId", "hwnd": "NativeWindowHandle",
         "helptext": "HelpText", "value": "Value", "pid": "ProcessId"}


def _quote(v: str) -> str:
    if "'" not in v:
        return f"'{v}'"
    if '"' not in v:
        return f'"{v}"'
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in v.split("'")) + ")"


def _wildcard_regex(value: str) -> str:
    import re
    out, i = [], 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value) and value[i + 1] in "*?":
            out.append(re.escape(value[i + 1]))
            i += 2
            continue
        out.append(".*" if c == "*" else "." if c == "?" else re.escape(c))
        i += 1
    return "^" + "".join(out) + "$"


class XPathLike(SelectorFormat):
    name = "XPath-like (UIA)"

    def applies_to(self, node):
        return node.tech == "uia"

    def from_selector(self, selector, node):
        out = []
        for st in selector.steps:
            axis = "//" if st.deep else "/"
            preds = []
            for f in st.filters:
                attr = "@" + ATTRS.get(f.name, f.name)
                if f.op is None:
                    preds.append(attr)
                elif f.op in ("=", "?=") and not f.has_wildcards:
                    preds.append(f"{attr}={_quote(f.literal or '')}")
                elif f.op == "!=":
                    preds.append(f"{attr}!={_quote(f.value)}")
                elif f.op == "*=":
                    preds.append(f"contains({attr}, {_quote(f.value)})")
                elif f.op == "^=":
                    preds.append(f"starts-with({attr}, {_quote(f.value)})")
                elif f.op == "$=":
                    v = _quote(f.value)
                    preds.append(f"substring({attr}, string-length({attr}) - string-length({v}) + 1)={v}")
                elif f.op == "~=":  # XPath 2.0
                    preds.append(f"matches({attr}, {_quote(f.value)})")
                else:  # = with * / ? wildcards: XPath 2.0 regular expression
                    preds.append(f"matches({attr}, {_quote(_wildcard_regex(f.value))})")
            role = st.role if st.role != "*" else "*"
            out.append(axis + role + "".join(f"[{p}]" for p in preds) + (f"[{st.nth}]" if st.nth else ""))
        return "".join(out)


def register(ctx):
    ctx.add_selector_format(XPathLike)
