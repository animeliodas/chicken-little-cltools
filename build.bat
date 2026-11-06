@echo off
rem Builds CLTools\build\d3d8.dll (x86) with MSVC Build Tools.
setlocal
set "HERE=%~dp0"
set "VCVARS="
for %%V in (2022 2019) do (
  if not defined VCVARS if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\%%V\BuildTools\VC\Auxiliary\Build\vcvars32.bat" set "VCVARS=%ProgramFiles(x86)%\Microsoft Visual Studio\%%V\BuildTools\VC\Auxiliary\Build\vcvars32.bat"
  if not defined VCVARS if exist "%ProgramFiles%\Microsoft Visual Studio\%%V\Community\VC\Auxiliary\Build\vcvars32.bat" set "VCVARS=%ProgramFiles%\Microsoft Visual Studio\%%V\Community\VC\Auxiliary\Build\vcvars32.bat"
)
if not defined VCVARS ( echo MSVC not found & exit /b 1 )
call "%VCVARS%" >nul || exit /b 1
if not exist "%HERE%build" mkdir "%HERE%build"
pushd "%HERE%build"
cl /nologo /O2 /MT /W3 /EHsc /D_CRT_SECURE_NO_WARNINGS /LD "%HERE%src\hook\clhook.cpp" /Fe:d3d8.dll /link /DEF:"%HERE%src\hook\d3d8.def" || (popd & exit /b 1)
popd
echo OK: %HERE%build\d3d8.dll
