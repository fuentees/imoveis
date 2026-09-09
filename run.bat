@echo off
REM Roda UM ciclo do bot. Agende no Task Scheduler a cada 3 horas.
REM O log vai pro console e pro bot.log (a pasta do proprio script).
cd /d "%~dp0"
".venv\Scripts\python.exe" main.py --once
