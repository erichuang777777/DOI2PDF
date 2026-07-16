@echo off
setlocal
cd /d "%~dp0"
title DOI2PDF Browser Setup

if not exist ".venv\Scripts\python.exe" (
  echo [DOI2PDF] Run DOI2PDF.bat once before installing browser support.
  pause
  exit /b 1
)

echo [DOI2PDF] Installing optional Playwright support for authorized institutional login...
".venv\Scripts\python.exe" -m pip install -e ".[browser]"
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto :failed
type nul > ".venv\.doi2pdf-browser-installed"
echo.
echo [DOI2PDF] Browser support is ready. Start DOI2PDF.bat normally.
pause
exit /b 0

:failed
echo.
echo DOI2PDF browser setup failed. Copy the messages above when asking for help.
pause
exit /b 1
