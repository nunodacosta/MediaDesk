@echo off
setlocal
title YT-DLP Media Desk
cd /d "%~dp0"

rem ---------------------------------------------------------------------------
rem  Ha um unico ponto de entrada: "Media Desk.exe" (a mesma janela WebView2
rem  usada pelos pacotes da pasta dist). Se o executavel nao existir, nao se
rem  abre uma segunda interface no browser: mostra-se o erro e a solucao.
rem ---------------------------------------------------------------------------

set "APP_EXE=%~dp0Media Desk.exe"
if exist "%APP_EXE%" goto :arrancar

set "APP_EXE=%~dp0dist\Media Desk Portable\Media Desk.exe"
if exist "%APP_EXE%" goto :arrancar

rem Nomes antigos (pacotes anteriores a renomeacao).
set "APP_EXE=%~dp0YT-DLP-Media-Desk.exe"
if exist "%APP_EXE%" goto :arrancar

set "APP_EXE=%~dp0dist\Media Desk Portable\YT-DLP-Media-Desk.exe"
if exist "%APP_EXE%" goto :arrancar

echo ==========================================
echo  [ERRO] "Media Desk.exe" nao encontrado.
echo  Gere os pacotes com:
echo    powershell -ExecutionPolicy Bypass -File build_portable.ps1
echo  Ou coloque "Media Desk.exe" nesta pasta.
echo ==========================================
pause
exit /b 1

:arrancar
echo A abrir YT-DLP Media Desk...
rem O proprio executavel trata de instancia unica: se a app ja estiver aberta,
rem esta chamada apenas traz a janela existente para a frente.
start "" /d "%~dp0" "%APP_EXE%"
exit /b 0
