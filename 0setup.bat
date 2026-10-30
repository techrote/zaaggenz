@echo off
setlocal
cd /d "%~dp0"

echo.
echo [ZaagGenZ] Setup
echo.

where py >nul 2>nul
if errorlevel 1 goto :python_missing

py -3.13 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)" >nul 2>nul
if errorlevel 1 goto :python_missing

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)" >nul 2>nul
    if errorlevel 1 goto :venv_wrong_python
) else (
    echo [1/3] Creating Python 3.13 virtual environment...
    py -3.13 -m venv .venv
    if errorlevel 1 goto :failed
)

echo [2/3] Updating pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed

echo [3/3] Installing ZaagGenZ in editable mode...
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto :failed

echo.
echo [ZaagGenZ] Setup complete.
echo Run 1run.bat to launch the Compose workspace.
exit /b 0

:python_missing
echo.
echo ERROR: Python 3.13 was not found through the Windows py launcher.
echo Install it with:
echo   winget install -e --id Python.Python.3.13
echo Then reopen this terminal and run 0setup.bat again.
exit /b 1

:venv_wrong_python
echo.
echo ERROR: .venv exists but is not using Python 3.13.
echo Remove or rename the existing .venv, then run 0setup.bat again.
exit /b 1

:failed
set "EXITCODE=%errorlevel%"
if "%EXITCODE%"=="0" set "EXITCODE=1"
echo.
echo [ZaagGenZ] Setup failed with exit code %EXITCODE%.
exit /b %EXITCODE%
