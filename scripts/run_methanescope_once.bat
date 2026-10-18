@echo off
REM Optional Windows Task Scheduler script; does NOT automatically set a schedule.
set "PROJECT=%~dp0.."
cd /d "%PROJECT%"
"%PROJECT%\.venv\Scripts\python.exe" -m methanescope.monitor run-once
exit /b %ERRORLEVEL%
