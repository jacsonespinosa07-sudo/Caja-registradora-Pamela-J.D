"""
Extras de la Caja Registradora (Pamela J.D):
  - Métodos de pago (efectivo, tarjeta, transferencia)
  - Cierre de caja (arqueo diario) con gastos y retiros
  - Reportes (ventas por día, más vendidos, por cobrar, stock bajo)
  - Anulación / devolución de ventas (sin borrarlas)

Las tablas las crea database.py. Funciona con SQLite y con MySQL.
"""
import re
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime

import database as db
import seguridad

COLOR_FONDO = "#fdf2f0"
COLOR_HEADER = "#f8c3bd"
COLOR_FILA_ALT = "#fff8f6"
COLOR_BLANCO = "#ffffff"

METODOS_PAGO = ["Efectivo", "Tarjeta", "Transferencia"]
STOCK_BAJO = 3  # de este número hacia abajo el producto sale marcado con ⚠


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _hoy():
    return datetime.now().strftime("%Y-%m-%d")


def _ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _hora():
    return datetime.now().strftime("%H:%M:%S")


def _fmt(valor):
    return f"${valor:,.0f}"


def _a_numero(texto):
    digitos = re.sub(r"[^\d]", "", texto or "")
    return float(digitos) if digitos else None


def _fecha_valida(texto):
    try:
        datetime.strptime(texto, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _crear_tree(parent, columnas, alto=None, selectmode="browse"):
    tree = ttk.Treeview(parent, columns=[c[0] for c in columnas],
                        show="headings", selectmode=selectmode,
                        **({"height": alto} if alto else {}))
    for cid, txt, ancho, anchor in columnas:
        tree.heading(cid, text=txt)
        tree.column(cid, width=ancho, anchor=anchor)
    tree.tag_configure("par", background=COLOR_FILA_ALT)
    tree.tag_configure("impar", background=COLOR_BLANCO)
    return tree


def _llenar(tree, filas):
    for item in tree.get_children():
        tree.delete(item)
    for i, valores in enumerate(filas):
        tree.insert("", "end", tags=("par" if i % 2 == 0 else "impar",), values=valores)


# ---------------------------------------------------------------------------
# Consultas (separadas de la interfaz)
# ---------------------------------------------------------------------------
def resumen_dia(fecha):
    """Todo lo que entró y salió de la caja en un día (AAAA-MM-DD)."""
    like = f"{fecha}%"
    conn = db.conectar()
    try:
        cur = conn.cursor()
        cur.execute("SELECT monto_inicial FROM caja_aperturas WHERE fecha = ?", (fecha,))
        fila = cur.fetchone()
        apertura = fila[0] if fila else None

        cur.execute("""SELECT COALESCE(metodo_pago, 'Efectivo'), COALESCE(SUM(total), 0)
                       FROM ventas
                       WHERE fecha LIKE ? AND COALESCE(forma_pago, 'Contado') = 'Contado'
                         AND COALESCE(estado, 'Activa') = 'Activa'
                       GROUP BY COALESCE(metodo_pago, 'Efectivo')""", (like,))
        ventas = dict(cur.fetchall())

        cur.execute("""SELECT COALESCE(a.metodo_pago, 'Efectivo'), COALESCE(SUM(a.monto), 0)
                       FROM abonos a JOIN ventas v ON v.id = a.venta_id
                       WHERE a.fecha LIKE ? AND COALESCE(v.estado, 'Activa') = 'Activa'
                       GROUP BY COALESCE(a.metodo_pago, 'Efectivo')""", (like,))
        abonos = dict(cur.fetchall())

        cur.execute("""SELECT COALESCE(SUM(total), 0) FROM ventas
                       WHERE fecha LIKE ? AND forma_pago = 'Crédito'
                         AND COALESCE(estado, 'Activa') = 'Activa'""", (like,))
        credito = cur.fetchone()[0]

        cur.execute("""SELECT tipo, COALESCE(SUM(monto), 0) FROM caja_movimientos
                       WHERE fecha = ? GROUP BY tipo""", (fecha,))
        movs = dict(cur.fetchall())

        cur.execute("""SELECT COUNT(*), COALESCE(SUM(total), 0) FROM ventas
                       WHERE fecha_anulacion LIKE ? AND COALESCE(estado, 'Activa') != 'Activa'""",
                    (like,))
        n_anul, total_anul = cur.fetchone()
    finally:
        conn.close()

    gastos = movs.get("Gasto", 0)
    retiros = movs.get("Retiro", 0)
    esperado = ((apertura or 0) + ventas.get("Efectivo", 0) + abonos.get("Efectivo", 0)
                - gastos - retiros)
    return {
        "apertura": apertura, "ventas": ventas, "abonos": abonos, "credito": credito,
        "gastos": gastos, "retiros": retiros, "esperado": esperado,
        "total_vendido": sum(ventas.values()) + credito,
        "n_anuladas": n_anul, "total_anuladas": total_anul,
    }


def datos_reporte(desde, hasta):
    """Datos para la pestaña de reportes entre dos fechas (incluidas)."""
    conn = db.conectar()
    try:
        cur = conn.cursor()
        activa = "COALESCE(estado, 'Activa') = 'Activa'"

        cur.execute(f"""SELECT SUBSTR(fecha, 1, 10) AS d, COUNT(*), SUM(total) FROM ventas
                        WHERE SUBSTR(fecha, 1, 10) BETWEEN ? AND ? AND {activa}
                        GROUP BY SUBSTR(fecha, 1, 10) ORDER BY d DESC""", (desde, hasta))
        por_dia = cur.fetchall()

        cur.execute("""SELECT d.nombre_producto, SUM(d.cantidad), SUM(d.subtotal)
                       FROM venta_detalle d JOIN ventas v ON v.id = d.venta_id
                       WHERE SUBSTR(v.fecha, 1, 10) BETWEEN ? AND ?
                         AND COALESCE(v.estado, 'Activa') = 'Activa'
                       GROUP BY d.nombre_producto
                       ORDER BY SUM(d.cantidad) DESC, SUM(d.subtotal) DESC LIMIT 30""",
                    (desde, hasta))
        top = cur.fetchall()

        cur.execute("""SELECT t.metodo, SUM(t.monto) FROM (
                          SELECT COALESCE(metodo_pago, 'Efectivo') AS metodo, total AS monto
                          FROM ventas
                          WHERE SUBSTR(fecha, 1, 10) BETWEEN ? AND ?
                            AND COALESCE(forma_pago, 'Contado') = 'Contado'
                            AND COALESCE(estado, 'Activa') = 'Activa'
                          UNION ALL
                          SELECT COALESCE(a.metodo_pago, 'Efectivo'), a.monto
                          FROM abonos a JOIN ventas v ON v.id = a.venta_id
                          WHERE SUBSTR(a.fecha, 1, 10) BETWEEN ? AND ?
                            AND COALESCE(v.estado, 'Activa') = 'Activa'
                       ) t GROUP BY t.metodo ORDER BY SUM(t.monto) DESC""",
                    (desde, hasta, desde, hasta))
        metodos = cur.fetchall()

        cur.execute("""SELECT COALESCE(SUM(v.total - COALESCE(
                           (SELECT SUM(a.monto) FROM abonos a WHERE a.venta_id = v.id), 0)), 0)
                       FROM ventas v
                       WHERE v.forma_pago = 'Crédito' AND COALESCE(v.estado, 'Activa') = 'Activa'""")
        por_cobrar = cur.fetchone()[0]

        cur.execute("""SELECT COUNT(*), COALESCE(SUM(total), 0) FROM ventas
                       WHERE SUBSTR(fecha, 1, 10) BETWEEN ? AND ?
                         AND COALESCE(estado, 'Activa') != 'Activa'""", (desde, hasta))
        n_anul, total_anul = cur.fetchone()

        cur.execute("""SELECT tipo, COALESCE(SUM(monto), 0) FROM caja_movimientos
                       WHERE fecha BETWEEN ? AND ? GROUP BY tipo""", (desde, hasta))
        movs = dict(cur.fetchall())

        cur.execute("SELECT nombre, stock FROM productos WHERE stock <= ? ORDER BY stock, nombre",
                    (STOCK_BAJO,))
        stock_bajo = cur.fetchall()
    finally:
        conn.close()

    return {
        "por_dia": por_dia, "top": top, "metodos": metodos, "por_cobrar": por_cobrar,
        "n_ventas": sum(f[1] for f in por_dia), "total": sum((f[2] or 0) for f in por_dia),
        "n_anuladas": n_anul, "total_anuladas": total_anul,
        "gastos": movs.get("Gasto", 0), "retiros": movs.get("Retiro", 0),
        "stock_bajo": stock_bajo,
    }


def anular_venta_db(venta_id, estado, motivo):
    """Marca la venta como 'Anulada' o 'Devuelta', devuelve los productos al
    stock y la deja en el historial (no se borra nada). Es seguro si dos cajas
    intentan anular la misma venta al mismo tiempo: solo una lo logra."""
    conn = db.conectar()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM ventas WHERE id = ?", (venta_id,))
        if not cur.fetchone():
            raise ValueError("La venta no existe.")

        # Se "reserva" la anulación primero: solo avanza si la venta seguía activa
        sets, params = ["estado = ?"], [estado]
        if db.tiene_columna("ventas", "motivo_anulacion"):
            sets.append("motivo_anulacion = ?"); params.append(motivo)
        if db.tiene_columna("ventas", "fecha_anulacion"):
            sets.append("fecha_anulacion = ?"); params.append(_ahora())
        params.append(venta_id)
        cur.execute(f"""UPDATE ventas SET {', '.join(sets)}
                        WHERE id = ? AND COALESCE(estado, 'Activa') = 'Activa'""", params)
        if cur.rowcount == 0:
            cur.execute("SELECT COALESCE(estado, 'Activa') FROM ventas WHERE id = ?", (venta_id,))
            raise ValueError(f"La venta ya está marcada como {cur.fetchone()[0]}.")

        cur.execute("SELECT producto_id, cantidad FROM venta_detalle WHERE venta_id = ?", (venta_id,))
        for producto_id, cantidad in cur.fetchall():
            cur.execute("UPDATE productos SET stock = stock + ? WHERE id = ?", (cantidad, producto_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def estado_venta(venta_id):
    conn = db.conectar()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(estado, 'Activa') FROM ventas WHERE id = ?", (venta_id,))
        fila = cur.fetchone()
    finally:
        conn.close()
    return fila[0] if fila else None


# ---------------------------------------------------------------------------
# Ventanitas de diálogo
# ---------------------------------------------------------------------------
def pedir_monto_y_metodo(parent, titulo, mensaje):
    """Pide un monto y el método de pago. Devuelve (texto_monto, metodo) o None."""
    dlg = tk.Toplevel(parent)
    dlg.title(titulo)
    dlg.configure(bg=COLOR_FONDO)
    dlg.resizable(False, False)
    dlg.transient(parent)
    resultado = {"valor": None}

    ttk.Label(dlg, text=mensaje, justify="left").grid(
        row=0, column=0, columnspan=2, padx=14, pady=(14, 8), sticky="w")
    ttk.Label(dlg, text="Monto:").grid(row=1, column=0, padx=(14, 4), pady=4, sticky="e")
    ent = ttk.Entry(dlg, width=16)
    ent.grid(row=1, column=1, padx=(0, 14), pady=4, sticky="w")
    ttk.Label(dlg, text="Método de pago:").grid(row=2, column=0, padx=(14, 4), pady=4, sticky="e")
    combo = ttk.Combobox(dlg, values=METODOS_PAGO, state="readonly", width=14)
    combo.set("Efectivo")
    combo.grid(row=2, column=1, padx=(0, 14), pady=4, sticky="w")

    def aceptar(e=None):
        resultado["valor"] = (ent.get().strip(), combo.get())
        dlg.destroy()

    botones = ttk.Frame(dlg)
    botones.grid(row=3, column=0, columnspan=2, pady=12)
    ttk.Button(botones, text="Aceptar", command=aceptar).pack(side="left", padx=6)
    ttk.Button(botones, text="Cancelar", command=dlg.destroy).pack(side="left", padx=6)
    ent.bind("<Return>", aceptar)
    dlg.bind("<Escape>", lambda e: dlg.destroy())

    dlg.wait_visibility()
    dlg.grab_set()
    ent.focus_set()
    parent.wait_window(dlg)
    return resultado["valor"]


def pedir_anulacion(parent, venta_id, cliente, total):
    """Pregunta si es anulación o devolución y el motivo. Devuelve (estado, motivo) o None."""
    dlg = tk.Toplevel(parent)
    dlg.title("Anular / devolver venta")
    dlg.configure(bg=COLOR_FONDO)
    dlg.resizable(False, False)
    dlg.transient(parent)
    resultado = {"valor": None}

    ttk.Label(
        dlg, justify="left",
        text=f"Venta #{venta_id} - {cliente}\nTotal: {_fmt(total)}\n\n"
             "Los productos vuelven al stock. La venta queda en el historial\n"
             "marcada con su motivo (no se borra)."
    ).grid(row=0, column=0, columnspan=2, padx=14, pady=(14, 8), sticky="w")

    ttk.Label(dlg, text="Tipo:").grid(row=1, column=0, padx=(14, 4), pady=4, sticky="e")
    combo = ttk.Combobox(dlg, state="readonly", width=34,
                         values=["Anulada (error al registrar)", "Devuelta (el cliente devolvió)"])
    combo.set("Anulada (error al registrar)")
    combo.grid(row=1, column=1, padx=(0, 14), pady=4, sticky="w")

    ttk.Label(dlg, text="Motivo *:").grid(row=2, column=0, padx=(14, 4), pady=4, sticky="e")
    ent = ttk.Entry(dlg, width=37)
    ent.grid(row=2, column=1, padx=(0, 14), pady=4, sticky="w")

    def aceptar(e=None):
        motivo = ent.get().strip()
        if not motivo:
            messagebox.showwarning("Falta el motivo", "Escribe el motivo.", parent=dlg)
            ent.focus_set()
            return
        estado = "Anulada" if combo.get().startswith("Anulada") else "Devuelta"
        resultado["valor"] = (estado, motivo)
        dlg.destroy()

    botones = ttk.Frame(dlg)
    botones.grid(row=3, column=0, columnspan=2, pady=12)
    ttk.Button(botones, text="Continuar", command=aceptar).pack(side="left", padx=6)
    ttk.Button(botones, text="Cancelar", command=dlg.destroy).pack(side="left", padx=6)
    ent.bind("<Return>", aceptar)
    dlg.bind("<Escape>", lambda e: dlg.destroy())

    dlg.wait_visibility()
    dlg.grab_set()
    ent.focus_set()
    parent.wait_window(dlg)
    return resultado["valor"]


# ---------------------------------------------------------------------------
# Pestaña: Cierre de caja
# ---------------------------------------------------------------------------
class TabCierreCaja(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._construir()
        self.cargar()
        self.bind("<Map>", self._al_mostrar)

    def _al_mostrar(self, event=None):
        if event is not None and event.widget is not self:
            return
        self.cargar()

    def _construir(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=2)
        self.rowconfigure(3, weight=1)

        # ---- Barra superior: fecha + apertura ----
        top = ttk.LabelFrame(self, text="💰 Caja del día")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 0))
        ttk.Label(top, text="Fecha:").pack(side="left", padx=(8, 4), pady=8)
        self.ent_fecha = ttk.Entry(top, width=11)
        self.ent_fecha.insert(0, _hoy())
        self.ent_fecha.pack(side="left")
        self.ent_fecha.bind("<Return>", lambda e: self.cargar())
        ttk.Button(top, text="📅", width=3,
                   command=lambda: self.app.abrir_calendario(self.ent_fecha)).pack(side="left", padx=(2, 6))
        ttk.Button(top, text="Ver", command=self.cargar).pack(side="left")
        ttk.Button(top, text="Hoy", command=self._ir_hoy).pack(side="left", padx=4)
        self.lbl_estado = ttk.Label(top, text="", style="Subtitulo.TLabel")
        self.lbl_estado.pack(side="left", padx=16)
        ttk.Button(top, text="🔓 Abrir caja / cambiar efectivo inicial",
                   command=self.abrir_caja).pack(side="right", padx=8)

        # ---- Resumen (izquierda) ----
        izq = ttk.LabelFrame(self, text="Resumen del día")
        izq.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        izq.rowconfigure(0, weight=1)
        izq.columnconfigure(0, weight=1)
        self.tree_res = _crear_tree(izq, [
            ("concepto", "Concepto", 280, "w"),
            ("monto", "Monto", 120, "e"),
        ], selectmode="none")
        self.tree_res.tag_configure("total", background=COLOR_HEADER, font=("Segoe UI", 10, "bold"))
        self.tree_res.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        # ---- Gastos y retiros (derecha) ----
        der = ttk.LabelFrame(self, text="Gastos y retiros de efectivo")
        der.grid(row=1, column=1, sticky="nsew", padx=6, pady=6)
        der.rowconfigure(1, weight=1)
        der.columnconfigure(0, weight=1)

        form = ttk.Frame(der)
        form.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 0))
        self.combo_mov_tipo = ttk.Combobox(form, values=["Gasto", "Retiro"], state="readonly", width=8)
        self.combo_mov_tipo.set("Gasto")
        self.combo_mov_tipo.pack(side="left")
        ttk.Label(form, text="Monto:").pack(side="left", padx=(8, 2))
        self.ent_mov_monto = ttk.Entry(form, width=10)
        self.ent_mov_monto.pack(side="left")
        ttk.Label(form, text="Concepto:").pack(side="left", padx=(8, 2))
        self.ent_mov_concepto = ttk.Entry(form)
        self.ent_mov_concepto.pack(side="left", fill="x", expand=True)
        self.ent_mov_concepto.bind("<Return>", lambda e: self.registrar_movimiento())
        ttk.Button(form, text="➕ Registrar", command=self.registrar_movimiento).pack(side="left", padx=(8, 0))

        self.tree_mov = _crear_tree(der, [
            ("hora", "Hora", 70, "center"),
            ("tipo", "Tipo", 70, "center"),
            ("monto", "Monto", 90, "e"),
            ("concepto", "Concepto", 200, "w"),
        ])
        self.tree_mov.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        ttk.Button(der, text="🗑 Eliminar", command=self.eliminar_movimiento).grid(
            row=1, column=1, padx=(0, 8), pady=6, sticky="n")

        # ---- Cerrar caja ----
        cierre = ttk.LabelFrame(self, text="Cerrar caja (cuenta el efectivo y escríbelo aquí)")
        cierre.grid(row=2, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 6))
        ttk.Label(cierre, text="Efectivo contado:").pack(side="left", padx=(8, 4), pady=8)
        self.ent_contado = ttk.Entry(cierre, width=14)
        self.ent_contado.pack(side="left")
        ttk.Label(cierre, text="Nota:").pack(side="left", padx=(12, 4))
        self.ent_nota_cierre = ttk.Entry(cierre)
        self.ent_nota_cierre.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(cierre, text="🔒 Cerrar caja", command=self.cerrar_caja).pack(side="right", padx=8, pady=6)

        # ---- Cierres anteriores ----
        hist = ttk.LabelFrame(self, text="Cierres anteriores")
        hist.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=6, pady=(0, 6))
        hist.rowconfigure(0, weight=1)
        hist.columnconfigure(0, weight=1)
        self.tree_cierres = _crear_tree(hist, [
            ("fecha", "Fecha", 100, "center"),
            ("esperado", "Debía haber", 110, "e"),
            ("contado", "Se contó", 110, "e"),
            ("dif", "Diferencia", 110, "e"),
            ("nota", "Nota", 300, "w"),
        ], alto=4)
        self.tree_cierres.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

    # ------------------------------------------------------------------
    def _fecha(self):
        f = self.ent_fecha.get().strip()
        if not _fecha_valida(f):
            messagebox.showerror("Fecha inválida",
                                 "Escribe la fecha como AAAA-MM-DD, por ejemplo 2026-10-05.")
            return None
        return f

    def _ir_hoy(self):
        self.ent_fecha.delete(0, "end")
        self.ent_fecha.insert(0, _hoy())
        self.cargar()

    def cargar(self):
        fecha = self._fecha()
        if not fecha:
            return
        r = resumen_dia(fecha)

        if r["apertura"] is None:
            self.lbl_estado.config(text="⚠ Caja sin abrir (no hay efectivo inicial)")
        else:
            self.lbl_estado.config(text=f"Efectivo inicial: {_fmt(r['apertura'])}")

        otros = [m for m in METODOS_PAGO if m != "Efectivo"]
        otros += sorted(m for m in (set(r["ventas"]) | set(r["abonos"]))
                        if m != "Efectivo" and m not in otros)
        filas = [
            ("Efectivo inicial (apertura)",
             "Sin abrir" if r["apertura"] is None else _fmt(r["apertura"]), None),
            ("+ Ventas de contado en efectivo", _fmt(r["ventas"].get("Efectivo", 0)), None),
            ("+ Abonos de crédito en efectivo", _fmt(r["abonos"].get("Efectivo", 0)), None),
            ("− Gastos", _fmt(r["gastos"]), None),
            ("− Retiros", _fmt(r["retiros"]), None),
            ("= EFECTIVO QUE DEBE HABER", _fmt(r["esperado"]), "total"),
            ("", "", None),
        ] + [
            (f"{m} (ventas + abonos)", _fmt(r["ventas"].get(m, 0) + r["abonos"].get(m, 0)), None)
            for m in otros
        ] + [
            ("Ventas a crédito del día (total)", _fmt(r["credito"]), None),
            ("TOTAL VENDIDO (contado + crédito)", _fmt(r["total_vendido"]), "total"),
            ("Ventas anuladas/devueltas ese día",
             f"{r['n_anuladas']} ({_fmt(r['total_anuladas'])})", None),
        ]
        for item in self.tree_res.get_children():
            self.tree_res.delete(item)
        for i, (concepto, monto, tag) in enumerate(filas):
            tags = (tag,) if tag else (("par" if i % 2 == 0 else "impar"),)
            self.tree_res.insert("", "end", tags=tags, values=(concepto, monto))

        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT id, COALESCE(hora, ''), tipo, monto, COALESCE(concepto, '')
                           FROM caja_movimientos WHERE fecha = ? ORDER BY id DESC""", (fecha,))
            movs = cur.fetchall()
            cur.execute("""SELECT fecha, efectivo_esperado, efectivo_contado, diferencia, COALESCE(nota, '')
                           FROM cierres_caja ORDER BY id DESC LIMIT 15""")
            cierres = cur.fetchall()
        finally:
            conn.close()

        for item in self.tree_mov.get_children():
            self.tree_mov.delete(item)
        for i, (mid, hora, tipo, monto, concepto) in enumerate(movs):
            self.tree_mov.insert("", "end", iid=str(mid), tags=("par" if i % 2 == 0 else "impar",),
                                 values=(hora, tipo, _fmt(monto), concepto))

        _llenar(self.tree_cierres, [
            (f, _fmt(e or 0), _fmt(c or 0),
             ("+" if (d or 0) > 0 else "") + _fmt(d or 0), n)
            for f, e, c, d, n in cierres
        ])

    # ------------------------------------------------------------------
    def abrir_caja(self):
        fecha = self._fecha()
        if not fecha:
            return
        texto = simpledialog.askstring(
            "Abrir caja",
            f"Efectivo con el que empieza la caja el {fecha}\n(si empieza en cero, escribe 0):",
            parent=self.app)
        if texto is None:
            return
        monto = _a_numero(texto)
        if monto is None:
            messagebox.showerror("Monto inválido", "Escribe un número.")
            return
        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM caja_aperturas WHERE fecha = ?", (fecha,))
            if cur.fetchone()[0]:
                cur.execute("UPDATE caja_aperturas SET monto_inicial = ? WHERE fecha = ?", (monto, fecha))
            else:
                db.insertar(cur, "caja_aperturas", {"fecha": fecha, "monto_inicial": monto, "hora": _hora()})
            conn.commit()
        finally:
            conn.close()
        self.cargar()

    def registrar_movimiento(self):
        fecha = self._fecha()
        if not fecha:
            return
        monto = _a_numero(self.ent_mov_monto.get())
        concepto = self.ent_mov_concepto.get().strip()
        if not monto or monto <= 0:
            messagebox.showerror("Monto inválido", "Escribe un monto mayor a 0.")
            self.ent_mov_monto.focus_set()
            return
        if not concepto:
            messagebox.showwarning("Falta el concepto", "Escribe en qué se gastó o para qué fue el retiro.")
            self.ent_mov_concepto.focus_set()
            return
        conn = db.conectar()
        try:
            db.insertar(conn.cursor(), "caja_movimientos", {
                "fecha": fecha, "hora": _hora(), "tipo": self.combo_mov_tipo.get(),
                "monto": monto, "concepto": concepto})
            conn.commit()
        finally:
            conn.close()
        self.ent_mov_monto.delete(0, "end")
        self.ent_mov_concepto.delete(0, "end")
        self.cargar()

    def eliminar_movimiento(self):
        sel = self.tree_mov.selection()
        if not sel:
            messagebox.showwarning("Seleccionar", "Selecciona un gasto o retiro de la lista.")
            return
        if not messagebox.askyesno("Eliminar", "¿Eliminar este movimiento de caja?"):
            return
        if not seguridad.pedir_clave(self.app, "eliminar el movimiento"):
            return
        conn = db.conectar()
        try:
            conn.execute("DELETE FROM caja_movimientos WHERE id = ?", (sel[0],))
            conn.commit()
        finally:
            conn.close()
        self.cargar()

    def cerrar_caja(self):
        fecha = self._fecha()
        if not fecha:
            return
        r = resumen_dia(fecha)
        contado = _a_numero(self.ent_contado.get())
        if contado is None:
            messagebox.showerror("Falta el efectivo", "Escribe cuánto efectivo contaste en la caja.")
            self.ent_contado.focus_set()
            return
        if r["apertura"] is None and not messagebox.askyesno(
                "Caja sin abrir",
                "Este día no tiene efectivo inicial registrado (se toma como $0).\n\n¿Cerrar de todas formas?"):
            return

        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM cierres_caja WHERE fecha = ?", (fecha,))
            ya_cerrada = cur.fetchone()[0] > 0
        finally:
            conn.close()
        if ya_cerrada and not messagebox.askyesno(
                "Ya hay un cierre", f"El {fecha} ya tiene un cierre registrado.\n\n¿Registrar otro?"):
            return

        diferencia = contado - r["esperado"]
        if not messagebox.askyesno(
                "Confirmar cierre",
                f"Debía haber: {_fmt(r['esperado'])}\nSe contó:    {_fmt(contado)}\n"
                f"Diferencia:  {_fmt(diferencia)}\n\n¿Cerrar la caja?"):
            return

        conn = db.conectar()
        try:
            db.insertar(conn.cursor(), "cierres_caja", {
                "fecha": fecha, "fecha_cierre": _ahora(), "efectivo_esperado": r["esperado"],
                "efectivo_contado": contado, "diferencia": diferencia,
                "nota": self.ent_nota_cierre.get().strip()})
            conn.commit()
        finally:
            conn.close()

        if abs(diferencia) < 0.5:
            messagebox.showinfo("Caja cerrada", "La caja cuadra perfecto. ✔")
        elif diferencia > 0:
            messagebox.showinfo("Caja cerrada", f"Caja cerrada con un SOBRANTE de {_fmt(diferencia)}.")
        else:
            messagebox.showwarning("Caja cerrada", f"Caja cerrada con un FALTANTE de {_fmt(-diferencia)}.")
        self.ent_contado.delete(0, "end")
        self.ent_nota_cierre.delete(0, "end")
        self.cargar()


# ---------------------------------------------------------------------------
# Pestaña: Reportes
# ---------------------------------------------------------------------------
class TabReportes(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._construir()
        self.cargar()
        self.bind("<Map>", self._al_mostrar)

    def _al_mostrar(self, event=None):
        if event is not None and event.widget is not self:
            return
        self.cargar()

    def _construir(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(3, weight=1)

        top = ttk.LabelFrame(self, text="📈 Reportes")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 0))
        ttk.Label(top, text="Desde:").pack(side="left", padx=(8, 4), pady=8)
        self.ent_desde = ttk.Entry(top, width=11)
        self.ent_desde.pack(side="left")
        ttk.Button(top, text="📅", width=3,
                   command=lambda: self.app.abrir_calendario(self.ent_desde)).pack(side="left", padx=(2, 10))
        ttk.Label(top, text="Hasta:").pack(side="left", padx=(0, 4))
        self.ent_hasta = ttk.Entry(top, width=11)
        self.ent_hasta.pack(side="left")
        ttk.Button(top, text="📅", width=3,
                   command=lambda: self.app.abrir_calendario(self.ent_hasta)).pack(side="left", padx=(2, 10))
        for e in (self.ent_desde, self.ent_hasta):
            e.bind("<Return>", lambda ev: self.cargar())
        ttk.Button(top, text="Buscar", command=self.cargar).pack(side="left", padx=4)
        ttk.Button(top, text="Hoy", command=self._hoy).pack(side="left", padx=4)
        ttk.Button(top, text="Este mes", command=self._este_mes).pack(side="left", padx=4)
        self._este_mes(recargar=False)

        self.lbl_resumen = ttk.Label(self, text="", style="Subtitulo.TLabel", wraplength=900, justify="left")
        self.lbl_resumen.grid(row=1, column=0, columnspan=2, sticky="w", padx=10, pady=6)

        def caja(texto, fila, col, columnas):
            lf = ttk.LabelFrame(self, text=texto)
            lf.grid(row=fila, column=col, sticky="nsew", padx=6, pady=6)
            lf.rowconfigure(0, weight=1)
            lf.columnconfigure(0, weight=1)
            tree = _crear_tree(lf, columnas)
            tree.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
            return tree

        self.tree_dia = caja("Ventas por día", 2, 0, [
            ("fecha", "Fecha", 100, "center"), ("n", "Ventas", 70, "center"), ("total", "Total", 110, "e")])
        self.tree_top = caja("Productos más vendidos", 2, 1, [
            ("prod", "Producto", 220, "w"), ("cant", "Unidades", 80, "center"), ("total", "Total", 110, "e")])
        self.tree_metodos = caja("Dinero recibido por método de pago", 3, 0, [
            ("metodo", "Método", 160, "w"), ("total", "Total", 120, "e")])
        self.tree_bajo = caja(f"⚠ Stock bajo (de {STOCK_BAJO} unidades o menos)", 3, 1, [
            ("prod", "Producto", 240, "w"), ("stock", "Stock", 80, "center")])

    def _hoy(self):
        hoy = _hoy()
        self.ent_desde.delete(0, "end"); self.ent_desde.insert(0, hoy)
        self.ent_hasta.delete(0, "end"); self.ent_hasta.insert(0, hoy)
        self.cargar()

    def _este_mes(self, recargar=True):
        hoy = datetime.now()
        self.ent_desde.delete(0, "end"); self.ent_desde.insert(0, hoy.strftime("%Y-%m-01"))
        self.ent_hasta.delete(0, "end"); self.ent_hasta.insert(0, hoy.strftime("%Y-%m-%d"))
        if recargar:
            self.cargar()

    def cargar(self):
        desde = self.ent_desde.get().strip()
        hasta = self.ent_hasta.get().strip()
        if not (_fecha_valida(desde) and _fecha_valida(hasta)):
            messagebox.showerror("Fecha inválida", "Escribe las fechas como AAAA-MM-DD.")
            return
        if desde > hasta:
            messagebox.showerror("Fechas al revés", "La fecha 'Desde' no puede ser después de 'Hasta'.")
            return

        d = datos_reporte(desde, hasta)
        self.lbl_resumen.config(text=(
            f"Vendido: {_fmt(d['total'])} en {d['n_ventas']} ventas   |   "
            f"Anuladas/devueltas: {d['n_anuladas']} ({_fmt(d['total_anuladas'])})   |   "
            f"Gastos: {_fmt(d['gastos'])}   |   Retiros: {_fmt(d['retiros'])}   |   "
            f"Por cobrar (crédito, total): {_fmt(d['por_cobrar'])}"))

        _llenar(self.tree_dia, [(f, n, _fmt(t or 0)) for f, n, t in d["por_dia"]])
        _llenar(self.tree_top, [(p, f"{c:g}", _fmt(t or 0)) for p, c, t in d["top"]])
        _llenar(self.tree_metodos, [(m, _fmt(t or 0)) for m, t in d["metodos"]])
        _llenar(self.tree_bajo, [(p, s) for p, s in d["stock_bajo"]])