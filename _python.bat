@echo off
rem Finds a Python 3 interpreter for the CLTools launchers. Sets PY (console) and PYW (no console).
set "PY="
set "PYW="
where py >nul 2>nul && py -3 -c "import sys" >nul 2>nul && (set "PY=py -3" & set "PYW=pyw -3")
if not defined PY (
  where python >nul 2>nul && python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && (set "PY=python" & set "PYW=pythonw")
)
if not defined PY (
  echo Python 3.10+ was not found. Run Setup.bat first.
  pause
  exit /b 1
)
exit /b 0
