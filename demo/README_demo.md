# Demo

* `demo_shop.html`: a small web shop used for demos and screenshots: navigation links, a search box, a login form, six identical "Add to cart" buttons (to show `:nth`), a table, a shadow DOM web component and a same-origin iframe. Serve it with `python -m http.server` from this folder so the tab has a real host.
* `record_demo.py`: records a self-captioned demo video of every feature (about 8 minutes) with ffmpeg. It is not part of the app.

## Recording the demo video

The video itself is not stored in the repository (it is about 14 MB). To record it:

```powershell
.venv\Scripts\python demo\record_demo.py          # record (needs ffmpeg on PATH)
.venv\Scripts\python demo\record_demo.py --dry    # rehearse without recording
.venv\Scripts\python demo\record_demo.py --only 5,6
```

The script drives the real mouse and keyboard, so don't touch the PC while it runs. It records one monitor: set `MON_X`, `MON_Y`, `SCREEN_W` and `SCREEN_H` at the top of the script to that monitor's position and work area. File dialogs and Explorer windows use a neutral folder (`C:\SpectraDemo` by default, or the `SPECTRA_DEMO_STAGE` environment variable), which is removed afterwards. The output goes to `demo/chapters/`.

## Chapters

1. **Intro and layout**: UI tree, ancestry and attribute editor, selector box with live validation, properties, Locators & code, Try it, Log.
2. **Pick on the desktop**: F3 in Character Map, Spectra minimizes, live highlight while hovering, click to capture (the click is not passed to the app), properties and filtering, the tree follows, Ctrl capture on the Copy button.
3. **Selector editor**: wildcard value (`Character*`), match operators (`~=` regex, `*=` contains), ticking/unticking attributes, adding an ancestry level, the Index (`:nth`), Highlight matches, a syntax error, Regenerate.
4. **File Explorer and wildcards**: two Explorer windows, `* - File Explorer` matches both, `store*` narrows it to one.
5. **Web pages without an extension**: Browsers ▸ Launch Chrome, the demo store in a second tab, the DOM in the tree, F3 inside the page, the 3rd "Add to cart" gets `:nth(3)`, CSS/XPath/Playwright/Selenium, Index 5 and all six highlighted, F4 browser inspect mode, shadow DOM and iframe elements, Repair of a broken selector.
6. **Try it**: Set value in the search box, Click the Search button, fill the email and click Sign in, element screenshot, Set value and Toggle in Character Map.
7. **example.com**: picking an element of a real public page.
8. **Extras**: Follow focus while tabbing through the form, Raw view, Save and Open selector files, F1 syntax help, the Log, and a Python script using the Spectra API to click two "Add to cart" buttons.
9. **Outro**: feature summary.
