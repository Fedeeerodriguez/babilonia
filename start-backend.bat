@echo off
cd /d "%~dp0backend"
if not exist venv (
  echo Creando venv...
  python -m venv venv
)
call venv\Scripts\activate
pip install -q -r requirements.txt
if not exist .env copy .env.example .env
python run.py
