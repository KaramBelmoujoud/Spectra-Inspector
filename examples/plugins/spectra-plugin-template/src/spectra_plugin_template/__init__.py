"""Example pip-installable plugin: a "Markdown note" exporter.

It writes a short Markdown snippet describing the selected element, handy for test plans and bug reports.
"""
from spectra.plugins import Exporter, PluginInfo

PLUGIN = PluginInfo(
    id="markdown_note",
    name="Markdown note",
    version="0.1.0",
    author="Your name",
    description="Exports the selected element as a Markdown note (role, name and selector).",
    api_version="1.0",
    homepage="https://example.invalid/spectra-plugin-template",  # your project page
)


class MarkdownNote(Exporter):
    name = "Markdown note"

    def export(self, node, selector_text):
        name = node.get("name") or node.get("text") or ""
        return "\n".join([
            f"**{node.role()}** {name!r}" if name else f"**{node.role()}**",
            "",
            "```",
            selector_text,
            "```",
        ])


def register(ctx):
    ctx.add_exporter(MarkdownNote)
