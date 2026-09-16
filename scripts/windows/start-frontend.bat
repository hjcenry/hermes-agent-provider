@echo off
setlocal EnableExtensions
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-frontend.ps1"
if errorlevel 1 pause
exit /b %ERRORLEVEL%
