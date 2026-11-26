# Spectra 0.2 plugin showcase

`demo/Spectra_0.2_Plugins_Showcase.mp4` is a 3 min 53 s recording (1920x1032, 30 fps, H.264, no audio; on-screen captions explain each step) of Spectra Inspector 0.2.0 showing the plugin system. It is not stored in the repository (`demo/*.mp4` is git-ignored); it was recorded on a real Windows desktop with a scripted mouse and keyboard, using Character Map, the demo store (`demo_shop.html`) in Chrome, and the example plugin `examples/plugins/hello_spectra.py`.

| Time | Chapter |
|---|---|
| 0:01 | Spectra Inspector 0.2.0: plugins |
| 0:04 | 1 · Plugins ▸ Plugin Manager |
| 0:23 | 2 · Exporters and formats for a desktop app |
| 0:37 | 3 · Accessibility summary |
| 0:41 | 4 · Plugin actions: Copy as JSON |
| 0:54 | 5 · Export menu |
| 1:06 | 6 · Python console |
| 1:43 | 7 · Web exporters |
| 2:03 | 7 · Web elements in the console |
| 2:22 | 8 · Switch a plugin off |
| 2:44 | 9 · Install a third-party plugin |
| 3:17 | 10 · The new plugin at work |
| 3:33 | 11 · Switch it off again |
| 3:46 | Spectra Inspector 0.2.0 · plugins |

What each chapter shows:

1. **Plugin Manager**: the six built-in plugins with version, author, source and status, the security warning, details of a plugin, and *Reload*.
2. **Desktop exporters**: picking Character Map's text box; *Locators & code* shows the pywinauto, Robot Framework and XPath-like (UIA) sections added by plugins.
3. **Accessibility summary**: the rows a property-provider plugin adds to *Properties*.
4. **Plugin actions**: *Copy as JSON* in the *Try it* tab, pasted into the Python console.
5. **Export menu**: copying the element in the XPath-like notation.
6. **Python console**: `node.label()`, `find()` with a wildcard plus `highlight()`, `find_all()`, an example snippet that generates a selector, and a mistake shown as a normal traceback.
7. **Web exporters**: the third "Add to cart" button gets Playwright, Selenium and Robot Framework (Browser) code; *Export > Copy as Playwright*; the console frames all six buttons in turn.
8. **Switching a plugin off and on**: unticking *Web code exporters* removes its sections, ticking it brings them back.
9. **Installing a third-party plugin**: *Install from file…* with `hello_spectra.py` (next to the pip-installable `spectra-plugin-template`), the install warning and the first-time trust confirmation.
10. **The new plugin at work**: its *Say hello* action and the *Hello* panel following the selection.
11. **Switching it off again**: its action and panel disappear.
