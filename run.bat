@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" goto run
echo First run: setting up ZeroStudio. This takes a minute and needs Python 3.10 or newer.
py -3 -m venv .venv 2>nul || python -m venv .venv
if not exist ".venv\Scripts\python.exe" (
  echo Python was not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo Installing PySide6 failed. Check your internet connection and run this again.
  pause
  exit /b 1
)
:run
start "" ".venv\Scripts\pythonw.exe" main.py %*
