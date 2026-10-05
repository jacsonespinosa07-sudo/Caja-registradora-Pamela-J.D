"""
Envío de facturas por correo (SMTP).

La configuración del correo que ENVÍA las facturas vive en el archivo
`config_correo.json`, junto a main.py (o junto al .exe). La primera vez que se
intenta enviar un correo, si el archivo no existe, se crea una plantilla para
que la llenes.

Con Gmail:
  1. Activa la verificación en dos pasos en la cuenta.
  2. Crea una "contraseña de aplicación" (Cuenta de Google > Seguridad).
  3. Pon esa clave de 16 letras en "clave" (NO la contraseña normal).

IMPORTANTE: config_correo.json tiene una contraseña. No lo subas a GitHub
(agrégalo al .gitignore).
"""
import json
import mimetypes
import os
import re
import smtplib
import sys
from email.message import EmailMessage

import database as db

def _resumen_texto(venta_id):
    try:
        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("SELECT total FROM ventas WHERE id = ?", (venta_id,))
            fila = cur.fetchone()
            total = fila[0] if fila else 0
            cur.execute("""SELECT nombre_producto, cantidad, subtotal
                           FROM venta_detalle WHERE venta_id = ? ORDER BY id""", (venta_id,))
            detalle = cur.fetchall()
        finally:
            conn.close()
    except Exception:
        return ""
    lineas = [f"- {n} x{c}: ${s:,.0f}" for n, c, s in detalle]
    return "\n".join(lineas) + f"\n\nTotal: ${total:,.0f}" 


class ConfigCorreoError(Exception):
    """El correo remitente no está configurado (o está incompleto)."""


def _carpeta_app():
    if getattr(sys, "frozen", False):          # cuando corre como .exe (PyInstaller)
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


RUTA_CONFIG = os.path.join(_carpeta_app(), "config_correo.json")

PLANTILLA = {
    "servidor": "smtp.gmail.com",
    "puerto": 587,
    "usuario": "tu_correo@gmail.com",
    "clave": "tu_clave_de_aplicacion",
    "nombre_remitente": "Pamela J.D",
}


def es_correo_valido(texto):
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", (texto or "").strip()))


def cargar_config():
    if not os.path.exists(RUTA_CONFIG):
        try:
            with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
                json.dump(PLANTILLA, f, indent=4, ensure_ascii=False)
        except OSError:
            pass
        raise ConfigCorreoError(
            "Falta configurar el correo que envía las facturas.\n"
            f"Llena este archivo y vuelve a intentar:\n{RUTA_CONFIG}"
        )

    try:
        with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        raise ConfigCorreoError(f"No se pudo leer el archivo de configuración:\n{RUTA_CONFIG}")

    for clave in ("servidor", "puerto", "usuario", "clave"):
        if not cfg.get(clave):
            raise ConfigCorreoError(f"Falta '{clave}' en el archivo:\n{RUTA_CONFIG}")

    if cfg["usuario"] == PLANTILLA["usuario"] or cfg["clave"] == PLANTILLA["clave"]:
        raise ConfigCorreoError(
            "El archivo de configuración todavía tiene los valores de ejemplo.\n"
            f"Edítalo con tu correo y clave de aplicación:\n{RUTA_CONFIG}"
        )
    return cfg


def enviar_factura(destino, ruta_factura, venta_id, nombre_negocio, nombre_cliente=""):
    """Envía por correo el archivo de la factura como adjunto.
    Lanza ConfigCorreoError si falta configurar, u otra excepción si falla el envío."""
    cfg = cargar_config()
    ruta_factura = str(ruta_factura)

    remitente_nombre = cfg.get("nombre_remitente") or nombre_negocio
    saludo = f"Hola {nombre_cliente}," if nombre_cliente else "Hola,"

    msg = EmailMessage()
    msg["Subject"] = f"Factura de venta #{venta_id} - {nombre_negocio}"
    msg["From"] = f"{remitente_nombre} <{cfg['usuario']}>"
    msg["To"] = destino
    def _resumen_texto(venta_id):
        ...

    resumen = _resumen_texto(venta_id)
    msg.set_content(
        f"{saludo}\n\n"
        f"Adjuntamos la factura de tu compra #{venta_id} en {nombre_negocio}.\n\n"
        + (f"Detalle de tu compra:\n{resumen}\n\n" if resumen else "")
        + "Para ver la factura completa, descarga el archivo adjunto y ábrelo con doble clic.\n\n"
        "Gracias por tu compra."
    )

    tipo, _ = mimetypes.guess_type(ruta_factura)
    maintype, subtype = (tipo or "application/octet-stream").split("/", 1)
    with open(ruta_factura, "rb") as f:
        msg.add_attachment(f.read(), maintype=maintype, subtype=subtype,
                           filename=os.path.basename(ruta_factura))

    puerto = int(cfg["puerto"])
    if puerto == 465:
        servidor = smtplib.SMTP_SSL(cfg["servidor"], puerto, timeout=20)
    else:
        servidor = smtplib.SMTP(cfg["servidor"], puerto, timeout=20)
        servidor.starttls()
    try:
        servidor.login(cfg["usuario"], cfg["clave"])
        servidor.send_message(msg)
    finally:
        servidor.quit()