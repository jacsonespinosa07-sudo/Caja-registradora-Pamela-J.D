"""
Módulo de base de datos para la Caja Registradora.

Funciona con dos motores, según el archivo config_db.json (junto al programa):
  - SQLite (un solo PC, sin instalar nada)
  - MySQL / MariaDB (varios PCs conectados al PC principal)

El resto del programa escribe las consultas con "?" como parámetro; aquí se
traducen solas a MySQL. Ver config_db.ejemplo.json.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime

# Si es True, cuando la base está vacía se cargan productos y materiales de
# ejemplo. En el PC de producción déjalo en False.
CARGAR_DATOS_EJEMPLO = False


# ---------------------------------------------------------------------------
# Configuración (config_db.json)
# ---------------------------------------------------------------------------
def _carpeta_app():
    if getattr(sys, "frozen", False):          # ejecutable creado con PyInstaller
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_PATH = os.path.join(_carpeta_app(), "config_db.json")

_CONFIG_DEFECTO = {
    "modo": "sqlite",
    "sqlite": {"ruta": "caja.db"},
    "mysql": {"host": "127.0.0.1", "puerto": 3306, "usuario": "caja",
              "clave": "", "base": "caja_pamela"},
}


def _buscar(d, *nombres):
    """Valor de la primera clave que exista (sin importar mayúsculas), o None."""
    if not isinstance(d, dict):
        return None
    bajos = {str(k).strip().lower(): v for k, v in d.items()}
    for n in nombres:
        v = bajos.get(n)
        if v is not None and v != "":
            return v
    return None


def _interpretar_config(datos):
    """Entiende config_db.json aunque use otros nombres de clave
    (user/password/database, usuario/clave/base, etc.). Devuelve (config, error)."""
    config = json.loads(json.dumps(_CONFIG_DEFECTO))
    if not isinstance(datos, dict):
        return config, "config_db.json debe ser un objeto JSON { ... }."

    bloque_mysql = _buscar(datos, "mysql", "mariadb")
    bloque_mysql = bloque_mysql if isinstance(bloque_mysql, dict) else None
    bloque_sqlite = _buscar(datos, "sqlite")
    bloque_sqlite = bloque_sqlite if isinstance(bloque_sqlite, dict) else None
    fuente = bloque_mysql or datos            # datos de MySQL: dentro de "mysql" o sueltos arriba

    host = _buscar(fuente, "host", "hostname", "servidor", "server", "db_host", "mysql_host")
    puerto = _buscar(fuente, "puerto", "port", "db_port", "mysql_port")
    usuario = _buscar(fuente, "usuario", "user", "username", "uid", "db_user", "mysql_user")
    clave = _buscar(fuente, "clave", "password", "contrasena", "contraseña", "pass", "pwd",
                    "db_password", "mysql_password")
    base = _buscar(fuente, "base", "database", "db", "dbname", "db_name", "schema",
                   "nombre_base", "mysql_database")
    ruta = _buscar(bloque_sqlite or datos, "ruta", "path", "archivo", "file", "db_path",
                   "sqlite_path", "db_file")

    modo_txt = str(_buscar(datos, "modo", "mode", "tipo", "type", "motor", "engine", "db_type",
                           "db_engine", "driver", "dialect", "backend") or "").strip().lower()
    if "mysql" in modo_txt or "maria" in modo_txt:
        modo = "mysql"
    elif "sqlite" in modo_txt:
        modo = "sqlite"
    elif modo_txt:
        return config, (f"No entiendo el modo \"{modo_txt}\" en config_db.json.\n"
                        "Debe ser \"mysql\" o \"sqlite\".")
    elif host or bloque_mysql:
        modo = "mysql"
    elif ruta or bloque_sqlite:
        modo = "sqlite"
    else:
        return config, ("No pude entender config_db.json (claves encontradas: "
                        f"{', '.join(map(str, datos)) or 'ninguna'}).\n\n"
                        "Debe llevar \"modo\": \"mysql\" y los datos de conexión: "
                        "host, puerto, usuario, clave y base.")

    config["modo"] = modo
    if modo == "mysql":
        faltan = [n for n, v in (("host", host), ("usuario", usuario), ("base", base)) if not v]
        if faltan:
            return config, ("Al config_db.json le faltan datos de MySQL: " + ", ".join(faltan) + ".")
        try:
            puerto = int(puerto) if puerto else 3306
        except (TypeError, ValueError):
            puerto = 3306
        config["mysql"] = {"host": str(host), "puerto": puerto, "usuario": str(usuario),
                           "clave": "" if clave is None else str(clave), "base": str(base)}
    elif ruta:
        config["sqlite"]["ruta"] = str(ruta)
    return config, None


def _leer_config():
    """Devuelve (config, error). Si el archivo no existe usa SQLite local."""
    if not os.path.exists(CONFIG_PATH):
        config = json.loads(json.dumps(_CONFIG_DEFECTO))
        # Instalaciones antiguas: la ruta de la base la daba rutas.config_db()
        try:
            import rutas
            ruta, _compartida, error = rutas.config_db()
            if ruta:
                config["sqlite"]["ruta"] = ruta
            return config, error
        except Exception:
            return config, None
    try:
        with open(CONFIG_PATH, encoding="utf-8-sig") as f:
            datos = json.load(f)
    except Exception as e:
        return json.loads(json.dumps(_CONFIG_DEFECTO)), \
            f"No se pudo leer config_db.json:\n{CONFIG_PATH}\n\n{e}"
    return _interpretar_config(datos)


_CONFIG, _ERROR_CONFIG = _leer_config()
MODO = _CONFIG["modo"]

if MODO == "mysql":
    _my = _CONFIG["mysql"]
    DB_PATH = f"MySQL {_my['host']}:{_my['puerto']}/{_my['base']}"
else:
    _ruta = _CONFIG["sqlite"]["ruta"]
    DB_PATH = _ruta if os.path.isabs(_ruta) or _ruta.startswith("\\\\") \
        else os.path.join(_carpeta_app(), _ruta)


# ---------------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------------
def _traducir_mysql(sql, hay_parametros):
    """SQLite -> MySQL: '?' pasa a '%s' y se traducen unas pocas palabras."""
    sql = (sql.replace("INSERT OR REPLACE INTO", "REPLACE INTO")
              .replace("INSERT OR IGNORE INTO", "INSERT IGNORE INTO"))
    if hay_parametros:
        if "?" in sql:
            # Consulta estilo SQLite: se escapa el % literal y ? pasa a %s
            sql = sql.replace("%", "%%").replace("?", "%s")
        # Si no tiene "?", se asume que ya usa %s y se deja tal cual
    return sql


class _CursorMySQL:
    """Cursor de MySQL que se usa igual que el de sqlite3."""

    def __init__(self, cursor):
        self._c = cursor

    def execute(self, sql, params=None):
        if params:
            self._c.execute(_traducir_mysql(sql, True), tuple(params))
        else:
            self._c.execute(_traducir_mysql(sql, False))
        return self

    def executemany(self, sql, secuencia):
        self._c.executemany(_traducir_mysql(sql, True), [tuple(p) for p in secuencia])
        return self

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return list(self._c.fetchall())

    def fetchmany(self, n=None):
        return list(self._c.fetchmany(n) if n else self._c.fetchmany())

    @property
    def lastrowid(self):
        return self._c.lastrowid

    @property
    def rowcount(self):
        return self._c.rowcount

    @property
    def description(self):
        return self._c.description

    def __iter__(self):
        return iter(self._c)

    def close(self):
        self._c.close()


class _ConexionMySQL:
    """Conexión de MySQL que se usa igual que la de sqlite3."""

    def __init__(self, conexion):
        self._conn = conexion

    def cursor(self):
        return _CursorMySQL(self._conn.cursor())

    def execute(self, sql, params=None):
        return self.cursor().execute(sql, params)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def _conectar_mysql():
    import pymysql
    from pymysql.constants import FIELD_TYPE
    from pymysql.converters import conversions

    # Los DECIMAL/SUM de MySQL llegan como float (igual que en SQLite)
    conv = conversions.copy()
    conv[FIELD_TYPE.DECIMAL] = float
    conv[FIELD_TYPE.NEWDECIMAL] = float

    my = _CONFIG["mysql"]
    conexion = pymysql.connect(
        host=my["host"], port=int(my["puerto"]), user=my["usuario"],
        password=my["clave"], database=my["base"], charset="utf8mb4",
        connect_timeout=10, autocommit=False, conv=conv)
    return _ConexionMySQL(conexion)


def conectar():
    if MODO == "mysql":
        return _conectar_mysql()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def verificar_acceso():
    """Devuelve None si la base está accesible, o un texto explicando el problema."""
    if _ERROR_CONFIG:
        return _ERROR_CONFIG

    if MODO == "mysql":
        try:
            import pymysql  # noqa: F401
        except ImportError:
            return ("Falta instalar el conector de MySQL.\n\n"
                    "Abre una terminal y escribe:\n    pip install pymysql")
        try:
            _conectar_mysql().close()
        except Exception as e:
            my = _CONFIG["mysql"]
            return (f"No se pudo conectar a MySQL ({my['host']}:{my['puerto']}, "
                    f"base '{my['base']}'):\n\n{e}\n\n"
                    "Revisa que el PC principal esté encendido y en la misma red, "
                    "que MySQL esté corriendo y los datos de config_db.json.")
        return None

    carpeta = os.path.dirname(DB_PATH)
    if carpeta and not os.path.isdir(carpeta):
        return (f"No se encuentra la carpeta de la base de datos:\n{carpeta}\n\n"
                "Revisa que el PC principal esté encendido y conectado a la misma red.")
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        conn.close()
    except sqlite3.Error as e:
        return f"No se pudo abrir la base de datos:\n{DB_PATH}\n\n{e}"
    return None


def firma_cambios():
    """Valor que cambia cuando alguien (en cualquier PC) guarda algo. Sirve para
    que la pantalla se actualice sola. Devuelve None si no se pudo leer."""
    conn = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute("""
            SELECT
              (SELECT COUNT(*) FROM ventas),
              (SELECT COALESCE(MAX(id), 0) FROM ventas),
              (SELECT COALESCE(SUM(CASE WHEN COALESCE(estado, 'Activa') <> 'Activa'
                                        THEN 1 ELSE 0 END), 0) FROM ventas),
              (SELECT COUNT(*) FROM abonos),
              (SELECT COALESCE(SUM(monto), 0) FROM abonos),
              (SELECT COUNT(*) FROM productos),
              (SELECT COALESCE(SUM(stock), 0) FROM productos),
              (SELECT COALESCE(SUM(precio), 0) FROM productos),
              (SELECT COUNT(*) FROM clientes),
              (SELECT COUNT(*) FROM materiales),
              (SELECT COALESCE(SUM(stock_actual), 0) FROM materiales),
              (SELECT COUNT(*) FROM caja_aperturas),
              (SELECT COUNT(*) FROM caja_movimientos),
              (SELECT COUNT(*) FROM cierres_caja)
        """)
        return tuple(float(x) for x in cur.fetchone())
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()


# ---------------------------------------------------------------------------
# Creación de tablas
# ---------------------------------------------------------------------------
_TABLAS_MYSQL = [
    """CREATE TABLE IF NOT EXISTS productos (
        id INT(11) NOT NULL AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(255) NOT NULL,
        tipo VARCHAR(100) NOT NULL,
        precio DECIMAL(12,2) NOT NULL,
        stock INT(11) NOT NULL DEFAULT 0,
        codigo_barras VARCHAR(100) NULL,
        UNIQUE KEY idx_productos_codigo_barras (codigo_barras)
    )""",
    """CREATE TABLE IF NOT EXISTS materiales (
        id INT(11) NOT NULL AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(255) NOT NULL UNIQUE,
        unidad VARCHAR(50) NOT NULL DEFAULT 'unidad',
        stock_actual DECIMAL(10,2) NOT NULL DEFAULT 0,
        codigo_barras VARCHAR(100) NULL,
        UNIQUE KEY idx_materiales_codigo_barras (codigo_barras)
    )""",
    """CREATE TABLE IF NOT EXISTS movimientos_material (
        id INT(11) NOT NULL AUTO_INCREMENT PRIMARY KEY,
        material_id INT(11) NOT NULL,
        tipo ENUM('entrada','salida') NOT NULL,
        cantidad DECIMAL(10,2) NOT NULL,
        motivo TEXT,
        fecha DATETIME,
        FOREIGN KEY (material_id) REFERENCES materiales(id)
    )""",
    """CREATE TABLE IF NOT EXISTS entradas_mercancia (
        id INT(11) NOT NULL AUTO_INCREMENT PRIMARY KEY,
        material_id INT(11) NULL,
        cantidad DECIMAL(12,2) NOT NULL,
        fecha VARCHAR(50),
        nota TEXT,
        tipo_item VARCHAR(50),
        nombre VARCHAR(255),
        item_id INT(11) NULL
    )""",
    """CREATE TABLE IF NOT EXISTS clientes (
        id INT(11) NOT NULL AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(255) NOT NULL,
        nit VARCHAR(50),
        rut VARCHAR(50),
        telefono VARCHAR(50),
        correo VARCHAR(150),
        direccion VARCHAR(255),
        fecha_registro DATETIME
    )""",
    """CREATE TABLE IF NOT EXISTS ventas (
        id INT(11) NOT NULL AUTO_INCREMENT PRIMARY KEY,
        fecha DATETIME NOT NULL,
        total DECIMAL(12,2) NOT NULL,
        cliente_id INT(11) NULL,
        cliente_nombre VARCHAR(255),
        cliente_telefono VARCHAR(50),
        cliente_nit VARCHAR(50),
        cliente_rut VARCHAR(50),
        cliente_correo VARCHAR(150),
        forma_pago VARCHAR(50) DEFAULT 'Contado',
        metodo_pago VARCHAR(50) DEFAULT 'Efectivo',
        estado VARCHAR(20) DEFAULT 'Activa',
        motivo_anulacion VARCHAR(255) NULL,
        fecha_anulacion DATETIME NULL,
        INDEX idx_ventas_fecha (fecha),
        FOREIGN KEY (cliente_id) REFERENCES clientes(id)
    )""",
    """CREATE TABLE IF NOT EXISTS venta_detalle (
        id INT(11) NOT NULL AUTO_INCREMENT PRIMARY KEY,
        venta_id INT(11) NOT NULL,
        producto_id INT(11) NOT NULL,
        nombre_producto VARCHAR(255),
        cantidad INT(11) NOT NULL,
        precio_unitario DECIMAL(12,2) NOT NULL,
        subtotal DECIMAL(12,2) NOT NULL,
        FOREIGN KEY (venta_id) REFERENCES ventas(id),
        FOREIGN KEY (producto_id) REFERENCES productos(id)
    )""",
    """CREATE TABLE IF NOT EXISTS abonos (
        id INT(11) NOT NULL AUTO_INCREMENT PRIMARY KEY,
        venta_id INT(11) NOT NULL,
        fecha DATETIME NOT NULL,
        monto DECIMAL(12,2) NOT NULL,
        nota TEXT,
        metodo_pago VARCHAR(50) DEFAULT 'Efectivo',
        FOREIGN KEY (venta_id) REFERENCES ventas(id)
    )""",
    """CREATE TABLE IF NOT EXISTS caja_aperturas (
        id INT(11) NOT NULL AUTO_INCREMENT PRIMARY KEY,
        fecha VARCHAR(20) NOT NULL,
        monto_inicial DECIMAL(12,2) NOT NULL,
        creado_en VARCHAR(50) NULL,
        UNIQUE KEY idx_caja_aperturas_fecha (fecha)
    )""",
    """CREATE TABLE IF NOT EXISTS caja_movimientos (
        id INT(11) NOT NULL AUTO_INCREMENT PRIMARY KEY,
        fecha VARCHAR(20) NOT NULL,
        tipo VARCHAR(20) NOT NULL,
        monto DECIMAL(12,2) NOT NULL,
        concepto VARCHAR(255),
        creado_en VARCHAR(50) NULL,
        hora VARCHAR(20) NULL,
        INDEX idx_caja_movimientos_fecha (fecha)
    )""",
    """CREATE TABLE IF NOT EXISTS cierres_caja (
        id INT(11) NOT NULL AUTO_INCREMENT PRIMARY KEY,
        fecha VARCHAR(20) NOT NULL,
        efectivo_esperado DECIMAL(12,2),
        efectivo_contado DECIMAL(12,2),
        diferencia DECIMAL(12,2),
        nota TEXT,
        creado_en VARCHAR(50) NULL
    )""",
]

# Columnas que el programa necesita y que una base creada antes podría no tener.
# Solo se AGREGAN (nunca se borra ni se cambia nada existente).
_COLUMNAS_NECESARIAS_MYSQL = [
    ("ventas", "motivo_anulacion", "VARCHAR(255) NULL"),
    ("entradas_mercancia", "precio_proveedor", "DECIMAL(12,2) NOT NULL DEFAULT 0"),
]


# ---------------------------------------------------------------------------
# Columnas reales de las tablas: el programa se adapta a lo que exista
# ---------------------------------------------------------------------------
_CACHE_COLUMNAS = {}


def columnas_de(tabla, refrescar=False):
    """Nombres (en minúscula) de las columnas de la tabla; vacío si no existe."""
    if refrescar or tabla not in _CACHE_COLUMNAS:
        conn = conectar()
        try:
            cur = conn.cursor()
            if MODO == "mysql":
                cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ?", (tabla,))
                cols = {str(f[0]).lower() for f in cur.fetchall()}
            else:
                cur.execute(f"PRAGMA table_info({tabla})")
                cols = {str(f[1]).lower() for f in cur.fetchall()}
        finally:
            conn.close()
        _CACHE_COLUMNAS[tabla] = cols
    return _CACHE_COLUMNAS[tabla]


def tiene_columna(tabla, columna):
    return columna.lower() in columnas_de(tabla)


def col_o_vacio(tabla, columna):
    """Expresión SQL para leer una columna opcional: si no existe devuelve ''."""
    return f"COALESCE({columna}, '')" if tiene_columna(tabla, columna) else "''"


def insertar(cur, tabla, datos):
    """INSERT que solo usa las columnas que la tabla realmente tiene, y rellena
    'creado_en' si la tabla lo tiene. Así funciona con bases creadas por
    versiones distintas del programa."""
    cols = columnas_de(tabla)
    datos = {k: v for k, v in datos.items() if k.lower() in cols}
    if "creado_en" in cols and "creado_en" not in datos:
        datos["creado_en"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    nombres = list(datos)
    cur.execute(f"INSERT INTO {tabla} ({', '.join(nombres)}) VALUES ({', '.join('?' for _ in nombres)})",
                [datos[n] for n in nombres])
    return cur


def _columnas(cur, tabla):
    cur.execute(f"PRAGMA table_info({tabla})")
    return {fila[1] for fila in cur.fetchall()}


def _agregar_columna(cur, tabla, columna, ddl):
    """(SQLite) Agrega la columna si la tabla todavía no la tiene."""
    if columna not in _columnas(cur, tabla):
        cur.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {ddl}")


def _quitar_check_tipo(conn):
    """(SQLite) Reconstruye 'productos' sin el CHECK de tipo (conserva todos los
    datos). Si la tabla ya está migrada, no hace nada."""
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


def _crear_tablas_mysql(conn):
    cur = conn.cursor()
    for ddl in _TABLAS_MYSQL:
        cur.execute(ddl + " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
    conn.commit()
    for tabla, columna, ddl in _COLUMNAS_NECESARIAS_MYSQL:
        if columna not in columnas_de(tabla, refrescar=True):
            try:
                cur.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {ddl}")
                conn.commit()
            except Exception:
                conn.rollback()   # sin permiso para alterar: el programa sigue, sin esa columna


def _crear_tablas_sqlite(conn):
    conn.execute("PRAGMA journal_mode = DELETE")
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
    _agregar_columna(cur, "productos", "codigo_barras", "TEXT")
    conn.commit()
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
    _agregar_columna(cur, "materiales", "codigo_barras", "TEXT")
    cur.execute("UPDATE materiales SET codigo_barras = NULL WHERE codigo_barras = ''")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_materiales_codigo_barras "
                "ON materiales(codigo_barras) WHERE codigo_barras IS NOT NULL")

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
    _agregar_columna(cur, "clientes", "correo", "TEXT")

    # ---------------- VENTAS ----------------
    # estado: Activa / Anulada / Devuelta (las anuladas no se borran)
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
            metodo_pago TEXT DEFAULT 'Efectivo',
            estado TEXT DEFAULT 'Activa',
            motivo_anulacion TEXT,
            fecha_anulacion TEXT,
            FOREIGN KEY (cliente_id) REFERENCES clientes(id)
        )
    """)
    for columna, ddl in [
        ("cliente_nombre", "TEXT NOT NULL DEFAULT ''"),
        ("cliente_telefono", "TEXT NOT NULL DEFAULT ''"),
        ("cliente_id", "INTEGER REFERENCES clientes(id)"),
        ("cliente_nit", "TEXT NOT NULL DEFAULT ''"),
        ("cliente_rut", "TEXT NOT NULL DEFAULT ''"),
        ("cliente_correo", "TEXT"),
        ("forma_pago", "TEXT DEFAULT 'Contado'"),
        ("metodo_pago", "TEXT DEFAULT 'Efectivo'"),
        ("estado", "TEXT DEFAULT 'Activa'"),
        ("motivo_anulacion", "TEXT"),
        ("fecha_anulacion", "TEXT"),
    ]:
        _agregar_columna(cur, "ventas", columna, ddl)

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
            metodo_pago TEXT DEFAULT 'Efectivo',
            FOREIGN KEY (venta_id) REFERENCES ventas(id)
        )
    """)
    _agregar_columna(cur, "abonos", "metodo_pago", "TEXT DEFAULT 'Efectivo'")

    # ---------------- CAJA DEL DÍA ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS caja_aperturas (
            fecha TEXT PRIMARY KEY,
            monto_inicial REAL NOT NULL,
            hora TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS caja_movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            hora TEXT,
            tipo TEXT NOT NULL,
            monto REAL NOT NULL,
            concepto TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cierres_caja (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            fecha_cierre TEXT,
            efectivo_esperado REAL,
            efectivo_contado REAL,
            diferencia REAL,
            nota TEXT
        ) 
    """)
         # ---------------- ENTRADAS DE MERCANCÍA ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS entradas_mercancia (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER,
            tipo_item TEXT DEFAULT 'material',
            nombre TEXT,
            cantidad REAL NOT NULL,
            precio_proveedor REAL NOT NULL DEFAULT 0,
            fecha TEXT NOT NULL,
            nota TEXT
        )
    """)
    _agregar_columna(cur, "entradas_mercancia", "precio_proveedor", "REAL NOT NULL DEFAULT 0")
    conn.commit()

    # ---------------- ÍNDICES ----------------
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_venta_detalle_venta ON venta_detalle(venta_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_abonos_venta ON abonos(venta_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_caja_movimientos_fecha ON caja_movimientos(fecha)")
    conn.commit()


def inicializar_db():
    """Crea las tablas si no existen. Se llama al arrancar la app."""
    conn = conectar()
    try:
        if MODO == "mysql":
            _crear_tablas_mysql(conn)
        else:
            _crear_tablas_sqlite(conn)

        if CARGAR_DATOS_EJEMPLO:
            _cargar_ejemplos(conn)
    finally:
        conn.close()
    _CACHE_COLUMNAS.clear()


def _cargar_ejemplos(conn):
    cur = conn.cursor()
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


def borrar_datos_prueba():
    """Borra ventas, clientes, abonos, movimientos y cierres (no toca productos
    ni materiales) y reinicia los números."""
    conn = conectar()
    cur = conn.cursor()

    # De las tablas que dependen de otras a las principales
    tablas = ["abonos", "venta_detalle", "movimientos_material", "ventas", "clientes",
              "caja_movimientos", "caja_aperturas", "cierres_caja"]
    con_ids = [t for t in tablas if t != "caja_aperturas"]  # esta usa fecha como clave

    try:
        for tabla in tablas:
            cur.execute(f"DELETE FROM {tabla}")

        if MODO == "mysql":
            for tabla in con_ids:
                cur.execute(f"ALTER TABLE {tabla} AUTO_INCREMENT = 1")
        else:
            marcas = ", ".join("?" for _ in con_ids)
            cur.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({marcas})", con_ids)

        conn.commit()
        print("Datos de prueba eliminados correctamente.")
    except Exception as e:
        conn.rollback()
        print(f"Error al borrar los datos: {e}")
    finally:
        conn.close()