@echo off
echo ============================================
echo   Generando el ejecutable de Pamela J.D.
echo ============================================
echo.

echo [1/3] Instalando las herramientas necesarias (solo la primera vez)...
python -m pip install --upgrade pip
python -m pip install pillow reportlab pyinstaller

echo.
echo [2/3] Generando CajaPamelaJD.exe ...
python -m PyInstaller --onefile --windowed --noconfirm ^
    --name "CajaPamelaJD" ^
    --icon "assets\icono.ico" ^
    --add-data "assets;assets" ^
    main.py

echo.
echo [3/3] Verificando la base de datos junto al ejecutable...
if exist "dist\caja.db" (
    echo Ya existe una caja.db en dist\ ^(tus ventas reales^) - NO se toca, para no perder datos.
) else (
    if exist "caja.db" (
        copy /Y "caja.db" "dist\caja.db" >nul
        echo Se copio caja.db por primera vez junto al ejecutable.
    ) else (
        echo No se encontro caja.db para copiar; el programa creara una nueva vacia.
    )
)

echo.
echo ============================================
echo   LISTO. Tu programa esta en la carpeta "dist"
echo   Archivo: dist\CajaPamelaJD.exe
echo ============================================
pause
