@echo off
REM Media Hub: Free Podcast Editing Software - Windows installer (uses WSL + Ubuntu)
REM No support is provided. If something breaks, it is yours to fix.
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Please right-click this file and choose "Run as administrator".
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-windows.ps1"
pause
