"""
motor_cashflow.py — Motor central del sistema
Genera:
 - Cashflow mensual (proyectado + real + desvío)
 - Conciliación automática extracto vs proyectado
 - Resumen semanal
 - KPIs financieros
"""
import pandas as pd
import numpy as np
from datetime import date, timedelta
import sys, os
sys.path.insert(0, '.')
from config import (
    ESTACIONALIDAD, CONDICIONES_COBRO, MESES_AGUINALDO,
    SALDO_MINIMO_CRITICO, SALDO_MINIMO_ALERTA
)
from src.utils.helpers import (
    nombre_mes, fmt_ars, semaforo, semaforo_color,
    ajustar_fecha_cobro, logger
)


# ══════════════════════════════════════════════════════════════════════
# MODELO DE PARÁMETROS DEL CASHFLOW
# ══════════════════════════════════════════════════════════════════════

class ParametrosCashflow:
    """Contiene todos los parámetros configurables del cashflow."""
    def __init__(self):
        # Ingresos
        self.budget_anual           = 108_000_000_000
        self.saldo_inicial          = 13_900_000_000

        # Egresos fijos mensuales base
        self.sueldos_brutos         = 420_000
        self.cargas_sociales_base   = 134_400    # base (Jun/Dic = x1.5)
        self.art                    = 12_000
        self.obra_social            = 18_000

        # Impuestos (se replica mes anterior, editable)
        self.iva_mensual            = 98_400
        self.iibb_mensual           = 34_500
        self.ganancias_mensual      = 25_000

        # Planes AFIP
        self.plan_afip_1            = 12_000
        self.plan_afip_2            = 8_500
        self.plan_afip_3            = 0

        # Préstamos
        self.prestamos = [
            {"nombre": "Banco Galicia",     "cuota": 42_000, "mes_ini": 1, "mes_fin": 12},
            {"nombre": "Banco Nación",      "cuota": 85_000, "mes_ini": 3, "mes_fin": 12},
        ]

        # Gastos fijos operativos
        self.alquiler               = 95_000
        self.expensas_abl           = 8_000
        self.servicios              = 18_700
        self.seguros                = 9_000
        self.honorarios             = 35_000
        self.otros_fijos            = 15_000

        # Proveedores variables (% de ventas del mes)
        self.pct_proveedores_ventas = 0.55

    def to_dict(self) -> dict:
        return self.__dict__


# ══════════════════════════════════════════════════════════════════════
# PROYECCIÓN DE INGRESOS
# ══════════════════════════════════════════════════════════════════════

def proyectar_ingresos(params: ParametrosCashflow, año: int = 2025) -> pd.DataFrame:
    """
    Proyecta ingresos mes a mes usando estacionalidad y condiciones de cobro.
    Retorna DataFrame con columnas: mes, mes_nombre, venta_bruta, venta_neta,
    cobro_contado, cobro_30, cobro_60, cobro_90, total_cobros
    """
    meses_nombre = list(ESTACIONALIDAD.keys())
    suma_coefs   = sum(ESTACIONALIDAD.values())
    rows = []

    for i, mes_nombre_str in enumerate(meses_nombre, 1):
        coef      = ESTACIONALIDAD[mes_nombre_str]
        venta     = (params.budget_anual / suma_coefs) * coef
        venta_net = venta  # sin devoluciones por ahora

        # Cobros según condición (con desfase de meses)
        cobro_cont = venta_net * CONDICIONES_COBRO["contado"]

        # Cobro 30d: ventas del mes anterior
        if i > 1:
            coef_prev = list(ESTACIONALIDAD.values())[i-2]
            venta_prev = (params.budget_anual / suma_coefs) * coef_prev
            cobro_30 = venta_prev * CONDICIONES_COBRO["dias_30"]
        else:
            cobro_30 = 0  # Enero: sin mes anterior visible

        # Cobro 60d: ventas de hace 2 meses
        if i > 2:
            coef_prev2 = list(ESTACIONALIDAD.values())[i-3]
            venta_prev2 = (params.budget_anual / suma_coefs) * coef_prev2
            cobro_60 = venta_prev2 * CONDICIONES_COBRO["dias_60"]
        else:
            cobro_60 = 0

        # Cobro 90d: ventas de hace 3 meses
        if i > 3:
            coef_prev3 = list(ESTACIONALIDAD.values())[i-4]
            venta_prev3 = (params.budget_anual / suma_coefs) * coef_prev3
            cobro_90 = venta_prev3 * CONDICIONES_COBRO["dias_90"]
        else:
            cobro_90 = 0

        total_cobros = cobro_cont + cobro_30 + cobro_60 + cobro_90

        rows.append({
            "mes":          i,
            "mes_nombre":   mes_nombre_str,
            "venta_bruta":  venta,
            "venta_neta":   venta_net,
            "cobro_contado": cobro_cont,
            "cobro_30d":    cobro_30,
            "cobro_60d":    cobro_60,
            "cobro_90d":    cobro_90,
            "total_cobros": total_cobros,
        })

    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════
# PROYECCIÓN DE EGRESOS
# ══════════════════════════════════════════════════════════════════════

def proyectar_egresos(params: ParametrosCashflow, df_ingresos: pd.DataFrame) -> pd.DataFrame:
    """
    Proyecta egresos mes a mes.
    Incluye lógica de aguinaldo en Jun/Dic.
    """
    rows = []
    meses_nombre = list(ESTACIONALIDAD.keys())

    for i in range(1, 13):
        mes_nombre_str = meses_nombre[i-1]
        es_aguinaldo   = i in MESES_AGUINALDO
        mult_aguinaldo = 1.5 if es_aguinaldo else 1.0

        # Sueldos y cargas
        sueldos      = params.sueldos_brutos
        cargas_soc   = params.cargas_sociales_base * mult_aguinaldo
        art          = params.art
        obra_social  = params.obra_social

        # Impuestos (replicar mes anterior)
        iva          = params.iva_mensual
        iibb         = params.iibb_mensual
        ganancias    = params.ganancias_mensual

        # Planes AFIP
        plan_afip    = params.plan_afip_1 + params.plan_afip_2 + params.plan_afip_3

        # Préstamos (solo en el rango de meses definido)
        cuotas_prest = sum(
            p["cuota"] for p in params.prestamos
            if p["mes_ini"] <= i <= p["mes_fin"]
        )

        # Gastos fijos
        gastos_fijos = (
            params.alquiler + params.expensas_abl + params.servicios +
            params.seguros + params.honorarios + params.otros_fijos
        )

        # Proveedores variables (% de ventas del mes)
        venta_mes  = df_ingresos.loc[df_ingresos["mes"] == i, "venta_neta"].values
        venta_mes  = float(venta_mes[0]) if len(venta_mes) > 0 else 0
        proveedores = venta_mes * params.pct_proveedores_ventas

        total_egresos = (
            sueldos + cargas_soc + art + obra_social +
            iva + iibb + ganancias + plan_afip +
            cuotas_prest + gastos_fijos + proveedores
        )

        rows.append({
            "mes":             i,
            "mes_nombre":      mes_nombre_str,
            "sueldos":         sueldos,
            "cargas_sociales": cargas_soc,
            "art":             art,
            "obra_social":     obra_social,
            "iva":             iva,
            "iibb":            iibb,
            "ganancias":       ganancias,
            "plan_afip":       plan_afip,
            "cuotas_prestamos": cuotas_prest,
            "gastos_fijos":    gastos_fijos,
            "proveedores":     proveedores,
            "total_egresos":   total_egresos,
            "aguinaldo_mes":   es_aguinaldo,
        })

    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════
# CASHFLOW MENSUAL COMPLETO
# ══════════════════════════════════════════════════════════════════════

def generar_cashflow_mensual(
    params: ParametrosCashflow,
    df_real: pd.DataFrame = None,  # extracto bancario parseado
    año: int = 2025
) -> pd.DataFrame:
    """
    Genera el cashflow mensual completo:
    - Proyectado (de los parámetros)
    - Real (de los extractos bancarios cargados)
    - Desvío y semáforo

    Returns DataFrame con una fila por mes.
    """
    df_ing = proyectar_ingresos(params, año)
    df_eg  = proyectar_egresos(params, df_ing)

    rows = []
    saldo_ini_proy = params.saldo_inicial
    saldo_ini_real = params.saldo_inicial

    for i in range(1, 13):
        mes_nombre_str = list(ESTACIONALIDAD.keys())[i-1]

        # Proyectado
        ing_proy = float(df_ing.loc[df_ing["mes"] == i, "total_cobros"].values[0])
        eg_proy  = float(df_eg.loc[df_eg["mes"] == i, "total_egresos"].values[0])
        res_proy = ing_proy - eg_proy
        saldo_fin_proy = saldo_ini_proy + res_proy

        # Real (de extracto bancario)
        if df_real is not None and not df_real.empty:
            df_mes = df_real[df_real["mes"] == i]
            ing_real = float(df_mes[df_mes["importe"] > 0]["importe"].sum())
            eg_real  = abs(float(df_mes[df_mes["importe"] < 0]["importe"].sum()))
            res_real = ing_real - eg_real
            saldo_fin_real = saldo_ini_real + res_real
            tiene_real = len(df_mes) > 0
        else:
            ing_real = eg_real = res_real = saldo_fin_real = None
            tiene_real = False

        # Desvíos
        dev_ing = (ing_real - ing_proy) if tiene_real else None
        dev_eg  = (eg_real  - eg_proy)  if tiene_real else None
        dev_pct_ing = (dev_ing / ing_proy * 100) if (tiene_real and ing_proy != 0) else None

        # Semáforo (basado en proyectado)
        sem = semaforo(saldo_fin_proy, SALDO_MINIMO_CRITICO, SALDO_MINIMO_ALERTA)
        sem_color = semaforo_color(saldo_fin_proy, SALDO_MINIMO_CRITICO, SALDO_MINIMO_ALERTA)

        rows.append({
            "mes":              i,
            "mes_nombre":       mes_nombre_str,
            # Proyectado
            "saldo_ini_proy":   saldo_ini_proy,
            "ing_proy":         ing_proy,
            "eg_proy":          eg_proy,
            "res_proy":         res_proy,
            "saldo_fin_proy":   saldo_fin_proy,
            # Real
            "saldo_ini_real":   saldo_ini_real if tiene_real else None,
            "ing_real":         ing_real,
            "eg_real":          eg_real,
            "res_real":         res_real,
            "saldo_fin_real":   saldo_fin_real,
            "tiene_real":       tiene_real,
            # Desvíos
            "dev_ing":          dev_ing,
            "dev_eg":           dev_eg,
            "dev_pct_ing":      dev_pct_ing,
            # Semáforo
            "semaforo":         sem,
            "semaforo_color":   sem_color,
            # Detalle ingresos
            "cobro_contado":    float(df_ing.loc[df_ing["mes"]==i,"cobro_contado"].values[0]),
            "cobro_30d":        float(df_ing.loc[df_ing["mes"]==i,"cobro_30d"].values[0]),
            "cobro_60d":        float(df_ing.loc[df_ing["mes"]==i,"cobro_60d"].values[0]),
            "cobro_90d":        float(df_ing.loc[df_ing["mes"]==i,"cobro_90d"].values[0]),
            "venta_neta":       float(df_ing.loc[df_ing["mes"]==i,"venta_neta"].values[0]),
            # Detalle egresos
            "sueldos":          float(df_eg.loc[df_eg["mes"]==i,"sueldos"].values[0]),
            "cargas_sociales":  float(df_eg.loc[df_eg["mes"]==i,"cargas_sociales"].values[0]),
            "iva":              float(df_eg.loc[df_eg["mes"]==i,"iva"].values[0]),
            "cuotas_prestamos": float(df_eg.loc[df_eg["mes"]==i,"cuotas_prestamos"].values[0]),
            "proveedores":      float(df_eg.loc[df_eg["mes"]==i,"proveedores"].values[0]),
            "aguinaldo_mes":    bool(df_eg.loc[df_eg["mes"]==i,"aguinaldo_mes"].values[0]),
        })

        # Avanzar saldo inicial
        saldo_ini_proy = saldo_fin_proy
        if tiene_real:
            saldo_ini_real = saldo_fin_real

    logger.ok(f"Cashflow mensual generado: {len(rows)} meses")
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════
# CONCILIACIÓN AUTOMÁTICA
# ══════════════════════════════════════════════════════════════════════

def conciliar_automatico(
    df_extracto: pd.DataFrame,
    df_cashflow: pd.DataFrame,
    tolerancia_pct: float = 0.05,   # 5% de tolerancia para match
    tolerancia_dias: int = 3,
) -> pd.DataFrame:
    """
    Concilia automáticamente los movimientos del extracto
    contra el cashflow proyectado.

    Match por: categoría + mes + importe aproximado.
    Estados: MATCH / DESVÍO / SIN_MATCH
    """
    if df_extracto.empty:
        return df_extracto.copy()

    df = df_extracto.copy()
    df["estado_conciliacion"] = "SIN_MATCH"
    df["match_descripcion"]   = ""

    # Totales proyectados por mes y categoría
    categorias_mes = {}
    if not df_cashflow.empty:
        for _, row in df_cashflow.iterrows():
            mes = int(row["mes"])
            categorias_mes[mes] = {
                "Cobranzas":        row.get("ing_proy", 0),
                "Sueldos":          row.get("sueldos", 0),
                "Cargas Sociales":  row.get("cargas_sociales", 0),
                "AFIP":             row.get("iva", 0),
                "Préstamos":        row.get("cuotas_prestamos", 0),
                "Proveedores":      row.get("proveedores", 0),
            }

    for idx, mov in df.iterrows():
        mes  = mov["mes"]
        cat  = mov["categoria"]
        imp  = abs(mov["importe"])
        proy = categorias_mes.get(mes, {}).get(cat, None)

        if proy is not None and proy > 0:
            dif_pct = abs(imp - proy) / proy if proy > 0 else 1.0
            if dif_pct <= tolerancia_pct:
                df.at[idx, "estado_conciliacion"] = "MATCH"
                df.at[idx, "match_descripcion"]   = f"Match {cat} — dif {dif_pct*100:.1f}%"
                df.at[idx, "monto_proyectado"]     = proy
                df.at[idx, "desvio"]               = imp - proy
            elif dif_pct <= 0.20:
                df.at[idx, "estado_conciliacion"] = "DESVÍO"
                df.at[idx, "match_descripcion"]   = f"Desvío {dif_pct*100:.1f}% en {cat}"
                df.at[idx, "monto_proyectado"]     = proy
                df.at[idx, "desvio"]               = imp - proy
        # else: queda SIN_MATCH

    n_match  = (df["estado_conciliacion"] == "MATCH").sum()
    n_desvio = (df["estado_conciliacion"] == "DESVÍO").sum()
    n_sin    = (df["estado_conciliacion"] == "SIN_MATCH").sum()
    pct      = (n_match + n_desvio) / len(df) * 100 if len(df) > 0 else 0

    logger.ok(
        f"Conciliación: {n_match} match | {n_desvio} desvío | "
        f"{n_sin} sin match | {pct:.0f}% conciliado"
    )
    return df


# ══════════════════════════════════════════════════════════════════════
# RESUMEN SEMANAL
# ══════════════════════════════════════════════════════════════════════

def generar_resumen_semanal(
    df_extracto: pd.DataFrame,
    df_cashflow: pd.DataFrame
) -> pd.DataFrame:
    """
    Agrupa los movimientos del extracto por semana.
    Calcula saldo acumulado semanal.
    """
    if df_extracto.empty:
        return pd.DataFrame()

    df = df_extracto.copy()
    df["semana_label"] = df.apply(
        lambda r: f"S{r['semana']:02d} — {r['mes_nombre'][:3]}" if r['semana'] else "—",
        axis=1
    )

    resumen = df.groupby(["semana", "semana_label"]).agg(
        ingresos=("importe", lambda x: x[x > 0].sum()),
        egresos= ("importe", lambda x: abs(x[x < 0].sum())),
        resultado=("importe", "sum"),
        movimientos=("importe", "count"),
    ).reset_index()

    resumen = resumen.sort_values("semana")
    resumen["saldo_acum"] = resumen["resultado"].cumsum()
    resumen["semaforo"] = resumen["saldo_acum"].apply(
        lambda s: semaforo(s, SALDO_MINIMO_CRITICO, SALDO_MINIMO_ALERTA)
    )

    return resumen


# ══════════════════════════════════════════════════════════════════════
# KPIs EJECUTIVOS
# ══════════════════════════════════════════════════════════════════════

def calcular_kpis(
    df_cashflow: pd.DataFrame,
    df_extracto: pd.DataFrame = None
) -> dict:
    """Calcula KPIs ejecutivos del período."""
    kpis = {}

    if df_cashflow.empty:
        return kpis

    # Saldo actual (último mes con real, o proyectado)
    df_con_real = df_cashflow[df_cashflow["tiene_real"]]
    if not df_con_real.empty:
        ultimo_real = df_con_real.iloc[-1]
        kpis["saldo_actual"]       = ultimo_real["saldo_fin_real"]
        kpis["saldo_actual_label"] = "Real"
        kpis["mes_actual"]         = ultimo_real["mes_nombre"]
    else:
        primer = df_cashflow.iloc[0]
        kpis["saldo_actual"]       = primer["saldo_fin_proy"]
        kpis["saldo_actual_label"] = "Proyectado"
        kpis["mes_actual"]         = primer["mes_nombre"]

    # Totales anuales proyectados
    kpis["ing_anual_proy"]   = df_cashflow["ing_proy"].sum()
    kpis["eg_anual_proy"]    = df_cashflow["eg_proy"].sum()
    kpis["res_anual_proy"]   = kpis["ing_anual_proy"] - kpis["eg_anual_proy"]

    # Totales reales acumulados
    df_r = df_cashflow[df_cashflow["tiene_real"]]
    kpis["ing_real_acum"]    = df_r["ing_real"].sum() if not df_r.empty else 0
    kpis["eg_real_acum"]     = df_r["eg_real"].sum()  if not df_r.empty else 0

    # Desvío promedio ingresos
    if not df_r.empty and df_r["dev_pct_ing"].notna().any():
        kpis["desvio_pct_ing_prom"] = df_r["dev_pct_ing"].mean()
    else:
        kpis["desvio_pct_ing_prom"] = 0

    # Meses críticos (saldo proyectado < umbral)
    kpis["meses_criticos"]  = df_cashflow[
        df_cashflow["saldo_fin_proy"] < SALDO_MINIMO_CRITICO
    ]["mes_nombre"].tolist()
    kpis["meses_alerta"]    = df_cashflow[
        (df_cashflow["saldo_fin_proy"] >= SALDO_MINIMO_CRITICO) &
        (df_cashflow["saldo_fin_proy"] <  SALDO_MINIMO_ALERTA)
    ]["mes_nombre"].tolist()

    # Saldo mínimo proyectado
    kpis["saldo_min_proy"]  = df_cashflow["saldo_fin_proy"].min()
    kpis["mes_saldo_min"]   = df_cashflow.loc[
        df_cashflow["saldo_fin_proy"].idxmin(), "mes_nombre"
    ]

    # Cheques pendientes (si hay extracto)
    if df_extracto is not None and not df_extracto.empty:
        cheques = df_extracto[df_extracto["categoria"] == "Cheques"]
        kpis["cheques_total"] = abs(cheques["importe"].sum())
        kpis["cheques_count"] = len(cheques)
        # Conciliación
        if "estado_conciliacion" in df_extracto.columns:
            total_mov = len(df_extracto)
            conciliados = (df_extracto["estado_conciliacion"].isin(["MATCH","DESVÍO"])).sum()
            kpis["pct_conciliado"] = conciliados / total_mov * 100 if total_mov > 0 else 0
        else:
            kpis["pct_conciliado"] = 0
    else:
        kpis["cheques_total"] = 0
        kpis["cheques_count"] = 0
        kpis["pct_conciliado"] = 0

    return kpis


if __name__ == "__main__":
    print("=== TEST MOTOR CASHFLOW ===\n")

    # Parámetros
    params = ParametrosCashflow()

    # Generar cashflow sin extracto real
    df_cf = generar_cashflow_mensual(params, año=2025)

    print("=== CASHFLOW MENSUAL PROYECTADO ===")
    for _, row in df_cf.iterrows():
        aguinaldo = " ⚠️ AGUINALDO" if row["aguinaldo_mes"] else ""
        print(
            f"  {row['mes_nombre']:12} | "
            f"SI: {fmt_ars(row['saldo_ini_proy']):>15} | "
            f"Ing: {fmt_ars(row['ing_proy']):>14} | "
            f"Eg: {fmt_ars(row['eg_proy']):>14} | "
            f"SF: {fmt_ars(row['saldo_fin_proy']):>15} | "
            f"{row['semaforo']}{aguinaldo}"
        )

    # Simular extracto real (Mayo)
    from src.parsers.parser_bancario import generar_extracto_muestra, parse_extracto
    df_muestra = generar_extracto_muestra()
    path_muestra = "./data/samples/extracto_mayo_2025.csv"
    df_muestra.to_csv(path_muestra, index=False)
    df_real = parse_extracto(path_muestra, banco="nacion")

    # Cashflow con real
    df_cf2 = generar_cashflow_mensual(params, df_real=df_real, año=2025)

    print("\n=== MAYO: REAL vs PROYECTADO ===")
    mayo = df_cf2[df_cf2["mes"] == 5].iloc[0]
    print(f"  Ingresos Proyectados: {fmt_ars(mayo['ing_proy'])}")
    print(f"  Ingresos Reales:      {fmt_ars(mayo['ing_real'])}")
    print(f"  Desvío Ingresos:      {fmt_ars(mayo['dev_ing'])} ({mayo['dev_pct_ing']:.1f}%)")
    print(f"  Egresos Proyectados:  {fmt_ars(mayo['eg_proy'])}")
    print(f"  Egresos Reales:       {fmt_ars(mayo['eg_real'])}")
    print(f"  Saldo Final Real:     {fmt_ars(mayo['saldo_fin_real'])}")

    # KPIs
    kpis = calcular_kpis(df_cf2, df_real)
    print("\n=== KPIs EJECUTIVOS ===")
    print(f"  Saldo actual:         {fmt_ars(kpis['saldo_actual'])} ({kpis['saldo_actual_label']})")
    print(f"  Ingresos anuales proy:{fmt_ars(kpis['ing_anual_proy'])}")
    print(f"  Egresos anuales proy: {fmt_ars(kpis['eg_anual_proy'])}")
    print(f"  Meses críticos:       {kpis['meses_criticos'] or 'Ninguno'}")
    print(f"  Meses en alerta:      {kpis['meses_alerta'] or 'Ninguno'}")
    print(f"  Saldo mínimo:         {fmt_ars(kpis['saldo_min_proy'])} ({kpis['mes_saldo_min']})")

    print("\n✅ motor_cashflow.py OK")
