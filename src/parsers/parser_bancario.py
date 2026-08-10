"""
parser_bancario.py — Parser inteligente de extractos bancarios
Soporta: Banco Nación, Galicia, BBVA, Santander, Macro, ICBC, genérico
Auto-detecta el banco, normaliza columnas y devuelve DataFrame limpio.
"""
import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, '.')
from config import FORMATOS_BANCO
from src.utils.helpers import (
    clasificar_movimiento, parse_fecha, logger, nombre_mes, fmt_ars
)


# ══════════════════════════════════════════════════════════════════════
# COLUMNAS ESTÁNDAR QUE DEVUELVE EL PARSER
# ══════════════════════════════════════════════════════════════════════
COLS_SALIDA = [
    "fecha",          # date
    "fecha_str",      # str DD/MM/YYYY
    "descripcion",    # str
    "importe",        # float (positivo=ingreso, negativo=egreso)
    "saldo",          # float (puede ser None si no está en el extracto)
    "tipo",           # "INGRESO" | "EGRESO"
    "categoria",      # clasificación automática
    "mes",            # int 1-12
    "mes_nombre",     # str "Enero"
    "año",            # int
    "semana",         # int semana del año
    "banco",          # str nombre banco
    "conciliado",     # bool (False por defecto)
    "monto_proyectado", # float (para comparar vs real, None por defecto)
    "desvio",         # float (None por defecto)
]


# ══════════════════════════════════════════════════════════════════════
# DETECCIÓN AUTOMÁTICA DE BANCO
# ══════════════════════════════════════════════════════════════════════

def detectar_banco(df_raw: pd.DataFrame, nombre_archivo: str = "") -> str:
    """
    Detecta automáticamente el banco según:
    1. Nombre del archivo
    2. Columnas presentes en el DataFrame
    """
    nombre_lower = nombre_archivo.lower()
    cols = [str(c).lower() for c in df_raw.columns]
    cols_str = " ".join(cols)

    # Por nombre de archivo
    if any(x in nombre_lower for x in ["nacion", "bna", "banco_nacion"]):
        return "nacion"
    if any(x in nombre_lower for x in ["galicia", "ggal"]):
        return "galicia"
    if any(x in nombre_lower for x in ["bbva", "frances"]):
        return "bbva"
    if any(x in nombre_lower for x in ["santander", "rio"]):
        return "santander"
    if any(x in nombre_lower for x in ["macro"]):
        return "macro"
    if any(x in nombre_lower for x in ["icbc"]):
        return "icbc"

    # Por columnas
    if "fecha op." in cols_str or "fecha op" in cols_str or "concepto" in cols_str:
        return "galicia"
    if "saldo ctacte" in cols_str:
        return "bbva"
    if "credito" in cols_str and "debito" in cols_str and "saldo" in cols_str:
        return "macro"
    if "detalle" in cols_str and "importe" in cols_str:
        return "icbc"

    return "generico"


# ══════════════════════════════════════════════════════════════════════
# PARSERS POR BANCO
# ══════════════════════════════════════════════════════════════════════

def _limpiar_importe(valor) -> float:
    """Convierte string de importe a float, manejando formatos ARS."""
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return 0.0
    s = str(valor).strip()
    s = s.replace("$", "").replace(" ", "")
    # Formato ARS: puntos de miles, coma decimal
    # "1.234.567,89" → "1234567.89"
    if "," in s and "." in s:
        # Si hay coma y punto, el último separador es el decimal
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    # Paréntesis = negativo: (1.234) → -1234
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except:
        return 0.0

def _parse_nacion(df: pd.DataFrame) -> pd.DataFrame:
    """Parser Banco Nación."""
    cols = {str(c).strip(): c for c in df.columns}
    col_fecha = next((cols[k] for k in cols if "fecha" in k.lower()), df.columns[0])
    col_desc  = next((cols[k] for k in cols if any(x in k.lower() for x in ["descrip", "concepto", "detalle", "movimiento"])), df.columns[1] if len(df.columns) > 1 else None)
    col_imp   = next((cols[k] for k in cols if any(x in k.lower() for x in ["importe", "monto", "credito", "debito"])), None)
    col_saldo = next((cols[k] for k in cols if "saldo" in k.lower()), None)

    rows = []
    for _, row in df.iterrows():
        fecha = parse_fecha(row.get(col_fecha))
        if not fecha:
            continue
        desc  = str(row.get(col_desc, "")).strip()
        imp   = _limpiar_importe(row.get(col_imp, 0))
        saldo = _limpiar_importe(row.get(col_saldo)) if col_saldo else None
        rows.append({"fecha": fecha, "descripcion": desc, "importe": imp, "saldo": saldo})
    return pd.DataFrame(rows)

def _parse_galicia(df: pd.DataFrame) -> pd.DataFrame:
    """Parser Banco Galicia — tiene columnas Debe/Haber separadas."""
    cols_lower = {str(c).lower().strip(): c for c in df.columns}
    col_fecha = next((cols_lower[k] for k in cols_lower if "fecha" in k), df.columns[0])
    col_desc  = next((cols_lower[k] for k in cols_lower if any(x in k for x in ["concepto", "descrip", "detalle"])), df.columns[1] if len(df.columns) > 1 else None)
    col_debe  = next((cols_lower[k] for k in cols_lower if "debe" in k), None)
    col_haber = next((cols_lower[k] for k in cols_lower if "haber" in k), None)
    col_imp   = next((cols_lower[k] for k in cols_lower if "importe" in k), None)
    col_saldo = next((cols_lower[k] for k in cols_lower if "saldo" in k), None)

    rows = []
    for _, row in df.iterrows():
        fecha = parse_fecha(row.get(col_fecha))
        if not fecha:
            continue
        desc = str(row.get(col_desc, "")).strip()
        if col_debe and col_haber:
            haber = _limpiar_importe(row.get(col_haber, 0))
            debe  = _limpiar_importe(row.get(col_debe, 0))
            imp   = haber - debe  # haber=ingreso(+), debe=egreso(-)
        elif col_imp:
            imp = _limpiar_importe(row.get(col_imp, 0))
        else:
            imp = 0.0
        saldo = _limpiar_importe(row.get(col_saldo)) if col_saldo else None
        rows.append({"fecha": fecha, "descripcion": desc, "importe": imp, "saldo": saldo})
    return pd.DataFrame(rows)

def _parse_generico(df: pd.DataFrame) -> pd.DataFrame:
    """
    Parser genérico — intenta mapear las columnas más probables.
    Funciona para cualquier extracto con columnas reconocibles.
    """
    cols_lower = {str(c).lower().strip(): c for c in df.columns}

    # Fecha
    col_fecha = None
    for k in cols_lower:
        if "fecha" in k or "date" in k:
            col_fecha = cols_lower[k]; break
    if col_fecha is None:
        col_fecha = df.columns[0]

    # Descripción
    col_desc = None
    for k in cols_lower:
        if any(x in k for x in ["descrip", "concepto", "detalle", "text", "memo", "movim"]):
            col_desc = cols_lower[k]; break
    if col_desc is None and len(df.columns) > 1:
        col_desc = df.columns[1]

    # Importe — buscar columna de importe o calcular debe-haber
    col_imp   = None
    col_debe  = None
    col_haber = None
    for k in cols_lower:
        if k in ("importe", "monto", "amount", "valor"):
            col_imp = cols_lower[k]; break
        if "debe" in k:
            col_debe = cols_lower[k]
        if "haber" in k:
            col_haber = cols_lower[k]

    # Saldo
    col_saldo = None
    for k in cols_lower:
        if "saldo" in k or "balance" in k:
            col_saldo = cols_lower[k]; break

    rows = []
    for _, row in df.iterrows():
        fecha = parse_fecha(row.get(col_fecha))
        if not fecha:
            continue
        desc = str(row.get(col_desc, "")).strip() if col_desc else ""
        if col_imp:
            imp = _limpiar_importe(row.get(col_imp, 0))
        elif col_debe and col_haber:
            haber = _limpiar_importe(row.get(col_haber, 0))
            debe  = _limpiar_importe(row.get(col_debe, 0))
            imp   = haber - debe
        else:
            imp = 0.0
        saldo = _limpiar_importe(row.get(col_saldo)) if col_saldo else None
        rows.append({"fecha": fecha, "descripcion": desc, "importe": imp, "saldo": saldo})
    return pd.DataFrame(rows)


PARSERS = {
    "nacion":    _parse_nacion,
    "galicia":   _parse_galicia,
    "bbva":      _parse_nacion,      # Estructura similar a Nación
    "santander": _parse_nacion,
    "macro":     _parse_galicia,     # Tiene debe/haber
    "icbc":      _parse_nacion,
    "generico":  _parse_generico,
}


# ══════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL — parse_extracto
# ══════════════════════════════════════════════════════════════════════

def parse_extracto(path_o_df, banco: str = None, nombre_archivo: str = "") -> pd.DataFrame:
    """
    Función principal. Recibe un path a CSV/XLSX o un DataFrame.
    Devuelve DataFrame normalizado con columnas estándar.

    Args:
        path_o_df: str (path) o pd.DataFrame
        banco: str o None (auto-detectar)
        nombre_archivo: str (para ayudar en la auto-detección)

    Returns:
        pd.DataFrame con COLS_SALIDA
    """
    # 1. Leer archivo
    if isinstance(path_o_df, str):
        nombre_archivo = nombre_archivo or os.path.basename(path_o_df)
        ext = os.path.splitext(path_o_df)[1].lower()
        try:
            if ext in (".xlsx", ".xls"):
                df_raw = pd.read_excel(path_o_df, header=0)
            else:
                # Intentar distintos encodings y separadores
                for enc in ["utf-8", "latin-1", "cp1252"]:
                    for sep in [",", ";", "\t", "|"]:
                        try:
                            df_raw = pd.read_csv(path_o_df, encoding=enc, sep=sep, header=0)
                            if len(df_raw.columns) > 2:
                                break
                        except:
                            continue
                    else:
                        continue
                    break
        except Exception as e:
            logger.error(f"Error leyendo archivo: {e}")
            return pd.DataFrame(columns=COLS_SALIDA)
    elif isinstance(path_o_df, pd.DataFrame):
        df_raw = path_o_df.copy()
    else:
        logger.error("parse_extracto: input inválido")
        return pd.DataFrame(columns=COLS_SALIDA)

    # Filtrar filas completamente vacías
    df_raw = df_raw.dropna(how="all")

    # 2. Detectar banco
    if not banco:
        banco = detectar_banco(df_raw, nombre_archivo)
    logger.info(f"Banco detectado: {FORMATOS_BANCO.get(banco, {}).get('nombre', banco)}")

    # 3. Parsear
    parser_fn = PARSERS.get(banco, _parse_generico)
    try:
        df_parsed = parser_fn(df_raw)
    except Exception as e:
        logger.warn(f"Error con parser {banco}, usando genérico: {e}")
        df_parsed = _parse_generico(df_raw)

    if df_parsed.empty:
        logger.warn("No se encontraron movimientos válidos")
        return pd.DataFrame(columns=COLS_SALIDA)

    # 4. Enriquecer
    nombre_banco = FORMATOS_BANCO.get(banco, {}).get("nombre", banco.title())
    df_parsed["banco"]     = nombre_banco
    df_parsed["tipo"]      = df_parsed["importe"].apply(lambda x: "INGRESO" if x > 0 else "EGRESO")
    df_parsed["categoria"] = df_parsed.apply(
        lambda r: clasificar_movimiento(r["descripcion"], r["importe"]), axis=1
    )
    df_parsed["mes"]        = df_parsed["fecha"].apply(lambda d: d.month if d else None)
    df_parsed["mes_nombre"] = df_parsed["mes"].apply(lambda m: nombre_mes(m) if m else None)
    df_parsed["año"]        = df_parsed["fecha"].apply(lambda d: d.year if d else None)
    df_parsed["semana"]     = df_parsed["fecha"].apply(
        lambda d: d.isocalendar()[1] if d else None
    )
    df_parsed["fecha_str"]         = df_parsed["fecha"].apply(
        lambda d: d.strftime("%d/%m/%Y") if d else ""
    )
    df_parsed["conciliado"]        = False
    df_parsed["monto_proyectado"]  = None
    df_parsed["desvio"]            = None

    # Ordenar por fecha
    df_parsed = df_parsed.sort_values("fecha").reset_index(drop=True)

    logger.ok(f"Extracto parseado: {len(df_parsed)} movimientos | {nombre_banco}")
    return df_parsed[COLS_SALIDA]


# ══════════════════════════════════════════════════════════════════════
# ESTADÍSTICAS DEL EXTRACTO
# ══════════════════════════════════════════════════════════════════════

def estadisticas_extracto(df: pd.DataFrame) -> dict:
    """Calcula estadísticas básicas de un extracto parseado."""
    if df.empty:
        return {}

    ingresos = df[df["importe"] > 0]["importe"].sum()
    egresos  = df[df["importe"] < 0]["importe"].sum()

    return {
        "total_movimientos": len(df),
        "ingresos_total":    ingresos,
        "egresos_total":     abs(egresos),
        "saldo_neto":        ingresos + egresos,
        "fecha_inicio":      df["fecha"].min(),
        "fecha_fin":         df["fecha"].max(),
        "banco":             df["banco"].iloc[0] if len(df) > 0 else "—",
        "por_categoria":     df.groupby("categoria")["importe"].sum().to_dict(),
        "por_mes":           df.groupby("mes_nombre")["importe"].sum().to_dict(),
        "ingresos_count":    (df["importe"] > 0).sum(),
        "egresos_count":     (df["importe"] < 0).sum(),
    }


# ══════════════════════════════════════════════════════════════════════
# GENERADOR DE DATOS DE MUESTRA
# ══════════════════════════════════════════════════════════════════════

def generar_extracto_muestra(año: int = 2025, mes: int = 5) -> pd.DataFrame:
    """
    Genera un extracto bancario de muestra realista
    para demo y testing (estilo Banco Nación).
    """
    from datetime import date as dt_date
    import random
    random.seed(42)

    movimientos = [
        # Ingresos
        ("02/05/2025", "TRANSF RECIB FARMACIA CENTRAL SA",         340000),
        ("05/05/2025", "ACREDITA CLIENTE FARMACIAS DEL PUEBLO",    285000),
        ("08/05/2025", "COBRO FACTURA A-0892 DROGUERIA NORTE",     156800),
        ("10/05/2025", "TRANSF RECIB FARMASHOP SRL",               412000),
        ("12/05/2025", "PAGO RECIB FARMACIAS MUNICIPALES",         198500),
        ("15/05/2025", "ACREDITA CLIENTE FARMACIA LA PAZ",          87400),
        ("18/05/2025", "TRANSF RECIB MEDICINEA SA",                523000),
        ("20/05/2025", "COBRO FACTURA B-1204 FARMADENT",           167200),
        ("22/05/2025", "PAGO RECIB FARMACIA SAN MARTIN",           340000),
        ("25/05/2025", "TRANSF RECIB FARMACIAS DEL SOL",           289000),
        ("28/05/2025", "ACREDITA CLIENTE FARMARED CABA",           456000),
        # Egresos
        ("05/05/2025", "DEBITO AFIP IVA MAYO 2025",               -98400),
        ("07/05/2025", "PAGO SUELDO MAYO 2025 PERSONAL",         -420000),
        ("07/05/2025", "AFIP SIPA CARGAS SOCIALES MAYO",         -134400),
        ("10/05/2025", "PAGO A LABORATORIO BAYER SA",            -280000),
        ("12/05/2025", "PAGO A LABORATORIO ROCHE ARGENTINA",     -195000),
        ("14/05/2025", "DEBITO AUTOMATICO ALQUILER MAYO",         -95000),
        ("15/05/2025", "CUOTA PRESTAMO BANCO GALICIA NRO 5",      -42000),
        ("16/05/2025", "PAGO A DISTRIBUIDOR FARMALOGIC",          -85000),
        ("19/05/2025", "DEBITO IMPUESTO INGRESOS BRUTOS",         -34500),
        ("20/05/2025", "CHEQUE 00124 ACME SERVICIOS SA",         -185000),
        ("21/05/2025", "PAGO A PROVEEDOR SERVICIOS TEC SRL",      -75000),
        ("22/05/2025", "COMISION MANTENIMIENTO CUENTA MAYO",       -3200),
        ("23/05/2025", "PAGO A LABORATORIO PFIZER ARG",          -320000),
        ("26/05/2025", "IMP DEBITO Y CREDITO MAYO",               -12400),
        ("27/05/2025", "DEBITO AUTOMATICO LUZ EDESUR",            -18700),
        ("28/05/2025", "CHEQUE 00125 PROVEEDOR ABC SRL",          -92000),
        ("29/05/2025", "CUOTA PLAN PAGO AFIP RG 5678",            -12000),
        ("30/05/2025", "DEBITO SEGUROS MAPFRE MAYO",               -9000),
    ]

    rows = []
    saldo = 2_100_000.0
    for fecha_str, desc, imp in movimientos:
        saldo += imp
        rows.append({
            "Fecha":       fecha_str,
            "Descripción": desc,
            "Importe":     imp,
            "Saldo":       saldo,
        })

    return pd.DataFrame(rows)


if __name__ == "__main__":
    print("=== TEST PARSER BANCARIO ===\n")

    # 1. Generar muestra
    df_muestra = generar_extracto_muestra()
    print(f"Extracto muestra: {len(df_muestra)} movimientos")
    print(df_muestra.to_string(index=False))

    # 2. Guardar muestra a CSV
    muestra_path = "./data/samples/extracto_mayo_2025.csv"
    df_muestra.to_csv(muestra_path, index=False, encoding="utf-8")
    print(f"\n✅ Muestra guardada: {muestra_path}")

    # 3. Parsear
    df_parsed = parse_extracto(muestra_path, banco="nacion")
    print(f"\n=== EXTRACTO PARSEADO ({len(df_parsed)} registros) ===")
    print(df_parsed[["fecha_str","descripcion","importe","categoria","tipo"]].to_string(index=False))

    # 4. Estadísticas
    stats = estadisticas_extracto(df_parsed)
    print(f"\n=== ESTADÍSTICAS ===")
    print(f"  Banco:        {stats['banco']}")
    print(f"  Período:      {stats['fecha_inicio']} → {stats['fecha_fin']}")
    print(f"  Movimientos:  {stats['total_movimientos']}")
    print(f"  Ingresos:     {fmt_ars(stats['ingresos_total'])}")
    print(f"  Egresos:      {fmt_ars(stats['egresos_total'])}")
    print(f"  Saldo neto:   {fmt_ars(stats['saldo_neto'])}")
    print(f"\n  Por categoría:")
    for cat, monto in sorted(stats["por_categoria"].items(), key=lambda x: abs(x[1]), reverse=True):
        print(f"    {cat}: {fmt_ars(monto)}")

    print("\n✅ parser_bancario.py OK")
