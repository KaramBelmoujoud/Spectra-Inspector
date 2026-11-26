# Contributing to Spectra Inspector

Thanks for helping! Bug reports, ideas, documentation fixes and pull requests are all welcome. Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Development setup

Spectra needs Windows 10/11 and a 64-bit Python 3.10 or newer.

```powershell
git clone https://github.com/OWNER/spectra-inspector.git
cd spectra-inspector
py -3 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m spectra          # start the app
```

## Tests and lint

```powershell
.venv\Scripts\python -m pytest           # all tests
.venv\Scripts\python -m pytest tests/test_core.py   # selector language only, works on any OS
.venv\Scripts\ruff check .
```

* `tests/test_core.py`: selector parsing, matching and generation on a fake tree. Runs everywhere.
* `tests/test_web.py`: drives a headless Chrome/Edge on a local page. Skipped when no Chromium browser is installed.
* `tests/test_windows.py`: live UI Automation checks. They start their own Character Map window and close only that one.

Please add a test for any behaviour you change where that's practical, and keep CI green.

## Code style

* Keep the existing style: small functions, type hints where they help, comments that explain *why*.
* `ruff` (configured in `pyproject.toml`) must pass. Line length is 120.
* Anything that talks to UI Automation, the DevTools protocol or the Java Access Bridge runs on the driver thread (`spectra/driver.py`). GUI code submits work with `driver.submit(...)` and gets results back through `UiBridge`; it never calls COM objects directly.
* Never block the GUI thread on the driver (`driver.call`) from Qt code: UI Automation may need the GUI thread to answer for Spectra's own windows.

## Adding a back end

A back end makes a new UI technology inspectable. It lives in `spectra/backends/` and implements the interface in `spectra/core/node.py`:

* `Backend` (one per technology): `tech` (the selector prefix, such as `"uia"`), `title`, `root()`, `from_point(x, y)` and `available()`.
* `Node` (one per element): `key()` (a stable identity), `role()`, `selector_attrs()`, `suggested_attrs(is_top)`, `properties()`, `label()`, `rect()`, `children()` and `parent()`. Optionally `find(step, deep, budget)` as a fast search path (return `None` to let the engine walk `children()`).

Register it in `Service.init()` (`spectra/service.py`), route on-screen picking to it in `Service.element_at()` if it applies, and add its prefix to `TECHS` in `spectra/core/selector.py`. The search engine, selector generator, editor, validation and code views then work without further changes.

## Pull requests

1. Fork, create a branch, and keep the change focused.
2. Describe what changed and how you tested it (the PR template has a checklist).
3. Update `README.md` and `CHANGELOG.md` when behaviour visible to users changes.

By contributing you agree that your contributions are licensed under the [Apache License 2.0](LICENSE).
