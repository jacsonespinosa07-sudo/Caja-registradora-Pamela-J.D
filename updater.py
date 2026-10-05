import os
import sys
import time
import subprocess
import urllib.request
import json

# URL donde alojarás la información de la última versión
VERSION_URL = "https://raw.githubusercontent.com/TU_USUARIO/TU_REPOSITO/main/version.json"
VERSION_ACTUAL = "1.0.0"

def comprobar_actualizacion():
    """Consulta la web para ver si hay una versión superior disponible."""
    try:
        req = urllib.request.urlopen(VERSION_URL, timeout=5)
        datos = json.loads(req.read().decode('utf-8'))
        
        version_remota = datos.get("version")
        url_descarga = datos.get("url_exe")
        
        if version_remota > VERSION_ACTUAL:
            return version_remota, url_descarga
    except Exception as e:
        print(f"Error comprobando actualización: {e}")
    return None, None

def ejecutar_actualización(url_descarga):
    """Descarga el nuevo .exe y lanza el comando de reemplazo."""
    exe_actual = sys.executable
    dir_actual = os.path.dirname(exe_actual)
    exe_nuevo = os.path.join(dir_actual, "actualización_temp.exe")

    # 1. Descargar el nuevo ejecutable
    urllib.request.urlretrieve(url_descarga, exe_nuevo)

    # 2. Crear un comando de script Batch que reemplaza el EXE al cerrarse
    bat_script = os.path.join(dir_actual, "update.bat")
    
    contenido_bat = f"""@echo off
timeout /t 2 /nobreak > nul
move /y "{exe_nuevo}" "{exe_actual}"
start "" "{exe_actual}"
del "%~f0"
"""
    with open(bat_script, "w") as f:
        f.write(contenido_bat)

    # 3. Ejecuatar el batch en segundo plano y cerrar la aplicación actual
    subprocess.Popen([bat_script], shell=True)
    sys.exit(0)