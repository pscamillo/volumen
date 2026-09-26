@echo off
rem volumen.bat - start Volumen on Windows. Needs uv (https://docs.astral.sh/uv/).
rem Double-click, or run from a terminal. uv is found even when this terminal
rem was opened before uv was installed and its PATH is not up to date yet.
cd /d "%~dp0"
where uv >nul 2>nul && (set "UV=uv" & goto run)
if exist "%USERPROFILE%\.local\bin\uv.exe" (set "UV=%USERPROFILE%\.local\bin\uv.exe" & goto run)
if exist "%USERPROFILE%\.cargo\bin\uv.exe" (set "UV=%USERPROFILE%\.cargo\bin\uv.exe" & goto run)
echo uv was not found. Install it from https://docs.astral.sh/uv/ and run this again.
pause
exit /b 1
:run
"%UV%" run app.py
if errorlevel 1 (
  echo Volumen exited with an error. See the messages above.
  pause
)
