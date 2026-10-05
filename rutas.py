"""
Utilidades para resolver rutas de archivos, tanto cuando el programa corre
como script de Python normal (python main.py) como cuando está empaquetado
en un .exe con PyInstaller.
"""
import os
import sys


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
