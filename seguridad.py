"""
Contraseña para proteger acciones delicadas (por ejemplo, eliminar una venta).

La contraseña NO se guarda en texto: en `clave_admin.json` (junto a main.py o
junto al .exe) solo queda un hash con sal. La primera vez que se pide una clave
y el archivo no existe, la app te deja crearla.

Si olvidas la clave, borra `clave_admin.json` y vuelve a crearla.
Agrega `clave_admin.json` al .gitignore para no subirlo a GitHub.

Uso en main.py:
    import seguridad
    ...
    if not seguridad.pedir_clave(self, "eliminar la venta"):
        return
"""
import hashlib
import hmac
import json
import os
import secrets
import sys
from tkinter import messagebox, simpledialog

LARGO_MINIMO = 4
INTENTOS = 3
ITERACIONES = 200_000


def _carpeta_app():
    if getattr(sys, "frozen", False):          # cuando corre como .exe (PyInstaller)
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


RUTA_CLAVE = os.path.join(_carpeta_app(), "clave_admin.json")


def _hash(clave, sal):
    return hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, ITERACIONES).hex()


def _leer():
    try:
        with open(RUTA_CLAVE, "r", encoding="utf-8") as f:
            datos = json.load(f)
        bytes.fromhex(datos["sal"])
        datos["hash"]
        return datos
    except (OSError, ValueError, KeyError):
        return None


def _crear_clave(parent):
    messagebox.showinfo(
        "Crear contraseña",
        "Todavía no hay una contraseña para esta acción.\n"
        "Vas a crearla ahora; luego se pedirá cada vez.",
        parent=parent
    )
    clave1 = simpledialog.askstring("Crear contraseña", "Escribe la nueva contraseña:",
                                    show="*", parent=parent)
    if clave1 is None:
        return False
    if len(clave1) < LARGO_MINIMO:
        messagebox.showerror("Contraseña muy corta",
                             f"Debe tener al menos {LARGO_MINIMO} caracteres.", parent=parent)
        return False
    clave2 = simpledialog.askstring("Crear contraseña", "Escríbela otra vez para confirmar:",
                                    show="*", parent=parent)
    if clave2 != clave1:
        messagebox.showerror("No coinciden", "Las dos contraseñas no son iguales.", parent=parent)
        return False

    sal = secrets.token_bytes(16)
    try:
        with open(RUTA_CLAVE, "w", encoding="utf-8") as f:
            json.dump({"sal": sal.hex(), "hash": _hash(clave1, sal)}, f)
    except OSError as e:
        messagebox.showerror("Error", f"No se pudo guardar la contraseña: {e}", parent=parent)
        return False
    messagebox.showinfo("Contraseña creada", "Contraseña guardada.", parent=parent)
    return True


def pedir_clave(parent, motivo="continuar"):
    """Pide la contraseña. Devuelve True solo si es correcta.
    Si todavía no existe una, ofrece crearla."""
    datos = _leer()
    if datos is None:
        return _crear_clave(parent)

    sal = bytes.fromhex(datos["sal"])
    for intento in range(1, INTENTOS + 1):
        clave = simpledialog.askstring(
            "Contraseña requerida",
            f"Escribe la contraseña para {motivo}:",
            show="*", parent=parent
        )
        if clave is None:
            return False
        if hmac.compare_digest(_hash(clave, sal), datos["hash"]):
            return True
        restantes = INTENTOS - intento
        if restantes:
            messagebox.showerror("Contraseña incorrecta",
                                 f"Contraseña incorrecta. Te quedan {restantes} intento(s).",
                                 parent=parent)
    messagebox.showerror("Acceso denegado", "Demasiados intentos fallidos.", parent=parent)
    return False