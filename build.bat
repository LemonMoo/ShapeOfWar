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
set APP_VERSION=0.3.2

echo Generating version resource ...
python make_version_file.py "build_version_game.txt" "%APP_VERSION%" "Shapes of War" "Shapes of War" "ShapesOfWar.exe"
if errorlevel 1 (
  echo.
  echo Could not generate the version resource.
  pause
  exit /b 1
)

echo Building ShapesOfWar.exe ...
REM  GPU battle renderer (app/ui/gl_battle.py) pulls in moderngl + pyopengltk.
REM  None of it is reachable by static analysis, so PyInstaller needs telling:
REM    glcontext  ships a compiled wgl.*.pyd that moderngl loads at RUNTIME by
REM               name -- --collect-all is what actually brings the .pyd along,
REM               a plain --hidden-import does not.
REM    OpenGL.*   PyOpenGL picks its platform and array backends dynamically too.
REM  Without these the exe builds fine and then falls back to the Tk canvas on
REM  every machine, which is exactly the failure that is easy to miss.
python -m PyInstaller --noconfirm --onefile --windowed --name "ShapesOfWar" --version-file "build_version_game.txt" --collect-all glcontext --hidden-import moderngl --hidden-import pyopengltk --hidden-import numpy --hidden-import OpenGL --hidden-import OpenGL.platform.win32 --hidden-import OpenGL.arrays.ctypesarrays --hidden-import OpenGL.arrays.numpymodule --hidden-import OpenGL.arrays.lists --hidden-import OpenGL.arrays.numbers --hidden-import OpenGL.arrays.strings main.py

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
