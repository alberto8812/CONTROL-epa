@echo off
setlocal enabledelayedexpansion

echo.
echo   NovaHold - Instalador
echo.

REM 1. Check Python exists
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no encontrado.
    echo         Descarga Python 3.11 o superior desde:
    echo         https://www.python.org/downloads/
    echo.
    echo         Durante la instalacion, marca la opcion:
    echo         "Add Python to PATH"
    pause
    exit /b 1
)

REM 2. Check Python 3.11+
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
for /f "tokens=1,2 delims=." %%a in ("!PY_VER!") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)

if !PY_MAJOR! LSS 3 goto :python_old
if !PY_MAJOR! EQU 3 if !PY_MINOR! LSS 11 goto :python_old
echo [OK] Python !PY_VER!
goto :after_python_check

:python_old
echo [ERROR] Requiere Python 3.11 o superior (encontrado: !PY_VER!)
echo         Descarga desde https://www.python.org/downloads/
pause
exit /b 1

:after_python_check

REM 3. Check/install pipx
where pipx >nul 2>&1
if errorlevel 1 (
    echo   Instalando pipx...
    python -m pip install --user pipx --quiet
    if errorlevel 1 (
        echo [ERROR] No se pudo instalar pipx.
        pause
        exit /b 1
    )
    python -m pipx ensurepath
)
echo [OK] pipx listo

REM 4. Install novahold
set SCRIPT_DIR=%~dp0
echo   Instalando novahold...
pipx install "%SCRIPT_DIR:~0,-1%" --force --quiet
if errorlevel 1 (
    echo [ERROR] No se pudo instalar novahold.
    pause
    exit /b 1
)
echo [OK] novahold instalado

REM 5. Install Chromium (Playwright browser)
echo   Instalando Chromium (puede tardar unos minutos)...
set PIPX_HOME=%USERPROFILE%\.local\pipx
if not defined PIPX_HOME_ENV set PIPX_HOME_ENV=%PIPX_HOME%
set PLAYWRIGHT_BIN=%PIPX_HOME%\venvs\novahold\Scripts\playwright.exe
if exist "%PLAYWRIGHT_BIN%" (
    "%PLAYWRIGHT_BIN%" install chromium
    echo [OK] Chromium listo
) else (
    echo [AVISO] No se encontro playwright en el venv.
    echo         Ejecuta manualmente: playwright install chromium
)

echo.
echo   Instalacion completa!
echo.
echo   IMPORTANTE: Abre una terminal NUEVA (cmd o PowerShell) y ejecuta:
echo.
echo     nova
echo.
echo   Si "nova" no es reconocido, reinicia el equipo y vuelve a intentarlo.
echo.
pause
