@echo off
REM ==========================================================
REM  Build ShapesOfWar.exe — standalone Tkinter desktop app.
REM  Re-run this after editing any game files to refresh the exe.
REM
REM  APP_VERSION is stamped into the exe's Windows version
REM  resource (Explorer's Details tab, Task Manager). Bump it to
REM  match the release tag you're about to cut.
REM ==========================================================
setlocal
cd /d "%~dp0"
set APP_VERSION=0.0.9

echo Generating version resource ...
python make_version_file.py "build_version_game.txt" "%APP_VERSION%" "Shapes of War" "Shapes of War" "ShapesOfWar.exe"
if errorlevel 1 (
  echo.
  echo Could not generate the version resource.
  pause
  exit /b 1
)

echo Building ShapesOfWar.exe ...
python -m PyInstaller --noconfirm --onefile --windowed --name "ShapesOfWar" --version-file "build_version_game.txt" main.py

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
