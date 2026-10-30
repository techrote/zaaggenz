@echo off
setlocal
cd /d "%~dp0"

echo.
echo [ZaagGenZ] Setup
echo.

:check_python
where py >nul 2>nul
if errorlevel 1 goto :offer_python_install

py -3.13 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)" >nul 2>nul
if errorlevel 1 goto :offer_python_install
goto :python_ready

:offer_python_install
echo Python 3.13 was not found through the Windows py launcher.
echo.
where winget >nul 2>nul
if errorlevel 1 goto :winget_missing

choice /C YN /N /M "Install Python 3.13 now with winget? [Y/N] "
if errorlevel 2 goto :python_declined

echo.
echo [ZaagGenZ] Installing Python 3.13...
winget install -e --id Python.Python.3.13 --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto :python_install_failed

echo.
echo [ZaagGenZ] Verifying Python 3.13...
where py >nul 2>nul
if errorlevel 1 goto :python_restart_required
py -3.13 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)" >nul 2>nul
if errorlevel 1 goto :python_restart_required
echo [ZaagGenZ] Python 3.13 is ready.
echo.
goto :python_ready

:python_ready
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)" >nul 2>nul
    if errorlevel 1 goto :venv_wrong_python
) else (
    echo [1/5] Creating Python 3.13 virtual environment...
    py -3.13 -m venv .venv
    if errorlevel 1 goto :failed
)

echo [2/5] Updating pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed

echo [3/5] Materializing authenticated recovered runtime...
".venv\Scripts\python.exe" baseline\recovered_source\materialize.py
if errorlevel 1 goto :failed
if not exist "app\webapp.py" goto :materialize_missing

echo [4/5] Installing recovered runtime requirements...
".venv\Scripts\python.exe" -m pip install -r app\requirements.txt
if errorlevel 1 goto :failed

echo [5/5] Installing ZaagGenZ in editable mode...
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto :failed

echo.
echo [ZaagGenZ] Setup complete.
echo Run 1run.bat to launch the Compose workspace.
exit /b 0

:winget_missing
echo.
echo ERROR: winget is not available, so Python 3.13 cannot be installed automatically.
echo Install Python 3.13 manually, then run 0setup.bat again.
exit /b 1

:python_declined
echo.
echo Python 3.13 installation was skipped.
echo To install it later, run:
echo   winget install -e --id Python.Python.3.13
exit /b 1

:python_install_failed
set "EXITCODE=%errorlevel%"
if "%EXITCODE%"=="0" set "EXITCODE=1"
echo.
echo ERROR: winget could not install Python 3.13 ^(exit code %EXITCODE%^).
echo You can retry manually with:
echo   winget install -e --id Python.Python.3.13
exit /b %EXITCODE%

:python_restart_required
echo.
echo Python 3.13 was installed, but the py launcher is not visible in this terminal yet.
echo Close and reopen PowerShell, then run 0setup.bat again.
exit /b 1

:venv_wrong_python
echo.
echo ERROR: .venv exists but is not using Python 3.13.
echo Remove or rename the existing .venv, then run 0setup.bat again.
exit /b 1

:materialize_missing
echo.
echo ERROR: recovered runtime materialization completed without app\webapp.py.
echo The checkout may be incomplete or corrupted.
exit /b 1

:failed
set "EXITCODE=%errorlevel%"
if "%EXITCODE%"=="0" set "EXITCODE=1"
echo.
echo [ZaagGenZ] Setup failed with exit code %EXITCODE%.
exit /b %EXITCODE%
