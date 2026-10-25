@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-demo.ps1"
if errorlevel 1 (
  echo.
  echo DEMO stop reported an error. See the message above.
  pause
  exit /b 1
)
endlocal
