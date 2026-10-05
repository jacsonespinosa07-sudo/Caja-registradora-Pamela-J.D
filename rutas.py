"""
Utilidades para resolver rutas de archivos, tanto cuando el programa corre
como script de Python normal (python main.py) como cuando está empaquetado
en un .exe con PyInstaller.
"""
import os
import sys
import json


def ruta_base():
    """Carpeta donde debe vivir todo lo que necesita persistir entre usos
    del programa: la base de datos (caja.db) y las facturas generadas.

    - Si el programa está empaquetado como .exe, esto es la carpeta donde
      está el .exe (NO la carpeta temporal donde PyInstaller descomprime
      los archivos, que se borra al cerrar el programa).
    - Si se corre como script normal, es la carpeta donde están los .py.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def ruta_recurso(*partes):
    """Carpeta de archivos empaquetados DENTRO del .exe (solo lectura, como
    las imágenes del logo). PyInstaller los descomprime en una carpeta
    temporal identificada por sys._MEIPASS mientras el programa está abierto.
    """
    base = getattr(sys, "_MEIPASS", ruta_base())
    return os.path.join(base, *partes)



def config_db():
    """Devuelve (ruta_de_la_base, es_personalizada, error).
    Si existe config_db.json con {"db_path": "..."}, usa esa ruta (base compartida).
    Si no existe, usa caja.db junto al programa, como siempre."""
    base = ruta_base()
    por_defecto = os.path.join(base, "caja.db")
    archivo = os.path.join(base, "config_db.json")
    if not os.path.exists(archivo):
        return por_defecto, False, None
    try:
        with open(archivo, "r", encoding="utf-8-sig") as f:
            ruta = str(json.load(f).get("db_path", "")).strip()
    except (OSError, ValueError, AttributeError):
        return por_defecto, True, ("No se pudo leer config_db.json. Revisa que esté bien escrito "
                                   "(usa barras normales /, no invertidas).")
    if not ruta:
        return por_defecto, True, "config_db.json no tiene la ruta 'db_path'."
    return ruta, True, None