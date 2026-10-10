"""
Entrada de mercancía para la Caja Registradora.

Pestaña para sumar stock cuando llega mercancía nueva (zapatos/productos o
materiales de peletería), dejando un historial de cada entrada. Si te
equivocas, puedes anular una entrada (pide la clave de seguridad).

Para los materiales de peletería también se puede fijar el precio de venta
(es el que usa la Caja Peletería).

La búsqueda mira zapatos y peletería a la vez (opción "Todos").
"""
import re
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

import database as db
import seguridad

COLOR_FILA_ALT = "#fff8f6"
COLOR_BLANCO = "#ffffff"


def _ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fmt_cant(valor):
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    return str(int(v)) if v.is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")


def _fmt_precio(valor):
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return ""
    return f"${v:,.0f}" if v > 0 else "sin precio"


def _a_numero(texto):
    """'50.000', '$50,000' o '50000' -> 50000.0 (None si no hay número)."""
    digitos = re.sub(r"[^\d]", "", texto or "")
    return float(digitos) if digitos else None


def _tabla_y_columna(tipo):
    """Tabla y columna de stock según el tipo de artículo."""
    if tipo == "producto":
        return "productos", "stock"
    return "materiales", "stock_actual"


def _quitar_llaves_foraneas(conn):
    """(MySQL) La tabla entradas_mercancia guarda productos y materiales en el
    mismo historial, así que no puede tener llave foránea hacia 'materiales'."""
    cur = conn.cursor()
    try:
        cur.execute("""SELECT DISTINCT CONSTRAINT_NAME
                       FROM information_schema.KEY_COLUMN_USAGE
                       WHERE TABLE_SCHEMA = DATABASE()
                         AND TABLE_NAME = 'entradas_mercancia'
                         AND REFERENCED_TABLE_NAME IS NOT NULL""")
        for (nombre,) in cur.fetchall():
            cur.execute(f"ALTER TABLE entradas_mercancia DROP FOREIGN KEY `{nombre}`")
        if "material_id" in db.columnas_de("entradas_mercancia", refrescar=True):
            cur.execute("ALTER TABLE entradas_mercancia MODIFY material_id INT NULL")
        conn.commit()
    except Exception:
        conn.rollback()   # sin permiso para alterar: el programa sigue igual


def asegurar_tabla():
    conn = db.conectar()
    try:
        cur = conn.cursor()
        id_ddl = "INT AUTO_INCREMENT PRIMARY KEY" if db.MODO == "mysql" \
            else "INTEGER PRIMARY KEY AUTOINCREMENT"
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS entradas_mercancia (
                id {id_ddl},
                item_id INT NULL,
                tipo_item VARCHAR(50) DEFAULT 'material',
                nombre VARCHAR(255) NULL,
                cantidad DECIMAL(12, 2) NOT NULL,
                precio_proveedor DECIMAL(12, 2) NOT NULL DEFAULT 0,
                fecha VARCHAR(50) NOT NULL,
                nota TEXT
            )
        """)
        conn.commit()

        # Agregar columnas faltantes si la tabla ya existía de antes
        existentes = db.columnas_de("entradas_mercancia", refrescar=True)
        for col, ddl in (("tipo_item", "VARCHAR(50) DEFAULT 'material'"),
                         ("nombre", "VARCHAR(255) NULL"),
                         ("item_id", "INT NULL")):
            if col not in existentes:
                cur.execute(f"ALTER TABLE entradas_mercancia ADD COLUMN {col} {ddl}")
                if "precio_proveedor" not in existentes:
                 cur.execute("ALTER TABLE entradas_mercancia "
                        "ADD COLUMN precio_proveedor DECIMAL(12,2) NOT NULL DEFAULT 0")
            conn.commit()
        conn.commit()

        # Precio de venta de los materiales (lo usa la Caja Peletería)
        if "precio" not in db.columnas_de("materiales", refrescar=True):
            cur.execute("ALTER TABLE materiales ADD COLUMN precio DECIMAL(12,2) NOT NULL DEFAULT 0")
            conn.commit()

        if db.MODO == "mysql":
            _quitar_llaves_foraneas(conn)
    finally:
        conn.close()
    db.columnas_de("entradas_mercancia", refrescar=True)
    db.columnas_de("materiales", refrescar=True)


def _crear_tree(parent, columnas, alto=None):
    tree = ttk.Treeview(parent, columns=[c[0] for c in columnas],
                        show="headings", selectmode="browse",
                        **({"height": alto} if alto else {}))
    for cid, txt, ancho, anchor in columnas:
        tree.heading(cid, text=txt)
        tree.column(cid, width=ancho, anchor=anchor)
    tree.tag_configure("par", background=COLOR_FILA_ALT)
    tree.tag_configure("impar", background=COLOR_BLANCO)
    return tree


class TabEntradaMercancia(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._seleccion = None          # (tipo, id, nombre)
        self._precios = {}              # iid -> precio actual (solo materiales)
        asegurar_tabla()
        self._construir()
        self.cargar()
        self.bind("<Visibility>", self._al_mostrar)

    def _al_cambiar_tipo(self):
        """Se ejecuta cuando el usuario cambia el filtro (todos / productos / materiales)."""
        self._limpiar_seleccion()
        self.ent_buscar.delete(0, "end")
        self.cargar_resultados()
        self.ent_buscar.focus_set()

    # ------------------------------------------------------------------
    # Construcción de la interfaz
    # ------------------------------------------------------------------
    def _construir(self):
        self.columnconfigure(0, weight=2)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)

        # ---- Barra superior: filtro + búsqueda ----
        top = ttk.LabelFrame(
            self, text="📥 Entrada de mercancía: escanea el código o escribe el nombre")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 0))
        top.columnconfigure(5, weight=1)

        self.var_tipo = tk.StringVar(value="todos")
        ttk.Radiobutton(top, text="Todos", variable=self.var_tipo,
                        value="todos", command=self._al_cambiar_tipo
                        ).grid(row=0, column=0, padx=8, pady=8)
        ttk.Radiobutton(top, text="Zapatos / productos", variable=self.var_tipo,
                        value="producto", command=self._al_cambiar_tipo
                        ).grid(row=0, column=1, padx=8, pady=8)
        ttk.Radiobutton(top, text="Peletería (materiales)", variable=self.var_tipo,
                        value="material", command=self._al_cambiar_tipo
                        ).grid(row=0, column=2, padx=8, pady=8)

        ttk.Label(top, text="Buscar:").grid(row=0, column=4, padx=(12, 4), sticky="e")
        self.ent_buscar = ttk.Entry(top)
        self.ent_buscar.grid(row=0, column=5, padx=4, pady=8, sticky="ew")
        self.ent_buscar.bind("<Return>", self._buscar_enter)
        ttk.Button(top, text="Ver todos", command=self._ver_todos).grid(row=0, column=6, padx=8)

        # ---- Resultados (izquierda) ----
        izq = ttk.LabelFrame(self, text="Artículos")
        izq.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        izq.rowconfigure(0, weight=1)
        izq.columnconfigure(0, weight=1)
        self.tree_res = _crear_tree(izq, [
            ("nombre", "Nombre", 230, "w"),
            ("tipo", "Tipo", 80, "center"),
            ("codigo", "Código", 110, "w"),
            ("precio", "Precio", 90, "center"),
            ("stock", "Stock actual", 90, "center"),
        ])
        self.tree_res.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.tree_res.bind("<<TreeviewSelect>>", self._al_seleccionar)

        # ---- Formulario de entrada (derecha) ----
        der = ttk.LabelFrame(self, text="Registrar entrada")
        der.grid(row=1, column=1, sticky="nsew", padx=6, pady=6)
        der.columnconfigure(1, weight=1)

        self.lbl_sel = ttk.Label(der, text="Selecciona un artículo de la lista",
                                 style="Subtitulo.TLabel", wraplength=260)
        self.lbl_sel.grid(row=0, column=0, columnspan=2, padx=8, pady=(10, 2), sticky="w")
        self.lbl_stock = ttk.Label(der, text="")
        self.lbl_stock.grid(row=1, column=0, columnspan=2, padx=8, pady=(0, 10), sticky="w")

        ttk.Label(der, text="Cantidad que llegó:").grid(row=2, column=0, padx=8, pady=6, sticky="e")
        self.ent_cant = ttk.Entry(der)
        self.ent_cant.grid(row=2, column=1, padx=8, pady=6, sticky="ew")
        self.ent_cant.bind("<Return>", lambda e: self.registrar())

        ttk.Label(der, text="Precio de proveedor:").grid(row=3, column=0, padx=8, pady=6, sticky="e")
        self.ent_precio_prov = ttk.Entry(der)
        self.ent_precio_prov.grid(row=3, column=1, padx=8, pady=6, sticky="ew")
        self.ent_precio_prov.bind("<Return>", lambda e: self.registrar())

        ttk.Label(der, text="Precio de venta:").grid(row=4, column=0, padx=8, pady=6, sticky="e")
        self.ent_precio = ttk.Entry(der, state="disabled")
        self.ent_precio.grid(row=4, column=1, padx=8, pady=6, sticky="ew")
        self.ent_precio.bind("<Return>", lambda e: self.registrar())
        self.lbl_precio_hint = ttk.Label(der, text="(solo materiales de peletería)",
                                         style="Sugerencia.TLabel")
        self.lbl_precio_hint.grid(row=5, column=1, padx=8, sticky="w")

        ttk.Label(der, text="Nota (proveedor, factura):").grid(row=6, column=0, padx=8, pady=6, sticky="e")
        self.ent_nota = ttk.Entry(der)
        self.ent_nota.grid(row=6, column=1, padx=8, pady=6, sticky="ew")
        self.ent_nota.bind("<Return>", lambda e: self.registrar())

        ttk.Button(der, text="✅ Registrar entrada", command=self.registrar).grid(
            row=7, column=0, columnspan=2, padx=8, pady=14, sticky="ew")

        # ---- Historial ----
        hist = ttk.LabelFrame(self, text="Últimas entradas registradas")
        hist.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=6, pady=(0, 6))
        hist.rowconfigure(1, weight=1)
        hist.columnconfigure(0, weight=1)

        # Barra de búsqueda del historial
        filtros = ttk.Frame(hist)
        filtros.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 0))

        ttk.Label(filtros, text="Fecha:").pack(side="left", padx=(0, 4))
        self.ent_h_fecha = ttk.Entry(filtros, width=11)
        self.ent_h_fecha.pack(side="left")
        ttk.Button(filtros, text="📅", width=3,
                   command=lambda: self.app.abrir_calendario(self.ent_h_fecha)
                   ).pack(side="left", padx=(2, 10))

        ttk.Label(filtros, text="Tipo:").pack(side="left", padx=(0, 4))
        self.combo_h_tipo = ttk.Combobox(filtros, values=["Todos", "Producto", "Material"],
                                         state="readonly", width=10)
        self.combo_h_tipo.set("Todos")
        self.combo_h_tipo.pack(side="left", padx=(0, 10))

        ttk.Label(filtros, text="Artículo:").pack(side="left", padx=(0, 4))
        self.ent_h_articulo = ttk.Entry(filtros, width=18)
        self.ent_h_articulo.pack(side="left", padx=(0, 10))

        ttk.Label(filtros, text="Nota:").pack(side="left", padx=(0, 4))
        self.ent_h_nota = ttk.Entry(filtros, width=16)
        self.ent_h_nota.pack(side="left", padx=(0, 10))

        for ent in (self.ent_h_fecha, self.ent_h_articulo, self.ent_h_nota):
            ent.bind("<Return>", lambda e: self.cargar_historial())
        self.combo_h_tipo.bind("<<ComboboxSelected>>", lambda e: self.cargar_historial())

        ttk.Button(filtros, text="🔍 Buscar entradas",
                   command=self.cargar_historial).pack(side="left", padx=(0, 6))
        ttk.Button(filtros, text="Ver todas",
                   command=self._ver_todas_historial).pack(side="left")

        self.tree_hist = _crear_tree(hist, [
            ("fecha", "Fecha", 150, "center"),
            ("tipo", "Tipo", 90, "center"),
            ("nombre", "Artículo", 240, "w"),
            ("cantidad", "Cantidad", 90, "center"),
            ("precio_prov", "P. proveedor", 100, "center"),
            ("nota", "Nota", 220, "w"),
        ], alto=6)
        self.tree_hist.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        ttk.Button(hist, text="↩ Anular entrada", command=self.anular_entrada).grid(
            row=1, column=1, padx=10, pady=6, sticky="n")

    # ------------------------------------------------------------------
    # Carga de datos
    # ------------------------------------------------------------------
    def cargar(self):
        self.cargar_resultados(self.ent_buscar.get().strip())
        self.cargar_historial()

    def _al_mostrar(self, event=None):
        if event is not None and event.widget is not self:
            return
        self.cargar_resultados(self.ent_buscar.get().strip())
        self.after(100, self.ent_buscar.focus_set)

    def _tipos_a_buscar(self):
        t = self.var_tipo.get()
        return ["producto", "material"] if t == "todos" else [t]

    def cargar_resultados(self, filtro=""):
        """Busca en zapatos y/o peletería. Devuelve filas (tipo, id, nombre, codigo, stock)."""
        filas = []
        precios = {}
        conn = db.conectar()
        try:
            cur = conn.cursor()
            for tipo in self._tipos_a_buscar():
                tabla, col_stock = _tabla_y_columna(tipo)
                col_precio = "COALESCE(precio, 0)" if tipo == "material" else "0"
                if filtro:
                    cur.execute(f"""SELECT id, nombre, COALESCE(codigo_barras, ''), {col_stock},
                                           {col_precio}
                                    FROM {tabla}
                                    WHERE codigo_barras = ? OR nombre LIKE ?
                                    ORDER BY nombre ASC""",
                                (filtro, f"%{filtro}%"))
                else:
                    cur.execute(f"""SELECT id, nombre, COALESCE(codigo_barras, ''), {col_stock},
                                           {col_precio}
                                    FROM {tabla}
                                    ORDER BY nombre ASC""")
                for (id_, nombre, codigo, stock, precio) in cur.fetchall():
                    filas.append((tipo, id_, nombre, codigo, stock))
                    if tipo == "material":
                        precios[f"{tipo}:{id_}"] = float(precio)
        finally:
            conn.close()

        filas.sort(key=lambda f: str(f[2]).lower())
        self._precios = precios

        for row in self.tree_res.get_children():
            self.tree_res.delete(row)
        for i, (tipo, id_, nombre, codigo, stock) in enumerate(filas):
            iid = f"{tipo}:{id_}"
            precio_txt = _fmt_precio(precios[iid]) if tipo == "material" else "—"
            self.tree_res.insert(
                "", "end", iid=iid,
                tags=("par" if i % 2 == 0 else "impar",),
                values=(nombre, "Producto" if tipo == "producto" else "Material",
                        codigo, precio_txt, _fmt_cant(stock)))
        return filas

    def cargar_historial(self):
        condiciones, params = [], []

        fecha = self.ent_h_fecha.get().strip()
        if fecha:
            condiciones.append("fecha LIKE ?")
            params.append(f"{fecha}%")

        tipo = self.combo_h_tipo.get().lower()
        if tipo in ("producto", "material"):
            condiciones.append("tipo_item = ?")
            params.append(tipo)

        articulo = self.ent_h_articulo.get().strip()
        if articulo:
            condiciones.append("nombre LIKE ?")
            params.append(f"%{articulo}%")

        nota = self.ent_h_nota.get().strip()
        if nota:
            condiciones.append("nota LIKE ?")
            params.append(f"%{nota}%")

        where = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""

        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute(f"""SELECT id, fecha, tipo_item, nombre, cantidad,
                                   COALESCE(precio_proveedor, 0), COALESCE(nota, '')
                            FROM entradas_mercancia {where}
                            ORDER BY id DESC LIMIT 200""", params)
            filas = cur.fetchall()
        finally:
            conn.close()

        for item in self.tree_hist.get_children():
            self.tree_hist.delete(item)
        for i, (eid, fecha, tipo_it, nombre, cant, prov, nota) in enumerate(filas):
            self.tree_hist.insert("", "end", iid=str(eid),
                                  tags=("par" if i % 2 == 0 else "impar",),
                                  values=(fecha, "Producto" if tipo_it == "producto" else "Material",
                                          nombre, _fmt_cant(cant),
                                          _fmt_precio(prov) if float(prov) > 0 else "—",
                                          nota))

    def _ver_todas_historial(self):
        self.ent_h_fecha.delete(0, "end")
        self.combo_h_tipo.set("Todos")
        self.ent_h_articulo.delete(0, "end")
        self.ent_h_nota.delete(0, "end")
        self.cargar_historial()

    # ------------------------------------------------------------------
    # Búsqueda y selección
    # ------------------------------------------------------------------
    def _ver_todos(self):
        self.ent_buscar.delete(0, "end")
        self.cargar_resultados()
        self.ent_buscar.focus_set()

    def _buscar_enter(self, event=None):
        filtro = self.ent_buscar.get().strip()
        filas = self.cargar_resultados(filtro)
        if not filtro:
            return
        if not filas:
            t = self.var_tipo.get()
            donde = ("Zapatos o Peletería" if t == "todos"
                     else "Zapatos" if t == "producto" else "Peletería")
            messagebox.showwarning(
                "No encontrado",
                f"No se encontró nada con '{filtro}'.\n\n"
                f"Si es un artículo nuevo, créalo primero en la pestaña {donde}.")
            self.ent_buscar.delete(0, "end")
            self.ent_buscar.focus_set()
            return
        if len(filas) == 1:
            tipo, id_ = filas[0][0], filas[0][1]
            self.tree_res.selection_set(f"{tipo}:{id_}")
            self.ent_buscar.delete(0, "end")
            self.ent_cant.focus_set()

    def _al_seleccionar(self, event=None):
        sel = self.tree_res.selection()
        if not sel:
            return
        tipo, id_txt = sel[0].split(":", 1)
        valores = self.tree_res.item(sel[0], "values")   # nombre, tipo, codigo, precio, stock
        self._seleccion = (tipo, int(id_txt), valores[0])
        self.lbl_sel.config(text=f"{valores[0]}  ({valores[1]})")
        self.lbl_stock.config(text=f"Stock actual: {valores[4]}")

        # El precio solo aplica a materiales: se precarga el actual
        self.ent_precio.config(state="normal")
        self.ent_precio.delete(0, "end")
        if tipo == "material":
            actual = self._precios.get(sel[0], 0)
            if actual > 0:
                self.ent_precio.insert(0, str(int(actual)))
            self.lbl_precio_hint.config(text="(déjalo vacío para no cambiarlo)")
        else:
            self.ent_precio.config(state="disabled")
            self.lbl_precio_hint.config(text="(solo materiales de peletería)")

    def _limpiar_seleccion(self):
        self._seleccion = None
        self.lbl_sel.config(text="Selecciona un artículo de la lista")
        self.lbl_stock.config(text="")
        self.ent_cant.delete(0, "end")
        self.ent_nota.delete(0, "end")
        self.ent_precio.config(state="normal")
        self.ent_precio.delete(0, "end")
        self.ent_precio.config(state="disabled")
        self.lbl_precio_hint.config(text="(solo materiales de peletería)")

    # ------------------------------------------------------------------
    # Registrar entrada
    # ------------------------------------------------------------------
    def registrar(self):
        if not self._seleccion:
            messagebox.showwarning("Selecciona un artículo",
                                   "Escanea o busca el artículo y selecciónalo de la lista.")
            return
        tipo, item_id, nombre = self._seleccion

        texto = self.ent_cant.get().strip().replace(",", ".")
        try:
            cantidad = float(texto)
        except ValueError:
            messagebox.showerror("Cantidad inválida", "Escribe la cantidad como número.")
            self.ent_cant.focus_set()
            return
        if cantidad <= 0:
            messagebox.showerror("Cantidad inválida", "La cantidad debe ser mayor a 0.")
            self.ent_cant.focus_set()
            return

        if tipo == "producto":
            if not cantidad.is_integer():
                messagebox.showerror("Cantidad inválida",
                                     "Los productos se cuentan en unidades enteras.")
                self.ent_cant.focus_set()
                return
            cantidad = int(cantidad)

        # Precio de venta (solo materiales; vacío = no se cambia)
        nuevo_precio = None
        if tipo == "material":
            texto_precio = self.ent_precio.get().strip()
            if texto_precio:
                nuevo_precio = _a_numero(texto_precio)
                if not nuevo_precio or nuevo_precio <= 0:
                    messagebox.showerror("Precio inválido", "Escribe un precio mayor a 0.")
                    self.ent_precio.focus_set()
                    return

        nota = self.ent_nota.get().strip()
        tabla, col_stock = _tabla_y_columna(tipo)

        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute(f"UPDATE {tabla} SET {col_stock} = {col_stock} + ? WHERE id = ?",
                        (cantidad, item_id))
            if cur.rowcount == 0:
                raise ValueError("Ese artículo ya no existe.")
            if nuevo_precio is not None:
                cur.execute("UPDATE materiales SET precio = ? WHERE id = ?",
                            (nuevo_precio, item_id))
            cur.execute(
                """INSERT INTO entradas_mercancia (fecha, tipo_item, item_id, nombre, cantidad, nota)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (_ahora(), tipo, item_id, nombre, cantidad, nota))
            cur.execute(f"SELECT {col_stock} FROM {tabla} WHERE id = ?", (item_id,))
            nuevo_stock = cur.fetchone()[0]
            conn.commit()
        except Exception as e:
            conn.rollback()
            messagebox.showerror("Error", f"No se pudo registrar la entrada:\n{e}")
            return
        finally:
            conn.close()

        msg = f"{nombre}\n+{_fmt_cant(cantidad)}  →  stock actual: {_fmt_cant(nuevo_stock)}"
        if nuevo_precio is not None:
            msg += f"\nPrecio de venta: {_fmt_precio(nuevo_precio)}"
        messagebox.showinfo("Entrada registrada", msg)

        self._limpiar_seleccion()
        self.cargar()
        self._refrescar_app()
        self.ent_buscar.focus_set()

    def _refrescar_app(self):
        """Actualiza las otras pestañas para que vean el stock nuevo."""
        for nombre in ("cargar_catalogo", "cargar_productos_admin", "cargar_materiales"):
            try:
                getattr(self.app, nombre)()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Anular una entrada (por error de digitación)
    # ------------------------------------------------------------------
    def anular_entrada(self):
        sel = self.tree_hist.selection()
        if not sel:
            messagebox.showwarning("Seleccionar", "Selecciona una entrada del historial para anular.")
            return
        entrada_id = int(sel[0])

        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT tipo_item, item_id, nombre, cantidad
                           FROM entradas_mercancia WHERE id = ?""", (entrada_id,))
            fila = cur.fetchone()
        finally:
            conn.close()

        if not fila:
            return
        tipo, item_id, nombre, cantidad = fila
        cantidad = float(cantidad)

        if not messagebox.askyesno(
                "Anular entrada",
                f"¿Anular la entrada de {_fmt_cant(cantidad)} de '{nombre}'?\n\n"
                "Se le restará esa cantidad al stock."):
            return
        if not seguridad.pedir_clave(self.app, "anular la entrada"):
            return

        tabla, col_stock = _tabla_y_columna(tipo)
        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT {col_stock} FROM {tabla} WHERE id = ?", (item_id,))
            actual = cur.fetchone()
            if actual is not None:
                if float(actual[0]) + 1e-9 < cantidad:
                    messagebox.showerror(
                        "No se puede anular",
                        f"Hoy hay solo {_fmt_cant(actual[0])} en stock (ya se vendió o usó parte), "
                        f"así que no se pueden restar {_fmt_cant(cantidad)}.")
                    return
                cur.execute(f"UPDATE {tabla} SET {col_stock} = {col_stock} - ? WHERE id = ?",
                            (cantidad, item_id))
            cur.execute("DELETE FROM entradas_mercancia WHERE id = ?", (entrada_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            messagebox.showerror("Error", f"No se pudo anular la entrada:\n{e}")
            return
        finally:
            conn.close()

        self.cargar()
        self._refrescar_app()