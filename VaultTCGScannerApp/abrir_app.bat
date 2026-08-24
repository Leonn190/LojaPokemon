@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" main.py
  exit /b %errorlevel%
)

echo Ambiente do app nao encontrado.
echo Rode instalar.bat primeiro.
pause
exit /b 1
