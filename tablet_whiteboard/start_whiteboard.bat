@echo off
setlocal
title Mobile Remote Bridge
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Please install Python or add it to PATH.
  echo.
  pause
  exit /b 1
)

python desktop_client.py %*
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Server exited with error code %EXIT_CODE%.
  echo Keep this window open and check the message above.
  echo.
  pause
)
exit /b %EXIT_CODE%
