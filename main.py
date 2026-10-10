"""
Caja Registradora - Venta de zapatos, moños,  y control de materiales.

Cómo ejecutar:
    python main.py

Base de datos: MySQL o SQLite, según config_db.json (ver database.py).
"""
import os
import re
import sys
import calendar
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime

try:
    import auto_migracion
except Exception:
    auto_migracion = None   
from historial_peleteria import PanelHistorialPeleteria
from credito_peleteria import PanelCreditoPeleteria
import cierre_peleteria
import caja_peleteria
import seguridad
import entradas
import database as db
import correo
import factura
import rutas
import caja_extra
from caja_extra import (METODOS_PAGO, STOCK_BAJO, TabCierreCaja, TabReportes,
                        anular_venta_db)

try:
    from PIL import Image, ImageTk
    PIL_DISPONIBLE = True
except ImportError:
    PIL_DISPONIBLE = False


# ---------------------------------------------------------------------------
# Paleta de colores (tomada del logo de Pamela J.D.)
# ---------------------------------------------------------------------------
NOMBRE_NEGOCIO = "Pamela J.D"
SUBTITULO_NEGOCIO = ""

COLOR_FONDO = "#fdf2f0"        # fondo general, rosa muy suave
COLOR_HEADER = "#f8c3bd"       # rosa del logo, para el encabezado
COLOR_ACCENT = "#e08787"       # rosa fuerte, botones y totales
COLOR_ACCENT_HOVER = "#c96b6b"  # rosa más oscuro, hover / presionado
COLOR_TEXTO = "#4a3636"        # marrón oscuro, combina con el negro del logo
COLOR_TEXTO_SUAVE = "#7a6363"
COLOR_BLANCO = "#ffffff"
COLOR_FILA_ALT = "#fff8f6"
COLOR_ANULADA = "#a05a5a"      # texto de ventas anuladas/devueltas
COLOR_STOCK_BAJO = "#c0392b"   # texto de productos con poco stock

LOGO_HEADER_PATH = rutas.ruta_recurso("assets", "logo_header.png")
LOGO_ICON_PATH = rutas.ruta_recurso("assets", "logo_icon.png")

# Si es True, la Caja exige el correo del comprador para poder cobrar
CORREO_OBLIGATORIO = True

# Tipos de producto que aparecen al crear/editar un producto
TIPOS_PRODUCTO = ["Zapato deportivo", "Bolichero", "Sandalia", "Moño", "Accesorio", "Otro"]

# Cada cuántos milisegundos se revisa si la otra caja guardó algo
INTERVALO_REVISION_MS = 5000


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def formato_precio(valor):
    return f"${valor:,.0f}"


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def a_numero(texto):
    """Convierte '50.000', '$50,000' o '50000' en 50000.0.
    Devuelve None si el texto no trae ningún número."""
    digitos = re.sub(r"[^\d]", "", texto or "")
    return float(digitos) if digitos else None


def configurar_filas_alternadas(tree):
    """Aplica un color de fondo suave a las filas pares para que la tabla
    sea más fácil de leer."""
    tree.tag_configure("par", background=COLOR_FILA_ALT)
    tree.tag_configure("impar", background=COLOR_BLANCO)


def tag_fila(indice):
    return "par" if indice % 2 == 0 else "impar"


# ---------------------------------------------------------------------------
# Ventana emergente de calendario (sin librerías externas) para elegir fechas
# ---------------------------------------------------------------------------
class CalendarioPopup(tk.Toplevel):
    MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
             "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    DIAS = ["Lu", "Ma", "Mi", "Ju", "Vi", "Sa", "Do"]

    def __init__(self, parent, entry_destino):
        super().__init__(parent)
        self.entry_destino = entry_destino
        self._widget_anterior = parent.focus_get()  # para devolverle el foco al cerrar
        self.title("Selecciona una fecha")
        self.resizable(False, False)
        self.configure(bg=COLOR_BLANCO)
        self.transient(parent)

        hoy = datetime.now()
        texto_actual = entry_destino.get().strip()
        try:
            hoy = datetime.strptime(texto_actual, "%Y-%m-%d")
        except ValueError:
            pass
        self.anio = hoy.year
        self.mes = hoy.month

        self._dibujar()

        self.protocol("WM_DELETE_WINDOW", self._cerrar)
        self.bind("<Escape>", lambda e: self._cerrar())

        self.grab_set()
        self.focus_set()

    def _cerrar(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        if self._widget_anterior is not None:
            try:
                self._widget_anterior.focus_set()
            except tk.TclError:
                pass

    def _dibujar(self):
        for w in self.winfo_children():
            w.destroy()

        escala = getattr(self.master, "escala", 1.0)

        def t(base):
            return max(6, round(base * escala))

        nav = tk.Frame(self, bg=COLOR_HEADER)
        nav.pack(fill="x")
        tk.Button(nav, text="◀", command=self._mes_anterior, relief="flat",
                  bg=COLOR_HEADER, activebackground=COLOR_ACCENT, bd=0, padx=8).pack(side="left")
        tk.Label(nav, text=f"{self.MESES[self.mes - 1]} {self.anio}", bg=COLOR_HEADER,
                 fg=COLOR_TEXTO, font=("Segoe UI", t(10), "bold")).pack(side="left", expand=True, fill="x")
        tk.Button(nav, text="▶", command=self._mes_siguiente, relief="flat",
                  bg=COLOR_HEADER, activebackground=COLOR_ACCENT, bd=0, padx=8).pack(side="left")

        grid = tk.Frame(self, bg=COLOR_BLANCO)
        grid.pack(padx=6, pady=6)

        for i, d in enumerate(self.DIAS):
            tk.Label(grid, text=d, width=3, bg=COLOR_BLANCO, fg=COLOR_TEXTO_SUAVE,
                     font=("Segoe UI", t(9), "bold")).grid(row=0, column=i, padx=1, pady=(0, 4))

        cal = calendar.Calendar(firstweekday=0)
        hoy = datetime.now().date()
        fila = 1
        for semana in cal.monthdayscalendar(self.anio, self.mes):
            for col, dia in enumerate(semana):
                if dia == 0:
                    tk.Label(grid, text="", width=3, bg=COLOR_BLANCO).grid(row=fila, column=col)
                else:
                    es_hoy = (dia == hoy.day and self.mes == hoy.month and self.anio == hoy.year)
                    btn = tk.Button(
                        grid, text=str(dia), width=3, relief="flat",
                        bg=COLOR_ACCENT if es_hoy else COLOR_BLANCO,
                        fg=COLOR_BLANCO if es_hoy else COLOR_TEXTO,
                        activebackground=COLOR_ACCENT_HOVER, activeforeground=COLOR_BLANCO,
                        font=("Segoe UI", t(9)),
                        command=lambda d=dia: self._elegir(d)
                    )
                    btn.grid(row=fila, column=col, padx=1, pady=1)
            fila += 1

        tk.Button(self, text="Hoy", relief="flat", bg=COLOR_FILA_ALT, fg=COLOR_TEXTO,
                  command=self._ir_hoy).pack(fill="x", padx=6, pady=(0, 6))

    def _mes_anterior(self):
        self.mes -= 1
        if self.mes == 0:
            self.mes, self.anio = 12, self.anio - 1
        self._dibujar()

    def _mes_siguiente(self):
        self.mes += 1
        if self.mes == 13:
            self.mes, self.anio = 1, self.anio + 1
        self._dibujar()

    def _ir_hoy(self):
        hoy = datetime.now()
        self.anio, self.mes = hoy.year, hoy.month
        self._dibujar()

    def _elegir(self, dia):
        fecha_txt = f"{self.anio:04d}-{self.mes:02d}-{dia:02d}"
        self.entry_destino.delete(0, "end")
        self.entry_destino.insert(0, fecha_txt)
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        try:
            self.entry_destino.focus_set()
        except tk.TclError:
            pass


# ---------------------------------------------------------------------------
# Aplicación principal
# ---------------------------------------------------------------------------
class CajaRegistradoraApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{NOMBRE_NEGOCIO} - Caja Registradora   [{db.DB_PATH}]")
        self.geometry("1050x700")
        self.minsize(950, 620)
        self.configure(bg=COLOR_FONDO)

        self.carrito = []  # lista de dicts: producto_id, nombre, precio, cantidad
        self.escala = 1.0  # nivel de zoom actual (1.0 = 100%)
        self._cliente_seleccionado_id = None  # id del cliente elegido en la Caja (None = cliente libre)
        self._clientes_disponibles = []

        self._crear_estilos()
        self._construir_encabezado()
        self._set_icono_ventana()

        notebook = ttk.Notebook(self, style="Rosa.TNotebook")
        notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.tab_caja = ttk.Frame(notebook)
        self.tab_productos = ttk.Frame(notebook)
        self.tab_materiales = ttk.Frame(notebook)
        self.tab_clientes = ttk.Frame(notebook)
        self.tab_credito = ttk.Frame(notebook)
        self.tab_historial = ttk.Frame(notebook)

        notebook.add(self.tab_caja, text="🧾 Caja")
        notebook.add(self.tab_productos, text="📦 Zapat")
        notebook.add(self.tab_materiales, text="🧵 Peleteria")

        self.tab_entradas = entradas.TabEntradaMercancia(notebook, self)
        notebook.add(self.tab_entradas, text="📥 Entrada")

        notebook.add(self.tab_clientes, text="🏢 Clientes")
        notebook.add(self.tab_credito, text="💳 Crédito Peleteria")
        notebook.add(self.tab_historial, text="📊 Historial")

        
        
        self.tab_cierre_caja = cierre_peleteria.TabCierreDividido(notebook, self)
        notebook.add(self.tab_cierre_caja, text="💰 Cierre de caja")

        self.tab_reportes = TabReportes(notebook, self)
        notebook.add(self.tab_reportes, text="📈 Reportes")

        self.tab_caja_pel = caja_peleteria.TabCajaPeleteria(notebook, self)
        notebook.add(self.tab_caja_pel, text="🧵 Caja Peletería")

        self._construir_tab_caja()
        self._construir_tab_productos()
        self._construir_tab_materiales()
        self._construir_tab_clientes()
        self._construir_tab_credito()
        self._construir_tab_historial()

        self.notebook = notebook
        notebook.bind("<<NotebookTabChanged>>", self._al_cambiar_pestana)

        # ---- Atajos de teclado para zoom ----
        for tecla in ("<Control-plus>", "<Control-equal>", "<Control-KP_Add>"):
            self.bind_all(tecla, self._zoom_in)
        for tecla in ("<Control-minus>", "<Control-KP_Subtract>"):
            self.bind_all(tecla, self._zoom_out)
        for tecla in ("<Control-0>", "<Control-KP_0>"):
            self.bind_all(tecla, self._zoom_reset)
        self.bind_all("<Control-MouseWheel>", self._zoom_rueda_mouse)

        self.refrescar_todo()
        self.after(200, lambda: self.ent_scan_codigo.focus_set())

        # ---- Revisión periódica: si la otra caja guardó algo, se actualiza la pantalla ----
        self._db_firma = self._firma_db()
        self.after(INTERVALO_REVISION_MS, self._revisar_cambios_db)

    # -----------------------------------------------------------------
    # Pestañas: cambio y actualización automática
    # -----------------------------------------------------------------
    def _al_cambiar_pestana(self, event=None):
        idx = self.notebook.index(self.notebook.select())
        if idx == 0:
            self.cargar_catalogo()
            self.after(100, lambda: self.ent_scan_codigo.focus_set())
        elif idx == 5:
            self.cargar_credito()
        elif idx == 6:
            self.cargar_historial()

    def _firma_db(self):
        """Valor que cambia cuando alguien guarda algo."""
        return db.firma_cambios()

    def _revisar_cambios_db(self):
        try:
            firma = self._firma_db()
            if firma is not None and firma != self._db_firma:
                self._db_firma = firma
                self._refrescar_pestana_visible()
        except Exception:
            pass
        finally:
            self.after(INTERVALO_REVISION_MS, self._revisar_cambios_db)

    def _recargar_conservando(self, tree, recargar):
        sel = tree.selection()
        recargar()
        if sel and tree.exists(sel[0]):
            tree.selection_set(sel[0])

    def _refrescar_pestana_visible(self):
        idx = self.notebook.index(self.notebook.select())
        if idx == 0:
            self._recargar_conservando(self.tree_catalogo, self.cargar_catalogo)
        elif idx == 5:
            self.cargar_credito()
        elif idx == 6:
            self._recargar_conservando(self.tree_hist, self.cargar_historial)
        elif idx == 7:
            self.tab_cierre_caja.cargar()
        elif idx == 8:
            self.tab_reportes.cargar()

    # -----------------------------------------------------------------
    # Zoom (Ctrl+ / Ctrl- / Ctrl+0)
    # -----------------------------------------------------------------
    ESCALA_MIN = 0.7
    ESCALA_MAX = 1.8
    ESCALA_PASO = 0.1

    def _zoom_in(self, event=None):
        self.escala = min(self.ESCALA_MAX, round(self.escala + self.ESCALA_PASO, 2))
        self._crear_estilos()

    def _zoom_out(self, event=None):
        self.escala = max(self.ESCALA_MIN, round(self.escala - self.ESCALA_PASO, 2))
        self._crear_estilos()

    def _zoom_reset(self, event=None):
        self.escala = 1.0
        self._crear_estilos()

    def _zoom_rueda_mouse(self, event):
        if event.delta > 0:
            self._zoom_in()
        else:
            self._zoom_out()

    def _t(self, tamano_base):
        return max(6, round(tamano_base * self.escala))

    def _crear_estilos(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=COLOR_FONDO)
        style.configure("TLabel", background=COLOR_FONDO, foreground=COLOR_TEXTO, font=("Segoe UI", self._t(10)))
        style.configure("TLabelframe", background=COLOR_FONDO, foreground=COLOR_TEXTO, bordercolor=COLOR_HEADER)
        style.configure("TLabelframe.Label", background=COLOR_FONDO, foreground=COLOR_ACCENT_HOVER,
                         font=("Segoe UI", self._t(10), "bold"))

        style.configure("Header.TFrame", background=COLOR_HEADER)
        style.configure("HeaderTitulo.TLabel", background=COLOR_HEADER, foreground=COLOR_TEXTO,
                         font=("Segoe UI", self._t(18), "bold"))
        style.configure("HeaderSubtitulo.TLabel", background=COLOR_HEADER, foreground=COLOR_TEXTO,
                         font=("Segoe UI", self._t(10)))

        style.configure("Rosa.TNotebook", background=COLOR_FONDO, borderwidth=0)
        style.configure("Rosa.TNotebook.Tab", background="#f4d9d5", foreground=COLOR_TEXTO,
                         font=("Segoe UI", self._t(10), "bold"), padding=(self._t(16), self._t(8)))
        style.map("Rosa.TNotebook.Tab",
                  background=[("selected", COLOR_ACCENT)],
                  foreground=[("selected", COLOR_BLANCO)])

        style.configure("TButton", background=COLOR_ACCENT, foreground=COLOR_BLANCO,
                         font=("Segoe UI", self._t(10), "bold"), padding=self._t(6), borderwidth=0)
        style.map("TButton",
                  background=[("active", COLOR_ACCENT_HOVER), ("pressed", COLOR_ACCENT_HOVER)],
                  foreground=[("disabled", "#cccccc")])

        style.configure("Treeview", rowheight=self._t(26), font=("Segoe UI", self._t(10)),
                         background=COLOR_BLANCO, fieldbackground=COLOR_BLANCO, foreground=COLOR_TEXTO,
                         bordercolor=COLOR_HEADER, borderwidth=1)
        style.configure("Treeview.Heading", font=("Segoe UI", self._t(10), "bold"),
                         background=COLOR_HEADER, foreground=COLOR_TEXTO, relief="flat")
        style.map("Treeview.Heading", background=[("active", COLOR_ACCENT)])
        style.map("Treeview", background=[("selected", COLOR_ACCENT)], foreground=[("selected", COLOR_BLANCO)])

        style.configure("TEntry", fieldbackground=COLOR_BLANCO, foreground=COLOR_TEXTO,
                         bordercolor=COLOR_HEADER, padding=self._t(4), font=("Segoe UI", self._t(10)))
        style.configure("TCombobox", fieldbackground=COLOR_BLANCO, foreground=COLOR_TEXTO,
                         bordercolor=COLOR_HEADER, padding=self._t(4), font=("Segoe UI", self._t(10)))
        style.configure("TSpinbox", fieldbackground=COLOR_BLANCO, foreground=COLOR_TEXTO,
                         padding=self._t(4), font=("Segoe UI", self._t(10)))

        style.configure("Total.TLabel", font=("Segoe UI", self._t(16), "bold"),
                         background=COLOR_FONDO, foreground=COLOR_ACCENT_HOVER)

        style.configure("Subtitulo.TLabel", font=("Segoe UI", self._t(11), "bold"),
                         background=COLOR_FONDO, foreground=COLOR_TEXTO)
        style.configure("Sugerencia.TLabel", font=("Segoe UI", self._t(9), "italic"),
                         background=COLOR_FONDO, foreground=COLOR_TEXTO_SUAVE)

        if hasattr(self, "ent_scan_codigo"):
            self.ent_scan_codigo.configure(font=("Segoe UI", self._t(12)))

    def _construir_encabezado(self):
        header = ttk.Frame(self, style="Header.TFrame")
        header.pack(fill="x", side="top")

        contenido = ttk.Frame(header, style="Header.TFrame")
        contenido.pack(fill="x", padx=16, pady=10)

        self._logo_header_img = None
        if PIL_DISPONIBLE and os.path.exists(LOGO_HEADER_PATH):
            try:
                img = Image.open(LOGO_HEADER_PATH)
                self._logo_header_img = ImageTk.PhotoImage(img)
                lbl_logo = tk.Label(contenido, image=self._logo_header_img, bg=COLOR_HEADER, bd=0)
                lbl_logo.pack(side="left", padx=(0, 12))
            except Exception:
                pass

        textos = ttk.Frame(contenido, style="Header.TFrame")
        textos.pack(side="left")
        ttk.Label(textos, text=NOMBRE_NEGOCIO, style="HeaderTitulo.TLabel").pack(anchor="w")
        ttk.Label(textos, text=SUBTITULO_NEGOCIO, style="HeaderSubtitulo.TLabel").pack(anchor="w")

    def _set_icono_ventana(self):
        if PIL_DISPONIBLE and os.path.exists(LOGO_ICON_PATH):
            try:
                self._icono_img = ImageTk.PhotoImage(Image.open(LOGO_ICON_PATH))
                self.iconphoto(True, self._icono_img)
            except Exception:
                pass

    def abrir_calendario(self, entry):
        CalendarioPopup(self, entry)

    # -----------------------------------------------------------------
    # TAB CAJA (punto de venta)
    # -----------------------------------------------------------------
    def _construir_tab_caja(self):
        frame = self.tab_caja
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)

        scan_frame = ttk.LabelFrame(frame, text="🔫 Escanear producto con la pistola lectora o buscar por nombre")
        scan_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 0))
        scan_frame.columnconfigure(1, weight=1)

        ttk.Label(scan_frame, text="Buscar:").grid(row=0, column=0, padx=(8, 4), pady=8, sticky="e")
        self.ent_scan_codigo = ttk.Entry(scan_frame, font=("Segoe UI", self._t(12)))
        self.ent_scan_codigo.grid(row=0, column=1, padx=4, pady=8, sticky="ew")
        self.ent_scan_codigo.bind("<Return>", self.escanear_codigo_barras)
        ttk.Label(scan_frame, text="(Escribe nombre o escanea código y presiona Enter)",
                  style="Sugerencia.TLabel").grid(row=0, column=2, padx=8, sticky="w")

        izq = ttk.LabelFrame(frame, text="Productos disponibles")
        izq.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        izq.rowconfigure(0, weight=1)
        izq.columnconfigure(0, weight=1)

        cols = ("nombre", "tipo", "precio", "stock")
        self.tree_catalogo = ttk.Treeview(izq, columns=cols, show="headings", selectmode="browse")
        for c, txt, w in [
            ("nombre", "Producto", 220),
            ("tipo", "Tipo", 90),
            ("precio", "Precio", 100),
            ("stock", "Stock", 70),
        ]:
            self.tree_catalogo.heading(c, text=txt)
            self.tree_catalogo.column(c, width=w, anchor="center" if c != "nombre" else "w")
        self.tree_catalogo.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        agregar_frame = ttk.Frame(izq)
        agregar_frame.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))
        ttk.Label(agregar_frame, text="Cantidad:").pack(side="left")
        self.spin_cantidad = ttk.Spinbox(agregar_frame, from_=1, to=999, width=6)
        self.spin_cantidad.set(1)
        self.spin_cantidad.pack(side="left", padx=6)
        ttk.Button(agregar_frame, text="Agregar al carrito ➜", command=self.agregar_al_carrito).pack(side="left", padx=6)

        der = ttk.LabelFrame(frame, text="Carrito de venta")
        der.grid(row=1, column=1, sticky="nsew", padx=6, pady=6)
        der.rowconfigure(0, weight=1)
        der.columnconfigure(0, weight=1)

        cols2 = ("nombre", "cantidad", "precio_unit", "subtotal")
        self.tree_carrito = ttk.Treeview(der, columns=cols2, show="headings", selectmode="browse")
        for c, txt, w in [
            ("nombre", "Producto", 200),
            ("cantidad", "Cant.", 60),
            ("precio_unit", "P. Unit.", 90),
            ("subtotal", "Subtotal", 100),
        ]:
            self.tree_carrito.heading(c, text=txt)
            self.tree_carrito.column(c, width=w, anchor="center" if c != "nombre" else "w")
        self.tree_carrito.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.tree_carrito.bind("<Double-1>", self._editar_precio_carrito)
        self.tree_carrito.tag_configure("modificado", foreground=COLOR_ACCENT_HOVER)

        botones_carrito = ttk.Frame(der)
        botones_carrito.grid(row=1, column=0, sticky="ew", padx=6)
        ttk.Button(botones_carrito, text="Quitar seleccionado", command=self.quitar_del_carrito).pack(side="left")
        ttk.Button(botones_carrito, text="Vaciar carrito", command=self.vaciar_carrito).pack(side="left", padx=6)

        cliente_frame = ttk.LabelFrame(der, text="Datos del cliente / empresa")
        cliente_frame.grid(row=2, column=0, sticky="ew", padx=6, pady=(10, 0))
        cliente_frame.columnconfigure(1, weight=1)

        ttk.Label(cliente_frame, text="Cliente guardado:").grid(row=0, column=0, padx=6, pady=4, sticky="e")
        self.combo_caja_cliente = ttk.Combobox(cliente_frame, state="readonly")
        self.combo_caja_cliente.grid(row=0, column=1, padx=6, pady=4, sticky="ew")
        self.combo_caja_cliente.bind("<<ComboboxSelected>>", self._al_elegir_cliente_guardado)
        ttk.Button(cliente_frame, text="✖ Venta libre", command=self._limpiar_cliente_caja).grid(
            row=0, column=2, padx=6, pady=4)

        ttk.Label(cliente_frame, text="Nombre / Razón social *:").grid(row=1, column=0, padx=6, pady=4, sticky="e")
        self.ent_cliente_nombre = ttk.Entry(cliente_frame)
        self.ent_cliente_nombre.grid(row=1, column=1, columnspan=2, padx=6, pady=4, sticky="ew")

        ttk.Label(cliente_frame, text="Teléfono:").grid(row=2, column=0, padx=6, pady=4, sticky="e")
        self.ent_cliente_telefono = ttk.Entry(cliente_frame)
        self.ent_cliente_telefono.grid(row=2, column=1, columnspan=2, padx=6, pady=4, sticky="ew")

        ttk.Label(cliente_frame, text="NIT:").grid(row=3, column=0, padx=6, pady=4, sticky="e")
        self.ent_cliente_nit = ttk.Entry(cliente_frame)
        self.ent_cliente_nit.grid(row=3, column=1, columnspan=2, padx=6, pady=4, sticky="ew")

        ttk.Label(cliente_frame, text="Correo *:" if CORREO_OBLIGATORIO else "Correo:").grid(
            row=4, column=0, padx=6, pady=4, sticky="e")
        self.ent_cliente_correo = ttk.Entry(cliente_frame)
        self.ent_cliente_correo.grid(row=4, column=1, columnspan=2, padx=6, pady=4, sticky="ew")

        ttk.Button(cliente_frame, text="💾 Guardar como cliente nuevo",
                   command=self.guardar_cliente_desde_caja).grid(row=5, column=0, columnspan=3, padx=6, pady=(4, 6), sticky="ew")

        # ---- Forma de pago (contado / crédito) y método (efectivo / tarjeta / transferencia) ----
        pago_frame = ttk.Frame(der)
        pago_frame.grid(row=3, column=0, sticky="ew", padx=6, pady=(8, 0))

        # El crédito ahora es solo para peletería: aquí todo es de contado.
        self.combo_forma_pago = ttk.Combobox(pago_frame, values=["Contado"],
                                             state="readonly", width=10)
        self.combo_forma_pago.set("Contado")
        self.ent_abono_inicial = ttk.Entry(pago_frame, width=12, state="disabled")

        ttk.Label(pago_frame, text="Método de pago:").grid(row=0, column=0, sticky="e")
        self.combo_metodo_pago = ttk.Combobox(pago_frame, values=METODOS_PAGO,
                                              state="readonly", width=13)
        self.combo_metodo_pago.set("Efectivo")
        self.combo_metodo_pago.grid(row=0, column=1, padx=6, pady=2, sticky="w")

        ttk.Label(pago_frame, text="Formato:").grid(row=1, column=0, sticky="e")
        self.combo_formato = ttk.Combobox(pago_frame, values=["Factura PDF", "Ticket POS"],
                                          state="readonly", width=13)
        self.combo_formato.set("Factura PDF")
        self.combo_formato.grid(row=1, column=1, padx=6, pady=2, sticky="w")

        total_frame = ttk.Frame(der)
        total_frame.grid(row=4, column=0, sticky="ew", padx=6, pady=10)
        self.lbl_total = ttk.Label(total_frame, text="Total: $0", style="Total.TLabel")
        self.lbl_total.pack(side="left")
        ttk.Button(total_frame, text="💵 Cobrar venta", command=self.cobrar_venta).pack(side="right", ipadx=10, ipady=5)

    def _al_cambiar_forma_pago(self, event=None):
        self.ent_abono_inicial.configure(state="normal")
        if self.combo_forma_pago.get() != "Crédito":
            self.ent_abono_inicial.delete(0, "end")
            self.ent_abono_inicial.configure(state="disabled")

    def _reset_forma_pago(self):
        self.combo_forma_pago.set("Contado")
        self.combo_metodo_pago.set("Efectivo")
        self._al_cambiar_forma_pago()

    def cargar_catalogo(self):
        for item in self.tree_catalogo.get_children():
            self.tree_catalogo.delete(item)
        conn = db.conectar()
        cur = conn.cursor()
        cur.execute("SELECT id, nombre, tipo, precio, stock FROM productos ORDER BY tipo, nombre")
        filas = cur.fetchall()
        conn.close()

        configurar_filas_alternadas(self.tree_catalogo)
        self.tree_catalogo.tag_configure("bajo", foreground=COLOR_STOCK_BAJO)
        for i, (pid, nombre, tipo, precio, stock) in enumerate(filas):
            bajo = stock <= STOCK_BAJO
            self.tree_catalogo.insert(
                "", "end", iid=str(pid),
                tags=(tag_fila(i), "bajo") if bajo else (tag_fila(i),),
                values=(nombre, tipo, formato_precio(precio), f"⚠ {stock}" if bajo else stock))

    def agregar_al_carrito(self):
        sel = self.tree_catalogo.selection()
        if not sel:
            messagebox.showwarning("Selecciona un producto", "Debes seleccionar un producto del catálogo.")
            return
        producto_id = int(sel[0])
        try:
            cantidad = int(self.spin_cantidad.get())
            if cantidad <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Cantidad inválida", "La cantidad debe ser un número entero mayor a 0.")
            return
        self._agregar_id_al_carrito(producto_id, cantidad)

    def escanear_codigo_barras(self, event=None):
        """Busca coincidencias por código de barras exacto O por nombre parcial.
        Si hay varias, el código exacto va primero."""
        busqueda = self.ent_scan_codigo.get().strip()
        self.ent_scan_codigo.delete(0, "end")
        if not busqueda:
            return

        conn = db.conectar()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, nombre
            FROM productos
            WHERE codigo_barras = ? OR nombre LIKE ?
            ORDER BY (codigo_barras = ?) DESC, nombre
        """, (busqueda, f"%{busqueda}%", busqueda))

        filas = cur.fetchall()
        conn.close()

        if not filas:
            messagebox.showwarning(
                "Producto no encontrado",
                f"No se encontró ningún producto con el código o nombre '{busqueda}'.\n\n"
                "Puedes asignarlo desde la pestaña 📦 Zapat."
            )
            self.ent_scan_codigo.focus_set()
            return

        # Si encuentra coincidencias, toma el primer producto encontrado
        producto_id, nombre = filas[0]
        self._agregar_id_al_carrito(producto_id, 1)
        self.ent_scan_codigo.focus_set()

    def _agregar_id_al_carrito(self, producto_id, cantidad):
        conn = db.conectar()
        cur = conn.cursor()
        cur.execute("SELECT nombre, precio, stock FROM productos WHERE id = ?", (producto_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return
        nombre, precio, stock = row

        ya_en_carrito = sum(i["cantidad"] for i in self.carrito if i["producto_id"] == producto_id)
        if ya_en_carrito + cantidad > stock:
            messagebox.showerror(
                "Stock insuficiente",
                f"Solo hay {stock} unidades de '{nombre}' disponibles ({ya_en_carrito} ya están en el carrito)."
            )
            return

        for item in self.carrito:
            if item["producto_id"] == producto_id:
                item["cantidad"] += cantidad
                break
        else:
            self.carrito.append({
                "producto_id": producto_id,
                "nombre": nombre,
                "precio": precio,
                "precio_original": precio,   # para marcar los precios con descuento
                "cantidad": cantidad,
            })

        self.refrescar_carrito()

    def refrescar_carrito(self):
        for item in self.tree_carrito.get_children():
            self.tree_carrito.delete(item)
        total = 0
        for idx, item in enumerate(self.carrito):
            subtotal = item["precio"] * item["cantidad"]
            total += subtotal
            modificado = item["precio"] != item.get("precio_original", item["precio"])
            self.tree_carrito.insert(
                "", "end", iid=str(idx),
                tags=("modificado",) if modificado else (),
                values=(item["nombre"], item["cantidad"],
                        formato_precio(item["precio"]), formato_precio(subtotal))
            )
        self.lbl_total.config(text=f"Total: {formato_precio(total)}")

    def quitar_del_carrito(self):
        sel = self.tree_carrito.selection()
        if not sel:
            return
        idx = int(sel[0])
        del self.carrito[idx]
        self.refrescar_carrito()

    def vaciar_carrito(self):
        self.carrito = []
        self.refrescar_carrito()

    def _editar_precio_carrito(self, event):
        """Doble clic en la columna P. Unit. para cambiar el precio (descuentos)."""
        if self.tree_carrito.identify_region(event.x, event.y) != "cell":
            return
        if self.tree_carrito.identify_column(event.x) != "#3":  # 3ª columna = P. Unit.
            return
        fila = self.tree_carrito.identify_row(event.y)
        if not fila:
            return
        idx = int(fila)
        x, y, w, h = self.tree_carrito.bbox(fila, "#3")

        entry = ttk.Entry(self.tree_carrito, justify="center")
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, int(self.carrito[idx]["precio"]))
        entry.select_range(0, "end")
        entry.focus_set()

        cerrado = {"ok": False}

        def cerrar():
            if not cerrado["ok"]:
                cerrado["ok"] = True
                entry.destroy()

        def guardar(e=None):
            nuevo = a_numero(entry.get())
            if nuevo is None or nuevo <= 0:
                cerrar()
                messagebox.showerror("Precio inválido", "Escribe un precio mayor a 0.")
                return
            cerrar()
            self.carrito[idx]["precio"] = nuevo
            self.refrescar_carrito()

        entry.bind("<Return>", guardar)
        entry.bind("<Escape>", lambda e: cerrar())
        entry.bind("<FocusOut>", lambda e: cerrar())

    def cargar_combo_clientes_caja(self):
        conn = db.conectar()
        cur = conn.cursor()
        cur.execute("SELECT id, nombre, nit FROM clientes ORDER BY nombre")
        self._clientes_disponibles = cur.fetchall()
        conn.close()

        etiquetas = [f"{nombre}" + (f" (NIT {nit})" if nit else "") for _id, nombre, nit in self._clientes_disponibles]
        self.combo_caja_cliente["values"] = etiquetas
        if self._cliente_seleccionado_id not in [c[0] for c in self._clientes_disponibles]:
            self.combo_caja_cliente.set("")

    def _al_elegir_cliente_guardado(self, event=None):
        idx = self.combo_caja_cliente.current()
        if idx == -1 or idx >= len(self._clientes_disponibles):
            return
        cliente_id, _nombre, _nit = self._clientes_disponibles[idx]

        conn = db.conectar()
        cur = conn.cursor()
        cur.execute("SELECT nombre, nit, telefono, COALESCE(correo, '') FROM clientes WHERE id = ?", (cliente_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return
        nombre, nit, telefono, correo_cli = row

        self._cliente_seleccionado_id = cliente_id
        self.ent_cliente_nombre.delete(0, "end"); self.ent_cliente_nombre.insert(0, nombre)
        self.ent_cliente_nit.delete(0, "end"); self.ent_cliente_nit.insert(0, nit or "")
        self.ent_cliente_telefono.delete(0, "end"); self.ent_cliente_telefono.insert(0, telefono or "")
        self.ent_cliente_correo.delete(0, "end"); self.ent_cliente_correo.insert(0, correo_cli or "")

    def _limpiar_cliente_caja(self):
        self._cliente_seleccionado_id = None
        self.combo_caja_cliente.set("")
        self.ent_cliente_nombre.delete(0, "end")
        self.ent_cliente_telefono.delete(0, "end")
        self.ent_cliente_nit.delete(0, "end")
        self.ent_cliente_correo.delete(0, "end")

    def guardar_cliente_desde_caja(self):
        nombre = self.ent_cliente_nombre.get().strip()
        if not nombre:
            messagebox.showwarning("Falta el nombre", "Escribe el nombre o razón social antes de guardarlo como cliente.")
            self.ent_cliente_nombre.focus_set()
            return
        nit = self.ent_cliente_nit.get().strip()
        telefono = self.ent_cliente_telefono.get().strip()
        correo_cli = self.ent_cliente_correo.get().strip()
        if correo_cli and not correo.es_correo_valido(correo_cli):
            messagebox.showerror("Correo inválido", "Escribe un correo válido, por ejemplo nombre@dominio.com")
            self.ent_cliente_correo.focus_set()
            return

        conn = db.conectar()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO clientes (nombre, nit, telefono, correo, direccion, fecha_registro) VALUES (?, ?, ?, ?, ?, ?)",
            (nombre, nit, telefono, correo_cli, "", ahora())
        )
        cliente_id = cur.lastrowid
        conn.commit()
        conn.close()

        self._cliente_seleccionado_id = cliente_id
        self.cargar_combo_clientes_caja()
        self.cargar_clientes()
        messagebox.showinfo("Cliente guardado", f"'{nombre}' quedó guardado y ya lo puedes reutilizar en próximas ventas.")

    def cobrar_venta(self):
        if not self.carrito:
            messagebox.showwarning("Carrito vacío", "Agrega al menos un producto antes de cobrar.")
            return

        cliente_nombre = self.ent_cliente_nombre.get().strip()
        cliente_telefono = self.ent_cliente_telefono.get().strip()
        cliente_nit = self.ent_cliente_nit.get().strip()
        cliente_correo = self.ent_cliente_correo.get().strip()
        if not cliente_nombre:
            messagebox.showwarning("Falta el cliente", "Escribe el nombre del cliente antes de cobrar.")
            self.ent_cliente_nombre.focus_set()
            return
        if CORREO_OBLIGATORIO and not cliente_correo:
            messagebox.showwarning("Falta el correo", "Escribe el correo del comprador para enviarle la factura.")
            self.ent_cliente_correo.focus_set()
            return
        if cliente_correo and not correo.es_correo_valido(cliente_correo):
            messagebox.showerror("Correo inválido", "Escribe un correo válido, por ejemplo nombre@dominio.com")
            self.ent_cliente_correo.focus_set()
            return

        total = sum(i["precio"] * i["cantidad"] for i in self.carrito)

        # ---- Forma y método de pago ----
        es_credito = self.combo_forma_pago.get() == "Crédito"
        forma_pago = "Crédito" if es_credito else "Contado"
        metodo_pago = self.combo_metodo_pago.get() or "Efectivo"
        abono_inicial = 0.0

        if es_credito:
            texto_abono = self.ent_abono_inicial.get().strip()
            if texto_abono:
                abono_inicial = a_numero(texto_abono)
                if abono_inicial is None:
                    messagebox.showerror("Abono inválido", "El abono inicial debe ser un número.")
                    return
            if abono_inicial >= total:
                messagebox.showwarning(
                    "Abono muy alto",
                    "El abono inicial no puede ser igual o mayor al total.\n"
                    "Si el cliente paga todo, usa la forma de pago 'Contado'."
                )
                return

            # El crédito necesita un cliente guardado para poder cobrarle después
            if self._cliente_seleccionado_id is None:
                if not messagebox.askyesno(
                        "Cliente no guardado",
                        f"Para vender a crédito el cliente debe estar guardado.\n\n"
                        f"¿Guardar a '{cliente_nombre}' ahora?"):
                    return
                conn0 = db.conectar()
                cur0 = conn0.cursor()
                cur0.execute(
                    "INSERT INTO clientes (nombre, nit, telefono, correo, direccion, fecha_registro) VALUES (?, ?, ?, ?, ?, ?)",
                    (cliente_nombre, cliente_nit, cliente_telefono, cliente_correo, "", ahora())
                )
                self._cliente_seleccionado_id = cur0.lastrowid
                conn0.commit()
                conn0.close()
                self.cargar_combo_clientes_caja()
                self.cargar_clientes()

        detalle_pago = f"Contado ({metodo_pago})"
        if es_credito:
            detalle_pago = (f"Crédito (abono inicial {formato_precio(abono_inicial)} en {metodo_pago}, "
                            f"saldo {formato_precio(total - abono_inicial)})")

        if not messagebox.askyesno(
                "Confirmar venta",
                f"Cliente: {cliente_nombre}\nTotal: {formato_precio(total)}\n"
                f"Pago: {detalle_pago}\n\n¿Confirmar venta?"):
            return

        conn = db.conectar()
        cur = conn.cursor()
        try:
            cur.execute(
                """INSERT INTO ventas (fecha, total, cliente_id, cliente_nombre, cliente_telefono, cliente_nit,
                                      cliente_correo, forma_pago, metodo_pago)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ahora(), total, self._cliente_seleccionado_id, cliente_nombre, cliente_telefono, cliente_nit,
                 cliente_correo, forma_pago, metodo_pago)
            )
            venta_id = cur.lastrowid

            for item in self.carrito:
                # Descuento atómico: si otra caja vendió lo último un segundo antes,
                # esta no se completa (nunca queda stock negativo).
                cur.execute("UPDATE productos SET stock = stock - ? WHERE id = ? AND stock >= ?",
                            (item["cantidad"], item["producto_id"], item["cantidad"]))
                if cur.rowcount == 0:
                    raise ValueError(f"Stock insuficiente para '{item['nombre']}'.")

                subtotal = item["precio"] * item["cantidad"]
                cur.execute("""
                    INSERT INTO venta_detalle (venta_id, producto_id, nombre_producto, cantidad, precio_unitario, subtotal)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (venta_id, item["producto_id"], item["nombre"], item["cantidad"], item["precio"], subtotal))

            if es_credito and abono_inicial > 0:
                cur.execute(
                    "INSERT INTO abonos (venta_id, fecha, monto, nota, metodo_pago) VALUES (?, ?, ?, ?, ?)",
                    (venta_id, ahora(), abono_inicial, "Abono inicial", metodo_pago)
                )

            # Si es un cliente guardado, deja su correo actualizado
            if self._cliente_seleccionado_id is not None and cliente_correo:
                cur.execute("UPDATE clientes SET correo = ? WHERE id = ?",
                            (cliente_correo, self._cliente_seleccionado_id))

            conn.commit()

        except Exception as e:
            conn.rollback()
            messagebox.showerror("Error", f"Ocurrió un error al procesar la venta: {e}")
            self.cargar_catalogo()
            return
        finally:
            conn.close()

        # ---- La venta ya quedó guardada: factura PDF, correo y limpieza ----
        ruta_pdf = None
        try:
            if self.combo_formato.get() == "Ticket POS":
                ruta_pdf = factura.generar_ticket_pos(venta_id)
            else:
                ruta_pdf = factura.generar_factura_pdf(venta_id)
            factura.abrir_factura(ruta_pdf)
        except Exception as e:
            messagebox.showerror("Error al generar factura", f"No se pudo generar la factura: {e}")

        nota_correo = ""
        if cliente_correo and ruta_pdf:
            try:
                self.config(cursor="watch")
                self.update_idletasks()
                correo.enviar_factura(cliente_correo, ruta_pdf, venta_id, NOMBRE_NEGOCIO, cliente_nombre)
                nota_correo = f"\n\nFactura enviada a {cliente_correo}."
            except correo.ConfigCorreoError as e:
                nota_correo = f"\n\nNo se envió el correo: {e}"
            except Exception as e:
                nota_correo = (f"\n\nNo se pudo enviar el correo ({e}).\n"
                               "Puedes reenviarla desde Historial > Enviar por correo.")
            finally:
                self.config(cursor="")

        if es_credito:
            messagebox.showinfo(
                "Venta a crédito registrada",
                f"Venta #{venta_id} registrada.\nSaldo pendiente: {formato_precio(total - abono_inicial)}"
                f"{nota_correo}"
            )
        else:
            messagebox.showinfo("Venta exitosa", f"Venta #{venta_id} registrada correctamente.{nota_correo}")

        self.vaciar_carrito()
        self._limpiar_cliente_caja()
        self._reset_forma_pago()
        try:
            self.refrescar_todo()
        except Exception as e:
            messagebox.showerror("Error al actualizar", f"La venta se guardó, pero falló al refrescar las tablas: {e}")

    # -----------------------------------------------------------------
    # TAB PRODUCTOS
    # -----------------------------------------------------------------
    def _construir_tab_productos(self):
        frame = self.tab_productos
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=1)

        # Formulario
        form = ttk.LabelFrame(frame, text="Gestión de Producto")
        form.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        fields = [
            ("Código Barras:", "ent_prod_codigo"),
            ("Nombre:", "ent_prod_nombre"),
            ("Tipo:", "combo_prod_tipo"),
            ("Precio:", "ent_prod_precio"),
            ("Stock:", "ent_prod_stock"),
        ]

        for idx, (label_txt, var_name) in enumerate(fields):
            ttk.Label(form, text=label_txt).grid(row=idx, column=0, padx=6, pady=6, sticky="e")
            if var_name == "combo_prod_tipo":
                widget = ttk.Combobox(form, values=TIPOS_PRODUCTO, state="readonly")
                widget.set(TIPOS_PRODUCTO[0])
            else:
                widget = ttk.Entry(form)
            widget.grid(row=idx, column=1, padx=6, pady=6, sticky="ew")
            setattr(self, var_name, widget)

        btn_frame = ttk.Frame(form)
        btn_frame.grid(row=len(fields), column=0, columnspan=2, pady=10)

        ttk.Button(btn_frame, text="Guardar", command=self.guardar_producto).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Limpiar", command=self.limpiar_form_producto).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Eliminar", command=self.eliminar_producto).pack(side="left", padx=4)

        # Tabla
        tabla_frame = ttk.Frame(frame)
        tabla_frame.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        tabla_frame.rowconfigure(0, weight=1)
        tabla_frame.columnconfigure(0, weight=1)

        cols = ("id", "codigo", "nombre", "tipo", "precio", "stock")
        self.tree_productos_admin = ttk.Treeview(tabla_frame, columns=cols, show="headings", selectmode="browse")
        for c, txt, w in [
            ("id", "ID", 40),
            ("codigo", "Código", 110),
            ("nombre", "Nombre", 200),
            ("tipo", "Tipo", 100),
            ("precio", "Precio", 90),
            ("stock", "Stock", 60),
        ]:
            self.tree_productos_admin.heading(c, text=txt)
            self.tree_productos_admin.column(c, width=w, anchor="center" if c not in ("nombre", "codigo") else "w")
        self.tree_productos_admin.grid(row=0, column=0, sticky="nsew")
        self.tree_productos_admin.bind("<<TreeviewSelect>>", self._al_seleccionar_producto)

    def cargar_productos_admin(self):
        for item in self.tree_productos_admin.get_children():
            self.tree_productos_admin.delete(item)
        conn = db.conectar()
        cur = conn.cursor()
        cur.execute("SELECT id, codigo_barras, nombre, tipo, precio, stock FROM productos ORDER BY id DESC")
        filas = cur.fetchall()
        conn.close()
        configurar_filas_alternadas(self.tree_productos_admin)
        for i, row in enumerate(filas):
            pid, cod, nom, tipo, precio, stock = row
            self.tree_productos_admin.insert("", "end", iid=str(pid), tags=(tag_fila(i),),
                                              values=(pid, cod or "", nom, tipo, formato_precio(precio), stock))

    def _al_seleccionar_producto(self, event=None):
        sel = self.tree_productos_admin.selection()
        if not sel:
            return
        pid = sel[0]
        conn = db.conectar()
        cur = conn.cursor()
        cur.execute("SELECT codigo_barras, nombre, tipo, precio, stock FROM productos WHERE id = ?", (pid,))
        row = cur.fetchone()
        conn.close()
        if row:
            cod, nom, tipo, precio, stock = row
            self.ent_prod_codigo.delete(0, "end"); self.ent_prod_codigo.insert(0, cod or "")
            self.ent_prod_nombre.delete(0, "end"); self.ent_prod_nombre.insert(0, nom)
            self.combo_prod_tipo.set(tipo)
            self.ent_prod_precio.delete(0, "end"); self.ent_prod_precio.insert(0, int(precio))
            self.ent_prod_stock.delete(0, "end"); self.ent_prod_stock.insert(0, stock)

    def limpiar_form_producto(self):
        self.ent_prod_codigo.delete(0, "end")
        self.ent_prod_nombre.delete(0, "end")
        self.combo_prod_tipo.set(TIPOS_PRODUCTO[0])
        self.ent_prod_precio.delete(0, "end")
        self.ent_prod_stock.delete(0, "end")
        if self.tree_productos_admin.selection():
            self.tree_productos_admin.selection_remove(self.tree_productos_admin.selection())

    def guardar_producto(self):
        codigo = self.ent_prod_codigo.get().strip() or None  # vacío = sin código (no choca con otros)
        nombre = self.ent_prod_nombre.get().strip()
        tipo = self.combo_prod_tipo.get().strip()
        try:
            precio = float(self.ent_prod_precio.get().strip())
            stock = int(self.ent_prod_stock.get().strip())
        except ValueError:
            messagebox.showerror("Datos inválidos", "El precio y el stock deben ser números válidos.")
            return

        if not nombre:
            messagebox.showwarning("Falta el nombre", "Ingresa un nombre de producto.")
            return

        sel = self.tree_productos_admin.selection()
        conn = db.conectar()
        cur = conn.cursor()
        try:
            if sel:
                pid = int(sel[0])
                cur.execute("""UPDATE productos SET codigo_barras=?, nombre=?, tipo=?, precio=?, stock=?
                               WHERE id=?""", (codigo, nombre, tipo, precio, stock, pid))
            else:
                cur.execute("""INSERT INTO productos (codigo_barras, nombre, tipo, precio, stock)
                               VALUES (?, ?, ?, ?, ?)""", (codigo, nombre, tipo, precio, stock))
            conn.commit()
        except Exception as e:
            conn.rollback()
            messagebox.showerror("No se pudo guardar",
                                 f"No se pudo guardar el producto (¿el código de barras ya existe?):\n{e}")
            return
        finally:
            conn.close()

        self.limpiar_form_producto()
        self.cargar_productos_admin()
        self.cargar_catalogo()

    def eliminar_producto(self):
        sel = self.tree_productos_admin.selection()
        if not sel:
            messagebox.showwarning("Seleccionar", "Selecciona un producto para eliminar.")
            return
        if not messagebox.askyesno("Confirmar", "¿Deseas eliminar este producto?"):
            return
        pid = int(sel[0])
        conn = db.conectar()
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM productos WHERE id = ?", (pid,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            messagebox.showerror("No se pudo eliminar",
                                 f"Este producto tiene ventas registradas y no se puede eliminar.\n\n{e}")
            return
        finally:
            conn.close()
        self.limpiar_form_producto()
        self.cargar_productos_admin()
        self.cargar_catalogo()

    # -----------------------------------------------------------------
    # TAB MATERIALES
    # -----------------------------------------------------------------
    def _construir_tab_materiales(self):
        frame = self.tab_materiales
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)

        buscar_frame = ttk.LabelFrame(frame, text="🔫 Buscar material por código de barras o nombre")
        buscar_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 0))
        buscar_frame.columnconfigure(1, weight=1)
        ttk.Label(buscar_frame, text="Buscar:").grid(row=0, column=0, padx=(8, 4), pady=8, sticky="e")
        self.ent_mat_buscar = ttk.Entry(buscar_frame)
        self.ent_mat_buscar.grid(row=0, column=1, padx=4, pady=8, sticky="ew")
        self.ent_mat_buscar.bind("<Return>", self.buscar_material)
        ttk.Button(buscar_frame, text="✖ Ver todos", command=self.limpiar_busqueda_material).grid(row=0, column=2, padx=8)

        form = ttk.LabelFrame(frame, text="Gestión de Materiales")
        form.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)

        ttk.Label(form, text="Código barras:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        self.ent_mat_codigo = ttk.Entry(form)
        self.ent_mat_codigo.grid(row=0, column=1, padx=6, pady=6, sticky="ew")

        ttk.Label(form, text="Nombre:").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        self.ent_mat_nombre = ttk.Entry(form)
        self.ent_mat_nombre.grid(row=1, column=1, padx=6, pady=6, sticky="ew")

        ttk.Label(form, text="Cantidad:").grid(row=2, column=0, padx=6, pady=6, sticky="e")
        self.ent_mat_cant = ttk.Entry(form)
        self.ent_mat_cant.grid(row=2, column=1, padx=6, pady=6, sticky="ew")

        ttk.Label(form, text="Unidad:").grid(row=3, column=0, padx=6, pady=6, sticky="e")
        self.ent_mat_unidad = ttk.Entry(form)
        self.ent_mat_unidad.grid(row=3, column=1, padx=6, pady=6, sticky="ew")

        btn_f = ttk.Frame(form)
        btn_f.grid(row=4, column=0, columnspan=2, pady=10)
        ttk.Button(btn_f, text="Guardar", command=self.guardar_material).pack(side="left", padx=4)
        ttk.Button(btn_f, text="Eliminar", command=self.eliminar_material).pack(side="left", padx=4)

        cols = ("id", "nombre", "cantidad", "unidad", "codigo")
        self.tree_mat = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        for c, txt in [("id", "ID"), ("nombre", "Nombre"), ("cantidad", "Cantidad"),
                       ("unidad", "Unidad"), ("codigo", "Código de barras")]:
            self.tree_mat.heading(c, text=txt)
        self.tree_mat.grid(row=1, column=1, sticky="nsew", padx=6, pady=6)

    def buscar_material(self, event=None):
        texto = self.ent_mat_buscar.get().strip()
        self.cargar_materiales(filtro=texto)

    def limpiar_busqueda_material(self):
        self.ent_mat_buscar.delete(0, "end")
        self.cargar_materiales()

    def cargar_materiales(self, filtro=""):
        for item in self.tree_mat.get_children():
            self.tree_mat.delete(item)
        conn = db.conectar()
        cur = conn.cursor()
        if filtro:
            cur.execute("""SELECT id, nombre, stock_actual, unidad, codigo_barras FROM materiales
                           WHERE codigo_barras = ? OR nombre LIKE ? ORDER BY nombre""",
                        (filtro, f"%{filtro}%"))
        else:
            cur.execute("""SELECT id, nombre, stock_actual, unidad, codigo_barras FROM materiales
                           ORDER BY nombre""")
        filas = cur.fetchall()
        conn.close()
        configurar_filas_alternadas(self.tree_mat)
        for i, (mid, nom, cant, uni, cod) in enumerate(filas):
            self.tree_mat.insert("", "end", iid=str(mid), tags=(tag_fila(i),),
                                 values=(mid, nom, cant, uni or "", cod or ""))

    def guardar_material(self):
        codigo = self.ent_mat_codigo.get().strip()
        nom = self.ent_mat_nombre.get().strip()
        uni = self.ent_mat_unidad.get().strip()
        if not nom:
            messagebox.showwarning("Falta el nombre", "Escribe el nombre del material.")
            return
        try:
            cant = float(self.ent_mat_cant.get().strip())
        except ValueError:
            messagebox.showerror("Error", "La cantidad debe ser numérica.")
            return

        conn = db.conectar()
        cur = conn.cursor()
        try:
            if codigo:
                cur.execute("SELECT nombre FROM materiales WHERE codigo_barras = ?", (codigo,))
                repetido = cur.fetchone()
                if repetido:
                    messagebox.showerror("Código repetido", f"Ese código ya está asignado a '{repetido[0]}'.")
                    return
            cur.execute("INSERT INTO materiales (codigo_barras, nombre, unidad, stock_actual) VALUES (?, ?, ?, ?)",
                        (codigo or None, nom, uni or "unidad", cant))
            conn.commit()
        except Exception as e:
            conn.rollback()
            messagebox.showerror("No se pudo guardar",
                                 f"No se pudo guardar el material (¿ya existe uno con ese nombre?):\n{e}")
            return
        finally:
            conn.close()

        self.ent_mat_codigo.delete(0, "end")
        self.ent_mat_nombre.delete(0, "end")
        self.ent_mat_cant.delete(0, "end")
        self.ent_mat_unidad.delete(0, "end")
        self.cargar_materiales()

    def eliminar_material(self):
        sel = self.tree_mat.selection()
        if not sel:
            messagebox.showwarning("Seleccionar", "Selecciona un material para eliminar.")
            return
        if not messagebox.askyesno("Confirmar", "¿Deseas eliminar este material?"):
            return
        conn = db.conectar()
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM materiales WHERE id = ?", (sel[0],))
            conn.commit()
        except Exception as e:
            conn.rollback()
            messagebox.showerror("No se pudo eliminar", f"No se pudo eliminar el material:\n{e}")
            return
        finally:
            conn.close()
        self.cargar_materiales()

    # -----------------------------------------------------------------
    # TAB CLIENTES
    # -----------------------------------------------------------------
    def _construir_tab_clientes(self):
        frame = self.tab_clientes
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=1)

        form = ttk.LabelFrame(frame, text="Datos Cliente")
        form.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        fields = [
            ("Nombre:", "ent_c_nombre"),
            ("NIT:", "ent_c_nit"),
            ("Correo:", "ent_c_correo"),
            ("Teléfono:", "ent_c_tel"),
            ("Dirección:", "ent_c_dir"),
        ]

        for i, (l, v) in enumerate(fields):
            ttk.Label(form, text=l).grid(row=i, column=0, padx=6, pady=6, sticky="e")
            ent = ttk.Entry(form)
            ent.grid(row=i, column=1, padx=6, pady=6, sticky="ew")
            setattr(self, v, ent)

        btn_f = ttk.Frame(form)
        btn_f.grid(row=len(fields), column=0, columnspan=2, pady=10)
        ttk.Button(btn_f, text="Guardar", command=self.guardar_cliente).pack(side="left", padx=4)
        ttk.Button(btn_f, text="Eliminar", command=self.eliminar_cliente).pack(side="left", padx=4)

        cols = ("id", "nombre", "nit", "correo", "telefono", "direccion")
        self.tree_cli = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        for c, txt in [("id", "ID"), ("nombre", "Nombre"), ("nit", "NIT"), ("correo", "Correo"),
                       ("telefono", "Teléfono"), ("direccion", "Dirección")]:
            self.tree_cli.heading(c, text=txt)
        self.tree_cli.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)

    def cargar_clientes(self):
        for item in self.tree_cli.get_children():
            self.tree_cli.delete(item)
        conn = db.conectar()
        cur = conn.cursor()
        cur.execute("SELECT id, nombre, nit, COALESCE(correo, ''), telefono, direccion FROM clientes ORDER BY nombre")
        filas = cur.fetchall()
        conn.close()
        configurar_filas_alternadas(self.tree_cli)
        for i, row in enumerate(filas):
            self.tree_cli.insert("", "end", iid=str(row[0]), tags=(tag_fila(i),), values=row)

    def guardar_cliente(self):
        nom = self.ent_c_nombre.get().strip()
        nit = self.ent_c_nit.get().strip()
        correo_cli = self.ent_c_correo.get().strip()
        tel = self.ent_c_tel.get().strip()
        dir_ = self.ent_c_dir.get().strip()

        if not nom:
            messagebox.showwarning("Falta nombre", "Escribe el nombre del cliente.")
            return
        if correo_cli and not correo.es_correo_valido(correo_cli):
            messagebox.showerror("Correo inválido", "Escribe un correo válido, por ejemplo nombre@dominio.com")
            return

        conn = db.conectar()
        cur = conn.cursor()
        cur.execute("INSERT INTO clientes (nombre, nit, telefono, correo, direccion, fecha_registro) VALUES (?, ?, ?, ?, ?, ?)",
                    (nom, nit, tel, correo_cli, dir_, ahora()))
        conn.commit()
        conn.close()

        self.ent_c_nombre.delete(0, "end")
        self.ent_c_nit.delete(0, "end")
        self.ent_c_correo.delete(0, "end")
        self.ent_c_tel.delete(0, "end")
        self.ent_c_dir.delete(0, "end")
        self.refrescar_todo()

    def eliminar_cliente(self):
        sel = self.tree_cli.selection()
        if not sel:
            messagebox.showwarning("Seleccionar", "Selecciona un cliente para eliminar.")
            return
        if not messagebox.askyesno("Confirmar", "¿Deseas eliminar este cliente?"):
            return
        conn = db.conectar()
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM clientes WHERE id = ?", (sel[0],))
            conn.commit()
        except Exception as e:
            conn.rollback()
            messagebox.showerror("No se pudo eliminar",
                                 f"Este cliente tiene ventas registradas y no se puede eliminar.\n\n{e}")
            return
        finally:
            conn.close()
        self.refrescar_todo()

    # -----------------------------------------------------------------
    # TAB CRÉDITO (ventas a crédito y abonos)
    # -----------------------------------------------------------------
       # -----------------------------------------------------------------
    # TAB CRÉDITO (solo peletería)
    # -----------------------------------------------------------------
    def _construir_tab_credito(self):
        self.tab_credito.rowconfigure(0, weight=1)
        self.tab_credito.columnconfigure(0, weight=1)
        self.panel_credito = PanelCreditoPeleteria(self.tab_credito, self)
        self.panel_credito.grid(row=0, column=0, sticky="nsew")

    def cargar_credito(self):
        if getattr(self, "panel_credito", None):
            self.panel_credito.cargar()
            
        # ----------------------------------------------------------------
    # TAB HISTORIAL
    # -----------------------------------------------------------------
    def _construir_tab_historial(self):
        base = self.tab_historial
        base.rowconfigure(0, weight=1)
        base.columnconfigure(0, weight=1)

        sub = ttk.Notebook(base, style="Rosa.TNotebook")
        sub.grid(row=0, column=0, sticky="nsew")
        self.sub_hist_zap = ttk.Frame(sub)
        self.sub_hist_pel = ttk.Frame(sub)
        sub.add(self.sub_hist_zap, text="👞 Zapatería")
        sub.add(self.sub_hist_pel, text="🧵 Peletería")

        # ---------- Zapatería (tu historial de siempre) ----------
        frame = self.sub_hist_zap
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        top = ttk.Frame(frame)
        top.grid(row=0, column=0, sticky="ew", padx=6, pady=6)

        ttk.Label(top, text="Filtrar por fecha:").pack(side="left", padx=4)
        self.ent_hist_fecha = ttk.Entry(top, width=12)
        self.ent_hist_fecha.pack(side="left", padx=4)
        ttk.Button(top, text="📅", width=3,
                   command=lambda: CalendarioPopup(self, self.ent_hist_fecha)).pack(side="left")

        ttk.Button(top, text="Buscar", command=self.cargar_historial).pack(side="left", padx=6)
        ttk.Button(top, text="🧾 Ticket POS", command=self.reimprimir_ticket_pos).pack(side="right", padx=6)
        ttk.Button(top, text="✉ Enviar por correo", command=self.enviar_factura_por_correo).pack(side="right", padx=6)
        ttk.Button(top, text="↩ Anular / devolver", command=self.anular_devolver_venta).pack(side="right", padx=6)

        cols = ("id", "fecha", "cliente", "total", "estado", "motivo")
        self.tree_hist = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        for c, txt, w in [
            ("id", "Venta #", 70),
            ("fecha", "Fecha", 150),
            ("cliente", "Cliente", 200),
            ("total", "Total", 100),
            ("estado", "Estado", 90),
            ("motivo", "Motivo", 220),
        ]:
            self.tree_hist.heading(c, text=txt)
            self.tree_hist.column(c, width=w, anchor="w" if c in ("cliente", "motivo") else "center")
        self.tree_hist.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)

        # ---------- Peletería ----------
        self.panel_hist_pel = PanelHistorialPeleteria(
            self.sub_hist_pel, self, lambda ent: CalendarioPopup(self, ent))
        self.panel_hist_pel.pack(fill="both", expand=True)

    def _ver_todas_historial(self):
        self.ent_hist_fecha.delete(0, "end")
        self.cargar_historial()

    def cargar_historial(self):
        for item in self.tree_hist.get_children():
            self.tree_hist.delete(item)
        fecha_filtro = self.ent_hist_fecha.get().strip()
        columnas = ("id, fecha, cliente_nombre, total, COALESCE(estado, 'Activa'), "
                    + db.col_o_vacio("ventas", "motivo_anulacion"))

        conn = db.conectar()
        cur = conn.cursor()
        if fecha_filtro:
            cur.execute(f"SELECT {columnas} FROM ventas WHERE fecha LIKE ? ORDER BY id DESC",
                        (f"{fecha_filtro}%",))
        else:
            cur.execute(f"SELECT {columnas} FROM ventas ORDER BY id DESC")
        filas = cur.fetchall()
        conn.close()

        configurar_filas_alternadas(self.tree_hist)
        self.tree_hist.tag_configure("anulada", foreground=COLOR_ANULADA)
        for i, (vid, fec, cli, tot, estado, motivo) in enumerate(filas):
            tags = ("anulada",) if estado != "Activa" else (tag_fila(i),)
            self.tree_hist.insert("", "end", iid=str(vid), tags=tags,
                                  values=(vid, fec, cli, formato_precio(tot), estado, motivo))

        if getattr(self, "panel_hist_pel", None):
            self.panel_hist_pel.cargar()

    def anular_devolver_venta(self):
        sel = self.tree_hist.selection()
        if not sel:
            messagebox.showwarning("Seleccionar", "Selecciona una venta del historial.")
            return
        venta_id = int(sel[0])

        conn = db.conectar()
        try:
            cur = conn.cursor()
            cur.execute("SELECT cliente_nombre, total, fecha, COALESCE(estado, 'Activa') "
                        "FROM ventas WHERE id = ?", (venta_id,))
            fila = cur.fetchone()
        finally:
            conn.close()

        if not fila:
            messagebox.showerror("Venta no encontrada", "La venta seleccionada ya no existe.")
            return
        cliente, total, fecha, estado_actual = fila
        if estado_actual != "Activa":
            messagebox.showinfo("Venta ya procesada",
                                f"La venta #{venta_id} ya está marcada como {estado_actual}.")
            return

        decision = caja_extra.pedir_anulacion(self, venta_id, cliente, total)
        if not decision:
            return
        if not seguridad.pedir_clave(self, "anular o devolver la venta"):
            return

        estado, motivo = decision
        try:
            anular_venta_db(venta_id, estado, motivo)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo procesar la venta: {e}")
            self.refrescar_todo()
            return

        aviso = f"La venta #{venta_id} quedó marcada como {estado} y los productos regresaron al stock."
        if not str(fecha).startswith(datetime.now().strftime("%Y-%m-%d")):
            aviso += ("\n\nOjo: la venta es de otro día. Si devolviste dinero en efectivo, "
                      "regístralo como Retiro en la pestaña Cierre de caja.")
        messagebox.showinfo("Venta actualizada", aviso)
        self.refrescar_todo()

    def reimprimir_factura(self):
        sel = self.tree_hist.selection()
        if not sel:
            messagebox.showwarning("Seleccionar", "Selecciona una venta del historial para reimprimir.")
            return
        venta_id = int(sel[0])

        if caja_extra.estado_venta(venta_id) != "Activa":
            messagebox.showwarning("Venta anulada", "Esta venta está anulada o devuelta; no se genera factura.")
            return

        try:
            ruta_pdf = factura.generar_factura_pdf(venta_id)
            factura.abrir_factura(ruta_pdf)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo volver a generar la factura: {e}")

    def reimprimir_ticket_pos(self):
        sel = self.tree_hist.selection()
        if not sel:
            messagebox.showwarning("Seleccionar", "Selecciona una venta del historial para el ticket.")
            return
        venta_id = int(sel[0])
        try:
            ruta = factura.generar_ticket_pos(venta_id)
            factura.abrir_factura(ruta)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar el ticket POS: {e}")

    def enviar_factura_por_correo(self):
        sel = self.tree_hist.selection()
        if not sel:
            messagebox.showwarning("Seleccionar", "Selecciona una venta del historial para enviar.")
            return
        venta_id = int(sel[0])

        if caja_extra.estado_venta(venta_id) != "Activa":
            messagebox.showwarning("Venta anulada", "Esta venta está anulada o devuelta; no se genera factura.")
            return

        conn = db.conectar()
        cur = conn.cursor()
        cur.execute("SELECT cliente_nombre, COALESCE(cliente_correo, '') FROM ventas WHERE id = ?", (venta_id,))
        fila = cur.fetchone()
        conn.close()
        if not fila:
            return
        nombre, correo_actual = fila

        texto = simpledialog.askstring(
            "Enviar factura por correo",
            f"Venta #{venta_id} - {nombre}\n\nCorreo del comprador:",
            initialvalue=correo_actual, parent=self
        )
        if texto is None:
            return
        destino = texto.strip()
        if not correo.es_correo_valido(destino):
            messagebox.showerror("Correo inválido", "Escribe un correo válido, por ejemplo nombre@dominio.com")
            return

        try:
            ruta_factura = factura.generar_factura_pdf(venta_id)
            self.config(cursor="watch")
            self.update_idletasks()
            correo.enviar_factura(destino, ruta_factura, venta_id, NOMBRE_NEGOCIO, nombre)
        except correo.ConfigCorreoError as e:
            messagebox.showwarning("Correo sin configurar", str(e))
            return
        except Exception as e:
            messagebox.showerror("No se pudo enviar", f"No se pudo enviar la factura: {e}")
            return
        finally:
            self.config(cursor="")

        if destino != correo_actual:
            conn = db.conectar()
            cur = conn.cursor()
            cur.execute("UPDATE ventas SET cliente_correo = ? WHERE id = ?", (destino, venta_id))
            conn.commit()
            conn.close()
        messagebox.showinfo("Factura enviada", f"Factura enviada a {destino}.")

    # -----------------------------------------------------------------
    # Refresco General
    # -----------------------------------------------------------------
    def refrescar_todo(self):
        self.cargar_catalogo()
        self.cargar_combo_clientes_caja()
        self.cargar_productos_admin()
        self.cargar_materiales()
        self.cargar_clientes()
        self.cargar_credito()
        self.cargar_historial()
        if hasattr(self, "tab_entradas"):
            self.tab_entradas.cargar()
        if hasattr(self, "tab_cierre_caja"):
            self.tab_cierre_caja.cargar()
        if hasattr(self, "tab_reportes"):
            self.tab_reportes.cargar()


# ---------------------------------------------------------------------------
# Punto de entrada de la aplicación
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    problema = db.verificar_acceso()
    if problema:
        raiz = tk.Tk()
        raiz.withdraw()
        messagebox.showerror("Base de datos no disponible", problema)
        raiz.destroy()
        sys.exit(1)

    db.inicializar_db()
    app = CajaRegistradoraApp()
    if auto_migracion:
        app.after(800, lambda: auto_migracion.migrar_datos_locales_si_hay(app, app.refrescar_todo))
    app.mainloop()
    