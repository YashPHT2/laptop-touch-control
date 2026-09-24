@echo off
REM Background launcher: runs start_server.bat and logs its output
call "%~dp0start_server.bat" > "%~dp0server_run.log" 2>&1
