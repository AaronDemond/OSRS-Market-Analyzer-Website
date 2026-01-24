@echo off
REM =============================================================================
REM TRENDING ITEMS AUTO-UPDATER (Runs Every 4 Hours)
REM =============================================================================
REM What: Wrapper script that runs update_trending.py in a loop
REM Why: Simpler than Task Scheduler for periodic execution
REM How: Run this once at startup, it loops forever with 4-hour sleep
REM
REM Usage: Double-click to start, or add to Windows Startup folder
REM To stop: Close the command window or Ctrl+C
REM =============================================================================

cd /d C:\Users\19024\OSRSWebsite

echo [%date% %time%] Trending updater started. First update in 4 hours...
timeout /t 14400 /nobreak

:loop
echo [%date% %time%] Starting trending update...
python scripts\update_trending.py
echo [%date% %time%] Update complete. Sleeping for 4 hours...
timeout /t 14400 /nobreak
goto loop
