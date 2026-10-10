"""
Caja de Peletería: vende los materiales (tabla materiales) con su precio.
Misma interfaz que la pestaña Caja.
Usa tablas propias: ventas_peleteria y venta_peleteria_detalle.
Las facturas y tickets los genera factura.py (logo, colores y datos de la empresa).
"""
import os
import re
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime

import database as db
import factura
import seguridad

try:
    from caja_extra import METODOS_PAGO
except Exception:
    METODOS_PAGO = ["Efectivo", "Tarjeta", "Transferencia"]

FORMAS_PAGO = ["Contado", "Crédito"]
FORMATOS = ["Factura PDF", "Ticket", "Sin comprobante"]

COLOR_FILA_ALT = "#fff8f6"
COLOR_BLANCO = "#ffffff"
COLOR_ANULADA = "#a05a5a"


def _ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _precio(valor):
    try:
        return f"${float(valor):,.0f}"
    except (TypeError, ValueError):
        return str(valor)


def _cant(valor):
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    return str(int(v)) if v.is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")


def _a_numero(texto):
    """'50.000', '$50,000' o '50000' -> 50000.0 (None si no hay número)."""
    digitos = re.sub(r"[^\d]", "", texto or "")
    return float(digitos) if digitos else None


def _crear_tree(parent, columnas, alto=None):
    tree = ttk.Treeview(parent, columns=[c[0] for c in columnas],
                        show="headings", selectmode="browse",
                        **({"height": alto} if alto else {}))
    for cid, txt, ancho, anchor in columnas:
        tree.heading(cid, text=txt)
        tree.column(cid, width=ancho, anchor=anchor)
    tree.tag_configure("par", background=COLOR_FILA_ALT)
    tree.tag_configure("impar", background=COLOR_BLANCO)
    tree.tag_configure("anulada", foreground=COLOR_ANULADA)
    return tree


def asegurar_tablas():
    """Crea las tablas de la caja de peletería y las columnas que faltan."""
    conn = db.conectar()
    try:
        cur = conn.cursor()
        id_ddl = "INT AUTO_INCREMENT PRIMARY KEY" if db.MODO == "mysql" \
            else "INTEGER PRIMARY KEY AUTOINCREMENT"
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS ventas_peleteria (
                id {id_ddl},
                fecha VARCHAR(50) NOT NULL,
                total DECIMAL(12,2) NOT NULL,
                cliente VARCHAR(255),
                metodo_pago VARCHAR(50),
                estado VARCHAR(20) DEFAULT 'Activa',
                motivo VARCHAR(255)
            )
        """)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS venta_peleteria_detalle (
                id {id_ddl},
                venta_id INT NOT NULL,
                material_id INT NOT NULL,
                nombre VARCHAR(255),
                cantidad DECIMAL(12,2) NOT NULL,
                precio_unitario DECIMAL(12,2) NOT NULL,
                subtotal DECIMAL(12,2) NOT NULL
            )
        """)
        # factura.py lee de aquí el saldo de las ventas a crédito
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS abonos_peleteria (
                id {id_ddl},
                venta_id INT NOT NULL,
                fecha VARCHAR(50) NOT NULL,
                monto DECIMAL(12,2) NOT NULL,
                nota VARCHAR(255),
                metodo_pago VARCHAR(50)
            )
        """)
        conn.commit()

        if "precio" not in db.columnas_de("materiales", refrescar=True):
            cur.execute("ALTER TABLE materiales ADD COLUMN precio DECIMAL(12,2) NOT NULL DEFAULT 0")
            conn.commit()

        extras = {
            "telefono": "VARCHAR(50)",
            "nit": "VARCHAR(50)",
            "correo": "VARCHAR(255)",
            "forma_pago": "VARCHAR(20)",
            "abono": "DECIMAL(12,2) DEFAULT 0",
            "saldo": "DECIMAL(12,2) DEFAULT 0",
        }
        existentes = db.columnas_de("ventas_peleteria", refrescar=True)
        for col, tipo in extras.items():
            if col not in existentes:
                cur.execute(f"ALTER TABLE ventas_peleteria ADD COLUMN {col} {tipo}")
                conn.commit()
    finally:
        conn.close()
    db.columnas_de("materiales", refrescar=True)
    db.columnas_de("ventas_peleteria", refrescar=True)


class TabCajaPeleteria(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.carrito = []   # dicts: material_id, nombre, precio, precio_original, cantidad
        self.clientes = {}  # nombre -> dict con datos del cliente guardado
        self.venta_libre = False
        self.tree_hist = None
        self.lbl_hoy = None
        self._win_hist = None
        asegurar_tablas()
        self._construir()
        self.cargar()
        self._cargar_clientes()
        self.bind("<Visibility>", self._al_mostrar)

    # ------------------------------------------------------------------
    # Interfaz (misma distribución que la pestaña Caja)
    # ------------------------------------------------------------------
    def _construir(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        # ---- Buscador ----
        top = ttk.LabelFrame(self, text="🔫 Escanear producto con la pistola lectora o buscar por nombre")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 0))
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Buscar:").grid(row=0, column=0, padx=(8, 4), pady=8, sticky="e")
        self.ent_buscar = ttk.Entry(top, font=("Segoe UI", 12))
        self.ent_buscar.grid(row=0, column=1, padx=4, pady=8, sticky="ew")
        self.ent_buscar.bind("<Return>", self._buscar_enter)
        ttk.Label(top, text="(Escribe nombre o escanea código y presiona Enter)",
                  style="Sugerencia.TLabel").grid(row=0, column=2, padx=8)

        # ---- Productos disponibles (izquierda) ----
        izq = ttk.LabelFrame(self, text="Productos disponibles")
        izq.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        izq.rowconfigure(0, weight=1)
        izq.columnconfigure(0, weight=1)
        self.tree_mat = _crear_tree(izq, [
            ("nombre", "Producto", 220, "w"),
            ("tipo", "Tipo", 100, "center"),
            ("precio", "Precio", 100, "center"),
            ("stock", "Stock", 80, "center"),
        ])
        self.tree_mat.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.tree_mat.bind("<Double-1>", lambda e: self.agregar_seleccion())

        agregar = ttk.Frame(izq)
        agregar.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))
        ttk.Label(agregar, text="Cantidad:").pack(side="left")
        self.spin_cantidad = ttk.Spinbox(agregar, from_=1, to=9999, width=6)
        self.spin_cantidad.set("1")
        self.spin_cantidad.pack(side="left", padx=6)
        ttk.Button(agregar, text="Agregar al carrito ➜",
                   command=self.agregar_seleccion).pack(side="left", padx=6)

        # ---- Carrito de venta (derecha) ----
        der = ttk.LabelFrame(self, text="Carrito de venta")
        der.grid(row=1, column=1, sticky="nsew", padx=6, pady=6)
        der.columnconfigure(0, weight=1)
        der.rowconfigure(0, weight=1)
        self.tree_car = _crear_tree(der, [
            ("nombre", "Producto", 200, "w"),
            ("cantidad", "Cant.", 60, "center"),
            ("precio", "P. Unit.", 90, "center"),
            ("subtotal", "Subtotal", 100, "center"),
        ], alto=5)
        self.tree_car.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.tree_car.bind("<Double-1>", self._editar_precio)

        botones = ttk.Frame(der)
        botones.grid(row=1, column=0, sticky="ew", padx=6)
        ttk.Button(botones, text="Quitar seleccionado", command=self.quitar).pack(side="left")
        ttk.Button(botones, text="Vaciar carrito", command=self.vaciar).pack(side="left", padx=6)
        ttk.Label(botones, text="(doble clic en el carrito para cambiar el precio)",
                  style="Sugerencia.TLabel").pack(side="left", padx=8)

        # ---- Datos del cliente / empresa ----
        cli = ttk.LabelFrame(der, text="Datos del cliente / empresa")
        cli.grid(row=2, column=0, sticky="ew", padx=6, pady=(8, 0))
        cli.columnconfigure(1, weight=1)

        ttk.Label(cli, text="Cliente guardado:").grid(row=0, column=0, sticky="e", padx=4, pady=3)
        self.combo_cliente = ttk.Combobox(cli, state="readonly")
        self.combo_cliente.grid(row=0, column=1, sticky="ew", padx=4, pady=3)
        self.combo_cliente.bind("<<ComboboxSelected>>", self._elegir_cliente)
        ttk.Button(cli, text="✖ Venta libre", command=self._venta_libre).grid(
            row=0, column=2, padx=4, pady=3)

        self.ent_nombre = self._campo(cli, 1, "Nombre / Razón social *:")
        self.ent_telefono = self._campo(cli, 2, "Teléfono:")
        self.ent_nit = self._campo(cli, 3, "NIT:")
        self.ent_correo = self._campo(cli, 4, "Correo *:")
        self.ent_nombre.bind("<KeyRelease>", lambda e: setattr(self, "venta_libre", False))

        ttk.Button(cli, text="💾 Guardar como cliente nuevo",
                   command=self._guardar_cliente).grid(
            row=5, column=0, columnspan=3, sticky="ew", padx=6, pady=(6, 6))

        # ---- Pago ----
        pago = ttk.Frame(der)
        pago.grid(row=3, column=0, sticky="ew", padx=6, pady=(8, 0))
        ttk.Label(pago, text="Forma de pago:").grid(row=0, column=0, sticky="e", padx=4, pady=3)
        self.combo_forma = ttk.Combobox(pago, values=FORMAS_PAGO, state="readonly", width=12)
        self.combo_forma.set("Contado")
        self.combo_forma.grid(row=0, column=1, sticky="w", padx=4, pady=3)
        self.combo_forma.bind("<<ComboboxSelected>>", self._cambio_forma)
        ttk.Label(pago, text="Abono inicial:").grid(row=0, column=2, sticky="e", padx=(20, 4), pady=3)
        self.ent_abono = ttk.Entry(pago, width=14, state="disabled")
        self.ent_abono.grid(row=0, column=3, sticky="w", padx=4, pady=3)

        ttk.Label(pago, text="Método de pago:").grid(row=1, column=0, sticky="e", padx=4, pady=3)
        self.combo_metodo = ttk.Combobox(pago, values=METODOS_PAGO, state="readonly", width=12)
        self.combo_metodo.set("Efectivo")
        self.combo_metodo.grid(row=1, column=1, sticky="w", padx=4, pady=3)

        ttk.Label(pago, text="Formato:").grid(row=2, column=0, sticky="e", padx=4, pady=3)
        self.combo_formato = ttk.Combobox(pago, values=FORMATOS, state="readonly", width=16)
        self.combo_formato.set("Factura PDF")
        self.combo_formato.grid(row=2, column=1, sticky="w", padx=4, pady=3)

        # ---- Total y cobrar ----
        total_f = ttk.Frame(der)
        total_f.grid(row=4, column=0, sticky="ew", padx=6, pady=10)
        self.lbl_total = ttk.Label(total_f, text="Total: $0", style="Total.TLabel")
        self.lbl_total.pack(side="left")
        ttk.Button(total_f, text="💵 Cobrar venta", command=self.cobrar).pack(
            side="right", ipadx=10, ipady=5)
        ttk.Button(total_f, text="📋 Ventas / Anular", command=self.abrir_historial).pack(
            side="right", padx=10, ipady=5)

    def _campo(self, parent, fila, texto):
        ttk.Label(parent, text=texto).grid(row=fila, column=0, sticky="e", padx=4, pady=3)
        ent = ttk.Entry(parent)
        ent.grid(row=fila, column=1, columnspan=2, sticky="ew", padx=4, pady=3)
        return ent

    # ------------------------------------------------------------------
    # Clientes
    # ------------------------------------------------------------------
    def _cols_cliente(self):
        """Detecta las columnas de la tabla clientes (si existe)."""
        try:
            cols = [c.lower() for c in db.columnas_de("clientes", refrescar=True)]
        except Exception:
            return None
        if not cols:
            return None

        def buscar(*opciones):
            for o in opciones:
                if o in cols:
                    return o
            return None

        mapa = {
            "nombre": buscar("nombre", "razon_social"),
            "telefono": buscar("telefono", "celular"),
            "nit": buscar("nit", "documento"),
            "correo": buscar("correo", "email"),
        }
        return mapa if mapa["nombre"] else None

    def _cargar_clientes(self):
        self.clientes = {}
        mapa = self._cols_cliente()
        if mapa:
            sel = ", ".join(f"COALESCE({mapa[k]}, '')" if mapa[k] else "''"
                            for k in ("nombre", "telefono", "nit", "correo"))
            conn = db.conectar()
            try:
                cur = conn.cursor()
                cur.execute(f"SELECT {sel} FROM clientes ORDER BY {mapa['nombre']}")
                for nombre, tel, nit, correo in cur.fetchall():
                    self.clientes[nombre] = {"nombre": nombre, "telefono": tel,
                                             "nit": nit, "correo": correo}
            except Exception:
                pass
            finally:
                conn.close()
        self.combo_cliente["values"] = list(self.clientes.keys())

    def _rellenar_cliente(self, datos):
        for ent, clave in ((self.ent_nombre, "nombre"), (self.ent_telefono, "telefono"),
                           (self.ent_nit, "nit"), (self.ent_correo, "correo")):
            ent.delete(0, "end")
            ent.insert(0, datos.get(clave, "") or "")

    def _elegir_cliente(self, event=None):
        datos = self.clientes.get(self.combo_cliente.get())
        if datos:
            self.venta_libre = False
            self._rellenar_cliente(datos)

    def _venta_libre(self):
        self.combo_cliente.set("")
        self._rellenar_cliente({})
        self.venta_libre = True

    def _guardar_cliente(self):
        nombre = self.ent_nombre.get().strip()
        correo = self.ent_correo.get().strip()
        if not nombre or not correo:
            messagebox.showwarning("Datos incompletos", "Nombre y correo son obligatorios.")
            return
        mapa = self._cols_cliente()
        if not mapa:
            messagebox.showerror("Clientes", "No se encontró la tabla de clientes.")
            return
        valores = {"nombre": nombre, "telefono": self.ent_telefono.get().strip(),
                   "nit": self.ent_nit.get().strip(), "correo": correo}
        cols = [mapa[k] for k in valores if mapa[k]]
        vals = [valores[k] for k in valores if mapa[k]]
        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute(f"INSERT INTO clientes ({', '.join(cols)}) "
                        f"VALUES ({', '.join('?' for _ in cols)})", vals)
            conn.commit()
        except Exception as e:
            conn.rollback()
            messagebox.showerror("Error", f"No se pudo guardar el cliente:\n{e}")
            return
        finally:
            conn.close()
        self._cargar_clientes()
        self.combo_cliente.set(nombre)
        messagebox.showinfo("Cliente guardado", f"'{nombre}' se guardó como cliente nuevo.")

    def _cambio_forma(self, event=None):
        if self.combo_forma.get() == "Crédito":
            self.ent_abono.config(state="normal")
        else:
            self.ent_abono.delete(0, "end")
            self.ent_abono.config(state="disabled")

    # ------------------------------------------------------------------
    # Datos
    # ------------------------------------------------------------------
    def cargar(self):
        self.cargar_lista(self.ent_buscar.get().strip())
        self.cargar_historial()

    def _al_mostrar(self, event=None):
        if event is not None and event.widget is not self:
            return
        self.cargar()
        self._cargar_clientes()
        self.after(100, self.ent_buscar.focus_set)

    def cargar_lista(self, filtro=""):
        cols = db.columnas_de("materiales")
        col_tipo = next((c for c in ("tipo", "categoria") if c in cols), None)
        expr_tipo = f"COALESCE({col_tipo}, '')" if col_tipo else "COALESCE(unidad, '')"
        conn = db.conectar()
        try:
            cur = conn.cursor()
            base = f"""SELECT id, nombre, {expr_tipo}, COALESCE(precio, 0), stock_actual
                       FROM materiales"""
            if filtro:
                cur.execute(base + " WHERE codigo_barras = ? OR nombre LIKE ? ORDER BY nombre",
                            (filtro, f"%{filtro}%"))
            else:
                cur.execute(base + " ORDER BY nombre")
            filas = cur.fetchall()
        finally:
            conn.close()

        for item in self.tree_mat.get_children():
            self.tree_mat.delete(item)
        for i, (mid, nombre, tipo, precio, stock) in enumerate(filas):
            self.tree_mat.insert("", "end", iid=str(mid),
                                 tags=("par" if i % 2 == 0 else "impar",),
                                 values=(nombre, tipo or "Otro",
                                         _precio(precio) if float(precio) > 0 else "sin precio",
                                         _cant(stock)))
        return filas

    # ------------------------------------------------------------------
    # Búsqueda y carrito
    # ------------------------------------------------------------------
    def _leer_cantidad(self):
        texto = self.spin_cantidad.get().strip().replace(",", ".")
        try:
            cantidad = float(texto)
            if cantidad <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Cantidad inválida", "Escribe una cantidad mayor a 0.")
            return None
        return cantidad

    def _buscar_enter(self, event=None):
        filtro = self.ent_buscar.get().strip()
        filas = self.cargar_lista(filtro)
        if not filtro:
            return
        if not filas:
            messagebox.showwarning(
                "No encontrado",
                f"No se encontró ningún material con '{filtro}'.\n\n"
                "Créalo primero en la pestaña Peleteria.")
            self.ent_buscar.delete(0, "end")
            self.ent_buscar.focus_set()
            return
        if len(filas) == 1:                       # un solo resultado: se agrega directo
            cantidad = self._leer_cantidad()
            if cantidad is None:
                return
            self._agregar(filas[0][0], cantidad)
            self.ent_buscar.delete(0, "end")
            self.cargar_lista()
            self.ent_buscar.focus_set()

    def agregar_seleccion(self):
        sel = self.tree_mat.selection()
        if not sel:
            messagebox.showwarning("Selecciona un producto", "Selecciona un producto de la lista.")
            return
        cantidad = self._leer_cantidad()
        if cantidad is None:
            return
        self._agregar(int(sel[0]), cantidad)

    def _agregar(self, material_id, cantidad):
        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("SELECT nombre, COALESCE(precio, 0), stock_actual FROM materiales WHERE id = ?",
                        (material_id,))
            fila = cur.fetchone()
        finally:
            conn.close()
        if not fila:
            return
        nombre, precio, stock = fila
        precio, stock = float(precio), float(stock)

        ya = sum(i["cantidad"] for i in self.carrito if i["material_id"] == material_id)
        if ya + cantidad > stock + 1e-9:
            messagebox.showerror(
                "Stock insuficiente",
                f"Solo hay {_cant(stock)} de '{nombre}' disponibles ({_cant(ya)} ya están en el carrito).")
            return

        for item in self.carrito:
            if item["material_id"] == material_id:
                item["cantidad"] += cantidad
                break
        else:
            self.carrito.append({"material_id": material_id, "nombre": nombre, "precio": precio,
                                 "precio_original": precio, "cantidad": cantidad})
        self.refrescar_carrito()

    def _total(self):
        return sum(i["precio"] * i["cantidad"] for i in self.carrito)

    def refrescar_carrito(self):
        for item in self.tree_car.get_children():
            self.tree_car.delete(item)
        for idx, item in enumerate(self.carrito):
            subtotal = item["precio"] * item["cantidad"]
            self.tree_car.insert(
                "", "end", iid=str(idx), tags=("par" if idx % 2 == 0 else "impar",),
                values=(item["nombre"], _cant(item["cantidad"]),
                        _precio(item["precio"]) if item["precio"] > 0 else "sin precio",
                        _precio(subtotal)))
        self.lbl_total.config(text=f"Total: {_precio(self._total())}")

    def quitar(self):
        sel = self.tree_car.selection()
        if sel:
            del self.carrito[int(sel[0])]
            self.refrescar_carrito()

    def vaciar(self):
        self.carrito = []
        self.refrescar_carrito()

    def _editar_precio(self, event):
        fila = self.tree_car.identify_row(event.y)
        if not fila:
            return
        item = self.carrito[int(fila)]
        texto = simpledialog.askstring(
            "Precio unitario", f"Precio unitario de '{item['nombre']}':",
            initialvalue=str(int(item["precio"])), parent=self)
        if texto is None:
            return
        nuevo = _a_numero(texto)
        if not nuevo or nuevo <= 0:
            messagebox.showerror("Precio inválido", "Escribe un precio mayor a 0.")
            return
        item["precio"] = nuevo
        self.refrescar_carrito()

    # ------------------------------------------------------------------
    # Cobrar
    # ------------------------------------------------------------------
    def cobrar(self):
        if not self.carrito:
            messagebox.showwarning("Carrito vacío", "Agrega al menos un producto antes de cobrar.")
            return
        if any(i["precio"] <= 0 for i in self.carrito):
            messagebox.showwarning(
                "Falta el precio",
                "Hay materiales sin precio. Dale doble clic en el carrito para ponerlo,\n"
                "o asígnalo en la pestaña Entrada.")
            return

        nombre = self.ent_nombre.get().strip()
        correo = self.ent_correo.get().strip()
        telefono = self.ent_telefono.get().strip()
        nit = self.ent_nit.get().strip()
        if not self.venta_libre and (not nombre or not correo):
            messagebox.showwarning(
                "Datos del cliente",
                "Escribe nombre y correo del cliente, elige un cliente guardado\n"
                "o pulsa 'Venta libre'.")
            return
        cliente = nombre or "Cliente mostrador"

        total = self._total()
        forma = self.combo_forma.get() or "Contado"
        metodo = self.combo_metodo.get() or "Efectivo"
        formato = self.combo_formato.get()

        abono = 0.0
        if forma == "Crédito":
            if self.venta_libre or not nombre:
                messagebox.showwarning("Crédito", "Una venta a crédito necesita un cliente.")
                return
            abono = _a_numero(self.ent_abono.get()) or 0.0
            if abono > total:
                messagebox.showerror("Abono inválido", "El abono no puede ser mayor al total.")
                return
        else:
            abono = total
        saldo = total - abono

        resumen = f"Cliente: {cliente}\nTotal: {_precio(total)}\nForma: {forma}\n"
        if forma == "Crédito":
            resumen += f"Abono: {_precio(abono)}   Saldo: {_precio(saldo)}\n"
        resumen += f"Pago: {metodo}\n\n¿Confirmar venta?"
        if not messagebox.askyesno("Confirmar venta", resumen):
            return

        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("""INSERT INTO ventas_peleteria
                           (fecha, total, cliente, metodo_pago, estado,
                            telefono, nit, correo, forma_pago, abono, saldo)
                           VALUES (?, ?, ?, ?, 'Activa', ?, ?, ?, ?, ?, ?)""",
                        (_ahora(), total, cliente, metodo, telefono, nit, correo,
                         forma, abono, saldo))
            venta_id = cur.lastrowid
            for item in self.carrito:
                cur.execute("""UPDATE materiales SET stock_actual = stock_actual - ?
                               WHERE id = ? AND stock_actual >= ?""",
                            (item["cantidad"], item["material_id"], item["cantidad"]))
                if cur.rowcount == 0:
                    raise ValueError(f"Stock insuficiente para '{item['nombre']}'.")
                cur.execute("""INSERT INTO venta_peleteria_detalle
                               (venta_id, material_id, nombre, cantidad, precio_unitario, subtotal)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (venta_id, item["material_id"], item["nombre"], item["cantidad"],
                             item["precio"], item["precio"] * item["cantidad"]))
            conn.commit()
        except Exception as e:
            conn.rollback()
            messagebox.showerror("Error", f"No se pudo registrar la venta:\n{e}")
            self.cargar_lista(self.ent_buscar.get().strip())
            return
        finally:
            conn.close()

        # En crédito, el abono inicial se guarda también en abonos_peleteria
        # (de ahí lee factura.py para mostrar abonado y saldo)
        if forma == "Crédito" and abono > 0:
            self._registrar_abono_inicial(venta_id, abono, metodo)

        archivo = None
        if formato != "Sin comprobante":
            archivo = self._generar_comprobante(venta_id, formato)

        msg = f"Venta de peletería #{venta_id} registrada."
        if archivo:
            msg += f"\n\nComprobante guardado en:\n{archivo}"
        messagebox.showinfo("Venta exitosa", msg)
        if archivo:
            try:
                os.startfile(archivo)
            except Exception:
                pass

        self.vaciar()
        self._venta_libre()
        self.venta_libre = False
        self.combo_forma.set("Contado")
        self._cambio_forma()
        self.combo_metodo.set("Efectivo")
        self.cargar()
        self._refrescar_app()

    def _registrar_abono_inicial(self, venta_id, abono, metodo):
        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("""INSERT INTO abonos_peleteria (venta_id, fecha, monto, nota, metodo_pago)
                           VALUES (?, ?, ?, ?, ?)""",
                        (venta_id, _ahora(), abono, "Abono inicial", metodo))
            conn.commit()
        except Exception as e:
            conn.rollback()
            messagebox.showwarning(
                "Abono inicial",
                f"La venta se guardó, pero no se pudo registrar el abono inicial:\n{e}")
        finally:
            conn.close()

    def _generar_comprobante(self, venta_id, formato):
        """Genera la factura PDF (logo y colores) o el ticket POS con factura.py.
        Devuelve la ruta del archivo, o None si falló."""
        try:
            return factura.generar_factura(venta_id, formato, tipo="peleteria")
        except Exception as e:
            messagebox.showwarning(
                "Comprobante",
                f"La venta se guardó, pero no se pudo generar el comprobante:\n{e}")
            return None

    # ------------------------------------------------------------------
    # Historial y anulación (ventana aparte)
    # ------------------------------------------------------------------
    def abrir_historial(self):
        if self._win_hist is not None and self._win_hist.winfo_exists():
            self._win_hist.lift()
            return
        win = tk.Toplevel(self)
        win.title("Ventas de peletería")
        win.geometry("820x380")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)
        self._win_hist = win
        self.lbl_hoy = ttk.Label(win, text="Vendido hoy: $0", style="Subtitulo.TLabel")
        self.lbl_hoy.grid(row=0, column=0, sticky="w", padx=8, pady=(8, 0))
        self.tree_hist = _crear_tree(win, [
            ("id", "Venta #", 70, "center"),
            ("fecha", "Fecha", 150, "center"),
            ("cliente", "Cliente", 200, "w"),
            ("total", "Total", 100, "center"),
            ("metodo", "Método", 110, "center"),
            ("estado", "Estado", 90, "center"),
        ])
        self.tree_hist.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        ttk.Button(win, text="↩ Anular venta", command=self.anular_venta).grid(
            row=1, column=1, padx=10, pady=6, sticky="n")
        self.cargar_historial()

    def cargar_historial(self):
        if self.tree_hist is None or self._win_hist is None or not self._win_hist.winfo_exists():
            return
        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT id, fecha, COALESCE(cliente, ''), total, COALESCE(metodo_pago, ''),
                                  COALESCE(estado, 'Activa')
                           FROM ventas_peleteria ORDER BY id DESC LIMIT 100""")
            filas = cur.fetchall()
            hoy = datetime.now().strftime("%Y-%m-%d")
            cur.execute("""SELECT COALESCE(SUM(total), 0) FROM ventas_peleteria
                           WHERE fecha LIKE ? AND COALESCE(estado, 'Activa') = 'Activa'""", (f"{hoy}%",))
            total_hoy = cur.fetchone()[0]
        finally:
            conn.close()

        for item in self.tree_hist.get_children():
            self.tree_hist.delete(item)
        for i, (vid, fecha, cliente, total, metodo, estado) in enumerate(filas):
            tags = ("anulada",) if estado != "Activa" else (("par" if i % 2 == 0 else "impar"),)
            self.tree_hist.insert("", "end", iid=str(vid), tags=tags,
                                  values=(vid, fecha, cliente, _precio(total), metodo, estado))
        self.lbl_hoy.config(text=f"Vendido hoy: {_precio(total_hoy)}")

    def anular_venta(self):
        sel = self.tree_hist.selection()
        if not sel:
            messagebox.showwarning("Seleccionar", "Selecciona una venta para anular.")
            return
        venta_id = int(sel[0])

        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("SELECT total, COALESCE(estado, 'Activa') FROM ventas_peleteria WHERE id = ?",
                        (venta_id,))
            fila = cur.fetchone()
        finally:
            conn.close()
        if not fila:
            return
        total, estado = fila
        if estado != "Activa":
            messagebox.showinfo("Venta ya anulada", f"La venta #{venta_id} ya está anulada.")
            return
        if not messagebox.askyesno(
                "Anular venta",
                f"¿Anular la venta #{venta_id} por {_precio(total)}?\n\n"
                "Los materiales regresan al stock."):
            return
        if not seguridad.pedir_clave(self.app, "anular la venta de peletería"):
            return

        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("SELECT material_id, cantidad FROM venta_peleteria_detalle WHERE venta_id = ?",
                        (venta_id,))
            for material_id, cantidad in cur.fetchall():
                cur.execute("UPDATE materiales SET stock_actual = stock_actual + ? WHERE id = ?",
                            (float(cantidad), material_id))
            cur.execute("UPDATE ventas_peleteria SET estado = 'Anulada', motivo = ? WHERE id = ?",
                        ("Anulada desde la caja de peletería", venta_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            messagebox.showerror("Error", f"No se pudo anular la venta:\n{e}")
            return
        finally:
            conn.close()

        self.cargar()
        self._refrescar_app()

    def _refrescar_app(self):
        """Actualiza las otras pestañas para que vean el stock nuevo."""
        try:
            self.app.cargar_materiales()
        except Exception:
            pass
        try:
            self.app.tab_entradas.cargar()
        except Exception:
            pass