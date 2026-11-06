@echo off
setlocal
cd /d "%~dp0"
title CLTools setup
echo ============================================
echo   CLTools setup - Disney's Chicken Little
echo ============================================
echo.
if not exist "..\Chick.exe" (
  echo [!] Chick.exe was not found next to the CLTools folder.
  echo     Extract the release zip INTO the game folder ^(Steam: Manage - Browse local files^).
  echo.
)
if not exist "..\d3d8.dll" (
  if exist "d3d8.dll" (
    copy /y "d3d8.dll" "..\d3d8.dll" >nul && echo [ok] d3d8.dll copied into the game folder.
  ) else (
    echo [!] d3d8.dll is missing from the game folder - FPS lock / hotkeys / overlay will not work.
  )
) else (
  echo [ok] d3d8.dll is in the game folder.
)
echo.
call "%~dp0_python.bat" >nul 2>nul
if errorlevel 1 (
  echo Python 3 is needed for the Inspector, Map Viewer and Recorder.
  echo ^(The FPS lock, hotkeys, overlay and free camera work without it.^)
  choice /m "Install Python 3.12 now with winget"
  if errorlevel 2 (
    echo Install Python from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and run Setup.bat again.
    pause
    exit /b 1
  )
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo Python installed. Close this window and run Setup.bat once more to finish.
  pause
  exit /b 0
)
call "%~dp0_python.bat"
echo Installing Python packages ^(PyQt6, pyqtgraph, numpy, pillow, pefile, capstone^)...
%PY% -m pip install --user --upgrade --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo [!] pip failed - see the messages above.
  pause
  exit /b 1
)
echo.
echo [ok] Done. Start the game from Steam, then use Inspector.bat / MapView.bat / Record.bat.
pause
