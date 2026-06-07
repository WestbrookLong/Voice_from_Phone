@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
set "CHASTREAM_DATA_ROOT=%SCRIPT_DIR%data"
set "CHASTREAM_DEBUG=1"
python "%SCRIPT_DIR%desktop_app.py"

