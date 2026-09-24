@echo off
REM ============================================================
REM  Laptop Touch Control - server launcher
REM ============================================================
REM  To require a PIN, open remote_config.txt next to this file
REM  and set it like this:   PIN=123456
REM ============================================================
cd /d "%~dp0"
python server.py
pause
