@echo off
cd /d C:\Users\black\Desktop\KSU_Spring_2026\Capstone\DiscordBot\AI_Capstone
call venv\Scripts\activate
set PYTHONPATH=src
python -m tournament_bot.main
pause