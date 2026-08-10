"""
gestor_facturas.py — Módulo de Facturas / Cuentas a Cobrar (AR)
Funciones:
  - Registro de facturas emitidas con condición de pago real
  - Cálculo automático de fecha de vencimiento por condición
  - Estado de cobro: pendiente / cobrado parcial / cobrado total / vencida
  - Proyección de cobranzas futuras basada en facturas reales
  - Análisis de desvío: venta real vs budget → causa raíz
  - Trazabilidad: cada factura sabe si fue cobrada y cuándo
  - Preparado para importación desde SAP (AR module)
  - Importación desde CSV/Excel del sistema de facturación
"""
import pandas as pd
import numpy as np
from datetime import date, timedelta
import os, sys
sys.path.insert(0, '.')
from src.utils.helpers import (
    parse_fecha, nombre_mes, fmt_ars, fmt_pct,
    ajustar_fecha_cobro, logger
)

FACTURAS_PATH = "./data/facturas.csv"

COLS_FACTURAS = [
    "id",
    "numero_factura",      # Ej: "A-00001234"
    "tipo",                # "A" | "B" | "C" | "NC" (nota crédito)
    "cliente",             # Nombre del cliente (farmacia)
    "cuit_cliente",        # CUIT para cruzar con SAP
    "fecha_emision",       # date
    "importe_bruto",       # float — importe total de la factura
    "descuento_pct",       # float — % descuento comercial
    "importe_neto",        # float — importe_bruto × (1 - descuento)
    "condicion_pago",      # "contado" | "30" | "60" | "90" | "120"
    "dias_condicion",      # int — días reales (0, 30, 60, 90, 120)
    "fecha_vto_cobro",     # date — fecha_emision + dias_condicion
    "fecha_vto_habil",     # date — ajustada a día hábil
    "mes_cobro_esperado",  # int — mes en que se espera cobrar
    "estado",              # "pendiente" | "cobrado" | "cobrado_parcial" | "vencida" | "nc"
    "importe_cobrado",     # float — lo que efectivamente se cobró
    "fecha_cobro_real",    # date — cuándo se acreditó
    "mes_emision",         # int
    "año_emision",         # int
    "linea_negocio",       # "Medicamentos" | "Cosmética" | "Nutrición" | "Otros"
    "observaciones",
]

CONDICIONES_DIAS = {
    "contado": 0,
    "15":      15,
    "30":      30,
    "45":      45,
    "60":      60,
    "90":      90,
    "120":     120,
}


# ══════════════════════════════════════════════════════════════════════
# CARGA Y GUARDADO
# ══════════════════════════════════════════════════════════════════════

def cargar_facturas() -> pd.DataFrame:
    if os.path.exists(FACTURAS_PATH):
        df = pd.read_csv(FACTURAS_PATH)
        for col in ["fecha_emision", "fecha_vto_cobro", "fecha_vto_habil", "fecha_cobro_real"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
        logger.info(f"Facturas cargadas: {len(df)} registros")
        return df
    return pd.DataFrame(columns=COLS_FACTURAS)

def guardar_facturas(df: pd.DataFrame):
    os.makedirs(os.path.dirname(FACTURAS_PATH), exist_ok=True)
    df.to_csv(FACTURAS_PATH, index=False)
    logger.ok(f"Facturas guardadas: {len(df)} registros")


# ══════════════════════════════════════════════════════════════════════
# AGREGAR FACTURA
# ══════════════════════════════════════════════════════════════════════

def agregar_factura(
    df: pd.DataFrame,
    numero: str,
    cliente: str,
    importe_bruto: float,
    condicion_pago: str,        # "contado" | "30" | "60" | "90" | "120"
    fecha_emision,              # date o str
    tipo: str = "A",
    cuit_cliente: str = "",
    descuento_pct: float = 0.0,
    linea_negocio: str = "Medicamentos",
    observaciones: str = "",
) -> pd.DataFrame:
    """
    Agrega una factura y calcula automáticamente:
    - importe_neto = bruto × (1 - descuento)
    - fecha_vto_cobro = fecha_emision + dias_condicion
    - fecha_vto_habil = ajustada a día hábil
    - mes_cobro_esperado
    """
    fe = parse_fecha(fecha_emision) if not isinstance(fecha_emision, date) else fecha_emision
    if fe is None:
        logger.error(f"Fecha inválida para factura {numero}")
        return df

    dias = CONDICIONES_DIAS.get(str(condicion_pago).lower(), 30)
    importe_neto = importe_bruto * (1 - descuento_pct / 100)
    fecha_vto    = fe + timedelta(days=dias)
    fecha_vto_h  = ajustar_fecha_cobro(fecha_vto)
    mes_cobro    = fecha_vto_h.month

    nuevo_id = int(df["id"].max() + 1) if not df.empty and len(df) > 0 else 1

    nueva = {
        "id":                  nuevo_id,
        "numero_factura":      numero.strip(),
        "tipo":                tipo.upper(),
        "cliente":             cliente.strip(),
        "cuit_cliente":        cuit_cliente.strip(),
        "fecha_emision":       fe,
        "importe_bruto":       float(importe_bruto),
        "descuento_pct":       float(descuento_pct),
        "importe_neto":        float(importe_neto),
        "condicion_pago":      str(condicion_pago),
        "dias_condicion":      dias,
        "fecha_vto_cobro":     fecha_vto,
        "fecha_vto_habil":     fecha_vto_h,
        "mes_cobro_esperado":  mes_cobro,
        "estado":              "pendiente",
        "importe_cobrado":     0.0,
        "fecha_cobro_real":    None,
        "mes_emision":         fe.month,
        "año_emision":         fe.year,
        "linea_negocio":       linea_negocio,
        "observaciones":       observaciones,
    }
    df_new = pd.concat([df, pd.DataFrame([nueva])], ignore_index=True)
    logger.info(
        f"Factura {numero} | {cliente} | {fmt_ars(importe_neto)} | "
        f"cond. {condicion_pago}d → cobro {fecha_vto_h.strftime('%d/%m/%Y')}"
    )
    return df_new


def registrar_cobro(
    df: pd.DataFrame,
    numero_factura: str,
    importe_cobrado: float,
    fecha_cobro,
) -> pd.DataFrame:
    """Registra el cobro (total o parcial) de una factura."""
    mask = df["numero_factura"] == numero_factura
    if mask.sum() == 0:
        logger.warn(f"Factura {numero_factura} no encontrada")
        return df

    idx = df[mask].index[0]
    importe_neto = float(df.at[idx, "importe_neto"])
    cobrado_anterior = float(df.at[idx, "importe_cobrado"] or 0)
    total_cobrado = cobrado_anterior + float(importe_cobrado)

    df.at[idx, "importe_cobrado"]  = total_cobrado
    df.at[idx, "fecha_cobro_real"] = parse_fecha(fecha_cobro) if not isinstance(fecha_cobro, date) else fecha_cobro

    if total_cobrado >= importe_neto * 0.99:  # tolerancia 1%
        df.at[idx, "estado"] = "cobrado"
    elif total_cobrado > 0:
        df.at[idx, "estado"] = "cobrado_parcial"

    logger.ok(f"Cobro registrado: {numero_factura} — {fmt_ars(importe_cobrado)} — Estado: {df.at[idx, 'estado']}")
    return df


# ══════════════════════════════════════════════════════════════════════
# IMPORTACIÓN DESDE CSV/EXCEL (sistema de facturación o SAP)
# ══════════════════════════════════════════════════════════════════════

def importar_facturas_csv(path: str, banco_mapeo: dict = None) -> pd.DataFrame:
    """
    Importa facturas desde CSV/Excel exportado del sistema.
    Detecta automáticamente las columnas más comunes.
    banco_mapeo: dict opcional para mapear nombres de columnas custom
    """
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".xlsx", ".xls"):
            df_raw = pd.read_excel(path)
        else:
            for enc in ["utf-8", "latin-1", "cp1252"]:
                for sep in [",", ";", "\t"]:
                    try:
                        df_raw = pd.read_csv(path, encoding=enc, sep=sep)
                        if len(df_raw.columns) >= 4:
                            break
                    except:
                        continue
                else:
                    continue
                break
    except Exception as e:
        logger.error(f"Error leyendo archivo de facturas: {e}")
        return pd.DataFrame(columns=COLS_FACTURAS)

    df_raw = df_raw.dropna(how="all")
    cols_lower = {str(c).lower().strip(): c for c in df_raw.columns}

    # Mapeo automático de columnas
    def find_col(*keywords):
        for kw in keywords:
            for k, v in cols_lower.items():
                if kw in k:
                    return v
        return None

    col_num    = find_col("numero", "nro", "factura", "comprobante", "nº")
    col_cli    = find_col("cliente", "razon", "nombre", "destinatario")
    col_imp    = find_col("importe", "total", "monto", "neto", "amount")
    col_cond   = find_col("condicion", "plazo", "vencimiento_dias", "dias")
    col_fecha  = find_col("fecha", "date", "emision")
    col_tipo   = find_col("tipo", "type", "comprobante")
    col_desc   = find_col("descuento", "bonif", "discount")
    col_linea  = find_col("linea", "rubro", "categoria", "producto")

    if not col_num or not col_imp:
        logger.error("No se encontraron columnas de número o importe en el archivo")
        return pd.DataFrame(columns=COLS_FACTURAS)

    df_result = pd.DataFrame(columns=COLS_FACTURAS)
    for _, row in df_raw.iterrows():
        numero  = str(row.get(col_num, "")).strip()
        imp_raw = row.get(col_imp, 0)
        if not numero or pd.isna(imp_raw):
            continue
        try:
            importe = float(str(imp_raw).replace("$","").replace(".","").replace(",",".").strip())
        except:
            continue

        cliente  = str(row.get(col_cli, "Sin nombre")).strip() if col_cli else "Sin nombre"
        cond_raw = str(row.get(col_cond, "30")).strip() if col_cond else "30"
        # Normalizar condición
        cond_map = {"contado": "contado", "0": "contado", "15":"15",
                    "30":"30", "45":"45", "60":"60", "90":"90", "120":"120"}
        condicion = cond_map.get(cond_raw.lower(), "30")

        fecha_raw = row.get(col_fecha, date.today()) if col_fecha else date.today()
        tipo_fac  = str(row.get(col_tipo, "A")).strip().upper()[:1] if col_tipo else "A"
        desc      = float(row.get(col_desc, 0) or 0) if col_desc else 0.0
        linea     = str(row.get(col_linea, "Medicamentos")).strip() if col_linea else "Medicamentos"

        df_result = agregar_factura(
            df_result, numero=numero, cliente=cliente,
            importe_bruto=importe, condicion_pago=condicion,
            fecha_emision=fecha_raw, tipo=tipo_fac,
            descuento_pct=desc, linea_negocio=linea,
        )

    logger.ok(f"Importación completada: {len(df_result)} facturas desde {os.path.basename(path)}")
    return df_result


# ══════════════════════════════════════════════════════════════════════
# PROYECCIÓN DE COBRANZAS (desde facturas reales)
# ══════════════════════════════════════════════════════════════════════

def proyectar_cobranzas_desde_facturas(
    df: pd.DataFrame,
    año: int = 2025,
) -> pd.DataFrame:
    """
    Proyecta los cobros esperados mes a mes basándose en facturas reales.
    Reemplaza la proyección estimada por estacionalidad.

    Returns DataFrame con columnas: mes, mes_nombre, cobro_esperado,
    cobros_reales, pendiente, pct_cobrado
    """
    if df.empty:
        return pd.DataFrame()

    df_año = df[df["año_emision"] == año].copy()
    rows = []
    for mes in range(1, 13):
        # Facturas cuyo cobro se espera este mes
        esperadas = df_año[df_año["mes_cobro_esperado"] == mes]
        cobro_esp  = float(esperadas["importe_neto"].sum())
        cobro_real = float(esperadas[esperadas["estado"].isin(["cobrado","cobrado_parcial"])]["importe_cobrado"].sum())
        pendiente  = cobro_esp - cobro_real
        pct        = (cobro_real / cobro_esp * 100) if cobro_esp > 0 else 0

        # Facturas vencidas de meses anteriores (cobranzas atrasadas)
        vencidas_ant = df_año[
            (df_año["mes_cobro_esperado"] < mes) &
            (df_año["estado"].isin(["pendiente", "cobrado_parcial", "vencida"]))
        ]
        mora = float(vencidas_ant["importe_neto"].sum() - vencidas_ant["importe_cobrado"].sum())

        rows.append({
            "mes":           mes,
            "mes_nombre":    nombre_mes(mes),
            "cobro_esperado": cobro_esp,
            "cobro_real":    cobro_real,
            "pendiente":     pendiente,
            "mora_acum":     mora,
            "pct_cobrado":   pct,
            "cant_facturas": len(esperadas),
        })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════
# ANÁLISIS DE DESVÍO: VENTAS vs BUDGET
# ══════════════════════════════════════════════════════════════════════

def analizar_desvio_vs_budget(
    df_facturas:  pd.DataFrame,
    budget_mensual: dict,   # {mes_int: monto_budget}
    año: int = 2025,
) -> pd.DataFrame:
    """
    Compara ventas reales (facturas emitidas) vs budget.
    Identifica la causa del desvío:
      - "Caída de ventas": se facturó menos que el budget
      - "Condición de pago elongada": se vendió bien pero el cobro llega tarde
      - "Sobreperformance": se facturó más que el budget
      - "Sin datos": no hay facturas del mes aún
    """
    if df_facturas.empty:
        return pd.DataFrame()

    df_año = df_facturas[df_facturas["año_emision"] == año]
    rows = []

    for mes in range(1, 13):
        budget = float(budget_mensual.get(mes, 0))
        df_mes = df_año[df_año["mes_emision"] == mes]

        if df_mes.empty:
            causa = "Sin datos"
            venta_real = 0.0
            cobro_real_mes = 0.0
        else:
            venta_real = float(df_mes["importe_neto"].sum())
            cobro_real_mes = float(df_mes[
                df_mes["estado"].isin(["cobrado","cobrado_parcial"])
            ]["importe_cobrado"].sum())
            causa = _clasificar_desvio(venta_real, cobro_real_mes, budget, df_mes)

        desvio_abs = venta_real - budget
        desvio_pct = (desvio_abs / budget * 100) if budget > 0 else 0

        # Distribución de condiciones de pago del mes
        if not df_mes.empty:
            dist_cond = df_mes.groupby("condicion_pago")["importe_neto"].sum().to_dict()
        else:
            dist_cond = {}

        rows.append({
            "mes":          mes,
            "mes_nombre":   nombre_mes(mes),
            "budget":       budget,
            "venta_real":   venta_real,
            "cobro_real":   cobro_real_mes,
            "desvio_abs":   desvio_abs,
            "desvio_pct":   desvio_pct,
            "causa":        causa,
            "dist_condiciones": str(dist_cond),
            "cant_facturas": len(df_mes),
        })

    return pd.DataFrame(rows)


def _clasificar_desvio(
    venta: float,
    cobro: float,
    budget: float,
    df_mes: pd.DataFrame,
) -> str:
    """Lógica de clasificación de la causa del desvío."""
    if budget == 0:
        return "Sin budget"

    pct_desvio = (venta - budget) / budget * 100

    if pct_desvio > 5:
        return "✅ Sobreperformance de ventas"
    elif pct_desvio < -15:
        return "🔴 Caída significativa de ventas"
    elif pct_desvio < -5:
        return "🟡 Ventas por debajo del budget"
    else:
        # Ventas OK pero ¿cobro llega tarde?
        if venta > 0:
            pct_cobrado = cobro / venta * 100
            # Analizar si hay muchas facturas a 60/90 días
            dias_prom = float(df_mes["dias_condicion"].mean()) if "dias_condicion" in df_mes.columns else 30
            if dias_prom > 45 and pct_cobrado < 40:
                return "🟡 Condición de pago elongada (cobro diferido)"
            elif pct_cobrado < 20:
                return "🔵 Cobro aún no vencido (normal)"
        return "🟢 Ventas en línea con budget"


# ══════════════════════════════════════════════════════════════════════
# RESUMEN EJECUTIVO AR
# ══════════════════════════════════════════════════════════════════════

def resumen_ar(df: pd.DataFrame) -> dict:
    """KPIs de cuentas a cobrar para el dashboard."""
    if df.empty:
        return {}

    pendientes = df[df["estado"] == "pendiente"]
    vencidas   = df[
        (df["estado"].isin(["pendiente","cobrado_parcial"])) &
        (df["fecha_vto_habil"].apply(
            lambda d: d < date.today() if isinstance(d, date) else False
        ))
    ]
    cobradas   = df[df["estado"] == "cobrado"]
    total_emit = float(df["importe_neto"].sum())
    total_cob  = float(df["importe_cobrado"].sum())

    # DSO — Days Sales Outstanding
    if len(cobradas) > 0 and total_emit > 0:
        # Promedio de días entre emisión y cobro
        def dias_cobro(row):
            if row.get("fecha_cobro_real") and row.get("fecha_emision"):
                fe = row["fecha_emision"]
                fc = row["fecha_cobro_real"]
                if isinstance(fe, date) and isinstance(fc, date):
                    return (fc - fe).days
            return None
        dias_list = cobradas.apply(dias_cobro, axis=1).dropna()
        dso = float(dias_list.mean()) if len(dias_list) > 0 else 0
    else:
        dso = 0

    return {
        "total_emitido":       total_emit,
        "total_cobrado":       total_cob,
        "total_pendiente":     total_emit - total_cob,
        "pct_cobrado":         (total_cob / total_emit * 100) if total_emit > 0 else 0,
        "cant_facturas":       len(df),
        "cant_pendientes":     len(pendientes),
        "cant_vencidas":       len(vencidas),
        "monto_vencido":       float(vencidas["importe_neto"].sum() - vencidas["importe_cobrado"].sum()),
        "dso_dias":            round(dso, 1),
        "por_condicion":       df.groupby("condicion_pago")["importe_neto"].sum().to_dict(),
        "por_linea":           df.groupby("linea_negocio")["importe_neto"].sum().to_dict(),
        "por_estado":          df.groupby("estado")["importe_neto"].sum().to_dict(),
    }


# ══════════════════════════════════════════════════════════════════════
# GENERAR DATOS DE MUESTRA
# ══════════════════════════════════════════════════════════════════════

def generar_facturas_muestra(año: int = 2025) -> pd.DataFrame:
    """Genera facturas de muestra realistas para una droguería."""
    df = pd.DataFrame(columns=COLS_FACTURAS)

    facturas = [
        # (num, cliente, importe, condicion, fecha, tipo, linea, estado, cobrado, fecha_cobro)
        ("A-0001","Farmacia Central SA",       485000, "30",      "05/01/2025", "A", "Medicamentos",  "cobrado",         485000, "04/02/2025"),
        ("A-0002","Farmacias del Pueblo SRL",  312000, "60",      "08/01/2025", "A", "Medicamentos",  "cobrado",         312000, "09/03/2025"),
        ("A-0003","Farmashop SRL",             198500, "contado", "12/01/2025", "A", "Cosmética",     "cobrado",         198500, "12/01/2025"),
        ("A-0004","Farmacia La Paz",           156000, "30",      "15/01/2025", "A", "Nutrición",     "cobrado",         156000, "14/02/2025"),
        ("A-0005","Medicinea SA",              425000, "90",      "20/01/2025", "A", "Medicamentos",  "cobrado",         425000, "20/04/2025"),
        ("A-0006","Farmadent SRL",             287000, "30",      "03/02/2025", "A", "Medicamentos",  "cobrado",         287000, "05/03/2025"),
        ("A-0007","Farmacia San Martín",       198000, "60",      "07/02/2025", "A", "Cosmética",     "cobrado",         198000, "08/04/2025"),
        ("A-0008","Farmared CABA",             534000, "30",      "10/02/2025", "A", "Medicamentos",  "cobrado",         534000, "12/03/2025"),
        ("A-0009","Farmacias Municipales",     312000, "contado", "14/02/2025", "A", "Nutrición",     "cobrado",         312000, "14/02/2025"),
        ("A-0010","Farmacia Central SA",       465000, "30",      "03/03/2025", "A", "Medicamentos",  "cobrado",         465000, "02/04/2025"),
        ("A-0011","Farmacias del Pueblo SRL",  298000, "60",      "07/03/2025", "A", "Medicamentos",  "cobrado",         298000, "06/05/2025"),
        ("A-0012","Farmashop SRL",             412000, "30",      "12/03/2025", "A", "Cosmética",     "cobrado",         412000, "11/04/2025"),
        ("A-0013","Farmacia La Paz",           185000, "contado", "18/03/2025", "A", "Nutrición",     "cobrado",         185000, "18/03/2025"),
        ("A-0014","Medicinea SA",              623000, "90",      "25/03/2025", "A", "Medicamentos",  "cobrado",         623000, "23/06/2025"),
        ("A-0015","Farmadent SRL",             312000, "30",      "02/04/2025", "A", "Medicamentos",  "cobrado",         312000, "02/05/2025"),
        ("A-0016","Farmacia San Martín",       245000, "60",      "07/04/2025", "A", "Cosmética",     "cobrado",         245000, "06/06/2025"),
        ("A-0017","Farmared CABA",             587000, "30",      "11/04/2025", "A", "Medicamentos",  "cobrado",         587000, "11/05/2025"),
        ("A-0018","Farmacias Municipales",     198000, "contado", "16/04/2025", "A", "Nutrición",     "cobrado",         198000, "16/04/2025"),
        ("A-0019","Farmacia Central SA",       512000, "30",      "05/05/2025", "A", "Medicamentos",  "cobrado",         512000, "04/06/2025"),
        ("A-0020","Farmacias del Pueblo SRL",  287000, "60",      "08/05/2025", "A", "Medicamentos",  "cobrado",         287000, "07/07/2025"),
        ("A-0021","Farmashop SRL",             345000, "30",      "12/05/2025", "A", "Cosmética",     "cobrado",         345000, "11/06/2025"),
        ("A-0022","Farmacia La Paz",           198000, "contado", "15/05/2025", "A", "Nutrición",     "cobrado",         198000, "15/05/2025"),
        ("A-0023","Medicinea SA",              478000, "90",      "20/05/2025", "A", "Medicamentos",  "cobrado",         478000, "18/08/2025"),
        ("A-0024","Farmadent SRL",             234000, "30",      "26/05/2025", "A", "Medicamentos",  "cobrado",         234000, "25/06/2025"),
        # Junio — facturas pendientes de cobro
        ("A-0025","Farmacia Central SA",       495000, "30",      "03/06/2025", "A", "Medicamentos",  "pendiente",       0,      None),
        ("A-0026","Farmacias del Pueblo SRL",  321000, "60",      "06/06/2025", "A", "Medicamentos",  "pendiente",       0,      None),
        ("A-0027","Farmashop SRL",             412000, "30",      "10/06/2025", "A", "Cosmética",     "cobrado_parcial", 200000, None),
        ("A-0028","Farmacia La Paz",           178000, "contado", "13/06/2025", "A", "Nutrición",     "cobrado",         178000, "13/06/2025"),
        ("A-0029","Medicinea SA",              587000, "90",      "17/06/2025", "A", "Medicamentos",  "pendiente",       0,      None),
        ("A-0030","Farmared CABA",             398000, "30",      "20/06/2025", "A", "Medicamentos",  "pendiente",       0,      None),
    ]

    for f in facturas:
        num,cli,imp,cond,femi,tipo,linea,estado,cobrado,fcobro = f
        df = agregar_factura(df, numero=num, cliente=cli, importe_bruto=imp,
                             condicion_pago=cond, fecha_emision=femi,
                             tipo=tipo, linea_negocio=linea)
        if estado != "pendiente" and cobrado > 0:
            df = registrar_cobro(df, num, cobrado, fcobro if fcobro else date.today())
        elif estado == "cobrado_parcial":
            df = registrar_cobro(df, num, cobrado, date.today())

    return df


if __name__ == "__main__":
    print("=== TEST GESTOR FACTURAS ===\n")

    df_f = generar_facturas_muestra()
    print(f"Facturas generadas: {len(df_f)}")

    print("\n=== MUESTRA DE FACTURAS ===")
    cols = ["numero_factura","cliente","importe_neto","condicion_pago",
            "fecha_vto_habil","mes_cobro_esperado","estado","importe_cobrado"]
    print(df_f[cols].to_string(index=False))

    print("\n=== PROYECCIÓN DE COBRANZAS ===")
    proy = proyectar_cobranzas_desde_facturas(df_f)
    for _, r in proy[proy["cobro_esperado"] > 0].iterrows():
        print(f"  {r['mes_nombre']:12}: Esperado {fmt_ars(r['cobro_esperado']):>14} | "
              f"Real {fmt_ars(r['cobro_real']):>14} | "
              f"Pendiente {fmt_ars(r['pendiente']):>14} | {r['pct_cobrado']:.0f}%")

    print("\n=== KPIs AR ===")
    kpis_ar = resumen_ar(df_f)
    print(f"  Total emitido:   {fmt_ars(kpis_ar['total_emitido'])}")
    print(f"  Total cobrado:   {fmt_ars(kpis_ar['total_cobrado'])}")
    print(f"  Pendiente:       {fmt_ars(kpis_ar['total_pendiente'])}")
    print(f"  % Cobrado:       {kpis_ar['pct_cobrado']:.1f}%")
    print(f"  DSO:             {kpis_ar['dso_dias']} días")
    print(f"  Vencidas:        {kpis_ar['cant_vencidas']} | {fmt_ars(kpis_ar['monto_vencido'])}")
    print(f"  Por condición:   {kpis_ar['por_condicion']}")

    # Análisis desvío vs budget simple
    budget_test = {i: 9_000_000 for i in range(1, 13)}
    df_dev = analizar_desvio_vs_budget(df_f, budget_test)
    print("\n=== ANÁLISIS DESVÍO VS BUDGET ===")
    for _, r in df_dev[df_dev["venta_real"] > 0].iterrows():
        print(f"  {r['mes_nombre']:12}: Venta {fmt_ars(r['venta_real']):>14} | "
              f"Budget {fmt_ars(r['budget']):>14} | "
              f"Desvío {r['desvio_pct']:+.1f}% | {r['causa']}")

    guardar_facturas(df_f)
    print("\n✅ gestor_facturas.py OK")
