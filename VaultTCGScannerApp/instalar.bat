@echo off
setlocal
cd /d "%~dp0"

echo ================================================
echo   VAULT TCG SCANNER - INSTALACAO ISOLADA
echo ================================================
echo.

set "PY_CMD="
py -3.12 -c "import sys" >nul 2>&1 && set "PY_CMD=py -3.12"
if not defined PY_CMD py -3.11 -c "import sys" >nul 2>&1 && set "PY_CMD=py -3.11"
if not defined PY_CMD python -c "import sys" >nul 2>&1 && set "PY_CMD=python"

if not defined PY_CMD (
  echo Python nao encontrado. Instale Python 3.11 ou 3.12 e tente novamente.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente virtual .venv...
  %PY_CMD% -m venv .venv
  if errorlevel 1 goto :error
)

echo Atualizando o pip do ambiente isolado...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error

echo Instalando dependencias do Vault TCG Scanner...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Instalacao concluida sem alterar os pacotes globais do Python.
echo Agora rode abrir_app.bat.
pause
exit /b 0

:error
echo.
echo A instalacao falhou. Copie a mensagem acima caso precise de ajuda.
pause
exit /b 1
