import pytest

from spectra.core.engine import Engine
from spectra.core.node import Backend, Node
from spectra.core.selector import SelectorSyntaxError, parse


class FakeNode(Node):
    tech = "uia"

    def __init__(self, role, parent=None, **attrs):
        self._role, self._parent, self._attrs, self._kids = role, parent, attrs, []
        if parent:
            parent._kids.append(self)

    def key(self):
        return id(self)

    def role(self):
        return self._role

    def selector_attrs(self):
        return self._attrs

    def suggested_attrs(self, is_top=False):
        return ["process", "name"] if is_top else ["automationid", "name"]

    def children(self):
        return self._kids

    def parent(self):
        return self._parent

    def rect(self):
        return (0, 0, 10, 10)


class FakeBackend(Backend):
    tech = "uia"

    def __init__(self, root):
        self._root = root

    def root(self):
        return self._root


@pytest.fixture
def tree():
    root = FakeNode("Desktop")
    w1 = FakeNode("Window", root, name="Untitled - Notepad", process="notepad.exe")
    w2 = FakeNode("Window", root, name="Calc", process="calc.exe")
    pane = FakeNode("Pane", w1)
    edit = FakeNode("Edit", pane, automationid="15", name="Text editor")
    b1 = FakeNode("Button", pane, name="OK")
    b2 = FakeNode("Button", pane, name="OK")
    menu = FakeNode("MenuBar", w1, name="Application")
    FakeNode("Button", w2, name="7", automationid="num7")
    eng = Engine()
    eng.register(FakeBackend(root))
    return eng, dict(root=root, w1=w1, w2=w2, pane=pane, edit=edit, b1=b1, b2=b2, menu=menu)


def test_roundtrip():
    text = 'uia:Window[process="notepad.exe"][name$=" - Notepad" i] >> Edit[automationid="15"]:nth(2)'
    sel = parse(text)
    assert sel.tech == "uia"
    assert len(sel.steps) == 2
    assert sel.steps[0].filters[1].case_insensitive
    assert sel.steps[1].deep and sel.steps[1].nth == 2
    assert parse(sel.to_text()).to_text() == sel.to_text()


def test_whitespace_is_descendant_and_bare_values():
    sel = parse("web:tab[host=github.com] button[type=submit]:visible")
    assert sel.tech == "web" and sel.steps[1].deep and sel.steps[1].visible
    assert sel.steps[1].filters[0].value == "submit"


@pytest.mark.parametrize("bad", ["", "Window[", "Window[name=]", "a > ", "a > web:b", "a:nth(0)", 'a[name="x]'])
def test_syntax_errors(bad):
    with pytest.raises(SelectorSyntaxError):
        parse(bad)


def test_operators(tree):
    eng, n = tree
    assert eng.find_all('Window[name^="Untitled"]').matches == [n["w1"]]
    assert eng.find_all('Window[name~="^C.l"]').matches == [n["w2"]]
    assert eng.find_all('Window[name?="*Notepad"]').matches == [n["w1"]]
    assert eng.find_all('Window[name*="notepad" i]').matches == [n["w1"]]
    assert eng.find_all('Window[name!="Calc"]').matches == [n["w1"]]
    assert eng.find_all('Window > Pane > Button').matches == [n["b1"], n["b2"]]
    assert eng.find_all('Window >> Button[name=OK]:nth(-1)').matches == [n["b2"]]
    assert eng.find_all('>> Edit').matches == [n["edit"]]
    assert eng.find_all('Window[process="notepad.exe"] > Button').matches == []


def test_generate_unique(tree):
    eng, n = tree
    sel, res = eng.generate(n["edit"])
    assert res.matches == [n["edit"]]
    assert sel.to_text() == 'uia:Window[process="notepad.exe"][name="Untitled - Notepad"] >> Edit[automationid="15"][name="Text editor"]'


def test_generate_needs_nth(tree):
    eng, n = tree
    sel, res = eng.generate(n["b2"])
    assert res.matches == [n["b2"]]
    assert sel.steps[-1].nth == 2


def test_generate_top_level(tree):
    eng, n = tree
    sel, res = eng.generate(n["w2"])
    assert res.matches == [n["w2"]]
    assert len(sel.steps) == 1


def test_generate_identical_windows():
    """Two identical top-level windows: the window step needs an index too."""
    root = FakeNode("Desktop")
    targets = []
    for _ in range(2):
        w = FakeNode("Window", root, name="Untitled - Notepad", process="notepad.exe")
        targets.append(FakeNode("Document", w, name="Text editor"))
    eng = Engine()
    eng.register(FakeBackend(root))
    for i, t in enumerate(targets):
        sel, res = eng.generate(t)
        assert res.matches == [t], sel.to_text()
        assert sel.steps[0].nth == i + 1
        assert len(sel.steps) == 2


def test_wildcards_in_equals(tree):
    eng, n = tree
    assert eng.find_all('Window[name="*Notepad"]').matches == [n["w1"]]
    assert eng.find_all('Window[name="untitled*" i]').matches == [n["w1"]]
    assert eng.find_all('Window[name="C?lc"]').matches == [n["w2"]]
    assert eng.find_all('Window[name="Calc?"]').matches == []
    assert eng.find_all('Window[name!="*Notepad"]').matches == [n["w2"]]
    assert eng.find_all('Window[name?="*Notepad"]').matches == [n["w1"]]  # old alias
    assert eng.find_all('Window[name="[*"]').matches == []  # [ stays literal, no fnmatch classes


def test_escaped_star_is_literal_and_round_trips():
    from spectra.core.selector import Filter
    sel = parse(r'Window[name="Untitled\* - Notepad"] >> Edit[name=a\?b]')
    f = sel.steps[0].filters[0]
    assert not f.has_wildcards and f.literal == "Untitled* - Notepad"
    assert f.matches("Untitled* - Notepad") and not f.matches("Untitled - Notepad")
    assert sel.steps[1].filters[0].matches("a?b") and not sel.steps[1].filters[0].matches("axb")
    assert parse(sel.to_text()).to_text() == sel.to_text()
    assert r'"Untitled\* - Notepad"' in sel.to_text()
    assert Filter("name", "*=", r"x\*").matches("ax*b")  # \* is literal with every operator
    plain = parse(r'Window[name="C:\\temp"]')  # other backslashes unchanged
    assert plain.steps[0].filters[0].value == "C:\\temp"
    assert parse(plain.to_text()).steps[0].filters[0].value == "C:\\temp"


def test_generator_escapes_real_stars():
    root = FakeNode("Desktop")
    w = FakeNode("Window", root, name="*Untitled - Notepad", process="notepad.exe")
    FakeNode("Window", root, name="Untitled - Notepad", process="notepad.exe")
    eng = Engine()
    eng.register(FakeBackend(root))
    sel, res = eng.generate(w)
    assert res.matches == [w]
    assert r'name="\*Untitled - Notepad"' in sel.to_text()
