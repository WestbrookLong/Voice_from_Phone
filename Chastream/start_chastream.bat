@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
set "CHASTREAM_DATA_ROOT=%SCRIPT_DIR%data"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%SCRIPT_DIR%desktop_app.py"
) else (
    start "" python "%SCRIPT_DIR%desktop_app.py"
)

