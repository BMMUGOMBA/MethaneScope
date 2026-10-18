@echo off
setlocal
REM MethaneScope Lesson 2.9 — safe, manual DRY-RUN by default
set "PROJECT=%~dp0.."
cd /d "%PROJECT%"
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Project virtual environment missing.
  exit /b 2
)
".venv\Scripts\python.exe" -m methanescope.scheduler run
exit /b %ERRORLEVEL%
