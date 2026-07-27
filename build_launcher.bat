@echo off
REM ==========================================================
REM  Build ShapesOfWarLauncher.exe — the small updater/launcher
REM  players run instead of the game directly. Re-run after
REM  editing launcher/launcher.py.
REM
REM  APP_VERSION is stamped into the exe's Windows version
REM  resource (Explorer's Details tab, Task Manager, SmartScreen's
REM  "More info" panel). Bump it to match the release tag you're
REM  about to cut.
REM ==========================================================
setlocal
cd /d "%~dp0"
set APP_VERSION=0.0.8

echo Generating version resource ...
python make_version_file.py "build_version_launcher.txt" "%APP_VERSION%" "Shapes of War" "Shapes of War Launcher" "ShapesOfWarLauncher.exe"
if errorlevel 1 (
  echo.
  echo Could not generate the version resource.
  pause
  exit /b 1
)

echo Building ShapesOfWarLauncher.exe ...
python -m PyInstaller --noconfirm --onefile --windowed --name "ShapesOfWarLauncher" --version-file "build_version_launcher.txt" launcher/launcher.py

if errorlevel 1 (
  echo.
  echo BUILD FAILED. Make sure Python and PyInstaller are installed:
  echo     python -m pip install pyinstaller
  echo.
  pause
  exit /b 1
)

echo.
echo Build complete: dist\ShapesOfWarLauncher.exe
pause
