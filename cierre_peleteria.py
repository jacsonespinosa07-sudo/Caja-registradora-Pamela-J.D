"""
Cierre de caja dividido: Zapatería y Peletería.

- TabCierreDividido: contenedor con dos sub-pestañas. Usa tu TabCierreCaja
  (de caja_extra.py) para zapatería, sin cambios.
- TabCierrePeleteria: arqueo diario de la caja de peletería. Usa tablas propias
  (peleteria_aperturas, peleteria_movimientos, peleteria_cierres), así no se
  mezcla ni toca el cierre de zapatería.
"""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import database as db
import seguridad
import caja_peleteria
from caja_extra import (METODOS_PAGO, TabCierreCaja, _a_numero, _ahora, _crear_tree,
                        _fecha_valida, _fmt, _hora, _hoy, _llenar,
                        COLOR_HEADER)


# ---------------------------------------------------------------------------
# Tablas
# ---------------------------------------------------------------------------
def asegurar_tablas_cierre():
    # Esta pestaña se crea antes que la Caja Peletería, así que se asegura
    # de que ventas_peleteria (y sus columnas) existan.
    caja_peleteria.asegurar_tablas()
    conn = db.conectar()
    try:
        cur = conn.cursor()
        id_ddl = "INT AUTO_INCREMENT PRIMARY KEY" if db.MODO == "mysql" \
            else "INTEGER PRIMARY KEY AUTOINCREMENT"
        cur.execute(f"""CREATE TABLE IF NOT EXISTS peleteria_aperturas (
                            id {id_ddl},
                            fecha VARCHAR(20) NOT NULL,
                            monto_inicial DECIMAL(12,2) NOT NULL DEFAULT 0,
                            hora VARCHAR(20))""")
        cur.execute(f"""CREATE TABLE IF NOT EXISTS peleteria_movimientos (
                            id {id_ddl},
                            fecha VARCHAR(20) NOT NULL,
                            hora VARCHAR(20),
                            tipo VARCHAR(20) NOT NULL,
                            monto DECIMAL(12,2) NOT NULL,
                            concepto VARCHAR(255))""")
        cur.execute(f"""CREATE TABLE IF NOT EXISTS peleteria_cierres (
                            id {id_ddl},
                            fecha VARCHAR(20) NOT NULL,
                            fecha_cierre VARCHAR(50),
                            efectivo_esperado DECIMAL(12,2),
                            efectivo_contado DECIMAL(12,2),
                            diferencia DECIMAL(12,2),
                            nota VARCHAR(255))""")
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Consulta del día (peletería)
# ---------------------------------------------------------------------------
def resumen_dia_peleteria(fecha):
    like = f"{fecha}%"
    conn = db.conectar()
    try:
        cur = conn.cursor()
        cur.execute("SELECT monto_inicial FROM peleteria_aperturas WHERE fecha = ?", (fecha,))
        fila = cur.fetchone()
        apertura = float(fila[0]) if fila else None

        # Ventas de contado, por método de pago
        cur.execute("""SELECT COALESCE(metodo_pago, 'Efectivo'), COALESCE(SUM(total), 0)
                       FROM ventas_peleteria
                       WHERE fecha LIKE ? AND COALESCE(forma_pago, 'Contado') = 'Contado'
                         AND COALESCE(estado, 'Activa') = 'Activa'
                       GROUP BY COALESCE(metodo_pago, 'Efectivo')""", (like,))
        ventas = {m: float(t) for m, t in cur.fetchall()}

        # Abono inicial de las ventas a crédito, por método de pago
        cur.execute("""SELECT COALESCE(metodo_pago, 'Efectivo'), COALESCE(SUM(abono), 0)
                       FROM ventas_peleteria
                       WHERE fecha LIKE ? AND forma_pago = 'Crédito'
                         AND COALESCE(estado, 'Activa') = 'Activa'
                       GROUP BY COALESCE(metodo_pago, 'Efectivo')""", (like,))
        abonos = {m: float(t) for m, t in cur.fetchall()}

        cur.execute("""SELECT COALESCE(SUM(total), 0) FROM ventas_peleteria
                       WHERE fecha LIKE ? AND forma_pago = 'Crédito'
                         AND COALESCE(estado, 'Activa') = 'Activa'""", (like,))
        credito = float(cur.fetchone()[0])

        cur.execute("""SELECT tipo, COALESCE(SUM(monto), 0) FROM peleteria_movimientos
                       WHERE fecha = ? GROUP BY tipo""", (fecha,))
        movs = {t: float(m) for t, m in cur.fetchall()}

        cur.execute("""SELECT COUNT(*), COALESCE(SUM(total), 0) FROM ventas_peleteria
                       WHERE fecha LIKE ? AND COALESCE(estado, 'Activa') != 'Activa'""", (like,))
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
        "n_anuladas": n_anul, "total_anuladas": float(total_anul),
    }


# ---------------------------------------------------------------------------
# Pestaña: Cierre de caja de peletería
# ---------------------------------------------------------------------------
class TabCierrePeleteria(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        asegurar_tablas_cierre()
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

        top = ttk.LabelFrame(self, text="💰 Caja del día - Peletería")
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

        cierre = ttk.LabelFrame(self, text="Cerrar caja (cuenta el efectivo y escríbelo aquí)")
        cierre.grid(row=2, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 6))
        ttk.Label(cierre, text="Efectivo contado:").pack(side="left", padx=(8, 4), pady=8)
        self.ent_contado = ttk.Entry(cierre, width=14)
        self.ent_contado.pack(side="left")
        ttk.Label(cierre, text="Nota:").pack(side="left", padx=(12, 4))
        self.ent_nota_cierre = ttk.Entry(cierre)
        self.ent_nota_cierre.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(cierre, text="🔒 Cerrar caja", command=self.cerrar_caja).pack(side="right", padx=8, pady=6)

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
        r = resumen_dia_peleteria(fecha)

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
            ("+ Abonos iniciales de crédito en efectivo", _fmt(r["abonos"].get("Efectivo", 0)), None),
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
            ("Ventas anuladas ese día",
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
                           FROM peleteria_movimientos WHERE fecha = ? ORDER BY id DESC""", (fecha,))
            movs = cur.fetchall()
            cur.execute("""SELECT fecha, efectivo_esperado, efectivo_contado, diferencia, COALESCE(nota, '')
                           FROM peleteria_cierres ORDER BY id DESC LIMIT 15""")
            cierres = cur.fetchall()
        finally:
            conn.close()

        for item in self.tree_mov.get_children():
            self.tree_mov.delete(item)
        for i, (mid, hora, tipo, monto, concepto) in enumerate(movs):
            self.tree_mov.insert("", "end", iid=str(mid), tags=("par" if i % 2 == 0 else "impar",),
                                 values=(hora, tipo, _fmt(float(monto)), concepto))

        _llenar(self.tree_cierres, [
            (f, _fmt(float(e or 0)), _fmt(float(c or 0)),
             ("+" if float(d or 0) > 0 else "") + _fmt(float(d or 0)), n)
            for f, e, c, d, n in cierres
        ])

    # ------------------------------------------------------------------
    def abrir_caja(self):
        fecha = self._fecha()
        if not fecha:
            return
        texto = simpledialog.askstring(
            "Abrir caja de peletería",
            f"Efectivo con el que empieza la caja de peletería el {fecha}\n(si empieza en cero, escribe 0):",
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
            cur.execute("SELECT COUNT(*) FROM peleteria_aperturas WHERE fecha = ?", (fecha,))
            if cur.fetchone()[0]:
                cur.execute("UPDATE peleteria_aperturas SET monto_inicial = ? WHERE fecha = ?",
                            (monto, fecha))
            else:
                cur.execute("INSERT INTO peleteria_aperturas (fecha, monto_inicial, hora) VALUES (?, ?, ?)",
                            (fecha, monto, _hora()))
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
            cur = conn.cursor()
            cur.execute("""INSERT INTO peleteria_movimientos (fecha, hora, tipo, monto, concepto)
                           VALUES (?, ?, ?, ?, ?)""",
                        (fecha, _hora(), self.combo_mov_tipo.get(), monto, concepto))
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
            cur = conn.cursor()
            cur.execute("DELETE FROM peleteria_movimientos WHERE id = ?", (sel[0],))
            conn.commit()
        finally:
            conn.close()
        self.cargar()

    def cerrar_caja(self):
        fecha = self._fecha()
        if not fecha:
            return
        r = resumen_dia_peleteria(fecha)
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
            cur.execute("SELECT COUNT(*) FROM peleteria_cierres WHERE fecha = ?", (fecha,))
            ya_cerrada = cur.fetchone()[0] > 0
        finally:
            conn.close()
        if ya_cerrada and not messagebox.askyesno(
                "Ya hay un cierre", f"El {fecha} ya tiene un cierre de peletería.\n\n¿Registrar otro?"):
            return

        diferencia = contado - r["esperado"]
        if not messagebox.askyesno(
                "Confirmar cierre",
                f"Debía haber: {_fmt(r['esperado'])}\nSe contó:    {_fmt(contado)}\n"
                f"Diferencia:  {_fmt(diferencia)}\n\n¿Cerrar la caja de peletería?"):
            return

        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("""INSERT INTO peleteria_cierres
                           (fecha, fecha_cierre, efectivo_esperado, efectivo_contado, diferencia, nota)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (fecha, _ahora(), r["esperado"], contado, diferencia,
                         self.ent_nota_cierre.get().strip()))
            conn.commit()
        finally:
            conn.close()

        if abs(diferencia) < 0.5:
            messagebox.showinfo("Caja cerrada", "La caja de peletería cuadra perfecto. ✔")
        elif diferencia > 0:
            messagebox.showinfo("Caja cerrada", f"Caja cerrada con un SOBRANTE de {_fmt(diferencia)}.")
        else:
            messagebox.showwarning("Caja cerrada", f"Caja cerrada con un FALTANTE de {_fmt(-diferencia)}.")
        self.ent_contado.delete(0, "end")
        self.ent_nota_cierre.delete(0, "end")
        self.cargar()


# ---------------------------------------------------------------------------
# Contenedor: Zapatería | Peletería
# ---------------------------------------------------------------------------
class TabCierreDividido(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        sub = ttk.Notebook(self, style="Rosa.TNotebook")
        sub.grid(row=0, column=0, sticky="nsew")
        self.zapateria = TabCierreCaja(sub, app)
        self.peleteria = TabCierrePeleteria(sub, app)
        sub.add(self.zapateria, text="👞 Zapatería")
        sub.add(self.peleteria, text="🧵 Peletería")

    def cargar(self):
        self.zapateria.cargar()
        self.peleteria.cargar()