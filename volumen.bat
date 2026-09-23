@echo off
rem volumen.bat — start Volumen on Windows. Needs uv on PATH
rem (https://docs.astral.sh/uv/). Double-click, or run from a terminal.
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo uv was not found on PATH. Install it from https://docs.astral.sh/uv/ and run again.
  pause
  exit /b 1
)
uv run app.py
if errorlevel 1 (
  echo Volumen exited with an error. See the messages above.
  pause
)
