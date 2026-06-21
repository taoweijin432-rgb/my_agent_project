@echo off
cd /d "%~dp0.."
".venv\Scripts\pythonw.exe" "scripts\run_server.py" --host 127.0.0.1 --port 8000 --log-to-file
