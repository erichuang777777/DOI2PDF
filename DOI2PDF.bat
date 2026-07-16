@echo off
setlocal
cd /d "%~dp0"
title DOI2PDF

where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required.
  echo Install it from https://www.python.org/downloads/ and select "Add Python to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [DOI2PDF] First-time setup: creating the private Python environment...
  py -3.11 -m venv .venv
  if errorlevel 1 py -3 -m venv .venv
  if errorlevel 1 goto :failed
)

if not exist ".venv\.doi2pdf-installed-0.8.4" (
  echo [DOI2PDF] Installing the lightweight application and web console...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -e ".[web]"
  if errorlevel 1 goto :failed
  type nul > ".venv\.doi2pdf-installed-0.8.4"
)

if not exist ".env" copy /y ".env.example" ".env" >nul
echo [DOI2PDF] Opening http://127.0.0.1:8765
echo Keep this window open while using DOI2PDF. Press Ctrl+C to stop.
".venv\Scripts\python.exe" -m doi2pdf.web
exit /b %errorlevel%

:failed
echo.
echo DOI2PDF setup failed. Copy the messages above when asking for help.
pause
exit /b 1
