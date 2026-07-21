@echo off
REM ==========================================================
REM  Rebuilds ShapesOfWar.exe from the current source, then
REM  launches it. Double-click THIS instead of dist\ShapesOfWar.exe
REM  if you want to always play your latest changes without running
REM  build.bat by hand first.
REM
REM  Windows won't let a running .exe overwrite/rebuild itself, so
REM  the trick is having a separate, non-running file - this one -
REM  do the rebuilding instead.
REM ==========================================================
setlocal
cd /d "%~dp0"

echo Building ShapesOfWar.exe ...
python -m PyInstaller --noconfirm --onefile --windowed --name "ShapesOfWar" main.py

if errorlevel 1 (
  echo.
  echo BUILD FAILED. Make sure Python and PyInstaller are installed:
  echo     python -m pip install pyinstaller
  echo.
  pause
  exit /b 1
)

echo.
echo Build complete - launching ShapesOfWar.exe ...
start "" "%~dp0dist\ShapesOfWar.exe"
