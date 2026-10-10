"""
Copia los datos de un archivo SQLite (caja.db) a la base MySQL del programa.
Uso:  python migrar_sqlite.py "C:\\ruta\\caja.db"
Solo LEE el .db; no lo modifica. Las tablas de MySQL que ya tengan datos se saltan.
"""
import sqlite3
import sys

import database as db

# Orden: primero las tablas de las que dependen las demás
TABLAS = ["clientes", "productos", "materiales", "movimientos_material",
          "ventas", "venta_detalle", "abonos", "caja_aperturas",
          "caja_movimientos", "cierres_caja", "entradas_mercancia"]

# Columnas que se llaman distinto en SQLite y en MySQL
ALIAS = {"fecha_cierre": "creado_en"}


def main():
    if db.MODO != "mysql":
        print("config_db.json no está en modo mysql. Revisa el archivo.")
        return
    if len(sys.argv) < 2:
        print('Uso: python migrar_sqlite.py "C:\\ruta\\caja.db"')
        return

    origen = sqlite3.connect(sys.argv[1])
    sc = origen.cursor()
    sc.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tablas_origen = {f[0].lower() for f in sc.fetchall()}

    destino = db.conectar()
    dc = destino.cursor()
    dc.execute("SET FOREIGN_KEY_CHECKS = 0")

    try:
        for tabla in TABLAS:
            if tabla not in tablas_origen:
                print(f"- {tabla}: no existe en el .db, se omite")
                continue

            dc.execute(f"SELECT COUNT(*) FROM {tabla}")
            if dc.fetchone()[0] > 0:
                print(f"- {tabla}: MySQL ya tiene datos, se omite")
                continue

            sc.execute(f"SELECT * FROM {tabla}")
            cols_origen = [d[0] for d in sc.description]
            filas = sc.fetchall()
            if not filas:
                print(f"- {tabla}: vacía en el .db")
                continue

            cols_destino = db.columnas_de(tabla, refrescar=True)

            pares = []   # (indice en origen, columna destino)
            for i, c in enumerate(cols_origen):
                nombre = c.lower()
                if nombre in cols_destino:
                    pares.append((i, nombre))
                elif ALIAS.get(nombre) in cols_destino and \
                        "creado_en" not in [x.lower() for x in cols_origen]:
                    pares.append((i, ALIAS[nombre]))

            nombres = [p[1] for p in pares]
            datos = []
            for fila in filas:
                valores = []
                for i, nombre in pares:
                    v = fila[i]
                    if nombre == "codigo_barras" and v == "":
                        v = None
                    valores.append(v)
                datos.append(valores)

            sql = (f"INSERT INTO {tabla} ({', '.join(nombres)}) "
                   f"VALUES ({', '.join('?' for _ in nombres)})")
            dc.executemany(sql, datos)
            destino.commit()
            print(f"OK {tabla}: {len(datos)} filas copiadas")
    except Exception as e:
        destino.rollback()
        print(f"ERROR: {e}")
    finally:
        dc.execute("SET FOREIGN_KEY_CHECKS = 1")
        destino.commit()
        destino.close()
        origen.close()


if __name__ == "__main__":
    main()