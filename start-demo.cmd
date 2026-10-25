@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-demo.ps1"
if errorlevel 1 (
  echo.
  echo DEMO did not start. See the error above.
  pause
  exit /b 1
)
endlocal
