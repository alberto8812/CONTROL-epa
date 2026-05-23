@echo off
setlocal enabledelayedexpansion

echo.
echo   NovaHold - Instalador
echo.

REM 1. Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no encontrado.
    echo         Descarga desde https://python.org
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK] Python %PY_VER%

REM 2. Check/install pipx
where pipx >nul 2>&1
if errorlevel 1 (
    echo   Instalando pipx...
    python -m pip install --user pipx --quiet
    python -m pipx ensurepath
)
echo [OK] pipx listo

REM 3. Install novahold
set SCRIPT_DIR=%~dp0
echo   Instalando novahold...
pipx install "%SCRIPT_DIR:~0,-1%" --force --quiet
echo [OK] novahold instalado

echo.
echo   Instalacion completa!
echo.
echo   Abri una terminal NUEVA y ejecuta: nova
echo.
pause
