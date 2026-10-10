"""
Generación de facturas (HTML y PDF) para la Caja Registradora.
Sirve para las dos cajas, con el mismo estilo:
  - tipo="zapateria"  -> ventas de zapatos/productos (tablas ventas / venta_detalle)
  - tipo="peleteria"  -> ventas de peletería (tablas ventas_peleteria / venta_peleteria_detalle)

Formatos:
  - Factura HTML: se guarda en la carpeta "facturas" y se abre con el navegador.
  - Factura PDF (A4, necesita fpdf2): es la que se envía por correo.
  - Ticket POS (PDF de 80 mm, necesita fpdf2): para impresora térmica.
"""
import os
import base64
import html
import subprocess
import sys

import database as db
import rutas

# Las facturas se guardan junto a la base de datos (no se pierden en el .exe)
CARPETA_FACTURAS = os.path.join(rutas.ruta_base(), "facturas")
# Los logos van empaquetados dentro del .exe (solo lectura)
CARPETA_ASSETS = rutas.ruta_recurso("assets")

# ---- Datos de la empresa (encabezado de la factura) ----
NOMBRE_NEGOCIO = "CREACIONES PAMELA J.D. S.A.S"
NIT_NEGOCIO = "901379169-1"
TELEFONO_NEGOCIO = "315 4696516 / 312 5838885"
CIUDAD_NEGOCIO = "Cúcuta, Norte de Santander"


COLOR_ACCENT = "#e08787"
COLOR_ACCENT_HOVER = "#c96b6b"
COLOR_TEXTO = "#4a3636"
COLOR_TEXTO_SUAVE = "#7a6363"
COLOR_FONDO = "#fdf2f0"
COLOR_FILA_ALT = "#fff8f6"


def formato_precio(valor):
    return f"${float(valor):,.0f}"


def _fmt_cant(valor):
    """2 -> '2', 1.5 -> '1.5' (las cantidades de peletería pueden tener decimales)."""
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    return str(int(v)) if v.is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")


def _es_pel(tipo):
    return str(tipo).lower().startswith("pel")


def _sufijo(tipo):
    """Para que la factura #1 de zapatería no pise la #1 de peletería."""
    return "_pel" if _es_pel(tipo) else ""


# ---------------------------------------------------------------------------
# Lectura de la venta (zapatería o peletería)
# ---------------------------------------------------------------------------
def _cargar_venta(venta_id, tipo="zapateria"):
    """Devuelve un diccionario con todo lo que necesitan la factura y el ticket."""
    conn = db.conectar()
    try:
        cur = conn.cursor()
        if _es_pel(tipo):
            cur.execute("""
                SELECT fecha, total, COALESCE(cliente, ''), COALESCE(telefono, ''), COALESCE(nit, ''),
                       COALESCE(forma_pago, 'Contado'), COALESCE(metodo_pago, 'Efectivo'),
                       COALESCE(estado, 'Activa')
                FROM ventas_peleteria WHERE id = ?
            """, (venta_id,))
            venta = cur.fetchone()
            if not venta:
                raise ValueError(f"No existe la venta de peletería #{venta_id}")
            cur.execute("""
                SELECT nombre, cantidad, precio_unitario, subtotal
                FROM venta_peleteria_detalle WHERE venta_id = ? ORDER BY id
            """, (venta_id,))
            detalle = cur.fetchall()
            cur.execute("SELECT COALESCE(SUM(monto), 0) FROM abonos_peleteria WHERE venta_id = ?",
                        (venta_id,))
            abonado = cur.fetchone()[0]
        else:
            cur.execute(f"""
                SELECT fecha, total, cliente_nombre, cliente_telefono, cliente_nit,
                       {db.col_o_vacio('ventas', 'forma_pago')},
                       {db.col_o_vacio('ventas', 'metodo_pago')},
                       {db.col_o_vacio('ventas', 'estado')}
                FROM ventas WHERE id = ?
            """, (venta_id,))
            venta = cur.fetchone()
            if not venta:
                raise ValueError(f"No existe la venta #{venta_id}")
            cur.execute("""
                SELECT nombre_producto, cantidad, precio_unitario, subtotal
                FROM venta_detalle WHERE venta_id = ? ORDER BY id
            """, (venta_id,))
            detalle = cur.fetchall()
            cur.execute("SELECT COALESCE(SUM(monto), 0) FROM abonos WHERE venta_id = ?", (venta_id,))
            abonado = cur.fetchone()[0]
    finally:
        conn.close()

    fecha, total, nombre, telefono, nit, forma_pago, metodo_pago, estado = venta
    return {
        "tipo": "peleteria" if _es_pel(tipo) else "zapateria",
        "fecha": fecha, "total": float(total),
        "cliente_nombre": nombre, "cliente_telefono": telefono, "cliente_nit": nit,
        "forma_pago": forma_pago or "Contado",
        "metodo_pago": metodo_pago or "Efectivo",
        "estado": estado or "Activa",
        "detalle": [(n, c, float(p), float(s)) for n, c, p, s in detalle],
        "abonado": float(abonado),
    }


def _ruta_logo():
    ruta_logo = os.path.join(CARPETA_ASSETS, "logo_header.png")
    if not os.path.exists(ruta_logo):
        ruta_logo = os.path.join(CARPETA_ASSETS, "logo_icon.png")
    return ruta_logo if os.path.exists(ruta_logo) else None


def _logo_base64():
    """Convierte el logo a base64 para incrustarlo dentro del HTML (así el
    archivo de la factura funciona solo, sin depender de otra ruta)."""
    ruta_logo = _ruta_logo()
    if not ruta_logo:
        return None
    with open(ruta_logo, "rb") as f:
        datos = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/png;base64,{datos}"


def generar_factura_html(venta_id, tipo="zapateria"):
    """Genera el HTML de la venta indicada y devuelve la ruta del archivo creado."""
    os.makedirs(CARPETA_FACTURAS, exist_ok=True)

    v = _cargar_venta(venta_id, tipo)
    fecha, total = v["fecha"], v["total"]
    cliente_nombre, cliente_telefono, cliente_nit = (
        v["cliente_nombre"], v["cliente_telefono"], v["cliente_nit"])

    filas_html = ""
    for nombre_producto, cantidad, precio_unitario, subtotal in v["detalle"]:
        filas_html += f"""
        <tr>
            <td>{html.escape(str(nombre_producto))}</td>
            <td class="centro">{_fmt_cant(cantidad)}</td>
            <td class="derecha">{formato_precio(precio_unitario)}</td>
            <td class="derecha">{formato_precio(subtotal)}</td>
        </tr>"""

    area_html = "<p><strong>Área:</strong> Peletería</p>" if _es_pel(tipo) else ""
    credito_html = ""
    if v["forma_pago"] == "Crédito":
        saldo = max(v["total"] - v["abonado"], 0)
        credito_html = f"""
                <tr>
                    <td colspan="3" class="derecha">Abonado</td>
                    <td class="derecha">{formato_precio(v['abonado'])}</td>
                </tr>
                <tr class="total-fila">
                    <td colspan="3" class="derecha">SALDO PENDIENTE</td>
                    <td class="derecha">{formato_precio(saldo)}</td>
                </tr>"""

    logo_data_uri = _logo_base64()
    logo_html = f'<img src="{logo_data_uri}" class="logo" alt="logo">' if logo_data_uri else ""

    plantilla = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Factura #{venta_id:05d} - {html.escape(NOMBRE_NEGOCIO)}</title>
<style>
    :root {{
        --accent: {COLOR_ACCENT};
        --accent-hover: {COLOR_ACCENT_HOVER};
        --texto: {COLOR_TEXTO};
        --texto-suave: {COLOR_TEXTO_SUAVE};
        --fondo: {COLOR_FONDO};
        --fila-alt: {COLOR_FILA_ALT};
    }}
    * {{ box-sizing: border-box; }}
    body {{
        font-family: 'Segoe UI', Arial, sans-serif;
        background: var(--fondo);
        color: var(--texto);
        margin: 0;
        padding: 24px;
    }}
    .hoja {{
        max-width: 720px;
        margin: 0 auto;
        background: #ffffff;
        border-radius: 10px;
        padding: 32px 40px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.08);
    }}
    .encabezado {{
        display: flex;
        align-items: center;
        gap: 16px;
        border-bottom: 3px solid var(--accent);
        padding-bottom: 16px;
        margin-bottom: 24px;
    }}
    .logo {{ height: 70px; width: auto; border-radius: 6px; }}
    .titulo-negocio h1 {{
        margin: 0;
        font-size: 20px;
        color: var(--texto);
    }}
    .titulo-negocio p {{
        margin: 3px 0 0;
        font-size: 13px;
        color: var(--texto-suave);
    }}
    .datos-factura {{
        display: flex;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 24px;
        margin-bottom: 24px;
    }}
    .bloque h3 {{
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--accent-hover);
        margin: 0 0 6px;
    }}
    .bloque p {{ margin: 2px 0; font-size: 14px; }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 20px;
    }}
    thead th {{
        background: var(--accent);
        color: #ffffff;
        text-align: left;
        padding: 10px 12px;
        font-size: 13px;
    }}
    tbody td {{
        padding: 10px 12px;
        font-size: 14px;
        border-bottom: 1px solid #eee;
    }}
    tbody tr:nth-child(even) {{ background: var(--fila-alt); }}
    .centro {{ text-align: center; }}
    .derecha {{ text-align: right; }}
    .total-fila td {{
        font-weight: bold;
        font-size: 16px;
        border-top: 2px solid var(--accent);
        border-bottom: none;
    }}
    .pie {{
        text-align: center;
        color: var(--texto-suave);
        font-size: 13px;
        margin-top: 24px;
    }}
    .botones-no-imprimir {{
        max-width: 720px;
        margin: 0 auto 16px;
        text-align: right;
    }}
    .botones-no-imprimir button {{
        background: var(--accent);
        color: #fff;
        border: none;
        padding: 10px 18px;
        border-radius: 6px;
        font-size: 14px;
        cursor: pointer;
    }}
    .botones-no-imprimir button:hover {{ background: var(--accent-hover); }}
    @media print {{
        body {{ background: #ffffff; padding: 0; }}
        .hoja {{ box-shadow: none; border-radius: 0; max-width: 100%; }}
        .botones-no-imprimir {{ display: none; }}
    }}
</style>
</head>
<body>
    <div class="botones-no-imprimir">
        <button onclick="window.print()">🖨 Imprimir / Guardar como PDF</button>
    </div>
    <div class="hoja">
        <div class="encabezado">
            {logo_html}
            <div class="titulo-negocio">
                <h1>{html.escape(NOMBRE_NEGOCIO)}</h1>
                <p>NIT: {html.escape(NIT_NEGOCIO)}</p>
                <p>{html.escape(CIUDAD_NEGOCIO)}</p>
                <p>Teléfono: {html.escape(TELEFONO_NEGOCIO)}</p>
            </div>
        </div>

        <div class="datos-factura">
            <div class="bloque">
                <h3>Factura</h3>
                <p><strong>N.º:</strong> {venta_id:05d}</p>
                <p><strong>Fecha:</strong> {html.escape(str(fecha))}</p>
                {area_html}
            </div>
            <div class="bloque">
                <h3>Cliente</h3>
                <p><strong>Nombre:</strong> {html.escape(cliente_nombre or '-')}</p>
                <p><strong>Teléfono:</strong> {html.escape(cliente_telefono or '-')}</p>
                <p><strong>NIT:</strong> {html.escape(cliente_nit or '-')}</p>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Producto</th>
                    <th class="centro">Cant.</th>
                    <th class="derecha">P. Unitario</th>
                    <th class="derecha">Subtotal</th>
                </tr>
            </thead>
            <tbody>
                {filas_html}
                <tr class="total-fila">
                    <td colspan="3" class="derecha">TOTAL</td>
                    <td class="derecha">{formato_precio(total)}</td>
                </tr>{credito_html}
            </tbody>
        </table>

        <p class="pie">¡Gracias por su compra!</p>
    </div>
</body>
</html>"""

    ruta_html = os.path.join(CARPETA_FACTURAS, f"factura{_sufijo(tipo)}_{venta_id:05d}.html")
    with open(ruta_html, "w", encoding="utf-8") as f:
        f.write(plantilla)

    return ruta_html


def abrir_factura(ruta_html):
    """Abre la factura en el navegador predeterminado de Windows."""
    try:
        os.startfile(ruta_html)  # Windows
    except AttributeError:
        if sys.platform == "darwin":
            subprocess.run(["open", ruta_html])
        else:
            subprocess.run(["xdg-open", ruta_html])


def _txt(valor):
    """Texto seguro para el PDF (las fuentes básicas solo aceptan latin-1)."""
    texto = "-" if valor in (None, "") else str(valor)
    return texto.encode("latin-1", "replace").decode("latin-1")


def generar_factura_pdf(venta_id, tipo="zapateria"):
    """Genera la factura en PDF y devuelve la ruta del archivo."""
    try:
        from fpdf import FPDF
    except ImportError:
        raise RuntimeError("Falta instalar fpdf2. En la terminal ejecuta: pip install fpdf2")

    os.makedirs(CARPETA_FACTURAS, exist_ok=True)

    v = _cargar_venta(venta_id, tipo)
    fecha, total = v["fecha"], v["total"]
    cli_nombre, cli_tel, cli_nit = v["cliente_nombre"], v["cliente_telefono"], v["cliente_nit"]
    detalle = v["detalle"]

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ---- Franja superior: logo + datos de la empresa + número y fecha ----
    ALTO_FRANJA = 34
    pdf.set_fill_color(248, 195, 189)
    pdf.rect(0, 0, 210, ALTO_FRANJA, style="F")

    x_texto = 15  # dónde empiezan los datos de la empresa
    ruta_logo = _ruta_logo()
    if ruta_logo:
        try:
            info = pdf.image(ruta_logo, x=15, y=6, h=22)
            ancho_logo = getattr(info, "rendered_width", None) or 22
            x_texto = 15 + ancho_logo + 5
        except Exception:
            x_texto = 15

    # Datos de la empresa al lado del logo
    pdf.set_text_color(74, 54, 54)
    pdf.set_xy(x_texto, 8)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(95, 6, _txt(NOMBRE_NEGOCIO))
    pdf.set_xy(x_texto, 15)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(95, 5, _txt(f"NIT: {NIT_NEGOCIO}"))
    pdf.set_xy(x_texto, 20)
    pdf.cell(95, 5, _txt(CIUDAD_NEGOCIO))

    # Número de factura y fecha a la derecha
    pdf.set_xy(140, 8)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(55, 7, _txt(f"Factura N.º {venta_id:05d}"), align="R")
    pdf.set_xy(140, 16)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(55, 6, _txt(fecha), align="R")
    if _es_pel(tipo):
        pdf.set_xy(140, 22)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(55, 6, _txt("PELETERÍA"), align="R")

    pdf.set_y(ALTO_FRANJA + 8)

    # ---- Datos del cliente ----
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(201, 107, 107)
    pdf.cell(0, 6, "CLIENTE", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(74, 54, 54)
    pdf.cell(0, 6, _txt(f"Nombre: {cli_nombre or '-'}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, _txt(f"Teléfono: {cli_tel or '-'}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, _txt(f"NIT: {cli_nit or '-'}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # ---- Tabla de productos ----
    anchos = (90, 20, 35, 35)
    pdf.set_fill_color(224, 135, 135)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(anchos[0], 9, "Producto", fill=True)
    pdf.cell(anchos[1], 9, "Cant.", align="C", fill=True)
    pdf.cell(anchos[2], 9, "P. Unitario", align="R", fill=True)
    pdf.cell(anchos[3], 9, "Subtotal", align="R", fill=True, new_x="LMARGIN", new_y="NEXT")

    pdf.set_text_color(74, 54, 54)
    pdf.set_font("Helvetica", "", 10)
    for i, (nombre, cant, precio, sub) in enumerate(detalle):
        if i % 2 == 0:
            pdf.set_fill_color(255, 248, 246)
        else:
            pdf.set_fill_color(255, 255, 255)
        nombre_corto = _txt(nombre)[:48]
        pdf.cell(anchos[0], 8, nombre_corto, fill=True)
        pdf.cell(anchos[1], 8, _fmt_cant(cant), align="C", fill=True)
        pdf.cell(anchos[2], 8, formato_precio(precio), align="R", fill=True)
        pdf.cell(anchos[3], 8, formato_precio(sub), align="R", fill=True,
                 new_x="LMARGIN", new_y="NEXT")

    # ---- Total ----
    pdf.ln(2)
    pdf.set_draw_color(224, 135, 135)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(sum(anchos[:3]), 10, "TOTAL", align="R")
    pdf.cell(anchos[3], 10, formato_precio(total), align="R", new_x="LMARGIN", new_y="NEXT")

    # ---- Si es a crédito: abonado y saldo ----
    if v["forma_pago"] == "Crédito":
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(sum(anchos[:3]), 7, "Abonado", align="R")
        pdf.cell(anchos[3], 7, formato_precio(v["abonado"]), align="R",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(sum(anchos[:3]), 8, "SALDO PENDIENTE", align="R")
        pdf.cell(anchos[3], 8, formato_precio(max(total - v["abonado"], 0)), align="R",
                 new_x="LMARGIN", new_y="NEXT")

    pdf.ln(8)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(122, 99, 99)
    pdf.cell(0, 6, _txt("¡Gracias por su compra!"), align="C")

    ruta_pdf = os.path.join(CARPETA_FACTURAS, f"factura{_sufijo(tipo)}_{venta_id:05d}.pdf")
    pdf.output(ruta_pdf)
    return ruta_pdf


# ---------------------------------------------------------------------------
# TICKET POS (80 mm): formato para impresora térmica
# ---------------------------------------------------------------------------
TICKET_ANCHO_MM = 80
TICKET_MARGEN_MM = 4


def _ticket_partir(pdf, texto, estilo, tam, ancho_max):
    """Parte un texto en varias líneas para que quepa en el ancho del ticket."""
    pdf.set_font("Helvetica", estilo, tam)
    lineas, actual = [], ""
    for palabra in _txt(texto).split():
        # Palabras larguísimas (más anchas que el ticket) se cortan
        while len(palabra) > 1 and pdf.get_string_width(palabra) > ancho_max:
            n = len(palabra)
            while n > 1 and pdf.get_string_width(palabra[:n]) > ancho_max:
                n -= 1
            if actual:
                lineas.append(actual)
                actual = ""
            lineas.append(palabra[:n])
            palabra = palabra[n:]
        prueba = (actual + " " + palabra).strip()
        if pdf.get_string_width(prueba) <= ancho_max:
            actual = prueba
        else:
            if actual:
                lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas or [""]


def generar_ticket_pos(venta_id, tipo="zapateria"):
    """Genera el ticket POS (PDF de 80 mm de ancho, alto automático) y
    devuelve la ruta del archivo."""
    try:
        from fpdf import FPDF
    except ImportError:
        raise RuntimeError("Falta instalar fpdf2. En la terminal ejecuta: pip install fpdf2")

    os.makedirs(CARPETA_FACTURAS, exist_ok=True)

    v = _cargar_venta(venta_id, tipo)
    fecha, total = v["fecha"], v["total"]
    cli_nombre, cli_nit = v["cliente_nombre"], v["cliente_nit"]
    forma_pago, metodo_pago, estado = v["forma_pago"], v["metodo_pago"], v["estado"]
    abonado = v["abonado"]
    detalle = v["detalle"]

    margen = TICKET_MARGEN_MM
    util = TICKET_ANCHO_MM - 2 * margen

    # PDF "medidor": sirve para saber cuánto mide cada texto y calcular el alto total
    medidor = FPDF(unit="mm", format=(TICKET_ANCHO_MM, 200))
    medidor.add_page()

    ops = []   # (modo, izquierda, derecha, estilo, tamaño)

    def centrado(texto, estilo="", tam=8):
        for linea in _ticket_partir(medidor, texto, estilo, tam, util):
            ops.append(("c", linea, "", estilo, tam))

    def izquierda(texto, estilo="", tam=8):
        for linea in _ticket_partir(medidor, texto, estilo, tam, util):
            ops.append(("l", linea, "", estilo, tam))

    def izq_der(a, b, estilo="", tam=8):
        ops.append(("lr", _txt(a), _txt(b), estilo, tam))

    def separador():
        ops.append(("sep", "", "", "", 3))

    centrado(NOMBRE_NEGOCIO, "B", 10)
    centrado(f"NIT: {NIT_NEGOCIO}")
    centrado(CIUDAD_NEGOCIO)
    centrado(f"Tel. {TELEFONO_NEGOCIO}")
    separador()
    centrado(f"TICKET DE VENTA N.º {venta_id:05d}", "B", 9)
    if _es_pel(tipo):
        centrado("PELETERÍA", "B", 8)
    centrado(str(fecha)[:19])
    if cli_nombre:
        izquierda(f"Cliente: {cli_nombre}")
    if cli_nit:
        izquierda(f"NIT/CC: {cli_nit}")
    separador()

    for nombre, cant, precio, sub in detalle:
        izquierda(nombre, "B", 8)
        izq_der(f"  {_fmt_cant(cant)} x {formato_precio(precio)}", formato_precio(sub))
    separador()

    izq_der("TOTAL", formato_precio(total), "B", 11)
    izq_der("Pago:", f"{forma_pago} ({metodo_pago})")
    if forma_pago == "Crédito":
        izq_der("Abonado:", formato_precio(abonado))
        izq_der("Saldo:", formato_precio(max(total - abonado, 0)), "B", 9)
    if estado != "Activa":
        separador()
        centrado(f"*** VENTA {estado.upper()} ***", "B", 9)
    separador()
    centrado("¡Gracias por su compra!", "B", 9)

    def alto_de(op):
        return 3 if op[0] == "sep" else op[4] * 0.42 + 0.8

    alto = sum(alto_de(op) for op in ops) + 2 * margen

    pdf = FPDF(unit="mm", format=(TICKET_ANCHO_MM, alto))
    pdf.set_margins(margen, margen, margen)
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    pdf.set_text_color(0, 0, 0)

    y = margen
    for modo, izq, der, estilo, tam in ops:
        h = alto_de((modo, izq, der, estilo, tam))
        if modo == "sep":
            pdf.set_draw_color(0, 0, 0)
            pdf.set_dash_pattern(dash=0.6, gap=0.8)
            pdf.line(margen, y + h / 2, TICKET_ANCHO_MM - margen, y + h / 2)
            pdf.set_dash_pattern()
        else:
            pdf.set_font("Helvetica", estilo, tam)
            pdf.set_xy(margen, y)
            if modo == "c":
                pdf.cell(util, h, izq, align="C")
            elif modo == "l":
                pdf.cell(util, h, izq, align="L")
            else:
                pdf.cell(util, h, izq, align="L")
                pdf.set_xy(margen, y)
                pdf.cell(util, h, der, align="R")
        y += h

    ruta = os.path.join(CARPETA_FACTURAS, f"ticket_pos{_sufijo(tipo)}_{venta_id:05d}.pdf")
    pdf.output(ruta)
    return ruta


def generar_factura(venta_id, formato="PDF", tipo="zapateria"):
    """Genera la factura en el formato pedido: 'PDF' (A4) o 'POS' / 'Ticket POS'
    (80 mm). Devuelve la ruta del archivo. tipo: 'zapateria' o 'peleteria'."""
    if "POS" in str(formato).upper() or "TICKET" in str(formato).upper():
        return generar_ticket_pos(venta_id, tipo)
    return generar_factura_pdf(venta_id, tipo)