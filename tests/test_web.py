"""Integration test against a real headless Chromium (skipped when none is installed)."""
import shutil
import subprocess
import tempfile
import time
import urllib.parse

import pytest

from spectra.backends.cdp import find_browser, probe
from spectra.backends.web import WebBackend
from spectra.core.engine import Engine
from spectra.core.webpaths import css_path, xpath

PAGE = """<!doctype html><html><head><title>Spectra test</title></head><body>
<form id="login"><input name="user" placeholder="User name"><input type="password" name="pw">
<button type="submit">Sign in</button></form>
<ul class="list"><li>One</li><li>Two</li><li>Two</li></ul>
<div id="host"></div>
<iframe srcdoc="<p>inside frame</p><button data-testid='frame-btn'>Frame button</button>"></iframe>
<script>
const r = document.getElementById('host').attachShadow({mode:'open'});
r.innerHTML = '<span class="s">shadow text</span><button aria-label="Close dialog">x</button>';
</script></body></html>"""

PORT = 9333


@pytest.fixture(scope="module")
def browser():
    exe = find_browser("Chrome") or shutil.which("chromium")
    if not exe:
        pytest.skip("no Chromium browser available")
    profile = tempfile.mkdtemp()
    url = "data:text/html," + urllib.parse.quote(PAGE)
    proc = subprocess.Popen([exe, "--headless=new", "--no-sandbox", "--disable-gpu",
                             f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}", url],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        if probe("127.0.0.1", PORT):
            break
        time.sleep(0.2)
    else:
        proc.kill()
        pytest.skip("browser did not open its debugging port")
    time.sleep(1.0)
    yield
    proc.kill()


@pytest.fixture
def engine(browser):
    wb = WebBackend()
    assert wb.add_endpoint("127.0.0.1", PORT)
    eng = Engine()
    eng.register(wb)
    return eng, wb


def test_tabs_and_tree(engine):
    eng, wb = engine
    tabs = wb.root().children()
    assert any(t.get("title") == "Spectra test" for t in tabs)


def test_search_through_shadow_and_frame(engine):
    eng, wb = engine
    r = eng.find_all('web:tab[title="Spectra test"] >> button[aria-label="Close dialog"]')
    assert len(r.matches) == 1, r.error
    r = eng.find_all('web:tab[title="Spectra test"] >> iframe >> button[data-testid="frame-btn"]')
    assert len(r.matches) == 1, r.error
    assert r.matches[0].get("text") == "Frame button"
    r = eng.find_all('web:tab >> li[text="Two"]')
    assert len(r.matches) == 2


def test_generate(engine):
    eng, wb = engine
    target = eng.find_all('web:tab >> li[text="Two"]:nth(2)').matches[0]
    sel, res = eng.generate(target)
    assert res.matches == [target], sel.to_text()
    assert sel.to_text().startswith("web:tab[")
    btn = eng.find_first('web:tab >> button[type="submit"]')
    sel, res = eng.generate(btn)
    assert res.matches == [btn]
    assert 'text="Sign in"' in sel.to_text() or "form#login" in sel.to_text() or 'id="login"' in sel.to_text()


def test_locators(engine):
    eng, wb = engine
    btn = eng.find_first('web:tab >> button[type="submit"]')
    page = btn.page
    assert css_path(btn) == "form#login > button"
    assert page.count_css(css_path(btn)) == 1
    assert page.count_xpath(xpath(btn)) == 1
    li = eng.find_all('web:tab >> li').matches[2]
    assert page.count_css(css_path(li)) == 1


def test_geometry_and_properties(engine):
    eng, wb = engine
    btn = eng.find_first('web:tab >> button[type="submit"]')
    box = btn.page.css_box(btn.bid)
    assert box and box[2] > box[0]
    props = dict(((g, k), v) for g, k, v in btn.properties())
    assert props[("Accessibility", "role")] == "button"
    assert props[("Accessibility", "name")] == "Sign in"
    hit = btn.page.node_at_css((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    assert hit == btn
    btn.page.highlight(btn.bid)
    btn.page.highlight(None)


def test_api_actions(browser):
    from spectra.api import Spectra
    s = Spectra(browser_port=PORT)
    el = s.find('web:tab[title="Spectra test"] >> input[name="user"]', timeout=5)
    el.set_value("alice")
    el.type_text("!")
    page = el.node.page
    assert page.ensure().evaluate("document.querySelector('input[name=user]').value") == "alice!"
    assert s.exists('web:tab >> button[text="Sign in"]')
    assert not s.exists('web:tab >> button[text="Nope"]')
