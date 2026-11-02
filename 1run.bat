@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto :missing_venv

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)" >nul 2>nul
if errorlevel 1 goto :wrong_python

if not exist "app\webapp.py" goto :missing_runtime

echo [ZaagGenZ] Launching Compose...
echo Press Ctrl+C in this window to stop the server.
echo.
".venv\Scripts\python.exe" -m zaaggenz_runtime --workspace compose --open %*
set "EXITCODE=%errorlevel%"

if not "%EXITCODE%"=="0" (
    echo.
    echo [ZaagGenZ] Runtime exited with code %EXITCODE%.
)
exit /b %EXITCODE%

:missing_venv
echo.
echo ERROR: .venv was not found.
echo Run 0setup.bat first.
exit /b 1

:wrong_python
echo.
echo ERROR: .venv is not using Python 3.13.
echo Remove or rename .venv, then run 0setup.bat again.
exit /b 1

:missing_runtime
echo.
echo ERROR: the recovered app runtime has not been materialized.
echo Run 0setup.bat to verify and materialize it.
exit /b 1
