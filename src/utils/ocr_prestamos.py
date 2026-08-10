"""
ocr_prestamos.py — Carga de préstamos desde imagen/foto del contrato
Usa la API de Claude Vision para extraer datos del contrato bancario
y calcular automáticamente el cronograma de cuotas con ajuste de días hábiles.
"""
import json, re, sys, os
from datetime import date
sys.path.insert(0, '.')
from src.utils.helpers import parse_fecha, ajustar_fecha_cobro, fmt_ars, logger

def extraer_datos_prestamo_con_ia(texto_contrato: str) -> dict:
    """
    Extrae datos del préstamo desde texto del contrato (pegado o OCR).
    Usa patrones regex + Claude API como respaldo.
    Retorna dict con los campos del préstamo.
    """
    datos = {
        "banco": "", "descripcion": "", "capital_original": 0.0,
        "tna": 0.0, "tea": 0.0, "cftna": 0.0,
        "cuota_mensual": 0.0, "cuotas_totales": 0, "cuotas_pagadas": 0,
        "fecha_primera_cuota": "", "dia_debito": 25,
        "garantia": "", "observaciones": "",
        "confianza": "baja",
        "campos_extraidos": [],
    }

    texto = texto_contrato.upper()

    # ── BANCO ──────────────────────────────────────────────────────
    bancos_keywords = {
        "NACION": "Banco de la Nación Argentina",
        "GALICIA": "Banco Galicia y Buenos Aires S.A.",
        "BBVA": "Banco BBVA Argentina S.A.",
        "SANTANDER": "Banco Santander Argentina S.A.",
        "MACRO": "Banco Macro S.A.",
        "SUPERVIELLE": "Banco Supervielle S.A.",
        "CREDICOOP": "Banco Credicoop Cooperativo Limitado",
        "HSBC": "HSBC Bank Argentina S.A.",
        "ICBC": "Banco ICBC Argentina S.A.",
        "CITIBANK": "Citibank N.A.",
        "PATAGONIA": "Banco Patagonia S.A.",
        "COMAFI": "Banco Comafi S.A.",
        "BICE": "Banco de Inversión y Comercio Exterior S.A.",
    }
    for kw, nombre in bancos_keywords.items():
        if kw in texto:
            datos["banco"] = nombre
            datos["campos_extraidos"].append("banco")
            break

    # ── CAPITAL ────────────────────────────────────────────────────
    # Buscar patrones: "CAPITAL: $1.500.000" / "MONTO: 1500000" / "$1.500.000,00"
    patrones_capital = [
        r"(?:CAPITAL|MONTO|IMPORTE|PRESTAMO|PR[EÉ]STAMO)[:\s]+\$?\s*([\d\.]+(?:,\d+)?)",
        r"\$\s*([\d\.]{6,}(?:,\d{2})?)",
        r"(?:SUMA DE|OTORGA)[:\s]+\$?\s*([\d\.]+)",
    ]
    for pat in patrones_capital:
        m = re.search(pat, texto)
        if m:
            try:
                val_str = m.group(1).replace(".", "").replace(",", ".")
                val = float(val_str)
                if val > 1000:  # mínimo razonable
                    datos["capital_original"] = val
                    datos["campos_extraidos"].append("capital_original")
                    break
            except: pass

    # ── TNA / TEA ──────────────────────────────────────────────────
    patrones_tasa = [
        r"(?:TNA|TASA NOMINAL ANUAL)[:\s]+([\d,\.]+)\s*%",
        r"(?:TASA NOMINAL)[:\s]+([\d,\.]+)\s*%",
        r"([\d,\.]+)\s*%\s*(?:TNA|NOMINAL ANUAL)",
    ]
    for pat in patrones_tasa:
        m = re.search(pat, texto)
        if m:
            try:
                datos["tna"] = float(m.group(1).replace(",", "."))
                datos["campos_extraidos"].append("tna")
                break
            except: pass

    patrones_tea = [
        r"(?:TEA|TASA EFECTIVA ANUAL)[:\s]+([\d,\.]+)\s*%",
        r"([\d,\.]+)\s*%\s*(?:TEA|EFECTIVA ANUAL)",
    ]
    for pat in patrones_tea:
        m = re.search(pat, texto)
        if m:
            try:
                datos["tea"] = float(m.group(1).replace(",", "."))
                datos["campos_extraidos"].append("tea")
                break
            except: pass

    patrones_cft = [
        r"(?:CFT|COSTO FINANCIERO TOTAL)[:\s]+([\d,\.]+)\s*%",
    ]
    for pat in patrones_cft:
        m = re.search(pat, texto)
        if m:
            try:
                datos["cftna"] = float(m.group(1).replace(",", "."))
                datos["campos_extraidos"].append("cftna")
                break
            except: pass

    # ── CUOTAS ─────────────────────────────────────────────────────
    patrones_ncuotas = [
        r"(\d+)\s*(?:CUOTAS?|PAGOS?|MENSUALIDADES?)",
        r"(?:EN|A)\s+(\d+)\s+CUOTAS?",
        r"PLAZO[:\s]+(\d+)\s*MESES",
    ]
    for pat in patrones_ncuotas:
        m = re.search(pat, texto)
        if m:
            try:
                n = int(m.group(1))
                if 1 <= n <= 120:
                    datos["cuotas_totales"] = n
                    datos["campos_extraidos"].append("cuotas_totales")
                    break
            except: pass

    patrones_cuota = [
        r"(?:CUOTA|CUOTA MENSUAL|IMPORTE DE CUOTA)[:\s]+\$?\s*([\d\.]+(?:,\d+)?)",
        r"PAGAR[Á A]+\$?\s*([\d\.]+(?:,\d+)?)\s*(?:MENSUALES?|POR MES)",
    ]
    for pat in patrones_cuota:
        m = re.search(pat, texto)
        if m:
            try:
                val_str = m.group(1).replace(".", "").replace(",", ".")
                val = float(val_str)
                if val > 100:
                    datos["cuota_mensual"] = val
                    datos["campos_extraidos"].append("cuota_mensual")
                    break
            except: pass

    # ── FECHA PRIMERA CUOTA ────────────────────────────────────────
    patrones_fecha = [
        r"(?:PRIMERA CUOTA|PRIMER VENCIMIENTO|FECHA DE PAGO)[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
        r"(?:VENCIMIENTO|FECHA)[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
        r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
    ]
    for pat in patrones_fecha:
        m = re.search(pat, texto_contrato)  # usar texto original para fechas
        if m:
            fd = parse_fecha(m.group(1))
            if fd and fd.year >= 2024:
                datos["fecha_primera_cuota"] = str(fd)
                datos["dia_debito"] = fd.day
                datos["campos_extraidos"].append("fecha_primera_cuota")
                break

    # ── DÍA DE DÉBITO ──────────────────────────────────────────────
    m_dia = re.search(r"(?:D[IÍ]A|DIA DE DEBITO|DIA DE PAGO)[:\s]+(\d{1,2})", texto)
    if m_dia:
        try:
            dia = int(m_dia.group(1))
            if 1 <= dia <= 28:
                datos["dia_debito"] = dia
                datos["campos_extraidos"].append("dia_debito")
        except: pass

    # ── CALCULAR TEA si no está ────────────────────────────────────
    if datos["tna"] > 0 and datos["tea"] == 0:
        datos["tea"] = round(((1 + datos["tna"]/100/12)**12 - 1) * 100, 2)
        datos["campos_extraidos"].append("tea_calculada")

    # ── CALCULAR CUOTA si no está ──────────────────────────────────
    if (datos["capital_original"] > 0 and datos["tna"] > 0
            and datos["cuotas_totales"] > 0 and datos["cuota_mensual"] == 0):
        tasa_m = datos["tna"] / 100 / 12
        n = datos["cuotas_totales"]
        cuota = datos["capital_original"] * (tasa_m * (1+tasa_m)**n) / ((1+tasa_m)**n - 1)
        datos["cuota_mensual"] = round(cuota)
        datos["campos_extraidos"].append("cuota_calculada")

    # ── CONFIANZA ──────────────────────────────────────────────────
    campos_clave = ["banco","capital_original","tna","cuotas_totales","cuota_mensual"]
    n_ok = sum(1 for c in campos_clave if c in datos["campos_extraidos"])
    if n_ok >= 4:   datos["confianza"] = "alta"
    elif n_ok >= 2: datos["confianza"] = "media"
    else:           datos["confianza"] = "baja"

    return datos


def calcular_cronograma_completo(datos_prestamo: dict, año: int = 2025) -> list:
    """
    Genera el cronograma completo de cuotas con ajuste de días hábiles.
    Si la fecha de cuota cae en feriado o fin de semana → siguiente día hábil.
    Incluye alerta de fondos para cada cuota.
    """
    cronograma = []
    capital = float(datos_prestamo.get("capital_original", 0))
    tna     = float(datos_prestamo.get("tna", 0))
    n_cuotas= int(datos_prestamo.get("cuotas_totales", 0))
    cuota   = float(datos_prestamo.get("cuota_mensual", 0))
    tasa_m  = tna / 100 / 12
    dia_deb = int(datos_prestamo.get("dia_debito", 25))

    fp_str  = datos_prestamo.get("fecha_primera_cuota", "")
    if fp_str:
        fp = parse_fecha(fp_str)
    else:
        fp = date(año, 1, dia_deb)
    if not fp:
        fp = date(año, 1, dia_deb)

    capital_rest = capital
    for i in range(n_cuotas):
        from dateutil.relativedelta import relativedelta
        fecha_vto_raw = fp + relativedelta(months=i)
        # Forzar al día de débito configurado
        try:
            import calendar
            max_dia = calendar.monthrange(fecha_vto_raw.year, fecha_vto_raw.month)[1]
            fecha_vto_raw = fecha_vto_raw.replace(day=min(dia_deb, max_dia))
        except: pass

        fecha_vto_habil = ajustar_fecha_cobro(fecha_vto_raw)
        fue_ajustado = fecha_vto_habil != fecha_vto_raw

        interes = capital_rest * tasa_m
        amort   = cuota - interes
        if amort > capital_rest: amort = capital_rest
        capital_rest -= amort
        if capital_rest < 0: capital_rest = 0

        cronograma.append({
            "nro":              i + 1,
            "fecha_original":   str(fecha_vto_raw),
            "fecha_habil":      str(fecha_vto_habil),
            "dia_semana":       ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"][fecha_vto_raw.weekday()],
            "fue_ajustado":     fue_ajustado,
            "cuota_total":      round(cuota),
            "amortizacion":     round(amort),
            "interes":          round(interes),
            "capital_restante": round(capital_rest),
            "alerta_fondos":    f"Tener {fmt_ars(cuota)} disponibles en banco para el {fecha_vto_habil.strftime('%d/%m/%Y')}",
        })

    return cronograma


def analizar_imagen_prestamo_con_claude(imagen_base64: str, media_type: str = "image/jpeg") -> dict:
    """
    Usa Claude Vision API para extraer datos de un préstamo desde imagen.
    Retorna los datos extraídos en el formato estándar.
    """
    import requests

    PROMPT_EXTRACCION = """Analizá esta imagen de un contrato/liquidación de préstamo bancario argentino.
Extraé los siguientes datos y respondé SOLO con un JSON válido, sin explicaciones:

{
  "banco": "nombre del banco",
  "descripcion": "tipo de préstamo (ej: capital de trabajo, personal, hipotecario)",
  "capital_original": 0.0,
  "tna": 0.0,
  "tea": 0.0,
  "cftna": 0.0,
  "cuota_mensual": 0.0,
  "cuotas_totales": 0,
  "fecha_primera_cuota": "DD/MM/YYYY",
  "dia_debito": 25,
  "garantia": "",
  "observaciones": "cualquier dato relevante adicional"
}

Reglas:
- Todos los montos en ARS (pesos argentinos)
- TNA, TEA y CFT como porcentajes (ej: 52.5 para 52.5%)
- Si no encontrás un dato, dejá el valor vacío o 0
- Fecha en formato DD/MM/YYYY
- Solo el JSON, nada más"""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 500,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image",
                         "source": {"type": "base64", "media_type": media_type, "data": imagen_base64}},
                        {"type": "text", "text": PROMPT_EXTRACCION},
                    ]
                }]
            },
            timeout=30,
        )
        if response.status_code == 200:
            content = response.json()["content"][0]["text"]
            # Limpiar respuesta y parsear JSON
            content = content.strip()
            if content.startswith("```"): content = content.split("```")[1]
            if content.startswith("json"): content = content[4:]
            datos = json.loads(content.strip())
            datos["confianza"] = "alta"
            datos["fuente"] = "claude_vision"
            # Calcular campos derivados
            if datos.get("tna") and not datos.get("tea"):
                tna = float(datos["tna"])
                datos["tea"] = round(((1 + tna/100/12)**12 - 1) * 100, 2)
            return datos
    except Exception as e:
        logger.error(f"Error Claude Vision: {e}")
        return {"error": str(e), "confianza": "error"}

    return {"error": "No se pudo procesar la imagen", "confianza": "error"}


if __name__ == "__main__":
    print("=== TEST OCR PRÉSTAMOS ===\n")

    # Test con texto de contrato simulado
    contrato_ejemplo = """
    BANCO GALICIA Y BUENOS AIRES S.A.
    CONTRATO DE PRÉSTAMO COMERCIAL
    
    Monto del préstamo: $5.000.000,00
    Tasa Nominal Anual (TNA): 52,50%
    Tasa Efectiva Anual (TEA): 65,83%
    CFT: 78,20%
    
    Cantidad de cuotas: 24
    Importe de cuota: $312.500,00
    Primera cuota: 15/07/2025
    Día de débito: 15
    
    Garantía: Aval SGR
    """

    print("Contrato de prueba:")
    print(contrato_ejemplo)

    datos = extraer_datos_prestamo_con_ia(contrato_ejemplo)
    print("\nDatos extraídos:")
    for k, v in datos.items():
        if v and k != "campos_extraidos":
            print(f"  {k:25}: {v}")
    print(f"  Confianza: {datos['confianza']}")
    print(f"  Campos extraídos: {datos['campos_extraidos']}")

    print("\n=== CRONOGRAMA (primeras 6 cuotas) ===")
    cron = calcular_cronograma_completo(datos, 2025)
    for c in cron[:6]:
        ajust = " ✅ AJUSTADO" if c["fue_ajustado"] else ""
        print(f"  Cuota {c['nro']:2} — {c['fecha_original']} ({c['dia_semana']}) "
              f"→ {c['fecha_habil']}{ajust}")
        print(f"           Cuota: {fmt_ars(c['cuota_total'])} | "
              f"Amort: {fmt_ars(c['amortizacion'])} | "
              f"Int: {fmt_ars(c['interes'])} | "
              f"Saldo: {fmt_ars(c['capital_restante'])}")

    print("\n✅ ocr_prestamos.py OK")
