@echo off
title Odisha Flood EWS

cd /d "%~dp0SIH 2026\backend"

echo.
echo ==========================================
echo    ODISHA FLOOD EARLY WARNING SYSTEM
echo ==========================================
echo.
echo Starting FastAPI server...
echo.

python main.py

echo.
echo ==========================================
echo Server stopped.
echo ==========================================
pause