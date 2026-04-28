@echo off
cd /d project_folder_file_path
call venv\Scripts\activate
set PYTHONPATH=src
python -m tournament_bot.main
pause