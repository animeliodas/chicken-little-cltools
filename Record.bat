@echo off
cd /d "%~dp0"
title CLTools recorder
call "%~dp0_python.bat" || exit /b 1
%PY% -m cltools.recorder
pause
