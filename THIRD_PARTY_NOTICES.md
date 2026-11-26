# Third-party notices

Spectra Inspector itself is licensed under the [Apache License 2.0](LICENSE). It uses the components below. When you install Spectra from source or with pip, they are downloaded separately under their own licenses. The Windows executable (`SpectraInspector.exe` and its folder) **includes** them, so this file, `LICENSE`, `NOTICE` and the texts in `licenses/` are shipped inside every build.

| Component | Used for | License | Source / license text |
|---|---|---|---|
| Qt 6 (via PySide6) | GUI toolkit | LGPL-3.0-only (also available under GPL and commercial terms) | https://code.qt.io, https://download.qt.io/official_releases/qt/ · [licenses/LGPL-3.0.txt](licenses/LGPL-3.0.txt), [licenses/GPL-3.0.txt](licenses/GPL-3.0.txt) |
| PySide6 and Shiboken6 (Qt for Python) | Python bindings for Qt | LGPL-3.0-only (also GPL / commercial) | https://code.qt.io/cgit/pyside/pyside-setup.git, https://download.qt.io/official_releases/QtForPython/ · [licenses/LGPL-3.0.txt](licenses/LGPL-3.0.txt) |
| comtypes | UI Automation over COM | MIT | https://github.com/enthought/comtypes/blob/main/LICENSE.txt |
| websocket-client | DevTools protocol connection | Apache-2.0 | https://github.com/websocket-client/websocket-client/blob/master/LICENSE |
| Pillow | Element screenshots | MIT-CMU (HPND) | https://github.com/python-pillow/Pillow/blob/main/LICENSE |
| CPython (in the .exe) | Python runtime | PSF-2.0 | https://docs.python.org/3/license.html |
| PyInstaller bootloader (in the .exe) | Starts the frozen app | GPL-2.0-or-later **with the PyInstaller bootloader exception**, which allows distributing the bootloader with programs under any license | https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt |
| Microsoft Visual C++ runtime DLLs (in the .exe, shipped with Python) | Runtime support | Microsoft redistributable terms | https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files |

## Qt and PySide6 (LGPL-3.0)

Spectra uses Qt and PySide6 under the GNU Lesser General Public License version 3. Spectra does not modify them.

* **Source code.** The complete, corresponding source code of Qt and PySide6 is available from the Qt Project at https://code.qt.io and https://download.qt.io/official_releases/QtForPython/ (pick the version listed below or in the build's `PySide6` folder).
* **Replacing the libraries.** The executable is built as a **folder** (PyInstaller "one-folder" mode, never "one-file"), so the Qt and PySide6 libraries stay ordinary, separate files inside `SpectraInspector\_internal\PySide6\` and `SpectraInspector\_internal\shiboken6\`. You may replace them with your own compatible build of the same Qt / PySide6 version (for example a modified one) and the application will use them. Builds must stay in one-folder mode to keep this possible.
* **License texts.** `licenses/LGPL-3.0.txt` and `licenses/GPL-3.0.txt` (the LGPL is a set of additional permissions on top of the GPL).

Versions used for the 0.1.0 release: Qt 6.12 / PySide6 6.12 (see `requirements.txt` for the minimum supported version).

## Python packages installed with pip

The other Python dependencies (comtypes, websocket-client, Pillow) are permissively licensed. Their full license texts are linked in the table above and are included in each installed package (`*.dist-info/licenses/`).
