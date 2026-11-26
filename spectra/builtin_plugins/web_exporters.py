"""Playwright, Selenium and Robot Framework snippets for the selected element."""
import json

from spectra.plugins import Exporter, PluginInfo

PLUGIN = PluginInfo(
    id="web_exporters", name="Web code exporters", version="1.0", author="Spectra Inspector contributors",
    description="Playwright, Selenium and Robot Framework (Browser library) code for web elements, and a "
                "Robot Framework keyword for desktop elements.")


def css_for(node) -> str:
    from spectra.core.webpaths import css_path
    return css_path(node)


class Playwright(Exporter):
    name = "Playwright (Python)"

    def applies_to(self, node):
        return node.tech == "web"

    def export(self, node, selector_text):
        return f"page.locator({json.dumps('css=' + css_for(node))}).click()"


class Selenium(Exporter):
    name = "Selenium (Python)"

    def applies_to(self, node):
        return node.tech == "web"

    def export(self, node, selector_text):
        return ("from selenium.webdriver.common.by import By\n"
                f"driver.find_element(By.CSS_SELECTOR, {json.dumps(css_for(node))}).click()")


class RobotFramework(Exporter):
    name = "Robot Framework"

    def applies_to(self, node):
        return node.tech in ("web", "uia", "java")

    def export(self, node, selector_text):
        if node.tech == "web":
            return ("*** Settings ***\n"
                    "Library    Browser\n\n"
                    "*** Test Cases ***\n"
                    "Click The Element\n"
                    f"    Click    css={css_for(node)}")
        # desktop: call the Spectra API from Robot's BuiltIn library, no extra Robot library needed
        sel = selector_text.replace("'''", "\\'\\'\\'")
        return ("*** Test Cases ***\n"
                "Click The Element\n"
                f"    ${{element}}=    Evaluate    __import__('spectra.api', fromlist=['Spectra']).Spectra()"
                f".find(r'''{sel}''', timeout=10)\n"
                "    Call Method    ${element}    click")


def register(ctx):
    for exporter in (Playwright, Selenium, RobotFramework):
        ctx.add_exporter(exporter)
