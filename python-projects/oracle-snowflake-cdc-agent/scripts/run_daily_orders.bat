@echo off
REM Runs scripts\daily_orders.py from the project folder and appends to logs\daily_orders.log.
REM Used by Windows Task Scheduler (see README: "Daily orders").
cd /d "%~dp0.."
if not exist logs mkdir logs
echo ==== %date% %time% ==== >> logs\daily_orders.log
python scripts\daily_orders.py %* >> logs\daily_orders.log 2>&1
