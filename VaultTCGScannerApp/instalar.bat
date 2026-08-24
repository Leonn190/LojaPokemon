@echo off
setlocal
cd /d "%~dp0"

py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  echo Instalando com Python 3.12...
  py -3.12 -m pip install --upgrade pip
  py -3.12 -m pip install -r requirements.txt
  goto :done
)

echo Python 3.12 nao encontrado. Tentando o Python padrao...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

:done
echo.
echo Instalacao concluida. Rode abrir_app.bat ou main.py.
pause
