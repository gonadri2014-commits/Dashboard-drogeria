"""
datos_maestros.py — Catálogos y datos de referencia
- Lista completa de bancos argentinos
- Unidades de negocio de Droguería del Sud
- Tipos de inversión
- Datos simulados realistas
"""
import pandas as pd
import json, os
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import sys
sys.path.insert(0, '.')
from src.utils.helpers import nombre_mes, fmt_ars, logger

# ══════════════════════════════════════════════════════════════════════
# BANCOS ARGENTINOS — Lista completa BCRA
# ══════════════════════════════════════════════════════════════════════

BANCOS_ARGENTINA = [
    # Bancos públicos
    "Banco de la Nación Argentina",
    "Banco de la Provincia de Buenos Aires",
    "Banco de la Ciudad de Buenos Aires",
    "Banco de la Provincia de Córdoba",
    "Banco de la Pampa",
    "Banco de la Provincia del Neuquén",
    "Banco de la Pampa S.E.M.",
    "Banco de Corrientes S.A.",
    "Banco de Entre Ríos S.A.",
    "Banco de Formosa S.A.",
    "Banco de Inversión y Comercio Exterior S.A. (BICE)",
    "Banco de la Rioja S.A.",
    "Banco del Chubut S.A.",
    "Banco del Tucumán S.A.",
    "Banco Municipal de Rosario",
    "Banco Provincia de Tierra del Fuego",
    "Banco Provincia del Neuquén S.A.",
    # Bancos privados nacionales
    "Banco Credicoop Cooperativo Limitado",
    "Banco Galicia y Buenos Aires S.A.",
    "Banco Macro S.A.",
    "Banco Supervielle S.A.",
    "Banco Patagonia S.A.",
    "Banco de Valores S.A.",
    "Banco Hipotecario S.A.",
    "Banco de San Juan S.A.",
    "Banco del Sol S.A.",
    "Banco de Santa Cruz S.A.",
    "Banco de Santiago del Estero S.A.",
    "Banco Comafi S.A.",
    "Banco de Servicios y Transacciones S.A.",
    "Banco Meridian S.A.",
    "Banco Voii S.A.",
    "Nuevo Banco del Chaco S.A.",
    "Nuevo Banco de Entre Ríos S.A.",
    "Banco Mariva S.A.",
    "Banco de Servicios Financieros S.A.",
    "Banco CMF S.A.",
    # Bancos privados extranjeros
    "Banco BBVA Argentina S.A.",
    "Banco Santander Argentina S.A.",
    "HSBC Bank Argentina S.A.",
    "Citibank N.A.",
    "Banco ICBC Argentina S.A.",
    "Banco Itaú Argentina S.A.",
    "JPMorgan Chase Bank N.A.",
    "BancTrust & Co. International Limited",
    "Deutsche Bank S.A.",
    # Financieras y otros
    "American Express Argentina S.A.",
    "Banco Bradesco Argentina S.A.",
    "Banco de la Republica Oriental del Uruguay",
    "Banco do Brasil S.A.",
    "Reba Compañía Financiera S.A.",
    "YPF S.A.",
    "Tarjeta Naranja S.A.",
    "Tarjeta Cencosud S.A.",
    "PSA Finance Argentina Cía. Financiera S.A.",
    "Toyota Compañía Financiera de Argentina S.A.",
    "Otro / No listado",
]

# ══════════════════════════════════════════════════════════════════════
# UNIDADES DE NEGOCIO — Droguería del Sud
# ══════════════════════════════════════════════════════════════════════

UNIDADES_NEGOCIO = {
    "Medicamentos":    {"color": "#2E75B6", "pct_ingresos": 0.72, "pct_egresos": 0.75},
    "Cosmética":       {"color": "#E91E63", "pct_ingresos": 0.13, "pct_egresos": 0.12},
    "Nutrición":       {"color": "#FF9800", "pct_ingresos": 0.09, "pct_egresos": 0.08},
    "Veterinaria":     {"color": "#4CAF50", "pct_ingresos": 0.04, "pct_egresos": 0.03},
    "Otros":           {"color": "#9C27B0", "pct_ingresos": 0.02, "pct_egresos": 0.02},
}

# ══════════════════════════════════════════════════════════════════════
# INVERSIONES PROYECTADAS
# ══════════════════════════════════════════════════════════════════════

INVERSIONES_PATH = "./data/inversiones.json"

def inversiones_vacia() -> dict:
    return {
        "año": 2025,
        "items": []
    }

def cargar_inversiones() -> dict:
    if os.path.exists(INVERSIONES_PATH):
        with open(INVERSIONES_PATH) as f:
            return json.load(f)
    d = inversiones_vacia()
    guardar_inversiones(d)
    return d

def guardar_inversiones(data: dict):
    os.makedirs(os.path.dirname(INVERSIONES_PATH), exist_ok=True)
    with open(INVERSIONES_PATH, "w") as f:
        json.dump(data, f, indent=2, default=str)

def agregar_inversion(data: dict, descripcion: str, monto: float,
                      mes: int, tipo: str, unidad: str = "General",
                      observaciones: str = "") -> dict:
    nuevo_id = max([x.get("id", 0) for x in data["items"]], default=0) + 1
    data["items"].append({
        "id": nuevo_id,
        "descripcion": descripcion,
        "tipo": tipo,
        "unidad_negocio": unidad,
        "monto": float(monto),
        "mes": mes,
        "mes_nombre": nombre_mes(mes),
        "estado": "proyectado",
        "observaciones": observaciones,
    })
    return data

def resumen_inversiones_mensual(data: dict) -> pd.DataFrame:
    if not data.get("items"):
        return pd.DataFrame({"mes": range(1,13), "mes_nombre": [nombre_mes(m) for m in range(1,13)],
                             "total_inversiones": [0.0]*12})
    df = pd.DataFrame(data["items"])
    resumen = df.groupby(["mes","mes_nombre"])["monto"].sum().reset_index()
    resumen.columns = ["mes","mes_nombre","total_inversiones"]
    todos = pd.DataFrame({"mes": range(1,13), "mes_nombre": [nombre_mes(m) for m in range(1,13)]})
    return todos.merge(resumen, on=["mes","mes_nombre"], how="left").fillna(0)

def generar_inversiones_demo(año: int = 2025) -> dict:
    """Inversiones simuladas realistas para una droguería."""
    data = inversiones_vacia()
    items = [
        # (desc, monto, mes, tipo, unidad)
        ("Modernización sistema WMS depósito central", 85_000_000, 2, "TI/Sistemas", "General"),
        ("Flota vehículos refrigerados (3 unidades)",  120_000_000, 3, "Infraestructura", "Medicamentos"),
        ("Expansión sucursal Córdoba",                  45_000_000, 4, "Infraestructura", "General"),
        ("Implementación módulo SAP HR",                18_000_000, 5, "TI/Sistemas", "General"),
        ("Equipamiento cadena de frío",                 32_000_000, 6, "Infraestructura", "Medicamentos"),
        ("Plazo fijo rendimiento (excedente julio)",    50_000_000, 7, "Inversión financiera", "General"),
        ("Renovación equipos computación",              12_000_000, 8, "TI/Sistemas", "General"),
        ("Expansión línea cosmética Rosario",           28_000_000, 9, "Infraestructura", "Cosmética"),
        ("Proyecto automatización picking",             95_000_000, 10, "TI/Sistemas", "General"),
        ("Fondo de contingencia Q4",                    60_000_000, 12, "Inversión financiera", "General"),
    ]
    for desc, monto, mes, tipo, unidad in items:
        data = agregar_inversion(data, desc, monto, mes, tipo, unidad)
    return data

# ══════════════════════════════════════════════════════════════════════
# CASHFLOW POR UNIDAD DE NEGOCIO
# ══════════════════════════════════════════════════════════════════════

def generar_cf_por_unidad(df_cashflow: pd.DataFrame, budget: dict) -> dict:
    """
    Distribuye el cashflow mensual por unidad de negocio
    según los porcentajes definidos en UNIDADES_NEGOCIO.
    """
    resultado = {}
    for unidad, config in UNIDADES_NEGOCIO.items():
        pct_ing = config["pct_ingresos"]
        pct_eg  = config["pct_egresos"]
        rows = []
        for _, row in df_cashflow.iterrows():
            rows.append({
                "mes":           row["mes"],
                "mes_nombre":    row["mes_nombre"],
                "ing_proy":      row["ing_proy"] * pct_ing,
                "eg_proy":       row["eg_proy"]  * pct_eg,
                "res_proy":      row["ing_proy"] * pct_ing - row["eg_proy"] * pct_eg,
                "saldo_fin":     0.0,  # calculado después
                "budget_ing":    budget["meses"].get(str(row["mes"]), {}).get("total", 0) * pct_ing,
            })
        df_u = pd.DataFrame(rows)
        # Encadenar saldo
        saldo = 0
        for i in df_u.index:
            saldo += df_u.at[i, "res_proy"]
            df_u.at[i, "saldo_fin"] = saldo
        resultado[unidad] = df_u
    return resultado

# ══════════════════════════════════════════════════════════════════════
# DESVÍOS AGRUPADOS POR CONCEPTO
# ══════════════════════════════════════════════════════════════════════

def agrupar_desvios(df_extracto: pd.DataFrame, df_cashflow: pd.DataFrame) -> pd.DataFrame:
    """
    Agrupa los desvíos del extracto vs proyectado por categoría y mes.
    Permite drill-down por concepto → detalle de movimientos.
    """
    if df_extracto.empty:
        return pd.DataFrame()

    rows = []
    for cat in df_extracto["categoria"].unique():
        df_cat = df_extracto[df_extracto["categoria"] == cat]
        for mes in df_cat["mes"].dropna().unique():
            df_m = df_cat[df_cat["mes"] == mes]
            real_total = float(df_m["importe"].sum())
            # Buscar proyectado para esta categoría y mes
            # Mapeo simple categoría → columna cashflow
            proy_val = _get_proyectado_categoria(cat, mes, df_cashflow)
            desvio   = real_total - proy_val if proy_val != 0 else real_total
            pct_dev  = (desvio / abs(proy_val) * 100) if proy_val != 0 else 0

            rows.append({
                "categoria":      cat,
                "mes":            mes,
                "mes_nombre":     nombre_mes(int(mes)),
                "real":           real_total,
                "proyectado":     proy_val,
                "desvio_abs":     desvio,
                "desvio_pct":     pct_dev,
                "cant_movimientos": len(df_m),
                "nivel":          "🔴" if abs(pct_dev)>20 else "🟡" if abs(pct_dev)>10 else "🟢",
            })

    return pd.DataFrame(rows).sort_values(["mes","desvio_abs"], ascending=[True, True])

def _get_proyectado_categoria(cat: str, mes: int, df_cf: pd.DataFrame) -> float:
    if df_cf.empty: return 0.0
    row = df_cf[df_cf["mes"] == mes]
    if row.empty: return 0.0
    r = row.iloc[0]
    mapa = {
        "Cobranzas":        r.get("ing_proy", 0),
        "Sueldos":          r.get("sueldos", 0) * -1,
        "Cargas Sociales":  r.get("cargas_sociales", 0) * -1,
        "AFIP":             r.get("iva", 0) * -1,
        "Préstamos":        r.get("cuotas_prestamos", 0) * -1,
        "Proveedores":      r.get("proveedores", 0) * -1,
        "Cheques":          0,
        "Servicios":        0,
        "Alquiler":         0,
    }
    return float(mapa.get(cat, 0))


if __name__ == "__main__":
    print(f"Bancos cargados: {len(BANCOS_ARGENTINA)}")
    print(f"Unidades de negocio: {list(UNIDADES_NEGOCIO.keys())}")
    inv = generar_inversiones_demo()
    guardar_inversiones(inv)
    print(f"Inversiones demo: {len(inv['items'])} items")
    res = resumen_inversiones_mensual(inv)
    total = res["total_inversiones"].sum()
    print(f"Total inversiones 2025: {fmt_ars(total)}")
    print("✅ datos_maestros.py OK")
