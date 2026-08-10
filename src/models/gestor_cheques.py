"""
gestor_cheques.py — Gestión completa de cheques emitidos y pagarés
Funciones:
  - Registro de cheques con ajuste automático a día hábil
  - Clasificación por estado (pendiente / cobrado / rechazado)
  - Alertas por vencimiento (hoy, próximos 7 días, próximos 30 días)
  - Resumen mensual para integrar al cashflow
  - Carga y persistencia en CSV
"""
import pandas as pd
from datetime import date, timedelta
import os, sys
sys.path.insert(0, '.')
from src.utils.helpers import (
    ajustar_fecha_cobro, es_habil, parse_fecha,
    nombre_mes, fmt_ars, logger
)

CHEQUES_PATH = "./data/cheques.csv"

COLS_CHEQUES = [
    "id",
    "numero",            # Número de cheque
    "beneficiario",      # Proveedor / empresa
    "concepto",          # Descripción del pago
    "monto",             # Importe
    "fecha_emision",     # Fecha de emisión
    "fecha_vto_original",# Vencimiento original
    "fecha_vto_habil",   # Vencimiento ajustado a día hábil (calculado)
    "dia_semana_vto",    # Día de la semana del vto original
    "fue_ajustado",      # True si se corrió por feriado/fin de semana
    "mes_impacta",       # Mes numérico donde impacta en el cashflow
    "mes_nombre",        # Nombre del mes
    "estado",            # pendiente / cobrado / rechazado / vencido
    "banco_emisor",      # Banco del cual se emite
    "observaciones",
]


# ══════════════════════════════════════════════════════════════════════
# CARGA Y GUARDADO
# ══════════════════════════════════════════════════════════════════════

def cargar_cheques() -> pd.DataFrame:
    """Carga los cheques desde el archivo CSV persistente."""
    if os.path.exists(CHEQUES_PATH):
        df = pd.read_csv(CHEQUES_PATH)
        # Parsear fechas
        for col in ["fecha_emision", "fecha_vto_original", "fecha_vto_habil"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
        logger.info(f"Cheques cargados: {len(df)} registros")
        return df
    else:
        logger.info("No hay archivo de cheques, creando nuevo.")
        return pd.DataFrame(columns=COLS_CHEQUES)


def guardar_cheques(df: pd.DataFrame):
    """Guarda el DataFrame de cheques al CSV."""
    os.makedirs(os.path.dirname(CHEQUES_PATH), exist_ok=True)
    df.to_csv(CHEQUES_PATH, index=False)
    logger.ok(f"Cheques guardados: {len(df)} registros → {CHEQUES_PATH}")


# ══════════════════════════════════════════════════════════════════════
# AGREGAR CHEQUE
# ══════════════════════════════════════════════════════════════════════

def agregar_cheque(
    df: pd.DataFrame,
    numero: str,
    beneficiario: str,
    monto: float,
    fecha_vto: str,              # DD/MM/YYYY o date
    concepto: str = "",
    fecha_emision: str = None,
    estado: str = "pendiente",
    banco_emisor: str = "Banco Nación",
    observaciones: str = "",
) -> pd.DataFrame:
    """
    Agrega un cheque al DataFrame.
    Calcula automáticamente:
      - fecha_vto_habil (ajuste día hábil)
      - dia_semana_vto
      - fue_ajustado
      - mes_impacta, mes_nombre
    """
    fecha_vto_orig = parse_fecha(fecha_vto)
    if fecha_vto_orig is None:
        logger.error(f"Fecha de vencimiento inválida: {fecha_vto}")
        return df

    fecha_vto_adj  = ajustar_fecha_cobro(fecha_vto_orig)
    fue_ajustado   = fecha_vto_adj != fecha_vto_orig

    dias_semana = {0:"Lunes",1:"Martes",2:"Miércoles",3:"Jueves",
                   4:"Viernes",5:"Sábado",6:"Domingo"}
    dia_sem = dias_semana[fecha_vto_orig.weekday()]

    fe = parse_fecha(fecha_emision) if fecha_emision else date.today()

    # Nuevo ID
    nuevo_id = int(df["id"].max() + 1) if not df.empty and "id" in df.columns and len(df) > 0 else 1

    nueva_fila = {
        "id":                 nuevo_id,
        "numero":             str(numero).strip(),
        "beneficiario":       beneficiario.strip(),
        "concepto":           concepto.strip(),
        "monto":              float(monto),
        "fecha_emision":      fe,
        "fecha_vto_original": fecha_vto_orig,
        "fecha_vto_habil":    fecha_vto_adj,
        "dia_semana_vto":     dia_sem,
        "fue_ajustado":       fue_ajustado,
        "mes_impacta":        fecha_vto_adj.month,
        "mes_nombre":         nombre_mes(fecha_vto_adj.month),
        "estado":             estado,
        "banco_emisor":       banco_emisor,
        "observaciones":      observaciones,
    }
    df_new = pd.concat([df, pd.DataFrame([nueva_fila])], ignore_index=True)

    if fue_ajustado:
        logger.warn(
            f"Cheque {numero} ({beneficiario}): vto {fecha_vto_orig.strftime('%d/%m/%Y')} "
            f"({dia_sem}) → ajustado a {fecha_vto_adj.strftime('%d/%m/%Y')}"
        )
    else:
        logger.info(f"Cheque {numero} ({beneficiario}): vto {fecha_vto_adj.strftime('%d/%m/%Y')} ({dia_sem}) ✓")

    return df_new


# ══════════════════════════════════════════════════════════════════════
# ACTUALIZAR ESTADO
# ══════════════════════════════════════════════════════════════════════

def actualizar_estado_cheque(df: pd.DataFrame, numero: str, nuevo_estado: str) -> pd.DataFrame:
    """Actualiza el estado de un cheque (pendiente/cobrado/rechazado/vencido)."""
    estados_validos = {"pendiente", "cobrado", "rechazado", "vencido"}
    if nuevo_estado not in estados_validos:
        logger.error(f"Estado inválido: {nuevo_estado}. Válidos: {estados_validos}")
        return df
    mask = df["numero"] == str(numero)
    if mask.sum() == 0:
        logger.warn(f"Cheque {numero} no encontrado")
        return df
    df.loc[mask, "estado"] = nuevo_estado
    logger.ok(f"Cheque {numero} → estado: {nuevo_estado}")
    return df


def marcar_cheques_vencidos(df: pd.DataFrame, fecha_hoy: date = None) -> pd.DataFrame:
    """
    Marca automáticamente como 'vencido' todos los cheques pendientes
    cuya fecha hábil ya pasó.
    """
    if fecha_hoy is None:
        fecha_hoy = date.today()
    mask = (
        (df["estado"] == "pendiente") &
        (df["fecha_vto_habil"].apply(
            lambda d: d < fecha_hoy if isinstance(d, date) else False
        ))
    )
    n_vencidos = mask.sum()
    if n_vencidos > 0:
        df.loc[mask, "estado"] = "vencido"
        logger.warn(f"{n_vencidos} cheques marcados como vencidos")
    return df


# ══════════════════════════════════════════════════════════════════════
# ALERTAS
# ══════════════════════════════════════════════════════════════════════

def alertas_cheques(df: pd.DataFrame, fecha_hoy: date = None) -> dict:
    """
    Genera alertas clasificadas por urgencia:
      - hoy:       vencen hoy
      - proximos7: vencen en los próximos 7 días hábiles
      - proximos30:vencen en los próximos 30 días
      - vencidos:  ya vencidos y siguen pendientes
    """
    if fecha_hoy is None:
        fecha_hoy = date.today()

    fecha_7d  = fecha_hoy + timedelta(days=7)
    fecha_30d = fecha_hoy + timedelta(days=30)

    df_pend = df[df["estado"] == "pendiente"].copy()
    if df_pend.empty:
        return {"hoy": pd.DataFrame(), "proximos7": pd.DataFrame(),
                "proximos30": pd.DataFrame(), "vencidos": pd.DataFrame()}

    def _fecha(v):
        if isinstance(v, date): return v
        if isinstance(v, str):  return parse_fecha(v)
        return None

    df_pend["_vto"] = df_pend["fecha_vto_habil"].apply(_fecha)

    hoy_df      = df_pend[df_pend["_vto"] == fecha_hoy].drop(columns=["_vto"])
    prox7_df    = df_pend[(df_pend["_vto"] > fecha_hoy) & (df_pend["_vto"] <= fecha_7d)].drop(columns=["_vto"])
    prox30_df   = df_pend[(df_pend["_vto"] > fecha_7d)  & (df_pend["_vto"] <= fecha_30d)].drop(columns=["_vto"])
    vencidos_df = df_pend[df_pend["_vto"] < fecha_hoy].drop(columns=["_vto"])

    total_urgente = float(hoy_df["monto"].sum() + vencidos_df["monto"].sum()) if not hoy_df.empty or not vencidos_df.empty else 0.0

    if not hoy_df.empty:
        logger.warn(f"🔴 {len(hoy_df)} cheques vencen HOY — Total: {fmt_ars(hoy_df['monto'].sum())}")
    if not vencidos_df.empty:
        logger.warn(f"🔴 {len(vencidos_df)} cheques vencidos pendientes — Total: {fmt_ars(vencidos_df['monto'].sum())}")
    if not prox7_df.empty:
        logger.warn(f"🟡 {len(prox7_df)} cheques vencen en 7 días — Total: {fmt_ars(prox7_df['monto'].sum())}")

    return {
        "hoy":        hoy_df,
        "proximos7":  prox7_df,
        "proximos30": prox30_df,
        "vencidos":   vencidos_df,
        "total_urgente": total_urgente,
    }


# ══════════════════════════════════════════════════════════════════════
# RESUMEN MENSUAL (para integrar al cashflow)
# ══════════════════════════════════════════════════════════════════════

def resumen_mensual_cheques(df: pd.DataFrame) -> pd.DataFrame:
    """
    Agrupa los cheques por mes (usando fecha hábil efectiva).
    Devuelve resumen mensual para integrar al cashflow.
    Solo considera cheques no rechazados.
    """
    df_validos = df[df["estado"] != "rechazado"].copy()
    if df_validos.empty:
        rows = [{"mes": i, "mes_nombre": nombre_mes(i), "total_cheques": 0.0, "cantidad": 0} for i in range(1, 13)]
        return pd.DataFrame(rows)

    resumen = df_validos.groupby(["mes_impacta", "mes_nombre"]).agg(
        total_cheques=("monto", "sum"),
        cantidad=("monto", "count"),
    ).reset_index().rename(columns={"mes_impacta": "mes"})

    # Completar meses faltantes
    todos_meses = pd.DataFrame({
        "mes": range(1, 13),
        "mes_nombre": [nombre_mes(i) for i in range(1, 13)]
    })
    resumen = todos_meses.merge(resumen, on=["mes", "mes_nombre"], how="left").fillna(0)
    resumen["total_cheques"] = resumen["total_cheques"].astype(float)
    resumen["cantidad"]      = resumen["cantidad"].astype(int)

    return resumen


# ══════════════════════════════════════════════════════════════════════
# GENERAR DATASET DE MUESTRA
# ══════════════════════════════════════════════════════════════════════

def generar_cheques_muestra() -> pd.DataFrame:
    """Genera cheques de muestra realistas para demo."""
    df = pd.DataFrame(columns=COLS_CHEQUES)

    cheques = [
        # num,  beneficiario,             monto,    fecha_vto,   concepto,             estado
        ("00120","ACME Servicios SA",       185000,  "03/05/2025", "Servicios informática","cobrado"),
        ("00121","Proveedor ABC SRL",        92000,  "12/05/2025", "Insumos oficina",       "cobrado"),
        ("00122","Distribuidora ZZZ SA",    141000,  "18/05/2025", "Fletes mayo",           "cobrado"),
        ("00123","Servicios TEC SRL",        58000,  "25/05/2025", "Mantenimiento",         "cobrado"),
        ("00124","Laboratorio Farmex SA",   285000,  "07/06/2025", "Compra medicamentos",   "pendiente"),
        ("00125","Proveedor Logístico",     112000,  "14/06/2025", "Logística distribución","pendiente"),
        ("00126","Imprenta Central",         35000,  "15/06/2025", "Material impreso",      "pendiente"),
        ("00127","Limpieza Profesional SRL", 28500,  "21/06/2025", "Servicio limpieza",     "pendiente"),
        ("00128","Consultoría IT",          150000,  "28/06/2025", "Desarrollo sistema",    "pendiente"),
        ("00129","Laboratorio Bayer SA",    320000,  "05/07/2025", "Pedido julio",          "pendiente"),
        ("00130","Roche Argentina SA",      198000,  "06/07/2025", "Medicamentos especiales","pendiente"),
        ("00131","Provmed Distribuidora",    87000,  "12/07/2025", "Insumos descartables",  "pendiente"),
        ("00132","Seguros Médicos SA",       15000,  "19/07/2025", "Prima seguro julio",    "pendiente"),
        ("00133","Alquileres del Sur SRL",   95000,  "01/08/2025", "Alquiler agosto",       "pendiente"),
    ]

    for num, benef, monto, fvto, concepto, estado in cheques:
        df = agregar_cheque(df, num, benef, monto, fvto, concepto=concepto, estado=estado)

    return df


if __name__ == "__main__":
    print("=== TEST GESTOR CHEQUES ===\n")

    # 1. Generar muestra
    df_ch = generar_cheques_muestra()
    print(f"\nCheques cargados: {len(df_ch)}")

    print("\n=== TODOS LOS CHEQUES ===")
    cols_show = ["numero","beneficiario","monto","fecha_vto_original","dia_semana_vto","fue_ajustado","fecha_vto_habil","mes_nombre","estado"]
    print(df_ch[cols_show].to_string(index=False))

    # 2. Cheques ajustados (cayeron en finde/feriado)
    ajustados = df_ch[df_ch["fue_ajustado"]]
    print(f"\n=== CHEQUES CON AJUSTE DE DÍA HÁBIL ({len(ajustados)}) ===")
    if not ajustados.empty:
        for _, r in ajustados.iterrows():
            print(f"  N°{r['numero']} — {r['beneficiario']}: "
                  f"{r['fecha_vto_original'].strftime('%d/%m/%Y')} ({r['dia_semana_vto']}) "
                  f"→ {r['fecha_vto_habil'].strftime('%d/%m/%Y')} ✓")

    # 3. Alertas (simulando fecha actual = 10/06/2025)
    fecha_sim = date(2025, 6, 10)
    print(f"\n=== ALERTAS AL {fecha_sim.strftime('%d/%m/%Y')} ===")
    alertas = alertas_cheques(df_ch, fecha_hoy=fecha_sim)
    print(f"  Vencen HOY:       {len(alertas['hoy'])} | {fmt_ars(alertas['hoy']['monto'].sum() if not alertas['hoy'].empty else 0)}")
    print(f"  Próximos 7 días:  {len(alertas['proximos7'])} | {fmt_ars(alertas['proximos7']['monto'].sum() if not alertas['proximos7'].empty else 0)}")
    print(f"  Próximos 30 días: {len(alertas['proximos30'])} | {fmt_ars(alertas['proximos30']['monto'].sum() if not alertas['proximos30'].empty else 0)}")
    print(f"  Vencidos:         {len(alertas['vencidos'])} | {fmt_ars(alertas['vencidos']['monto'].sum() if not alertas['vencidos'].empty else 0)}")

    # 4. Resumen mensual
    print("\n=== RESUMEN MENSUAL CHEQUES ===")
    resumen = resumen_mensual_cheques(df_ch)
    for _, r in resumen.iterrows():
        if r["cantidad"] > 0:
            print(f"  {r['mes_nombre']:12}: {fmt_ars(r['total_cheques']):>15} ({int(r['cantidad'])} cheques)")

    # 5. Guardar
    guardar_cheques(df_ch)
    print("\n✅ gestor_cheques.py OK")
