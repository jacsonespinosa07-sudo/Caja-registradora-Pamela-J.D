"""
Módulo de base de datos para la Caja Registradora.
Usa SQLite (no requiere instalar ningún motor de base de datos aparte).
"""

import sqlite3
import os

import rutas

DB_PATH = os.path.join(rutas.ruta_base(), "caja.db")


def conectar():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _columnas(cur, tabla):
    cur.execute(f"PRAGMA table_info({tabla})")
    return {fila[1] for fila in cur.fetchall()}


def _quitar_check_tipo(conn):
    """Reconstruye 'productos' sin el CHECK de tipo (conserva todos los datos).
    Si la tabla ya está migrada, no hace nada."""
    cur = conn.cursor()
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='productos'")
    fila = cur.fetchone()
    if not fila or "CHECK" not in (fila[0] or "").upper():
        return

    conn.commit()
    cur.execute("PRAGMA foreign_keys = OFF")
    try:
        cur.execute("DROP TABLE IF EXISTS productos_nueva")
        cur.execute("""
            CREATE TABLE productos_nueva (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                tipo TEXT NOT NULL,
                precio REAL NOT NULL,
                stock INTEGER NOT NULL DEFAULT 0,
                codigo_barras TEXT
            )
        """)
        cur.execute("""
            INSERT INTO productos_nueva (id, nombre, tipo, precio, stock, codigo_barras)
            SELECT id, nombre, tipo, precio, stock, NULLIF(codigo_barras, '')
            FROM productos
        """)
        cur.execute("DROP TABLE productos")
        cur.execute("ALTER TABLE productos_nueva RENAME TO productos")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.execute("PRAGMA foreign_keys = ON")


def inicializar_db():
    """Crea las tablas si no existen. Se llama al arrancar la app."""
    conn = conectar()
    cur = conn.cursor()

    # ---------------- PRODUCTOS (sin CHECK en tipo) ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            tipo TEXT NOT NULL,
            precio REAL NOT NULL,
            stock INTEGER NOT NULL DEFAULT 0,
            codigo_barras TEXT
        )
    """)
    conn.commit()

    # Migración: columna codigo_barras si la tabla es antigua
    if "codigo_barras" not in _columnas(cur, "productos"):
        cur.execute("ALTER TABLE productos ADD COLUMN codigo_barras TEXT")
        conn.commit()

    # Migración: quita el CHECK viejo que rechazaba los nuevos tipos
    _quitar_check_tipo(conn)

    # Códigos vacíos ("") pasan a NULL para que no choquen entre sí
    cur.execute("UPDATE productos SET codigo_barras = NULL WHERE codigo_barras = ''")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_productos_codigo_barras "
                "ON productos(codigo_barras) WHERE codigo_barras IS NOT NULL")
    conn.commit()

    # ---------------- MATERIALES ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS materiales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            unidad TEXT NOT NULL DEFAULT 'unidad',
            stock_actual REAL NOT NULL DEFAULT 0,
            codigo_barras TEXT
        )
    """)
    if "codigo_barras" not in _columnas(cur, "materiales"):
        cur.execute("ALTER TABLE materiales ADD COLUMN codigo_barras TEXT")
    cur.execute("UPDATE materiales SET codigo_barras = NULL WHERE codigo_barras = ''")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_materiales_codigo_barras "
                "ON materiales(codigo_barras) WHERE codigo_barras IS NOT NULL")

    # Historial de entradas y salidas de material
    cur.execute("""
        CREATE TABLE IF NOT EXISTS movimientos_material (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id INTEGER NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ('entrada', 'salida')),
            cantidad REAL NOT NULL,
            motivo TEXT,
            fecha TEXT NOT NULL,
            FOREIGN KEY (material_id) REFERENCES materiales(id)
        )
    """)

    # ---------------- CLIENTES ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            nit TEXT,
            rut TEXT,
            telefono TEXT,
            correo TEXT,
            direccion TEXT,
            fecha_registro TEXT NOT NULL
        )
    """)
    if "correo" not in _columnas(cur, "clientes"):
        cur.execute("ALTER TABLE clientes ADD COLUMN correo TEXT")

    # ---------------- VENTAS ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            total REAL NOT NULL,
            cliente_id INTEGER,
            cliente_nombre TEXT NOT NULL DEFAULT '',
            cliente_telefono TEXT NOT NULL DEFAULT '',
            cliente_nit TEXT NOT NULL DEFAULT '',
            cliente_rut TEXT NOT NULL DEFAULT '',
            cliente_correo TEXT,
            forma_pago TEXT DEFAULT 'Contado',
            FOREIGN KEY (cliente_id) REFERENCES clientes(id)
        )
    """)
    cols_ventas = _columnas(cur, "ventas")
    if "cliente_nombre" not in cols_ventas:
        cur.execute("ALTER TABLE ventas ADD COLUMN cliente_nombre TEXT NOT NULL DEFAULT ''")
    if "cliente_telefono" not in cols_ventas:
        cur.execute("ALTER TABLE ventas ADD COLUMN cliente_telefono TEXT NOT NULL DEFAULT ''")
    if "cliente_id" not in cols_ventas:
        cur.execute("ALTER TABLE ventas ADD COLUMN cliente_id INTEGER REFERENCES clientes(id)")
    if "cliente_nit" not in cols_ventas:
        cur.execute("ALTER TABLE ventas ADD COLUMN cliente_nit TEXT NOT NULL DEFAULT ''")
    if "cliente_rut" not in cols_ventas:
        cur.execute("ALTER TABLE ventas ADD COLUMN cliente_rut TEXT NOT NULL DEFAULT ''")
    if "cliente_correo" not in cols_ventas:
        cur.execute("ALTER TABLE ventas ADD COLUMN cliente_correo TEXT")
    if "forma_pago" not in cols_ventas:
        cur.execute("ALTER TABLE ventas ADD COLUMN forma_pago TEXT DEFAULT 'Contado'")

    # ---------------- DETALLE DE VENTA ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS venta_detalle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER NOT NULL,
            producto_id INTEGER NOT NULL,
            nombre_producto TEXT NOT NULL,
            cantidad INTEGER NOT NULL,
            precio_unitario REAL NOT NULL,
            subtotal REAL NOT NULL,
            FOREIGN KEY (venta_id) REFERENCES ventas(id),
            FOREIGN KEY (producto_id) REFERENCES productos(id)
        )
    """)

    # ---------------- ABONOS (crédito) ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS abonos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            monto REAL NOT NULL,
            nota TEXT,
            FOREIGN KEY (venta_id) REFERENCES ventas(id)
        )
    """)

    conn.commit()

    # ---------------- DATOS DE EJEMPLO (solo si está vacío) ----------------
    cur.execute("SELECT COUNT(*) FROM productos")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO productos (nombre, tipo, precio, stock) VALUES (?, ?, ?, ?)",
            [
                ("Zapato deportivo blanco", "Zapato deportivo", 120000, 10),
                ("Bolichero negro", "Bolichero", 95000, 8),
                ("Sandalia rosa", "Sandalia", 70000, 12),
                ("Moño mediano rojo", "Moño", 3500, 20),
            ],
        )
        conn.commit()

    cur.execute("SELECT COUNT(*) FROM materiales")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO materiales (nombre, unidad, stock_actual) VALUES (?, ?, ?)",
            [
                ("Cuero", "metros", 50),
                ("Suela", "pares", 40),
                ("Pegante", "galones", 10),
                ("Cinta satinada", "metros", 100),
            ],
        )
        conn.commit()

    conn.close()

def borrar_datos_prueba():
    conn = conectar()
    cur = conn.cursor()

    try:
        # Primero borramos las tablas que dependen de otras
        cur.execute("DELETE FROM abonos")
        cur.execute("DELETE FROM venta_detalle")
        cur.execute("DELETE FROM movimientos_material")

        # Después las tablas principales
        cur.execute("DELETE FROM ventas")
        cur.execute("DELETE FROM clientes")

        # Reiniciar los IDs
        cur.execute("DELETE FROM sqlite_sequence WHERE name IN (?, ?, ?, ?, ?)",
                    ("abonos", "venta_detalle", "movimientos_material", "ventas", "clientes"))

        conn.commit()

        print("Datos de prueba eliminados correctamente.")

    except Exception as e:
        conn.rollback()
        print(f"Error al borrar los datos: {e}")

    finally:
        conn.close()
     