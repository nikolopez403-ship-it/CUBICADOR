@echo off
chcp 65001 >nul
setlocal EnableExtensions
REM ============================================================
REM  Instalador del Cubicador de fierro (ejecutar una sola vez)
REM  Si no hay Python, lo instala automaticamente con winget.
REM ============================================================
cd /d "%~dp0.."
set "RAIZ=%CD%"
set "PY="

call :buscar_python
if defined PY goto tengo_python

echo No se encontro Python en este equipo.
where winget >nul 2>nul
if errorlevel 1 goto sin_winget
echo Instalando Python 3.12 (puede tardar unos minutos)...
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
call :buscar_python
if defined PY goto tengo_python

:sin_winget
echo.
echo No se pudo instalar Python automaticamente.
echo  1. Se abrira la pagina de descarga: instale Python 3.12
echo  2. En la primera pantalla del instalador MARQUE "Add python.exe to PATH"
echo  3. Vuelva a ejecutar este instalar.bat
start "" https://www.python.org/downloads/
pause
exit /b 1

:tengo_python
"%PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo Se encontro un Python antiguo en "%PY%". Se requiere Python 3.10 o superior.
    start "" https://www.python.org/downloads/
    pause
    exit /b 1
)
echo Usando Python: "%PY%"
echo Instalando dependencias...
"%PY%" -m pip install --upgrade pip --quiet
"%PY%" -m pip install -r "%RAIZ%\requirements.txt"
if errorlevel 1 goto error_pip

REM --- lanzador (usa la ruta exacta de Python, no depende del PATH) ---
> "%RAIZ%\windows\cubicar.bat" echo @echo off
>>"%RAIZ%\windows\cubicar.bat" echo chcp 65001 ^>nul
>>"%RAIZ%\windows\cubicar.bat" echo cd /d "%RAIZ%"
>>"%RAIZ%\windows\cubicar.bat" echo "%PY%" -m cubicador asistente
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
exit /b 0

:error_pip
echo.
echo Error instalando dependencias. Revise su conexion a internet y vuelva a intentar.
pause
exit /b 1

REM ------------------------------------------------------------
REM  Busca un Python real (ignora el acceso directo de Microsoft Store)
REM ------------------------------------------------------------
:buscar_python
set "PY="
for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PY=%%P"
if defined PY if exist "%PY%" exit /b 0
set "PY="
for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PY=%%P"
if defined PY if exist "%PY%" exit /b 0
set "PY="
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
if defined PY exit /b 0
for /d %%D in ("%ProgramFiles%\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
if defined PY exit /b 0
set "PY="
exit /b 0
