# PyInstaller spec: pyinstaller --noconfirm spectra.spec
#
# Keep this a ONE-FOLDER build (EXE with exclude_binaries + COLLECT), never one-file: Qt and PySide6 are
# used under the LGPL-3.0, and their libraries must stay separate, replaceable files (see THIRD_PARTY_NOTICES.md).
import os
import shutil

from PyInstaller.utils.hooks import collect_submodules

# built-in plugins are found at run time (pkgutil), so PyInstaller must be told to include them
hidden = (collect_submodules("comtypes") + ["comtypes.gen", "comtypes.gen.UIAutomationClient"]
          + collect_submodules("spectra.builtin_plugins") + collect_submodules("spectra.plugins"))

a = Analysis(["spectra_launcher.py"], pathex=["."], hiddenimports=hidden,
             excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.Qt3DCore"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SpectraInspector", console=False,
          upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="SpectraInspector")

# Ship the license, notices and the LGPL/GPL texts next to SpectraInspector.exe.
out = os.path.join(DISTPATH, "SpectraInspector")
for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
    shutil.copy(name, out)
shutil.copytree("licenses", os.path.join(out, "licenses"), dirs_exist_ok=True)
