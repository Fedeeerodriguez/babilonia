@echo off
echo === Tomi Babilonia · setup ===
cd /d "%~dp0backend"
if not exist venv python -m venv venv
call venv\Scripts\activate
pip install -r requirements.txt
if not exist .env copy .env.example .env
deactivate
cd /d "%~dp0frontend"
if not exist node_modules call npm install
if not exist .env copy .env.example .env
echo.
echo Listo. Edita backend\.env con DATABASE_URL de Supabase y OPENAI_API_KEY.
echo Despues corre start-backend.bat y start-frontend.bat
pause
