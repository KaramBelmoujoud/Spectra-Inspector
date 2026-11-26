@echo off
rem Spectra Inspector: first run creates a virtual environment and installs dependencies.
cd /d "%~dp0"
if not exist .venv (
    py -3 -m venv .venv || python -m venv .venv || (echo Python 3.10+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\python -m pip install -r requirements.txt || (pause & exit /b 1)
)
start "" .venv\Scripts\pythonw -m spectra
