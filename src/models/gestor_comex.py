"""
gestor_comex.py — Módulo de Comercio Exterior (COMEX)
Gestión de pagos de importaciones de medicamentos e insumos.

En Droguería del Sud ~18% de las compras son productos importados.
Flujo COMEX:
  1. Orden de compra al proveedor exterior (USD)
  2. Apertura SIRA (Sistema Importaciones Argentina) 
  3. Llegada mercadería + DUA (Declaración Única Aduanera)
  4. Pago al proveedor (30-180 días plazo)
  5. Impacto en cashflow: pago en USD + derechos aduaneros + estadística

Impacto cashflow:
  - Egreso en ARS equivalente al TC del día de pago
  - Derechos de importación (0% medicamentos esenciales, 2-10% otros)
  - Tasa estadística (0.5%)
  - Seguro y flete (CIF) ya incluidos en el precio de compra
  - IVA importación (10.5% o 21% según producto)
  - Percepción ARCA (3% o 6%)
"""
import pandas as pd
import json, os, sys
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
sys.path.insert(0, '.')
from src.utils.helpers import parse_fecha, nombre_mes, fmt_ars, ajustar_fecha_cobro, logger

COMEX_PATH         = "./data/comex_pagos.csv"
PROVEEDORES_PATH   = "./data/proveedores_principales.json"
TC_HISTORY_PATH    = "./data/tipo_cambio.json"

# Aranceles por categoría de producto (arancel externo común MERCOSUR)
ARANCELES = {
    "medicamentos_esenciales":    0.00,   # 0% OMS lista esencial
    "medicamentos_generales":     0.02,   # 2%
    "dispositivos_medicos":       0.06,   # 6%
    "cosmetica_importada":        0.20,   # 20%
    "insumos_farmaceuticos":      0.02,   # 2%
    "equipamiento_medico":        0.00,   # 0% temporario
}
TASA_ESTADISTICA = 0.005   # 0.5% sobre valor CIF
IVA_IMPORTACION  = 0.105   # 10.5% medicamentos / 21% otros
PERCEPCION_ARCA  = 0.03    # 3% sobre base imponible

COLS_COMEX = [
    "id", "proveedor", "pais_origen", "descripcion", "categoria",
    "fecha_orden",          # Fecha orden de compra
    "fecha_sira",           # Fecha aprobación SIRA/SIRASE
    "fecha_arribo",         # Fecha arribo al país
    "fecha_dua",            # Fecha despacho aduanero
    "fecha_pago_proveedor", # Fecha pago al exterior (puede ser 0, 30, 60, 90, 180 días)
    "dias_plazo_pago",
    "monto_usd",            # Monto en USD (FOB)
    "flete_seguro_usd",     # CIF-FOB
    "monto_cif_usd",        # Total CIF
    "tc_aplicado",          # Tipo de cambio ARS/USD
    "monto_ars_equivalente",
    "arancel_pct",
    "arancel_ars",
    "tasa_estadistica_ars",
    "iva_importacion_ars",
    "percepcion_arca_ars",
    "costo_total_ars",      # monto + aranceles + impuestos
    "estado",               # "en_transito" | "en_aduana" | "liberado" | "pagado"
    "banco_pago",           # Banco para el pago al exterior
    "unidad_negocio",
    "observaciones",
]


def cargar_comex() -> pd.DataFrame:
    if os.path.exists(COMEX_PATH):
        df = pd.read_csv(COMEX_PATH)
        for col in ["fecha_orden","fecha_sira","fecha_arribo","fecha_dua","fecha_pago_proveedor"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
        logger.info(f"COMEX cargado: {len(df)} operaciones")
        return df
    return pd.DataFrame(columns=COLS_COMEX)


def guardar_comex(df: pd.DataFrame):
    os.makedirs(os.path.dirname(COMEX_PATH), exist_ok=True)
    df.to_csv(COMEX_PATH, index=False)
    logger.ok(f"COMEX guardado: {len(df)} operaciones")


def agregar_operacion_comex(
    df: pd.DataFrame,
    proveedor: str,
    pais_origen: str,
    descripcion: str,
    categoria: str,
    monto_usd: float,
    fecha_orden,
    dias_plazo_pago: int = 60,
    flete_seguro_pct: float = 0.035,  # 3.5% del FOB como CIF típico
    tc_aplicado: float = 1200.0,
    banco_pago: str = "Banco Nación",
    unidad_negocio: str = "Medicamentos",
    observaciones: str = "",
) -> pd.DataFrame:
    """
    Registra una operación COMEX y calcula automáticamente:
    - Monto CIF = FOB × (1 + flete_seguro_pct)
    - Aranceles según categoría
    - IVA importación
    - Fecha de pago (ajustada a día hábil)
    - Costo total ARS incluyendo todos los impuestos
    """
    fe = parse_fecha(fecha_orden) if not isinstance(fecha_orden, date) else fecha_orden
    monto_cif = monto_usd * (1 + flete_seguro_pct)
    monto_cif_ars = monto_cif * tc_aplicado

    arancel_pct = ARANCELES.get(categoria, 0.02)
    arancel_ars = monto_cif_ars * arancel_pct
    tasa_est    = monto_cif_ars * TASA_ESTADISTICA
    iva_imp     = (monto_cif_ars + arancel_ars) * IVA_IMPORTACION
    percep      = monto_cif_ars * PERCEPCION_ARCA
    costo_total = monto_cif_ars + arancel_ars + tasa_est + iva_imp + percep

    # Fecha de pago al proveedor (ajustada a día hábil)
    fecha_pago_raw = fe + timedelta(days=dias_plazo_pago)
    fecha_pago = ajustar_fecha_cobro(fecha_pago_raw)

    nuevo_id = int(df["id"].max() + 1) if not df.empty and len(df) > 0 else 1

    nueva = {
        "id": nuevo_id, "proveedor": proveedor, "pais_origen": pais_origen,
        "descripcion": descripcion, "categoria": categoria,
        "fecha_orden": fe, "fecha_sira": None, "fecha_arribo": None,
        "fecha_dua": None, "fecha_pago_proveedor": fecha_pago,
        "dias_plazo_pago": dias_plazo_pago,
        "monto_usd": round(monto_usd, 2),
        "flete_seguro_usd": round(monto_usd * flete_seguro_pct, 2),
        "monto_cif_usd": round(monto_cif, 2),
        "tc_aplicado": tc_aplicado,
        "monto_ars_equivalente": round(monto_cif_ars),
        "arancel_pct": arancel_pct,
        "arancel_ars": round(arancel_ars),
        "tasa_estadistica_ars": round(tasa_est),
        "iva_importacion_ars": round(iva_imp),
        "percepcion_arca_ars": round(percep),
        "costo_total_ars": round(costo_total),
        "estado": "en_transito",
        "banco_pago": banco_pago,
        "unidad_negocio": unidad_negocio,
        "observaciones": observaciones,
    }
    df_new = pd.concat([df, pd.DataFrame([nueva])], ignore_index=True)
    logger.ok(f"COMEX: {proveedor} | USD {monto_usd:,.0f} | Pago: {fecha_pago.strftime('%d/%m/%Y')}")
    return df_new


def resumen_comex_mensual(df: pd.DataFrame, año: int = 2025) -> pd.DataFrame:
    """
    Agrupa pagos COMEX por mes para integrar al cashflow.
    Separa: pago proveedor exterior + impuestos aduaneros (derechos + IVA)
    """
    rows = {m: {
        "mes": m, "mes_nombre": nombre_mes(m),
        "pago_proveedores_usd": 0.0, "pago_proveedores_ars": 0.0,
        "aranceles_ars": 0.0, "iva_importacion_ars": 0.0,
        "total_egreso_ars": 0.0, "operaciones": 0,
    } for m in range(1, 13)}

    if df.empty:
        return pd.DataFrame(list(rows.values()))

    for _, r in df.iterrows():
        try:
            fp = r["fecha_pago_proveedor"]
            if isinstance(fp, str): fp = parse_fecha(fp)
            if fp and hasattr(fp, 'year') and fp.year == año:
                m = fp.month
                rows[m]["pago_proveedores_usd"] += float(r.get("monto_cif_usd", 0))
                rows[m]["pago_proveedores_ars"] += float(r.get("monto_ars_equivalente", 0))
                rows[m]["aranceles_ars"]         += float(r.get("arancel_ars", 0)) + float(r.get("tasa_estadistica_ars", 0))
                rows[m]["iva_importacion_ars"]   += float(r.get("iva_importacion_ars", 0))
                rows[m]["total_egreso_ars"]       += float(r.get("costo_total_ars", 0))
                rows[m]["operaciones"]            += 1
        except: continue

    return pd.DataFrame(list(rows.values()))


def alertas_comex_vencimientos(df: pd.DataFrame, fecha_hoy: date = None) -> list:
    """
    Genera alertas para pagos COMEX próximos a vencer.
    Incluye aviso de disponibilidad de fondos en el banco de pago.
    """
    if fecha_hoy is None: fecha_hoy = date.today()
    alertas = []
    if df.empty: return alertas

    df_pend = df[df["estado"].isin(["en_transito","en_aduana","liberado"])].copy()

    for _, r in df_pend.iterrows():
        try:
            fp = r["fecha_pago_proveedor"]
            if isinstance(fp, str): fp = parse_fecha(fp)
            if not fp: continue
            dias = (fp - fecha_hoy).days
            monto_usd = float(r.get("monto_usd", 0))
            monto_ars = float(r.get("costo_total_ars", 0))
            banco     = r.get("banco_pago", "banco")

            if dias < 0:
                alertas.append({"nivel":"critico","categoria":"comex",
                    "titulo":f"🔴 COMEX VENCIDO — {r['proveedor'][:30]}",
                    "detalle":f"USD {monto_usd:,.0f} | {fmt_ars(monto_ars)} | {abs(dias)}d vencido",
                    "monto":monto_ars,"fecha":fp,
                    "accion":f"⚠️ Verificar pago en {banco}. Riesgo de penalidades."})
            elif dias == 0:
                alertas.append({"nivel":"critico","categoria":"comex",
                    "titulo":f"🔴 COMEX VENCE HOY — {r['proveedor'][:30]}",
                    "detalle":f"USD {monto_usd:,.0f} | {fmt_ars(monto_ars)} | Banco: {banco}",
                    "monto":monto_ars,"fecha":fp,
                    "accion":f"💰 Verificar disponibilidad de fondos USD en {banco} HOY."})
            elif dias <= 7:
                alertas.append({"nivel":"alerta","categoria":"comex",
                    "titulo":f"🟡 COMEX en {dias}d — {r['proveedor'][:30]}",
                    "detalle":f"USD {monto_usd:,.0f} | {fmt_ars(monto_ars)} | Vence {fp.strftime('%d/%m/%Y')} | Banco: {banco}",
                    "monto":monto_ars,"fecha":fp,
                    "accion":f"💰 Prever fondos USD en {banco} para el {fp.strftime('%d/%m')}."})
            elif dias <= 30:
                alertas.append({"nivel":"info","categoria":"comex",
                    "titulo":f"🔵 COMEX en {dias}d — {r['proveedor'][:30]}",
                    "detalle":f"USD {monto_usd:,.0f} | {fmt_ars(monto_ars)} | Vence {fp.strftime('%d/%m/%Y')}",
                    "monto":monto_ars,"fecha":fp,
                    "accion":f"Incluir en planificación mensual de divisas."})
        except: continue

    return sorted(alertas, key=lambda x: {"critico":0,"alerta":1,"info":2}.get(x["nivel"],3))


def generar_comex_demo(año: int = 2025) -> pd.DataFrame:
    """Demo realista: 18% compras importadas = ~USD 620M/año = ~USD 52M/mes"""
    df = pd.DataFrame(columns=COLS_COMEX)

    operaciones = [
        # (proveedor, país, desc, cat, usd_monto, fecha_orden, días_plazo, banco)
        ("Fresenius Kabi AG",       "Alemania",  "Soluciones parenterales",        "medicamentos_generales",   4_200_000, "15/01/2025", 90,  "Citibank N.A."),
        ("Baxter International",    "EEUU",      "Bolsas y sistemas IV",            "dispositivos_medicos",     3_800_000, "20/01/2025", 60,  "Banco BBVA Argentina S.A."),
        ("Roche Diagnostics GmbH",  "Suiza",     "Reactivos diagnóstico",           "medicamentos_esenciales",  2_900_000, "10/02/2025", 90,  "Citibank N.A."),
        ("Sandoz GmbH",             "Austria",   "Genéricos importados",            "medicamentos_generales",   3_500_000, "15/02/2025", 60,  "Banco BBVA Argentina S.A."),
        ("B. Braun Melsungen",      "Alemania",  "Material descartable quirúrgico", "dispositivos_medicos",     2_100_000, "05/03/2025", 90,  "Citibank N.A."),
        ("Teva Pharmaceutical",     "Israel",    "APIs y genéricos bulk",           "insumos_farmaceuticos",    4_800_000, "10/03/2025", 90,  "Banco Credicoop Cooperativo Limitado"),
        ("Pfizer Inc.",             "EEUU",      "Vacunas importadas",              "medicamentos_esenciales",  8_500_000, "01/04/2025", 60,  "Citibank N.A."),
        ("MSD International",       "Irlanda",   "Oncológicos importados",          "medicamentos_esenciales",  6_200_000, "15/04/2025", 90,  "Citibank N.A."),
        ("Fresenius Kabi AG",       "Alemania",  "Nutrición parenteral",            "medicamentos_generales",   3_900_000, "05/05/2025", 90,  "Citibank N.A."),
        ("Abbott Laboratories",     "EEUU",      "Dispositivos cardiología",        "equipamiento_medico",      2_700_000, "20/05/2025", 60,  "Banco BBVA Argentina S.A."),
        ("L'Oréal S.A.",            "Francia",   "Cosmética importada premium",     "cosmetica_importada",      1_800_000, "01/06/2025", 30,  "Banco Galicia y Buenos Aires S.A."),
        ("Nestlé Health Science",   "Suiza",     "Nutrición clínica especializada", "insumos_farmaceuticos",    2_200_000, "15/06/2025", 60,  "Banco BBVA Argentina S.A."),
        ("Medtronic plc",           "Irlanda",   "Equipamiento médico implantable", "equipamiento_medico",      5_400_000, "01/07/2025", 120, "Citibank N.A."),
        ("Teva Pharmaceutical",     "Israel",    "Genéricos pediátricos",           "medicamentos_generales",   3_100_000, "15/07/2025", 90,  "Banco Credicoop Cooperativo Limitado"),
        ("Baxter International",    "EEUU",      "Fluidos y electrolitos",          "medicamentos_esenciales",  4_500_000, "01/08/2025", 60,  "Banco BBVA Argentina S.A."),
        ("Roche Diagnostics GmbH",  "Suiza",     "Kits diagnóstico PCR",            "medicamentos_esenciales",  3_300_000, "15/08/2025", 90,  "Citibank N.A."),
        ("Sandoz GmbH",             "Austria",   "Biosimilares importados",         "medicamentos_generales",   4_100_000, "01/09/2025", 90,  "Banco Credicoop Cooperativo Limitado"),
        ("Fresenius Kabi AG",       "Alemania",  "Soluciones oncológicas",          "medicamentos_esenciales",  5_800_000, "15/09/2025", 60,  "Citibank N.A."),
        ("Pfizer Inc.",             "EEUU",      "Vacunas campaña invierno",        "medicamentos_esenciales",  7_200_000, "01/10/2025", 60,  "Citibank N.A."),
        ("Abbott Laboratories",     "EEUU",      "Insumos laboratorio clínico",     "dispositivos_medicos",     2_900_000, "15/10/2025", 90,  "Banco BBVA Argentina S.A."),
        ("MSD International",       "Irlanda",   "Oncológicos Q4",                  "medicamentos_esenciales",  7_800_000, "01/11/2025", 90,  "Citibank N.A."),
        ("B. Braun Melsungen",      "Alemania",  "Material quirúrgico fin de año",  "dispositivos_medicos",     3_400_000, "15/11/2025", 60,  "Banco Credicoop Cooperativo Limitado"),
        ("Nestlé Health Science",   "Suiza",     "Stock fin de año nutrición",      "insumos_farmaceuticos",    2_800_000, "01/12/2025", 30,  "Banco BBVA Argentina S.A."),
        ("Fresenius Kabi AG",       "Alemania",  "Pedido extraordinario dic.",      "medicamentos_generales",   6_100_000, "15/12/2025", 60,  "Citibank N.A."),
    ]

    for prov, pais, desc, cat, usd, ford, dias, banco in operaciones:
        df = agregar_operacion_comex(
            df, proveedor=prov, pais_origen=pais,
            descripcion=desc, categoria=cat,
            monto_usd=usd, fecha_orden=ford,
            dias_plazo_pago=dias,
            tc_aplicado=1200.0,
            banco_pago=banco,
            unidad_negocio="Medicamentos" if "cosmetica" not in cat else "Cosmética",
        )
    return df


if __name__ == "__main__":
    print("=== TEST GESTOR COMEX ===\n")
    df = generar_comex_demo()
    print(f"Operaciones: {len(df)}")
    print(f"\n=== RESUMEN MENSUAL COMEX 2025 ===")
    res = resumen_comex_mensual(df, 2025)
    from src.utils.helpers import fmt_ars
    total_usd = 0; total_ars = 0
    for _, r in res.iterrows():
        if r["operaciones"] > 0:
            print(f"  {r['mes_nombre']:12}: USD {r['pago_proveedores_usd']:>12,.0f} | "
                  f"{fmt_ars(r['total_egreso_ars']):>18} ({int(r['operaciones'])} ops)")
            total_usd += r['pago_proveedores_usd']
            total_ars += r['total_egreso_ars']
    print(f"\n  TOTAL:         USD {total_usd:>12,.0f} | {fmt_ars(total_ars):>18}")

    alertas = alertas_comex_vencimientos(df, date(2025,6,1))
    print(f"\n=== ALERTAS COMEX al 01/06/2025 ===")
    for a in alertas[:5]:
        print(f"  [{a['nivel'].upper():8}] {a['titulo']}")

    guardar_comex(df)
    print("\n✅ gestor_comex.py OK")
