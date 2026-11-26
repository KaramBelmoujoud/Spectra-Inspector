"""CSS and XPath locators for web elements (for use in other tools)."""
from __future__ import annotations

import re

_CSS_IDENT = re.compile(r"-?[_a-zA-Z][_a-zA-Z0-9-]*")


def _css_escape_ident(s: str) -> str:
    if _CSS_IDENT.fullmatch(s):
        return s
    return "".join(c if c.isalnum() or c in "-_" else "\\" + c for c in s)


def _same_tag_index(node) -> tuple:
    par = node._parent
    if par is None:
        return 1, 1
    same = [k for k in par._kids if k.role() == node.role() and k.raw.get("parentId") == node.raw.get("parentId")]
    return (same.index(node) + 1 if node in same else 1), len(same)


def css_path(node) -> str:
    """Shortest reasonable CSS path, stopping at an id or a test-id ancestor.

    CSS cannot cross shadow roots or frames; the path covers the innermost
    document/shadow tree and is prefixed with a note when that happens.
    """
    from ..backends.web import TEST_ID_ATTRS, looks_dynamic

    parts = []
    cur = node
    crossed = False
    while cur is not None and hasattr(cur, "raw"):
        a = cur.html_attrs()
        tag = cur.role()
        if a.get("id") and not looks_dynamic(a["id"]):
            parts.append(f"{tag}#{_css_escape_ident(a['id'])}")
            break
        tid = next((k for k in TEST_ID_ATTRS if a.get(k)), None)
        if tid:
            parts.append(f'{tag}[{tid}="{a[tid]}"]')
            break
        if tag in ("html",):
            parts.append("html")
            break
        idx, total = _same_tag_index(cur)
        parts.append(f"{tag}:nth-of-type({idx})" if total > 1 else tag)
        par = cur._parent
        if par is not None and cur.raw.get("parentId") != par.raw.get("nodeId"):
            crossed = True
            break
        cur = par
    path = " > ".join(reversed(parts))
    return ("/* inside shadow root or frame */ " + path) if crossed else path


def xpath(node) -> str:
    from ..backends.web import TEST_ID_ATTRS, looks_dynamic

    parts = []
    cur = node
    while cur is not None and hasattr(cur, "raw"):
        a = cur.html_attrs()
        tag = cur.role()
        if a.get("id") and not looks_dynamic(a["id"]):
            parts.append(f"//{tag}[@id={_xq(a['id'])}]")
            break
        tid = next((k for k in TEST_ID_ATTRS if a.get(k)), None)
        if tid:
            parts.append(f"//{tag}[@{tid}={_xq(a[tid])}]")
            break
        idx, total = _same_tag_index(cur)
        parts.append(f"/{tag}[{idx}]" if total > 1 else f"/{tag}")
        par = cur._parent
        if par is not None and cur.raw.get("parentId") != par.raw.get("nodeId"):
            parts.append("/* shadow root or frame */")
            break
        cur = par
    return "".join(reversed(parts))


def _xq(s: str) -> str:
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in s.split("'")) + ")"
