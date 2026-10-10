"""
Migración automática: al abrir la app, si encuentra un caja.db (SQLite) con
datos que todavía no están en MySQL, ofrece pasarlos UNA sola vez.

- Solo actúa si la app está conectada a MySQL.
- Busca caja.db junto al .exe (o junto a main.py) y en la carpeta actual.
- No borra ni modifica el caja.db: al terminar deja un archivo caja.db.migrado
  como marca para no volver a preguntar.
"""
import os
import sys
from datetime import datetime

import database as db
import migrar_sqlite_a_mysql as mig

NOMBRE_DB = "caja.db"


def _carpetas():
    if getattr(sys, "frozen", False):          # corriendo como .exe
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    vistas, salida = set(), []
    for c in (base, os.getcwd()):
        c = os.path.abspath(c)
        if c not in vistas:
            vistas.add(c)
            salida.append(c)
    return salida


def _marcar(ruta, texto):
    try:
        with open(ruta + ".migrado", "w", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} - {texto}\n")
    except OSError:
        pass


def migrar_datos_locales_si_hay(parent=None, al_terminar=None):
    """Llamar una vez, justo después de abrir la ventana principal."""
    if db.MODO != "mysql":
        return
    from tkinter import messagebox

    for carpeta in _carpetas():
        ruta = os.path.join(carpeta, NOMBRE_DB)
        if not os.path.exists(ruta) or os.path.exists(ruta + ".migrado"):
            continue

        try:   # 1) simulacro: ¿hay algo nuevo que copiar?
            previo = mig.migrar(ruta, aplicar=False, log=lambda *a: None)
        except Exception as e:
            messagebox.showwarning(
                "Migración automática",
                f"No se pudo revisar {ruta}:\n{e}\n\nLa app sigue funcionando; "
                "se volverá a intentar al abrirla.", parent=parent)
            continue

        nuevos = {k: v[0] for k, v in previo.items()}
        if sum(nuevos.values()) == 0:
            _marcar(ruta, "sin datos nuevos")
            continue

        detalle = (f"  Productos: {nuevos['productos']}\n  Materiales: {nuevos['materiales']}\n"
                   f"  Entradas: {nuevos['entradas']}")
        if not messagebox.askyesno(
                "Datos guardados en este equipo",
                f"Se encontraron datos guardados localmente ({ruta}) que no están en MySQL:\n\n"
                f"{detalle}\n\n¿Pasarlos a MySQL ahora?\n(No se borra nada del archivo local.)",
                parent=parent):
            _marcar(ruta, "el usuario decidió no migrar")
            continue

        try:   # 2) migración real
            mig.migrar(ruta, aplicar=True, log=lambda *a: None)
        except Exception as e:
            messagebox.showerror("Migración automática", f"No se pudo copiar a MySQL:\n{e}",
                                 parent=parent)
            continue
        _marcar(ruta, f"migrado: {nuevos}")
        messagebox.showinfo("Migración lista", f"Datos copiados a MySQL:\n\n{detalle}", parent=parent)
        if al_terminar:
            try:
                al_terminar()
            except Exception:
                pass