# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-26

First public version.

### Added

* **Pick on screen (F3):** hover with a live, DPI-correct highlight, then click to capture (the click is not passed to the application) or press Ctrl. Esc or a right-click cancels. Spectra minimizes while you pick (toolbar toggle).
* **UI tree** for the desktop (UI Automation control and raw views), connected browsers (live DOM, shadow roots, iframes) and Java applications.
* **Properties:** every UI Automation property grouped by pattern, MSAA, Win32 details, Java, HTML attributes, accessibility role and name, geometry.
* **Selector language** with `>` / `>>` steps, `=` with `*` and `?` wildcards (`\*` for a literal star), `!=`, `*=`, `^=`, `$=`, `~=` regex, a case-insensitive flag, `:nth()` and `:visible`.
* **Selector generator** that finds the shortest unique selector, adding ancestors, `:nth()` (including on identical top-level windows) or a full path when needed.
* **Selector editor** with ancestry levels, attributes and match operators, live validation, Highlight matches, Regenerate and Repair.
* **Web pages without a browser extension** over the DevTools protocol: launch or connect to Chrome, Edge and other Chromium browsers, F3 hover-picking, F4 browser inspect mode, CSS and XPath with match counts, Playwright and Selenium snippets.
* **Java** applications through the Java Access Bridge.
* **Try it** actions: Focus, Click, Invoke, Toggle, Expand/Collapse, Select, Set value, Type text, Scroll into view, element screenshots.
* **Follow focus**, save and open selector files, F1 syntax help.
* **Python scripting API** (`spectra.api.Spectra`) using the same selectors.
* Crash and error log in `%LOCALAPPDATA%\Spectra\spectra.log`.
* Windows executable built with PyInstaller.

### Performance

* Desktop windows are listed from visible top-level windows instead of a UI Automation search over every hidden window (about 10x faster).
* All properties of an element are read in one cross-process request.
* Browser debugging ports are probed in parallel with a short timeout, so start-up no longer waits about 12 s when no browser is running.
* Tree selection is debounced and stale work is dropped, so arrow-keying through the tree stays responsive.

[0.1.0]: https://github.com/KaramBelmoujoud/Spectra-Inspector/releases/tag/v0.1.0
