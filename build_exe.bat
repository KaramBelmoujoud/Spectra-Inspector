@echo off
rem Builds dist\SpectraInspector\SpectraInspector.exe (a folder you can zip and copy anywhere).
rem spectra.spec also copies LICENSE, NOTICE, THIRD_PARTY_NOTICES.md and licenses\ into that folder.
cd /d "%~dp0"
if not exist .venv ( py -3 -m venv .venv || python -m venv .venv )
.venv\Scripts\python -m pip install -r requirements-dev.txt || (pause & exit /b 1)
rem Pre-generate the UI Automation COM wrappers so the frozen app does not need to.
.venv\Scripts\python -c "import comtypes.client as c; c.GetModule('UIAutomationCore.dll')"
.venv\Scripts\pyinstaller --noconfirm spectra.spec || (pause & exit /b 1)
echo.
echo Built: dist\SpectraInspector\SpectraInspector.exe (with LICENSE, NOTICE, THIRD_PARTY_NOTICES.md, licenses\)
pause
