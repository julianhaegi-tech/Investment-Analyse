@echo off
REM Startet die App direkt aus dem Quellcode (Alternative zur .exe). Benoetigt Python 3.10+.
cd /d "%~dp0"
if not exist .venv (
  echo Erstinstallation ...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt
)
.venv\Scripts\python run.py
