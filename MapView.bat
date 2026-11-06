@echo off
cd /d "%~dp0"
call "%~dp0_python.bat" || exit /b 1
start "" %PYW% -m cltools.mapview %*
