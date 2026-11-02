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
> "%RAIZ%\windows\cubicar.bat" echo @echo off
>>"%RAIZ%\windows\cubicar.bat" echo chcp 65001 ^>nul
>>"%RAIZ%\windows\cubicar.bat" echo cd /d "%RAIZ%"
>>"%RAIZ%\windows\cubicar.bat" echo python -m cubicador asistente
>>"%RAIZ%\windows\cubicar.bat" echo if errorlevel 1 pause

REM --- comando CUBICAR para AutoCAD (ruta con barras normales para LISP) ---
set "RUTA_LISP=%RAIZ:\=/%"
set "LSP=%RAIZ%\windows\cubicar.lsp"
> "%LSP%" echo ;; Comando CUBICAR: dibuja los cuadrantes de ciclo, cubica el fierro y exporta a Excel
>>"%LSP%" echo (defun c:CUBICAR ()
>>"%LSP%" echo   (startapp "cmd.exe" "/c \"%RUTA_LISP%/windows/cubicar.bat\"")
>>"%LSP%" echo   (princ "\nCubicador iniciado: siga las instrucciones en la linea de comandos.")
>>"%LSP%" echo   (princ)
>>"%LSP%" echo )
>>"%LSP%" echo (princ "\nCubicador de fierro cargado. Escriba CUBICAR para comenzar.")
>>"%LSP%" echo (princ)

echo.
echo ============================================================
echo  Listo.
echo  En AutoCAD: comando APPLOAD, cargue:
echo      %RAIZ%\windows\cubicar.lsp
echo  (agreguelo al "Maletin de inicio / Startup Suite" para que cargue siempre)
echo  Luego escriba CUBICAR con el plano de losas abierto.
echo ============================================================
pause
