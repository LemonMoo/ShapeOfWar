@echo off
REM ==========================================================
REM  Build ShapesOfWar.exe — standalone Tkinter desktop app.
REM  Re-run this after editing any game files to refresh the exe.
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
echo Build complete: dist\ShapesOfWar.exe
pause
