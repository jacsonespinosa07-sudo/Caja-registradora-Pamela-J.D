"""
Panel de historial de ventas de peletería (sub-pestaña dentro de Historial).
Misma barra que el historial de zapatería: filtro por fecha, buscar, anular y ticket.
"""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import database as db
import seguridad

try:
    from caja_peleteria import asegurar_tablas
except Exception:
    asegurar_tablas = None

COLOR_FILA_ALT = "#fff8f6"
COLOR_BLANCO = "#ffffff"
COLOR_ANULADA = "#a05a5a"


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


class PanelHistorialPeleteria(ttk.Frame):
    def __init__(self, parent, app, abrir_calendario=None):
        """abrir_calendario: función que recibe un Entry y abre el calendario."""
        super().__init__(parent)
        self.app = app
        self._abrir_calendario = abrir_calendario
        if asegurar_tablas:
            try:
                asegurar_tablas()
            except Exception:
                pass
        self._construir()
        self.cargar()
        self.bind("<Visibility>", lambda e: self.cargar() if e.widget is self else None)

    def _construir(self):
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew", padx=6, pady=6)

        ttk.Label(top, text="Filtrar por fecha:").pack(side="left", padx=4)
        self.ent_fecha = ttk.Entry(top, width=12)
        self.ent_fecha.pack(side="left", padx=4)
        self.ent_fecha.bind("<Return>", lambda e: self.cargar())
        if self._abrir_calendario:
            ttk.Button(top, text="📅", width=3,
                       command=lambda: self._abrir_calendario(self.ent_fecha)).pack(side="left")
        ttk.Button(top, text="Buscar", command=self.cargar).pack(side="left", padx=6)
        ttk.Button(top, text="Ver todas", command=self._ver_todas).pack(side="left")

        ttk.Button(top, text="🧾 Ticket", command=self.ver_ticket).pack(side="right", padx=6)
        ttk.Button(top, text="↩ Anular / devolver", command=self.anular).pack(side="right", padx=6)

        columnas = [("id", "Venta #", 70), ("fecha", "Fecha", 150), ("cliente", "Cliente", 200),
                    ("total", "Total", 100), ("estado", "Estado", 90), ("motivo", "Motivo", 220)]
        self.tree = ttk.Treeview(self, columns=[c[0] for c in columnas],
                                 show="headings", selectmode="browse")
        for cid, txt, w in columnas:
            self.tree.heading(cid, text=txt)
            self.tree.column(cid, width=w, anchor="w" if cid in ("cliente", "motivo") else "center")
        self.tree.tag_configure("par", background=COLOR_FILA_ALT)
        self.tree.tag_configure("impar", background=COLOR_BLANCO)
        self.tree.tag_configure("anulada", foreground=COLOR_ANULADA)
        self.tree.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)

    def _ver_todas(self):
        self.ent_fecha.delete(0, "end")
        self.cargar()

    def cargar(self):
        filtro = self.ent_fecha.get().strip()
        conn = db.conectar()
        try:
            cur = conn.cursor()
            sql = """SELECT id, fecha, COALESCE(cliente, ''), total,
                            COALESCE(estado, 'Activa'), COALESCE(motivo, '')
                     FROM ventas_peleteria"""
            if filtro:
                cur.execute(sql + " WHERE fecha LIKE ? ORDER BY id DESC", (f"{filtro}%",))
            else:
                cur.execute(sql + " ORDER BY id DESC")
            filas = cur.fetchall()
        finally:
            conn.close()

        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, (vid, fecha, cliente, total, estado, motivo) in enumerate(filas):
            tags = ("anulada",) if estado != "Activa" else (("par" if i % 2 == 0 else "impar"),)
            self.tree.insert("", "end", iid=str(vid), tags=tags,
                             values=(vid, fecha, cliente, _precio(total), estado, motivo))

    # ------------------------------------------------------------------
    def _venta_seleccionada(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Seleccionar", "Selecciona una venta de la lista.")
            return None
        return int(sel[0])

    def anular(self):
        venta_id = self._venta_seleccionada()
        if venta_id is None:
            return
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
        motivo = simpledialog.askstring("Motivo", "Motivo de la anulación (opcional):", parent=self)
        if motivo is None:
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
                        (motivo.strip() or "Anulada desde el historial", venta_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            messagebox.showerror("Error", f"No se pudo anular la venta:\n{e}")
            return
        finally:
            conn.close()

        self.cargar()
        for nombre in ("cargar_materiales",):
            try:
                getattr(self.app, nombre)()
            except Exception:
                pass
        try:
            self.app.tab_entradas.cargar()
        except Exception:
            pass

    def ver_ticket(self):
        venta_id = self._venta_seleccionada()
        if venta_id is None:
            return
        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT fecha, COALESCE(cliente, ''), total, COALESCE(metodo_pago, ''),
                                  COALESCE(estado, 'Activa')
                           FROM ventas_peleteria WHERE id = ?""", (venta_id,))
            cab = cur.fetchone()
            cur.execute("""SELECT nombre, cantidad, precio_unitario, subtotal
                           FROM venta_peleteria_detalle WHERE venta_id = ?""", (venta_id,))
            det = cur.fetchall()
        finally:
            conn.close()
        if not cab:
            return
        fecha, cliente, total, metodo, estado = cab

        l = ["Pamela J.D - Peletería", f"Venta #{venta_id}  ({estado})", fecha,
             f"Cliente: {cliente}", "-" * 36]
        for nombre, cant, pu, sub in det:
            l.append(str(nombre))
            l.append(f"   {_cant(cant)} x {_precio(pu)} = {_precio(sub)}")
        l += ["-" * 36, f"TOTAL: {_precio(total)}", f"Pago: {metodo}"]
        texto = "\n".join(l)

        win = tk.Toplevel(self)
        win.title(f"Ticket venta #{venta_id}")
        txt = tk.Text(win, width=40, height=min(30, len(l) + 2), font=("Consolas", 10))
        txt.insert("1.0", texto)
        txt.config(state="disabled")
        txt.pack(padx=10, pady=10)

        def copiar():
            win.clipboard_clear()
            win.clipboard_append(texto)

        ttk.Button(win, text="Copiar", command=copiar).pack(pady=(0, 10))