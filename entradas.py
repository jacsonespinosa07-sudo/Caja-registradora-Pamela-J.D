"""
Entrada de mercancía para la Caja Registradora.

Pestaña para sumar stock cuando llega mercancía nueva (zapatos/productos o
materiales de peletería), dejando un historial de cada entrada. Si te
equivocas, puedes anular una entrada (pide la clave de seguridad).
"""
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


def _tabla_y_columna(tipo):
    """Devuelve (tabla, columna_de_stock) según el tipo de artículo."""
    if tipo == "producto":
        return "productos", "stock"
    return "materiales", "stock_actual"


def asegurar_tabla():
    """Crea la tabla del historial de entradas si no existe."""
    conn = db.conectar()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entradas_mercancia (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL,
                tipo_item TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                nombre TEXT NOT NULL,
                cantidad REAL NOT NULL,
                nota TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


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
        self._seleccion = None  # (id, nombre)
        asegurar_tabla()
        self._construir()
        self.cargar()
        self.bind("<Map>", self._al_mostrar)

    # ------------------------------------------------------------------
    # Construcción de la interfaz
    # ------------------------------------------------------------------
    def _construir(self):
        self.columnconfigure(0, weight=2)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)

        # ---- Barra superior: tipo + búsqueda ----
        top = ttk.LabelFrame(
            self, text="📥 Entrada de mercancía: escanea el código o escribe el nombre")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 0))
        top.columnconfigure(3, weight=1)

        self.var_tipo = tk.StringVar(value="producto")
        ttk.Radiobutton(top, text="Zapatos / productos", variable=self.var_tipo,
                        value="producto", command=self._al_cambiar_tipo
                        ).grid(row=0, column=0, padx=8, pady=8)
        ttk.Radiobutton(top, text="Peletería (materiales)", variable=self.var_tipo,
                        value="material", command=self._al_cambiar_tipo
                        ).grid(row=0, column=1, padx=8, pady=8)

        ttk.Label(top, text="Buscar:").grid(row=0, column=2, padx=(12, 4), sticky="e")
        self.ent_buscar = ttk.Entry(top)
        self.ent_buscar.grid(row=0, column=3, padx=4, pady=8, sticky="ew")
        self.ent_buscar.bind("<Return>", self._buscar_enter)
        ttk.Button(top, text="Ver todos", command=self._ver_todos).grid(row=0, column=4, padx=8)

        # ---- Resultados (izquierda) ----
        izq = ttk.LabelFrame(self, text="Artículos")
        izq.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        izq.rowconfigure(0, weight=1)
        izq.columnconfigure(0, weight=1)
        self.tree_res = _crear_tree(izq, [
            ("nombre", "Nombre", 240, "w"),
            ("codigo", "Código", 120, "w"),
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

        ttk.Label(der, text="Nota (proveedor, factura):").grid(row=3, column=0, padx=8, pady=6, sticky="e")
        self.ent_nota = ttk.Entry(der)
        self.ent_nota.grid(row=3, column=1, padx=8, pady=6, sticky="ew")
        self.ent_nota.bind("<Return>", lambda e: self.registrar())

        ttk.Button(der, text="✅ Registrar entrada", command=self.registrar).grid(
            row=4, column=0, columnspan=2, padx=8, pady=14, sticky="ew")

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
        # Al entrar a la pestaña: refresca el stock y deja listo el buscador
        if event is not None and event.widget is not self:
            return
        self.cargar_resultados(self.ent_buscar.get().strip())
        self.after(100, self.ent_buscar.focus_set)

    def cargar_resultados(self, filtro=""):
        tabla, col = _tabla_y_columna(self.var_tipo.get())
        conn = db.conectar()
        try:
            cur = conn.cursor()
            if filtro:
                cur.execute(
                    f"""SELECT id, nombre, COALESCE(codigo_barras, ''), {col} FROM {tabla}
                        WHERE codigo_barras = ? OR nombre LIKE ? ORDER BY nombre""",
                    (filtro, f"%{filtro}%"))
            else:
                cur.execute(
                    f"SELECT id, nombre, COALESCE(codigo_barras, ''), {col} FROM {tabla} ORDER BY nombre")
            filas = cur.fetchall()
        finally:
            conn.close()

        for item in self.tree_res.get_children():
            self.tree_res.delete(item)
        for i, (iid, nombre, codigo, stock) in enumerate(filas):
            self.tree_res.insert("", "end", iid=str(iid),
                                 tags=("par" if i % 2 == 0 else "impar",),
                                 values=(nombre, codigo, _fmt_cant(stock)))
        return filas

    def cargar_historial(self):
        condiciones, params = [], []

        fecha = self.ent_h_fecha.get().strip()
        if fecha:
            condiciones.append("fecha LIKE ?")
            params.append(f"{fecha}%")

        tipo = self.combo_h_tipo.get()
        if tipo == "Producto":
            condiciones.append("tipo_item = 'producto'")
        elif tipo == "Material":
            condiciones.append("tipo_item = 'material'")

        articulo = self.ent_h_articulo.get().strip()
        if articulo:
            condiciones.append("nombre LIKE ?")
            params.append(f"%{articulo}%")

        nota = self.ent_h_nota.get().strip()
        if nota:
            condiciones.append("COALESCE(nota, '') LIKE ?")
            params.append(f"%{nota}%")

        where = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""

        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute(f"""SELECT id, fecha, tipo_item, nombre, cantidad, COALESCE(nota, '')
                            FROM entradas_mercancia {where}
                            ORDER BY id DESC LIMIT 200""", params)
            filas = cur.fetchall()
        finally:
            conn.close()

        for item in self.tree_hist.get_children():
            self.tree_hist.delete(item)
        for i, (eid, fecha, tipo, nombre, cant, nota) in enumerate(filas):
            self.tree_hist.insert("", "end", iid=str(eid),
                                  tags=("par" if i % 2 == 0 else "impar",),
                                  values=(fecha, "Producto" if tipo == "producto" else "Material",
                                          nombre, _fmt_cant(cant), nota))

    def _ver_todas_historial(self):
        self.ent_h_fecha.delete(0, "end")
        self.combo_h_tipo.set("Todos")
        self.ent_h_articulo.delete(0, "end")
        self.ent_h_nota.delete(0, "end")
        self.cargar_historial()

    # ------------------------------------------------------------------
    # Búsqueda y selección
    # ------------------------------------------------------------------
    def _al_cambiar_tipo(self):
        self._limpiar_seleccion()
        self.ent_buscar.delete(0, "end")
        self.cargar_resultados()
        self.ent_buscar.focus_set()

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
            donde = "Zapat" if self.var_tipo.get() == "producto" else "Peleteria"
            messagebox.showwarning(
                "No encontrado",
                f"No se encontró nada con '{filtro}'.\n\n"
                f"Si es un artículo nuevo, créalo primero en la pestaña {donde}.")
            self.ent_buscar.delete(0, "end")
            self.ent_buscar.focus_set()
            return
        if len(filas) == 1:
            # Un solo resultado (típico de la pistola lectora): lo selecciona y pasa a cantidad
            self.tree_res.selection_set(str(filas[0][0]))
            self.ent_buscar.delete(0, "end")
            self.ent_cant.focus_set()

    def _al_seleccionar(self, event=None):
        sel = self.tree_res.selection()
        if not sel:
            return
        valores = self.tree_res.item(sel[0], "values")
        self._seleccion = (int(sel[0]), valores[0])
        self.lbl_sel.config(text=valores[0])
        self.lbl_stock.config(text=f"Stock actual: {valores[2]}")

    def _limpiar_seleccion(self):
        self._seleccion = None
        self.lbl_sel.config(text="Selecciona un artículo de la lista")
        self.lbl_stock.config(text="")
        self.ent_cant.delete(0, "end")
        self.ent_nota.delete(0, "end")

    # ------------------------------------------------------------------
    # Registrar entrada
    # ------------------------------------------------------------------
    def registrar(self):
        if not self._seleccion:
            messagebox.showwarning("Selecciona un artículo",
                                   "Escanea o busca el artículo y selecciónalo de la lista.")
            return
        item_id, nombre = self._seleccion

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

        tipo = self.var_tipo.get()
        if tipo == "producto":
            if not cantidad.is_integer():
                messagebox.showerror("Cantidad inválida",
                                     "Los productos se cuentan en unidades enteras.")
                self.ent_cant.focus_set()
                return
            cantidad = int(cantidad)

        nota = self.ent_nota.get().strip()
        tabla, col = _tabla_y_columna(tipo)

        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute(f"UPDATE {tabla} SET {col} = {col} + ? WHERE id = ?", (cantidad, item_id))
            if cur.rowcount == 0:
                raise ValueError("Ese artículo ya no existe.")
            cur.execute(
                """INSERT INTO entradas_mercancia (fecha, tipo_item, item_id, nombre, cantidad, nota)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (_ahora(), tipo, item_id, nombre, cantidad, nota))
            cur.execute(f"SELECT {col} FROM {tabla} WHERE id = ?", (item_id,))
            nuevo_stock = cur.fetchone()[0]
            conn.commit()
        except Exception as e:
            conn.rollback()
            messagebox.showerror("Error", f"No se pudo registrar la entrada:\n{e}")
            return
        finally:
            conn.close()

        messagebox.showinfo(
            "Entrada registrada",
            f"{nombre}\n+{_fmt_cant(cantidad)}  →  stock actual: {_fmt_cant(nuevo_stock)}")

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

        if not messagebox.askyesno(
                "Anular entrada",
                f"¿Anular la entrada de {_fmt_cant(cantidad)} de '{nombre}'?\n\n"
                "Se le restará esa cantidad al stock."):
            return
        if not seguridad.pedir_clave(self.app, "anular la entrada"):
            return

        tabla, col = _tabla_y_columna(tipo)
        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT {col} FROM {tabla} WHERE id = ?", (item_id,))
            actual = cur.fetchone()
            if actual is not None:
                if actual[0] + 1e-9 < cantidad:
                    messagebox.showerror(
                        "No se puede anular",
                        f"Hoy hay solo {_fmt_cant(actual[0])} en stock (ya se vendió o usó parte), "
                        f"así que no se pueden restar {_fmt_cant(cantidad)}.")
                    return
                cur.execute(f"UPDATE {tabla} SET {col} = {col} - ? WHERE id = ?", (cantidad, item_id))
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