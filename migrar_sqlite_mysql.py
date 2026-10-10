"""
Copia productos, materiales y entradas de mercancía de un archivo SQLite
(el que guarda el .exe cuando no encuentra MySQL) hacia la base MySQL.

Se usa de dos formas:
  1) Automática: la app lo llama sola al abrir (ver auto_migracion.py).
  2) Manual, desde la terminal, en la carpeta del proyecto:

       python migrar_sqlite_a_mysql.py                 -> lista los .db
       python migrar_sqlite_a_mysql.py dist\\caja.db     -> SIMULACRO
       python migrar_sqlite_a_mysql.py dist\\caja.db --aplicar

- Si un producto/material ya existe en MySQL (mismo nombre), NO se toca.
- No se suma stock: se copia el stock que ya tenía cada uno.
- Es seguro repetirlo: no duplica lo que ya se copió.
"""
import os
import sqlite3
import sys

import database as db

IGNORAR = {".git", "venv", ".venv", "__pycache__", "site-packages", "node_modules", "build"}
TABLAS_CONTEO = ("productos", "materiales", "entradas_mercancia")
# Tablas que este script NO copia (solo se avisa si el origen tiene datos en ellas)
TABLAS_NO_COPIADAS = ("ventas", "venta_detalle", "clientes", "abonos", "ventas_peleteria",
                      "venta_peleteria_detalle", "abonos_peleteria", "caja_aperturas",
                      "caja_movimientos", "cierres_caja", "peleteria_aperturas",
                      "peleteria_movimientos", "peleteria_cierres", "movimientos_material")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def buscar_archivos_db():
    encontrados = []
    for dp, dirs, files in os.walk(os.getcwd()):
        dirs[:] = [d for d in dirs if d not in IGNORAR]
        for f in files:
            if f.lower().endswith((".db", ".sqlite", ".sqlite3")):
                encontrados.append(os.path.join(dp, f))
    return encontrados


def cols_origen(src, tabla):
    return [r[1].lower() for r in src.execute(f"PRAGMA table_info({tabla})")]


def existe_origen(src, tabla):
    return bool(src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                            (tabla,)).fetchone())


def contar_origen(src):
    return {t: (src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                if existe_origen(src, t) else "no existe") for t in TABLAS_CONTEO}


def pendientes_sin_copiar(src):
    """Tablas del origen con datos que este script no copia: {tabla: filas}."""
    out = {}
    for t in TABLAS_NO_COPIADAS:
        if existe_origen(src, t):
            n = src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            if n:
                out[t] = n
    return out


def contar_destino():
    """Lee de nuevo desde MySQL (conexión nueva) para confirmar lo que quedó guardado."""
    conn = db.conectar()
    out = {}
    try:
        cur = conn.cursor()
        for t in TABLAS_CONTEO:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                out[t] = cur.fetchone()[0]
            except Exception as e:
                out[t] = f"error: {e}"
        try:
            cur.execute("SELECT @@hostname, @@port, DATABASE()")
            servidor = cur.fetchone()
        except Exception:
            servidor = None
    finally:
        conn.close()
    return out, servidor


def preparar_tablas(log=print):
    """Se asegura de que existan las tablas/columnas nuevas antes de copiar."""
    for modulo, funcion in (("entradas", "asegurar_tabla"), ("caja_peleteria", "asegurar_tablas")):
        try:
            getattr(__import__(modulo), funcion)()
        except Exception as e:
            log(f"(aviso al preparar {modulo}: {e})")


# ---------------------------------------------------------------------------
# Copia
# ---------------------------------------------------------------------------
def copiar_catalogo(src, cur, tabla, mapa, log):
    """Copia productos/materiales que no existan (por nombre). Devuelve (copiados, ya_existian)."""
    if not existe_origen(src, tabla):
        log(f"  (la base de origen no tiene la tabla {tabla})")
        return 0, 0
    destino_cols = [c.lower() for c in db.columnas_de(tabla, refrescar=True)]
    comunes = [c for c in cols_origen(src, tabla) if c in destino_cols and c != "id"]

    cur.execute(f"SELECT id, nombre FROM {tabla}")
    existentes = {str(n).strip().lower(): i for i, n in cur.fetchall()}
    codigos = set()
    if "codigo_barras" in destino_cols:
        cur.execute(f"SELECT codigo_barras FROM {tabla} WHERE codigo_barras IS NOT NULL")
        codigos = {str(c[0]) for c in cur.fetchall() if c[0]}

    copiados = omitidos = 0
    for fila in src.execute(f"SELECT * FROM {tabla}"):
        fila = dict(fila)
        clave = str(fila.get("nombre", "")).strip().lower()
        if clave in existentes:
            mapa[fila["id"]] = existentes[clave]
            omitidos += 1
            continue
        valores = {c: fila[c] for c in comunes}
        if "codigo_barras" in valores:
            cod = valores["codigo_barras"]
            if not cod or str(cod) in codigos:
                valores["codigo_barras"] = None
            else:
                codigos.add(str(cod))
        cols = list(valores)
        cur.execute(f"INSERT INTO {tabla} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                    [valores[c] for c in cols])
        mapa[fila["id"]] = cur.lastrowid
        existentes[clave] = cur.lastrowid
        copiados += 1
        log(f"  + {tabla}: {fila.get('nombre')}")
    return copiados, omitidos


def copiar_entradas(src, cur, mapa_prod, mapa_mat):
    """Devuelve (copiadas, ya_estaban)."""
    tabla = "entradas_mercancia"
    if not existe_origen(src, tabla):
        return 0, 0
    destino_cols = [c.lower() for c in db.columnas_de(tabla, refrescar=True)]
    copiadas = repetidas = 0
    for fila in src.execute(f"SELECT * FROM {tabla} ORDER BY id"):
        fila = dict(fila)
        tipo = fila.get("tipo_item") or "material"
        viejo = fila.get("item_id") if fila.get("item_id") is not None else fila.get("material_id")
        nuevo = (mapa_prod if tipo == "producto" else mapa_mat).get(viejo)

        cur.execute(f"""SELECT COUNT(*) FROM {tabla}
                        WHERE fecha = ? AND COALESCE(nombre, '') = ? AND cantidad = ?""",
                    (fila.get("fecha"), fila.get("nombre") or "", fila.get("cantidad")))
        if cur.fetchone()[0]:
            repetidas += 1
            continue

        valores = {"fecha": fila.get("fecha"), "tipo_item": tipo, "item_id": nuevo,
                   "nombre": fila.get("nombre"), "cantidad": fila.get("cantidad"),
                   "nota": fila.get("nota"), "precio_costo": fila.get("precio_costo")}
        if tipo != "producto":
            valores["material_id"] = nuevo
        cols = [c for c in valores if c in destino_cols]
        cur.execute(f"INSERT INTO {tabla} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                    [valores[c] for c in cols])
        copiadas += 1
    return copiadas, repetidas


def migrar(ruta, aplicar=True, log=print):
    """Copia los datos del SQLite `ruta` a MySQL.
    aplicar=False hace un simulacro (se deshace al final).
    Devuelve {"productos": (copiados, ya_existian), "materiales": (...), "entradas": (...)}."""
    if db.MODO != "mysql":
        raise RuntimeError("La app no está conectada a MySQL (usa SQLite). "
                           "Revisa que config_db.json esté junto al programa.")
    preparar_tablas(log)

    src = sqlite3.connect(ruta)
    src.row_factory = sqlite3.Row
    conn = db.conectar()
    try:
        cur = conn.cursor()
        mapa_prod, mapa_mat = {}, {}
        res = {
            "productos": copiar_catalogo(src, cur, "productos", mapa_prod, log),
            "materiales": copiar_catalogo(src, cur, "materiales", mapa_mat, log),
        }
        res["entradas"] = copiar_entradas(src, cur, mapa_prod, mapa_mat)
        if aplicar:
            conn.commit()
        else:
            conn.rollback()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        src.close()
    return res


# ---------------------------------------------------------------------------
# Uso desde la terminal
# ---------------------------------------------------------------------------
def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    aplicar = "--aplicar" in sys.argv

    if not args:
        print("Archivos de base de datos encontrados:\n")
        for ruta in buscar_archivos_db():
            print("  ", ruta)
        print("\nVuelve a ejecutar así:\n  python migrar_sqlite_a_mysql.py \"RUTA\\archivo.db\"")
        return

    ruta = args[0]
    if not os.path.exists(ruta):
        print(f"No existe el archivo: {ruta}")
        return
    if db.MODO != "mysql":
        print("Este programa NO está conectado a MySQL (usa SQLite), así que no hay a dónde copiar.\n"
              "Revisa que config_db.json esté en esta carpeta.")
        return

    print(f"Origen : {ruta}\nDestino: {db.DB_PATH}")
    print("MODO   : " + ("APLICAR (guarda de verdad)" if aplicar
                         else "SIMULACRO (NO guarda nada; falta --aplicar)") + "\n")
    db.inicializar_db()

    src = sqlite3.connect(ruta)
    src.row_factory = sqlite3.Row
    print("Filas en el archivo de ORIGEN:", contar_origen(src), "\n")
    pendientes = pendientes_sin_copiar(src)
    src.close()
    if pendientes:
        print("ATENCIÓN - Este archivo también tiene datos que este script NO copia:")
        for t, n in pendientes.items():
            print(f"   {t}: {n} filas")
        print()

    res = migrar(ruta, aplicar=aplicar, log=print)

    print("\nResumen:")
    for nombre, (copiados, existian) in res.items():
        print(f"   {nombre}: {copiados} copiados, {existian} ya estaban")

    if aplicar:
        conteo, servidor = contar_destino()
        print("\nVerificación (leído de nuevo desde MySQL):")
        print("   Filas en el DESTINO:", conteo)
        if servidor:
            print(f"   Servidor: {servidor[0]}  puerto: {servidor[1]}  base: {servidor[2]}")
        print("\nListo: datos copiados a MySQL.")
    else:
        print("\nSIMULACRO: no se guardó nada. Si todo se ve bien, repite con --aplicar")


if __name__ == "__main__":
    main()