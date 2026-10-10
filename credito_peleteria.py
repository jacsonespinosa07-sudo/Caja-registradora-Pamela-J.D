"""
Pestaña Crédito (solo peletería): ventas a crédito y abonos.
Usa ventas_peleteria (forma_pago = 'Crédito') y la tabla abonos_peleteria.
"""
import tkinter as tk
from tkinter import ttk, messagebox

import database as db
import caja_peleteria
import caja_extra
from caja_extra import _a_numero, _ahora, _crear_tree, _fmt, _llenar


class PanelCreditoPeleteria(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        caja_peleteria.asegurar_tablas()
        self._construir()
        self.cargar()

    def _construir(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=2)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew", padx=6, pady=6)

        ttk.Label(top, text="Cliente:").pack(side="left", padx=4)
        self.ent_cliente = ttk.Entry(top, width=22)
        self.ent_cliente.pack(side="left", padx=4)
        self.ent_cliente.bind("<Return>", lambda e: self.cargar())

        self.var_solo_pendientes = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Solo con saldo pendiente", variable=self.var_solo_pendientes,
                        command=self.cargar).pack(side="left", padx=10)
        ttk.Button(top, text="Buscar", command=self.cargar).pack(side="left", padx=4)

        self.lbl_por_cobrar = ttk.Label(top, text="Por cobrar: $0", style="Subtitulo.TLabel")
        self.lbl_por_cobrar.pack(side="right", padx=6)

        self.tree = _crear_tree(self, [
            ("id", "Venta #", 70, "center"),
            ("fecha", "Fecha", 150, "center"),
            ("cliente", "Cliente", 200, "w"),
            ("telefono", "Teléfono", 110, "center"),
            ("total", "Total", 100, "center"),
            ("abonado", "Abonado", 100, "center"),
            ("saldo", "Saldo", 100, "center"),
        ])
        self.tree.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.tree.bind("<<TreeviewSelect>>", self.cargar_abonos)

        abajo = ttk.LabelFrame(self, text="Abonos de la venta seleccionada")
        abajo.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))
        abajo.columnconfigure(0, weight=1)
        abajo.rowconfigure(0, weight=1)
        self.tree_abonos = _crear_tree(abajo, [
            ("fecha", "Fecha", 150, "center"),
            ("monto", "Monto", 110, "center"),
            ("metodo", "Método", 110, "center"),
            ("nota", "Nota", 200, "w"),
        ], alto=4)
        self.tree_abonos.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        ttk.Button(abajo, text="💵 Registrar abono", command=self.registrar_abono).grid(
            row=0, column=1, padx=10, pady=6, sticky="n")

    def cargar(self):
        seleccionada = self.tree.selection()
        for item in self.tree.get_children():
            self.tree.delete(item)

        filtro = self.ent_cliente.get().strip()
        solo_pendientes = self.var_solo_pendientes.get()

        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT v.id, v.fecha, COALESCE(v.cliente, ''), COALESCE(v.telefono, ''), v.total,
                       COALESCE((SELECT SUM(a.monto) FROM abonos_peleteria a
                                 WHERE a.venta_id = v.id), 0)
                FROM ventas_peleteria v
                WHERE v.forma_pago = 'Crédito'
                  AND COALESCE(v.estado, 'Activa') = 'Activa'
                  AND COALESCE(v.cliente, '') LIKE ?
                ORDER BY v.id DESC
            """, (f"%{filtro}%",))
            filas = cur.fetchall()
        finally:
            conn.close()

        por_cobrar = 0.0
        indice = 0
        for vid, fecha, cliente, tel, total, abonado in filas:
            total, abonado = float(total), float(abonado)
            saldo = total - abonado
            if solo_pendientes and saldo <= 0:
                continue
            por_cobrar += max(saldo, 0)
            self.tree.insert("", "end", iid=str(vid),
                             tags=("par" if indice % 2 == 0 else "impar",),
                             values=(vid, fecha, cliente, tel, _fmt(total),
                                     _fmt(abonado), _fmt(saldo)))
            indice += 1

        self.lbl_por_cobrar.config(text=f"Por cobrar: {_fmt(por_cobrar)}")

        if seleccionada and self.tree.exists(seleccionada[0]):
            self.tree.selection_set(seleccionada[0])
        else:
            self.cargar_abonos()

    def cargar_abonos(self, event=None):
        for item in self.tree_abonos.get_children():
            self.tree_abonos.delete(item)
        sel = self.tree.selection()
        if not sel:
            return
        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT fecha, monto, COALESCE(metodo_pago, 'Efectivo'), COALESCE(nota, '')
                           FROM abonos_peleteria WHERE venta_id = ? ORDER BY id""", (sel[0],))
            filas = cur.fetchall()
        finally:
            conn.close()
        _llenar(self.tree_abonos, [(f, _fmt(float(m)), met, n) for f, m, met, n in filas])

    def registrar_abono(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Seleccionar", "Selecciona una venta a crédito de la lista.")
            return
        venta_id = int(sel[0])

        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("SELECT total, COALESCE(cliente, '') FROM ventas_peleteria WHERE id = ?",
                        (venta_id,))
            fila = cur.fetchone()
            cur.execute("SELECT COALESCE(SUM(monto), 0) FROM abonos_peleteria WHERE venta_id = ?",
                        (venta_id,))
            abonado = float(cur.fetchone()[0])
        finally:
            conn.close()
        if not fila:
            return
        total, cliente = float(fila[0]), fila[1]
        saldo = total - abonado

        if saldo <= 0:
            messagebox.showinfo("Cuenta saldada", "Esta venta ya está pagada por completo.")
            return

        datos = caja_extra.pedir_monto_y_metodo(
            self.app, "Registrar abono",
            f"Cliente: {cliente}\nSaldo pendiente: {_fmt(saldo)}")
        if datos is None:
            return
        texto, metodo = datos
        monto = _a_numero(texto)
        if not monto or monto <= 0:
            messagebox.showerror("Monto inválido", "Escribe un monto mayor a 0.")
            return
        if monto > saldo + 1e-9:
            messagebox.showerror("Monto muy alto",
                                 f"El abono no puede superar el saldo pendiente ({_fmt(saldo)}).")
            return

        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("""INSERT INTO abonos_peleteria (venta_id, fecha, monto, nota, metodo_pago)
                           VALUES (?, ?, ?, ?, ?)""", (venta_id, _ahora(), monto, "Abono", metodo))
            conn.commit()
        except Exception as e:
            conn.rollback()
            messagebox.showerror("Error", f"No se pudo registrar el abono:\n{e}")
            return
        finally:
            conn.close()

        nuevo_saldo = saldo - monto
        if nuevo_saldo <= 0:
            messagebox.showinfo("Abono registrado", "Abono registrado. ¡La cuenta quedó saldada!")
        else:
            messagebox.showinfo("Abono registrado",
                                f"Abono registrado.\nNuevo saldo: {_fmt(nuevo_saldo)}")
        self.cargar()