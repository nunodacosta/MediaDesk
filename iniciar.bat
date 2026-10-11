@echo off
setlocal enabledelayedexpansion
title YT-DLP Media Desk - Servidor

cd /d "%~dp0"

set "APP_DIR=%~dp0"
set "PYTHON_DIR=%APP_DIR%bin\python"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
set "PY_EMBED_URL=https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip"
set "PY_ZIP=%APP_DIR%bin\python_embed.zip"
set "GET_PIP_URL=https://bootstrap.pypa.io/get-pip.py"
set "GET_PIP=%APP_DIR%bin\get-pip.py"
set "LOG=%APP_DIR%launcher.log"

if not exist "%APP_DIR%bin" mkdir "%APP_DIR%bin"
if not exist "%PYTHON_DIR%" mkdir "%PYTHON_DIR%"
if not exist "%APP_DIR%downloads" mkdir "%APP_DIR%downloads"

echo ==========================================
echo  A tentar iniciar o servidor...
echo  SE DER ERRO, ESTA JANELA FICARA ABERTA.
echo ==========================================
echo.

if exist "%PYTHON_EXE%" (
    echo [OK] Python encontrado em bin\python
    goto :iniciar_servidor
)

echo [INFO] Python nao encontrado em bin\python
echo [INFO] A descarregar Python portatil...
echo.

bitsadmin /transfer python_download /priority high "%PY_EMBED_URL%" "%PY_ZIP%" >nul 2>&1

if not exist "%PY_ZIP%" (
    echo [ERRO] Falha no bitsadmin. A tentar com PowerShell...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PY_EMBED_URL%' -OutFile '%PY_ZIP%' -UseBasicParsing" 2>>"%LOG%"
)

if not exist "%PY_ZIP%" (
    echo.
    echo ==========================================
    echo [ERRO] Falha ao descarregar Python!
    echo ==========================================
    echo.
    echo Descarregue manualmente de:
    echo %PY_EMBED_URL%
    echo.
    echo Extraia o conteudo do ZIP para:
    echo %PYTHON_DIR%
    echo.
    pause
    exit /b 1
)

echo [OK] Download concluido. A extrair...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Expand-Archive -Path '%PY_ZIP%' -DestinationPath '%PYTHON_DIR%' -Force" 2>>"%LOG%"

if not exist "%PYTHON_EXE%" (
    echo [ERRO] Falha na extracao!
    pause
    exit /b 1
)

del "%PY_ZIP%" 2>nul

for %%f in ("%PYTHON_DIR%\*._pth") do (
    powershell -NoProfile -Command ^
        "(Get-Content '%%f') -replace '#import site','import site' | Set-Content '%%f'"
)

echo [INFO] A instalar pip...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%GET_PIP_URL%' -OutFile '%GET_PIP%' -UseBasicParsing" 2>>"%LOG%"

if exist "%GET_PIP%" (
    "%PYTHON_EXE%" "%GET_PIP%" --no-warn-script-location >nul 2>>"%LOG%"
    del "%GET_PIP%" 2>nul
    echo [OK] Pip instalado
) else (
    echo [AVISO] Falha ao instalar pip
)

echo [OK] Python instalado em bin\python
echo.

:iniciar_servidor
echo [INFO] A iniciar servidor...
echo.

"%PYTHON_EXE%" server.py

if %errorlevel% neq 0 (
    echo.
    echo ==========================================
    echo [ERRO] O servidor falhou ao iniciar.
    echo Verifique a mensagem de erro acima.
    echo ==========================================
    pause
)

exit /b 0