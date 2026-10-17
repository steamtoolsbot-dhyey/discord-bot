@echo off
title Discord Message Repeater Bot
cd /d "%~dp0"

echo ======================================================
echo           Starting Discord Repeater Bot
echo ======================================================

:: Check if python is in PATH
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    pause
    exit /b 1
)

:: Install requirements
echo Checking and installing requirements...
python -m pip install -r requirements.txt --quiet

:: Run the bot
echo Starting bot...
python bot.py

pause
