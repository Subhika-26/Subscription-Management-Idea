@echo off
cd /d "%~dp0"
echo ============================================
echo Brightloop Subscription Management System
echo ============================================
if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  py -m venv .venv
)
call ".venv\Scripts\activate.bat"
echo Installing required packages...
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Package installation failed. Check your internet connection and Python installation.
  pause
  exit /b 1
)
echo.
echo Starting Brightloop...
python app.py
pause
