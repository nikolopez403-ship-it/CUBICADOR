@echo off
chcp 65001 >nul
REM ============================================================
REM  Instalador del Cubicador de fierro (ejecutar una sola vez)
REM  Requiere Python 3.10+ instalado (https://www.python.org, marcar "Add to PATH")
REM ============================================================
cd /d "%~dp0.."
set RAIZ=%CD%

where python >nul 2>nul
if errorlevel 1 (
    echo No se encontro Python. Instalelo desde https://www.python.org marcando "Add python.exe to PATH".
    pause
    exit /b 1
)

echo Instalando dependencias...
python -m pip install --upgrade pip >nul
python -m pip install -r "%RAIZ%\requirements.txt"
if errorlevel 1 (
    echo Error instalando dependencias.
    pause
    exit /b 1
)

REM --- lanzador ---
(
echo @echo off
echo chcp 65001 ^>nul
echo cd /d "%RAIZ%"
echo python -m cubicador asistente
echo if errorlevel 1 pause
) > "%RAIZ%\windows\cubicar.bat"

REM --- comando CUBICAR para AutoCAD (ruta con barras normales para LISP) ---
set RUTA_LISP=%RAIZ:\=/%
(
echo ;; Comando CUBICAR: dibuja los cuadrantes de ciclo, cubica el fierro y exporta a Excel
echo (defun c:CUBICAR ()
echo   (startapp "cmd.exe" "/c \"%RUTA_LISP%/windows/cubicar.bat\"")
echo   (princ "\nCubicador iniciado: siga las instrucciones en la linea de comandos.")
echo   (princ)
echo )
echo (princ "\nCubicador de fierro cargado. Escriba CUBICAR para comenzar.")
echo (princ)
) > "%RAIZ%\windows\cubicar.lsp"

echo.
echo ============================================================
echo  Listo.
echo  En AutoCAD: comando APPLOAD, cargue:
echo      %RAIZ%\windows\cubicar.lsp
echo  (agreguelo al "Maletin de inicio / Startup Suite" para que cargue siempre)
echo  Luego escriba CUBICAR con el plano de losas abierto.
echo ============================================================
pause
