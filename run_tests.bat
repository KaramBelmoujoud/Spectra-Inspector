@echo off
cd /d "%~dp0"
.venv\Scripts\python -m pip install -q pytest
.venv\Scripts\python -m pytest -v tests
pause
