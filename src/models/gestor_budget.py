"""
gestor_budget.py — Budget mensual / presupuesto financiero
- Carga de budget mes a mes (manual o importado)
- Budget por línea de negocio (Medicamentos, Cosmética, etc.)
- Comparativo automático: budget vs facturación real vs cobranza real
- Análisis de desvío con causa raíz (ventas / cobranza / condición de pago)
- Preparado para importar desde SAP CO-PA
"""
import pandas as pd
import os, sys
sys.path.insert(0, '.')
from src.utils.helpers import nombre_mes, fmt_ars, fmt_pct, logger

BUDGET_PATH = "./data/budget.json"

LINEAS = ["Medicamentos", "Cosmética", "Nutrición", "Veterinaria", "Otros"]


# ══════════════════════════════════════════════════════════════════════
# ESTRUCTURA DEL BUDGET
# ══════════════════════════════════════════════════════════════════════

def budget_vacio(año: int = 2025) -> dict:
    """Estructura vacía del budget anual."""
    return {
        "año": año,
        "total_anual": 0.0,
        "meses": {
            str(m): {
                "total":          0.0,
                "Medicamentos":   0.0,
                "Cosmética":      0.0,
                "Nutrición":      0.0,
                "Veterinaria":    0.0,
                "Otros":          0.0,
                "egresos_total":  0.0,
                "resultado_neto": 0.0,
            }
            for m in range(1, 13)
        }
    }


def cargar_budget(año: int = 2025) -> dict:
    """Carga el budget desde archivo JSON."""
    import json
    if os.path.exists(BUDGET_PATH):
        with open(BUDGET_PATH) as f:
            data = json.load(f)
        if data.get("año") == año:
            logger.info(f"Budget {año} cargado — Total: {fmt_ars(data.get('total_anual', 0))}")
            return data
    # Budget default con estacionalidad base
    return _budget_default(año)

def guardar_budget(budget: dict):
    import json
    os.makedirs(os.path.dirname(BUDGET_PATH), exist_ok=True)
    with open(BUDGET_PATH, "w") as f:
        json.dump(budget, f, indent=2)
    logger.ok(f"Budget guardado — Año {budget['año']}")

def _budget_default(año: int = 2025) -> dict:
    """Budget por defecto con estacionalidad estándar droguería."""
    from config import ESTACIONALIDAD
    meses_list = list(ESTACIONALIDAD.keys())
    coefs      = list(ESTACIONALIDAD.values())
    suma_coefs = sum(coefs)
    total_anual = 120_000_000  # default

    budget = budget_vacio(año)
    budget["total_anual"] = total_anual

    for i, (mes_nombre, coef) in enumerate(zip(meses_list, coefs), 1):
        total_mes = total_anual / suma_coefs * coef
        budget["meses"][str(i)]["total"]         = round(total_mes, 0)
        budget["meses"][str(i)]["Medicamentos"]  = round(total_mes * 0.70, 0)
        budget["meses"][str(i)]["Cosmética"]     = round(total_mes * 0.15, 0)
        budget["meses"][str(i)]["Nutrición"]     = round(total_mes * 0.10, 0)
        budget["meses"][str(i)]["Veterinaria"]   = round(total_mes * 0.03, 0)
        budget["meses"][str(i)]["Otros"]         = round(total_mes * 0.02, 0)
        budget["meses"][str(i)]["egresos_total"] = round(total_mes * 0.65, 0)
        budget["meses"][str(i)]["resultado_neto"]= round(total_mes * 0.35, 0)

    return budget


# ══════════════════════════════════════════════════════════════════════
# ACTUALIZAR BUDGET
# ══════════════════════════════════════════════════════════════════════

def actualizar_mes(budget: dict, mes: int, valores: dict) -> dict:
    """
    Actualiza el budget de un mes.
    valores: dict con keys opcionales: total, Medicamentos, Cosmética, etc.
    """
    mes_str = str(mes)
    for k, v in valores.items():
        if k in budget["meses"][mes_str]:
            budget["meses"][mes_str][k] = float(v)
    # Recalcular total si se actualizaron líneas
    if any(k in LINEAS for k in valores):
        total = sum(budget["meses"][mes_str].get(l, 0) for l in LINEAS)
        budget["meses"][mes_str]["total"] = total
    # Recalcular total anual
    budget["total_anual"] = sum(
        budget["meses"][str(m)]["total"] for m in range(1, 13)
    )
    return budget


# ══════════════════════════════════════════════════════════════════════
# COMPARATIVO BUDGET vs REAL
# ══════════════════════════════════════════════════════════════════════

def comparativo_budget_real(
    budget: dict,
    df_facturas: pd.DataFrame = None,   # ventas reales
    df_cobranzas: pd.DataFrame = None,  # proyección cobranzas
) -> pd.DataFrame:
    """
    Genera tabla comparativa mes a mes:
    Budget de ventas / Ventas reales / Cobranza proyectada / Cobranza real
    Desvío con causa raíz.
    """
    rows = []
    for mes in range(1, 13):
        mes_str = str(mes)
        budget_mes = float(budget["meses"][mes_str].get("total", 0))

        # Ventas reales del mes (facturas emitidas)
        venta_real = 0.0
        if df_facturas is not None and not df_facturas.empty:
            filt = df_facturas[df_facturas["mes_emision"] == mes]
            venta_real = float(filt["importe_neto"].sum())

        # Cobranza proyectada y real del mes
        cobro_esp = cobro_real = 0.0
        if df_cobranzas is not None and not df_cobranzas.empty:
            filt_c = df_cobranzas[df_cobranzas["mes"] == mes]
            if not filt_c.empty:
                cobro_esp  = float(filt_c.iloc[0].get("cobro_esperado", 0))
                cobro_real = float(filt_c.iloc[0].get("cobro_real", 0))

        dev_venta_abs = venta_real - budget_mes
        dev_venta_pct = dev_venta_abs / budget_mes * 100 if budget_mes > 0 else 0
        dev_cobro_abs = cobro_real - cobro_esp
        dev_cobro_pct = dev_cobro_abs / cobro_esp * 100 if cobro_esp > 0 else 0

        # Causa raíz del desvío
        causa = _causa_raiz(budget_mes, venta_real, cobro_esp, cobro_real)

        rows.append({
            "mes":            mes,
            "mes_nombre":     nombre_mes(mes),
            "budget":         budget_mes,
            "venta_real":     venta_real,
            "dev_venta_abs":  dev_venta_abs,
            "dev_venta_pct":  dev_venta_pct,
            "cobro_esperado": cobro_esp,
            "cobro_real":     cobro_real,
            "dev_cobro_abs":  dev_cobro_abs,
            "dev_cobro_pct":  dev_cobro_pct,
            "causa_raiz":     causa,
            "tiene_datos":    venta_real > 0,
        })

    return pd.DataFrame(rows)


def _causa_raiz(budget, venta, cobro_esp, cobro_real) -> str:
    """Determina la causa del desvío entre budget, venta y cobranza."""
    if budget == 0:
        return "📋 Sin budget cargado"
    if venta == 0:
        return "📊 Sin datos de ventas aún"

    pct_venta = (venta - budget) / budget * 100

    if pct_venta > 10:
        return "✅ Ventas superan el budget"
    elif pct_venta < -20:
        return "🔴 Caída de ventas — Revisar clientes y mercado"
    elif pct_venta < -5:
        return "🟡 Ventas por debajo del budget"
    else:
        # Ventas OK — analizar cobranza
        if cobro_esp > 0:
            pct_cobro = cobro_real / cobro_esp * 100 if cobro_esp > 0 else 0
            if pct_cobro < 30 and cobro_real >= 0:
                # La venta estuvo bien pero el cobro tarda
                return "🟡 Cobro diferido — Condición de pago elongada"
            elif pct_cobro < 60:
                return "🟡 Cobro parcial — Revisar vencimientos"
            else:
                return "🟢 Ventas y cobranza en línea con budget"
        return "🟢 Ventas en línea con budget"


# ══════════════════════════════════════════════════════════════════════
# IMPORTAR BUDGET DESDE CSV (SAP / Excel)
# ══════════════════════════════════════════════════════════════════════

def importar_budget_csv(path: str, año: int = 2025) -> dict:
    """
    Importa budget desde CSV/Excel.
    Formato esperado: columnas Mes (1-12 o nombre), Total, y opcionalmente las líneas.
    """
    try:
        ext = os.path.splitext(path)[1].lower()
        df = pd.read_excel(path) if ext in (".xlsx",".xls") else pd.read_csv(path)
    except Exception as e:
        logger.error(f"Error leyendo budget: {e}")
        return budget_vacio(año)

    cols_lower = {str(c).lower().strip(): c for c in df.columns}
    col_mes   = next((cols_lower[k] for k in cols_lower if "mes" in k), None)
    col_total = next((cols_lower[k] for k in cols_lower if "total" in k or "venta" in k), None)
    if not col_mes or not col_total:
        logger.error("No se encontraron columnas Mes y Total en el archivo de budget")
        return budget_vacio(año)

    MESES_MAP = {
        "enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
        "julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12,
        "ene":1,"feb":2,"mar":3,"abr":4,"may":5,"jun":6,
        "jul":7,"ago":8,"sep":9,"oct":10,"nov":11,"dic":12,
    }

    budget = budget_vacio(año)
    for _, row in df.iterrows():
        mes_raw = str(row.get(col_mes,"")).strip()
        # Intentar número o nombre
        try:
            mes_num = int(mes_raw)
        except:
            mes_num = MESES_MAP.get(mes_raw.lower(), 0)
        if mes_num < 1 or mes_num > 12:
            continue

        total_raw = row.get(col_total, 0)
        try:
            total = float(str(total_raw).replace("$","").replace(".","").replace(",",".").strip())
        except:
            continue

        valores = {"total": total}
        for linea in LINEAS:
            col_linea = next((cols_lower[k] for k in cols_lower if linea.lower() in k), None)
            if col_linea:
                try:
                    v = float(str(row.get(col_linea,0)).replace("$","").replace(".","").replace(",",".").strip())
                    valores[linea] = v
                except:
                    pass

        budget = actualizar_mes(budget, mes_num, valores)

    logger.ok(f"Budget importado: {fmt_ars(budget['total_anual'])} anual")
    return budget


if __name__ == "__main__":
    from src.models.gestor_facturas import generar_facturas_muestra, proyectar_cobranzas_desde_facturas

    print("=== TEST BUDGET ===\n")
    budget = cargar_budget(2025)
    print(f"Budget anual: {fmt_ars(budget['total_anual'])}")
    print("\nBudget mensual:")
    for m in range(1, 13):
        total = budget["meses"][str(m)]["total"]
        print(f"  {nombre_mes(m):12}: {fmt_ars(total)}")

    df_f  = generar_facturas_muestra()
    df_cp = proyectar_cobranzas_desde_facturas(df_f)
    df_comp = comparativo_budget_real(budget, df_f, df_cp)
    print("\n=== COMPARATIVO BUDGET vs REAL ===")
    for _, r in df_comp[df_comp["tiene_datos"]].iterrows():
        print(f"  {r['mes_nombre']:12}: Budget {fmt_ars(r['budget']):>14} | "
              f"Venta {fmt_ars(r['venta_real']):>14} | "
              f"Desvío {r['dev_venta_pct']:+.1f}% | {r['causa_raiz']}")

    guardar_budget(budget)
    print("\n✅ gestor_budget.py OK")
