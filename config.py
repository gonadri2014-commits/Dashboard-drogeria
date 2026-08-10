"""
CASHFLOW ENTERPRISE — Droguería del Sud
Configuración central v3.0 — Integración SAP + Tiempo Real
"""
import os

# ── Empresa
EMPRESA        = "Droguería del Sud"
EMPRESA_CUIT   = "30-53888062-7"
EMPRESA_ADDR   = "Humberto I 1868, CABA | Córdoba | Bahía Blanca | Santa Fe"
MONEDA         = "ARS"
AÑO            = 2025

# ── Escala real de la empresa (datos BCRA / Nosis)
FACTURACION_ANUAL_BASE = 108_000_000_000   # ~$108B ARS (≈ USD 90M)
EMPLEADOS              = 1_100
FARMACIAS_CLIENTES     = 9_500
LABORATORIOS_PROV      = 400
PEDIDOS_DIARIOS        = 8_500
UNIDADES_ANUALES       = 195_000_000
MARKET_SHARE_PCT       = 24

# ── Umbrales de alerta (en pesos — escala real DdS)
SALDO_MINIMO_CRITICO   =   500_000_000   # $500M — rojo
SALDO_MINIMO_ALERTA    = 1_500_000_000   # $1.5B — amarillo
SALDO_RECOMENDADO      = 4_000_000_000   # $4B  — verde

# ── SAP
SAP_MODE = os.getenv("SAP_MODE", "demo")   # "demo" | "live"
SAP_HOST = os.getenv("SAP_HOST", "https://sap-dds.delsud.com.ar:50000")

# ── Feriados Argentina 2025
FERIADOS_2025 = [
    "2025-01-01","2025-03-03","2025-03-04","2025-03-24",
    "2025-04-02","2025-04-17","2025-04-18","2025-05-01",
    "2025-05-25","2025-06-16","2025-06-20","2025-07-09",
    "2025-08-18","2025-10-12","2025-11-20","2025-12-08","2025-12-25",
]

# ── Estacionalidad (sector farmacéutico)
ESTACIONALIDAD = {
    "Enero":1.00,"Febrero":0.92,"Marzo":0.95,"Abril":0.97,
    "Mayo":1.02,"Junio":1.10,"Julio":0.98,"Agosto":0.95,
    "Septiembre":1.00,"Octubre":1.05,"Noviembre":1.08,"Diciembre":1.35,
}

# ── Condiciones de cobro (farmacias)
CONDICIONES_COBRO = {"contado":0.40,"dias_30":0.35,"dias_60":0.15,"dias_90":0.10}

MESES_AGUINALDO = [6, 12]

# ── Formatos banco
FORMATOS_BANCO = {
    "nacion":    {"nombre":"Banco Nación",     "col_fecha":"Fecha",    "col_desc":"Descripción","col_importe":"Importe","col_saldo":"Saldo"},
    "galicia":   {"nombre":"Banco Galicia",     "col_fecha":"Fecha Op.","col_desc":"Concepto",   "col_importe":"Importe","col_saldo":"Saldo"},
    "bbva":      {"nombre":"BBVA Argentina",    "col_fecha":"Fecha",    "col_desc":"Descripción","col_importe":"Importe","col_saldo":"Saldo Ctacte"},
    "santander": {"nombre":"Santander",         "col_fecha":"Fecha",    "col_desc":"Descripción","col_importe":"Monto",  "col_saldo":"Saldo"},
    "macro":     {"nombre":"Banco Macro",       "col_fecha":"Fecha",    "col_desc":"Descripcion","col_importe":"Credito","col_saldo":"Saldo"},
    "icbc":      {"nombre":"ICBC",              "col_fecha":"Fecha",    "col_desc":"Detalle",    "col_importe":"Importe","col_saldo":"Saldo"},
    "credicoop": {"nombre":"Banco Credicoop",   "col_fecha":"Fecha",    "col_desc":"Descripción","col_importe":"Importe","col_saldo":"Saldo"},
    "supervielle":{"nombre":"Banco Supervielle","col_fecha":"Fecha",    "col_desc":"Descripción","col_importe":"Importe","col_saldo":"Saldo"},
    "generico":  {"nombre":"Banco Genérico",    "col_fecha":None,       "col_desc":None,         "col_importe":None,    "col_saldo":None},
}

CATEGORIAS_KEYWORDS = {
    "Cobranzas":       ["TRANSF RECIB","ACREDITA","COBRO","CLIENTE","FARMA","PAGO RECIB","CR ","FARMACITY","DR AHORRO"],
    "Sueldos":         ["SUELDO","REMUN","HABERES","REMUNER"],
    "Cargas Sociales": ["AFIP SIPA","OBRA SOCIAL","ART ","ANSES","CARGAS SOC"],
    "AFIP":            ["AFIP","IVA","GANANCIAS","INGRESOS BRUTOS","IIBB","ARCA","SICORE"],
    "Préstamos":       ["CUOTA PREST","AMORT","VENCIM PREST","PRESTAMO","CREDITO","CREDICOOP","SUPERVIELLE"],
    "Laboratorios":    ["PROVEEDOR","PAGO A ","LABORAT","DROGUERIA","ROEMMERS","BAGO","GADOR","PFIZER","ROCHE","NOVARTIS","MSD","ABBOTT"],
    "Cheques":         ["CHEQUE","CHQ","PAGO CHQ","DEBITO CHQ"],
    "Servicios":       ["LUZ","GAS","INTERNET","EDESUR","METROGAS","TELECOM","SERVICIO"],
    "Alquiler":        ["ALQUILER","LOCAC","RENT"],
    "Bancarios":       ["COMISION","MANTENIMIENTO","IMP DEBITO","IMP CREDITO","SELLADO"],
    "Inversiones":     ["INTERES ACRED","RENDIMIENTO","PLAZO FIJO","FCI","CAUCIÓN"],
    "Otros Egresos":   [],
}

COLORES = {
    "verde":"#00C49F","rojo":"#FF4D6D","amarillo":"#FFB347",
    "azul":"#2E75B6","gris":"#8884d8","naranja":"#FF8042",
    "verde_oscuro":"#166534","azul_oscuro":"#1F3864",
}

EXPORT_DIR = "exports"
print(f"✅ Config Enterprise cargada — {EMPRESA} | CUIT {EMPRESA_CUIT} | SAP MODE: {SAP_MODE.upper()}")
