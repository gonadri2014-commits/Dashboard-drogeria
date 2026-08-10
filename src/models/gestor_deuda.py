"""
gestor_deuda.py — Módulo integral de Deuda Financiera
Cubre:
  1. PRÉSTAMOS BANCARIOS  — capital, tasa, cuota, vencimiento final
  2. PLANES AFIP          — moratorias, facilidades, cuotas + interés resarcitorio
  3. IMPUESTOS PERIÓDICOS — IVA, IIBB, Ganancias, SIPA, Obra Social, ART
     → proyectado vs abonado real (linkeado al extracto bancario)
  4. TABLERO DE TASAS     — comparativa con tasa de referencia BCRA / mercado
     → análisis de rollover: ¿conviene refinanciar?
  5. ALERTAS DE VENCIMIENTO — automáticas para todos los tipos

Diseñado para carga única inicial + actualización incremental.
Preparado para linkear con SAP FI-TR.
"""
import pandas as pd
import json
import os
import sys
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
sys.path.insert(0, '.')
from src.utils.helpers import parse_fecha, nombre_mes, fmt_ars, fmt_pct, logger

# ── Rutas de persistencia ─────────────────────────────────────────────
PRESTAMOS_PATH   = "./data/prestamos.json"
AFIP_PLANES_PATH = "./data/afip_planes.json"
IMPUESTOS_PATH   = "./data/impuestos_config.json"
PAGOS_IMP_PATH   = "./data/pagos_impuestos.csv"
TASAS_REF_PATH   = "./data/tasas_referencia.json"


# ══════════════════════════════════════════════════════════════════════
# 1. PRÉSTAMOS BANCARIOS
# ══════════════════════════════════════════════════════════════════════

def prestamo_vacio() -> dict:
    return {
        "id": None, "banco": "", "descripcion": "", "tipo": "amortizante",
        "capital_original": 0.0, "capital_vigente": 0.0,
        "tna": 0.0, "tea": 0.0, "cftna": 0.0,  # tasas
        "cuota_mensual": 0.0, "cuotas_totales": 0, "cuotas_pagadas": 0,
        "fecha_otorgamiento": None, "fecha_primera_cuota": None,
        "fecha_vencimiento_final": None,
        "dia_debito": 25,  # día del mes en que se debita
        "moneda": "ARS", "estado": "vigente",
        "garantia": "", "observaciones": "",
        "historial_pagos": [],  # [{fecha, capital, interes, total}]
    }

def cargar_prestamos() -> list:
    if os.path.exists(PRESTAMOS_PATH):
        with open(PRESTAMOS_PATH) as f:
            data = json.load(f)
        logger.info(f"Préstamos cargados: {len(data)}")
        return data
    return []

def guardar_prestamos(prestamos: list):
    os.makedirs(os.path.dirname(PRESTAMOS_PATH), exist_ok=True)
    with open(PRESTAMOS_PATH, "w") as f:
        json.dump(prestamos, f, indent=2, default=str)
    logger.ok(f"Préstamos guardados: {len(prestamos)}")

def agregar_prestamo(prestamos: list, **kwargs) -> list:
    """Agrega un préstamo calculando TEA y fecha de vencimiento final."""
    p = prestamo_vacio()
    p.update(kwargs)
    p["id"] = max([x.get("id", 0) or 0 for x in prestamos], default=0) + 1

    # Calcular TEA desde TNA si no viene
    tna = float(p.get("tna", 0))
    if tna > 0 and p.get("tea", 0) == 0:
        p["tea"] = round(((1 + tna/100/12)**12 - 1) * 100, 2)

    # Capital vigente = original si es nuevo
    if p["capital_vigente"] == 0:
        p["capital_vigente"] = p["capital_original"]

    # Fecha de vencimiento final
    if p.get("fecha_primera_cuota") and p.get("cuotas_totales"):
        try:
            fp = parse_fecha(p["fecha_primera_cuota"])
            cuotas_rest = p["cuotas_totales"] - p.get("cuotas_pagadas", 0)
            p["fecha_vencimiento_final"] = str(fp + relativedelta(months=cuotas_rest - 1))
        except:
            pass

    prestamos.append(p)
    logger.ok(f"Préstamo agregado: {p['banco']} — {fmt_ars(p['capital_original'])} — TNA {tna}%")
    return prestamos

def cronograma_prestamo(p: dict, meses: int = 12) -> pd.DataFrame:
    """Genera el cronograma de cuotas para los próximos N meses."""
    rows = []
    capital_rest = float(p.get("capital_vigente", p.get("capital_original", 0)))
    tna          = float(p.get("tna", 0))
    cuota        = float(p.get("cuota_mensual", 0))
    tasa_mensual = tna / 100 / 12
    cuotas_pag   = int(p.get("cuotas_pagadas", 0))
    cuotas_tot   = int(p.get("cuotas_totales", 1))

    try:
        fp = parse_fecha(p.get("fecha_primera_cuota")) or date.today()
        fecha_actual = fp + relativedelta(months=cuotas_pag)
    except:
        fecha_actual = date.today()

    for i in range(meses):
        if cuotas_pag + i >= cuotas_tot:
            break
        interes  = capital_rest * tasa_mensual
        capital_amort = cuota - interes if cuota > interes else 0
        if capital_amort > capital_rest:
            capital_amort = capital_rest
        capital_rest -= capital_amort

        rows.append({
            "cuota_nro":    cuotas_pag + i + 1,
            "fecha":        str(fecha_actual + relativedelta(months=i)),
            "mes":          (fecha_actual + relativedelta(months=i)).month,
            "capital_amort": round(capital_amort, 2),
            "interes":       round(interes, 2),
            "total_cuota":   round(cuota, 2),
            "capital_rest":  round(capital_rest, 2),
            "banco":         p.get("banco", ""),
            "prestamo_id":   p.get("id", 0),
        })
    return pd.DataFrame(rows)

def resumen_cuotas_mensual(prestamos: list, año: int = 2025) -> pd.DataFrame:
    """Total de cuotas de todos los préstamos vigentes por mes."""
    rows = {m: {"mes": m, "mes_nombre": nombre_mes(m),
                "total_cuotas": 0.0, "total_capital": 0.0,
                "total_interes": 0.0, "cant_prestamos": 0}
            for m in range(1, 13)}

    for p in prestamos:
        if p.get("estado") != "vigente":
            continue
        cron = cronograma_prestamo(p, meses=24)
        for _, r in cron.iterrows():
            try:
                f = parse_fecha(r["fecha"])
                if f and f.year == año:
                    m = f.month
                    rows[m]["total_cuotas"]   += float(r["total_cuota"])
                    rows[m]["total_capital"]  += float(r["capital_amort"])
                    rows[m]["total_interes"]  += float(r["interes"])
                    rows[m]["cant_prestamos"] += 1
            except:
                continue

    return pd.DataFrame(list(rows.values()))


# ══════════════════════════════════════════════════════════════════════
# 2. PLANES DE FACILIDADES AFIP
# ══════════════════════════════════════════════════════════════════════

def plan_afip_vacio() -> dict:
    return {
        "id": None, "rg": "", "descripcion": "",
        "tipo": "moratoria",     # moratoria | facilidades | plan_pagos
        "impuesto": "",          # IVA | Ganancias | SIPA | Autónomos | Varios
        "deuda_original": 0.0, "deuda_vigente": 0.0,
        "tasa_interes_mensual": 0.0,  # % mensual (interés resarcitorio AFIP)
        "cuota_mensual": 0.0, "cuotas_totales": 0, "cuotas_pagadas": 0,
        "fecha_adhesion": None, "fecha_primera_cuota": None,
        "fecha_vencimiento_final": None,
        "dia_vencimiento": 16,   # día del mes del vencimiento de la cuota
        "estado": "vigente",     # vigente | cancelado | caducado
        "numero_plan": "",
        "observaciones": "",
    }

def cargar_planes_afip() -> list:
    if os.path.exists(AFIP_PLANES_PATH):
        with open(AFIP_PLANES_PATH) as f:
            data = json.load(f)
        logger.info(f"Planes AFIP cargados: {len(data)}")
        return data
    return []

def guardar_planes_afip(planes: list):
    os.makedirs(os.path.dirname(AFIP_PLANES_PATH), exist_ok=True)
    with open(AFIP_PLANES_PATH, "w") as f:
        json.dump(planes, f, indent=2, default=str)
    logger.ok(f"Planes AFIP guardados: {len(planes)}")

def agregar_plan_afip(planes: list, **kwargs) -> list:
    p = plan_afip_vacio()
    p.update(kwargs)
    p["id"] = max([x.get("id", 0) or 0 for x in planes], default=0) + 1
    if p["deuda_vigente"] == 0:
        p["deuda_vigente"] = p["deuda_original"]
    if p.get("fecha_primera_cuota") and p.get("cuotas_totales"):
        try:
            fp   = parse_fecha(p["fecha_primera_cuota"])
            rest = p["cuotas_totales"] - p.get("cuotas_pagadas", 0)
            p["fecha_vencimiento_final"] = str(fp + relativedelta(months=rest - 1))
        except:
            pass
    planes.append(p)
    logger.ok(f"Plan AFIP agregado: {p['rg']} — {p['impuesto']} — {fmt_ars(p['deuda_original'])}")
    return planes

def resumen_cuotas_afip_mensual(planes: list, año: int = 2025) -> pd.DataFrame:
    """Total de cuotas AFIP por mes."""
    rows = {m: {"mes": m, "mes_nombre": nombre_mes(m),
                "total_cuotas": 0.0, "cant_planes": 0}
            for m in range(1, 13)}

    for p in planes:
        if p.get("estado") != "vigente":
            continue
        cuota = float(p.get("cuota_mensual", 0))
        cuotas_pag = int(p.get("cuotas_pagadas", 0))
        cuotas_tot = int(p.get("cuotas_totales", 0))
        try:
            fp = parse_fecha(p.get("fecha_primera_cuota")) or date.today()
        except:
            fp = date.today()

        for i in range(cuotas_tot - cuotas_pag):
            f = fp + relativedelta(months=cuotas_pag + i)
            if f.year == año and 1 <= f.month <= 12:
                rows[f.month]["total_cuotas"] += cuota
                rows[f.month]["cant_planes"]  += 1

    return pd.DataFrame(list(rows.values()))


# ══════════════════════════════════════════════════════════════════════
# 3. IMPUESTOS PERIÓDICOS — Proyectado vs Abonado Real
# ══════════════════════════════════════════════════════════════════════

IMPUESTOS_DEFAULT = {
    "IVA": {
        "nombre": "IVA — DGI",
        "frecuencia": "mensual",
        "dia_vencimiento": 20,
        "monto_estimado": 98400.0,
        "activo": True,
        "categoria_extracto": "AFIP",
        "keywords_extracto": ["IVA", "DGI IVA", "DEBITO AFIP IVA"],
    },
    "IIBB": {
        "nombre": "Ingresos Brutos",
        "frecuencia": "mensual",
        "dia_vencimiento": 15,
        "monto_estimado": 34500.0,
        "activo": True,
        "categoria_extracto": "AFIP",
        "keywords_extracto": ["INGRESOS BRUTOS", "IIBB", "RENTAS"],
    },
    "SIPA": {
        "nombre": "Cargas Sociales SIPA",
        "frecuencia": "mensual",
        "dia_vencimiento": 14,
        "monto_estimado": 134400.0,
        "activo": True,
        "categoria_extracto": "Cargas Sociales",
        "keywords_extracto": ["SIPA", "AFIP SIPA", "CARGAS SOCIALES"],
    },
    "OBRA_SOCIAL": {
        "nombre": "Obra Social",
        "frecuencia": "mensual",
        "dia_vencimiento": 14,
        "monto_estimado": 18000.0,
        "activo": True,
        "categoria_extracto": "Cargas Sociales",
        "keywords_extracto": ["OBRA SOCIAL", "OSDE", "IOMA", "OSEN"],
    },
    "GANANCIAS": {
        "nombre": "Impuesto a las Ganancias",
        "frecuencia": "mensual",
        "dia_vencimiento": 20,
        "monto_estimado": 25000.0,
        "activo": True,
        "categoria_extracto": "AFIP",
        "keywords_extracto": ["GANANCIAS", "ANTICIPO GANANCIAS"],
    },
    "ART": {
        "nombre": "ART",
        "frecuencia": "mensual",
        "dia_vencimiento": 20,
        "monto_estimado": 12000.0,
        "activo": True,
        "categoria_extracto": "AFIP",
        "keywords_extracto": ["ART ", "PREVENCION ART", "EXPERTA ART"],
    },
    "BIENES_PERSONALES": {
        "nombre": "Bienes Personales",
        "frecuencia": "anual",
        "dia_vencimiento": 22,
        "mes_vencimiento": 6,  # Junio
        "monto_estimado": 0.0,
        "activo": False,
        "categoria_extracto": "AFIP",
        "keywords_extracto": ["BIENES PERSONALES"],
    },
}

def cargar_config_impuestos() -> dict:
    if os.path.exists(IMPUESTOS_PATH):
        with open(IMPUESTOS_PATH) as f:
            return json.load(f)
    guardar_config_impuestos(IMPUESTOS_DEFAULT)
    return IMPUESTOS_DEFAULT

def guardar_config_impuestos(config: dict):
    os.makedirs(os.path.dirname(IMPUESTOS_PATH), exist_ok=True)
    with open(IMPUESTOS_PATH, "w") as f:
        json.dump(config, f, indent=2)
    logger.ok("Configuración de impuestos guardada")

def proyectar_vencimientos_impuestos(config: dict, año: int = 2025) -> pd.DataFrame:
    """Genera el calendario de vencimientos impositivos del año."""
    rows = []
    for clave, imp in config.items():
        if not imp.get("activo", True):
            continue
        frec = imp.get("frecuencia", "mensual")
        if frec == "mensual":
            for mes in range(1, 13):
                try:
                    dia = min(int(imp.get("dia_vencimiento", 20)), 28)
                    f_vto = date(año, mes, dia)
                    rows.append({
                        "clave":       clave,
                        "impuesto":    imp["nombre"],
                        "mes":         mes,
                        "mes_nombre":  nombre_mes(mes),
                        "fecha_vto":   f_vto,
                        "monto_proy":  float(imp.get("monto_estimado", 0)),
                        "monto_real":  0.0,
                        "diferencia":  0.0,
                        "estado":      "pendiente",
                        "frecuencia":  "mensual",
                    })
                except:
                    continue
        elif frec == "anual":
            mes_vto = int(imp.get("mes_vencimiento", 6))
            dia     = min(int(imp.get("dia_vencimiento", 20)), 28)
            try:
                f_vto = date(año, mes_vto, dia)
                rows.append({
                    "clave":      clave,
                    "impuesto":   imp["nombre"],
                    "mes":        mes_vto,
                    "mes_nombre": nombre_mes(mes_vto),
                    "fecha_vto":  f_vto,
                    "monto_proy": float(imp.get("monto_estimado", 0)),
                    "monto_real": 0.0,
                    "diferencia": 0.0,
                    "estado":     "pendiente",
                    "frecuencia": "anual",
                })
            except:
                continue
    return pd.DataFrame(rows)

def conciliar_impuestos_con_extracto(
    df_vencimientos: pd.DataFrame,
    df_extracto:     pd.DataFrame,
    config_imp:      dict,
    tolerancia_dias: int = 5,
    tolerancia_pct:  float = 0.10,
) -> pd.DataFrame:
    """
    Cruza los vencimientos impositivos contra el extracto bancario.
    Match por: keyword en descripción + mes + monto aproximado.
    Actualiza monto_real, diferencia y estado.
    """
    if df_extracto.empty or df_vencimientos.empty:
        return df_vencimientos

    df = df_vencimientos.copy()

    for idx, row in df.iterrows():
        clave     = row["clave"]
        imp_cfg   = config_imp.get(clave, {})
        keywords  = imp_cfg.get("keywords_extracto", [])
        mes       = int(row["mes"])
        monto_p   = float(row["monto_proy"])

        # Filtrar extracto por mes y categoría
        df_mes = df_extracto[
            (df_extracto["mes"] == mes) &
            (df_extracto["importe"] < 0)
        ].copy()

        if df_mes.empty:
            continue

        # Buscar por keyword en descripción
        matched = pd.DataFrame()
        for kw in keywords:
            mask = df_mes["descripcion"].str.upper().str.contains(kw.upper(), na=False)
            if mask.any():
                matched = df_mes[mask]
                break

        if matched.empty:
            # Buscar por categoría
            cat = imp_cfg.get("categoria_extracto", "")
            if cat:
                matched = df_mes[df_mes["categoria"] == cat]

        if not matched.empty:
            monto_real = abs(float(matched["importe"].sum()))
            diferencia = monto_real - monto_p
            pct_dif    = abs(diferencia) / monto_p if monto_p > 0 else 0

            df.at[idx, "monto_real"]  = monto_real
            df.at[idx, "diferencia"]  = diferencia

            if pct_dif <= tolerancia_pct:
                df.at[idx, "estado"] = "✅ Pagado"
            elif monto_real > 0:
                df.at[idx, "estado"] = f"⚠️ Desvío {pct_dif*100:.0f}%"
            else:
                df.at[idx, "estado"] = "❌ No encontrado"
        else:
            # Verificar si ya venció
            try:
                f_vto = row["fecha_vto"]
                if isinstance(f_vto, str):
                    f_vto = parse_fecha(f_vto)
                if f_vto and f_vto < date.today():
                    df.at[idx, "estado"] = "🔴 Vencido sin pago"
                else:
                    df.at[idx, "estado"] = "🕐 Pendiente"
            except:
                pass

    logger.ok(f"Conciliación impuestos: {(df['estado'].str.startswith('✅')).sum()} pagados de {len(df)}")
    return df

def resumen_impuestos_mensual(df_vencimientos: pd.DataFrame) -> pd.DataFrame:
    """Agrupa vencimientos impositivos por mes para el cashflow."""
    if df_vencimientos.empty:
        return pd.DataFrame()
    return df_vencimientos.groupby(["mes","mes_nombre"]).agg(
        total_proyectado=("monto_proy",  "sum"),
        total_real=       ("monto_real", "sum"),
        cant_impuestos=   ("clave",      "count"),
        pagados=          ("estado",     lambda x: (x.str.startswith("✅")).sum()),
    ).reset_index()


# ══════════════════════════════════════════════════════════════════════
# 4. TASAS DE REFERENCIA Y TABLERO COMPARATIVO
# ══════════════════════════════════════════════════════════════════════

TASAS_REF_DEFAULT = {
    "fecha_actualizacion": str(date.today()),
    "tasas_bcra": {
        "tasa_politica_monetaria": 40.0,   # % TNA — Tasa de política monetaria BCRA
        "badlar_bancos_privados":  38.0,   # % TNA — Tasa BADLAR
        "plazo_fijo_30d":          37.5,   # % TNA — Plazo fijo 30 días
        "leliq":                   40.0,   # % TNA — LELIQ
        "prestamos_personales":    85.0,   # % TNA — Referencia préstamos personales
        "prestamos_pyme":          55.0,   # % TNA — Línea PyME SGR
    },
    "tasas_afip": {
        "interes_resarcitorio":    3.0,    # % mensual — mora AFIP
        "interes_punitorio":       4.5,    # % mensual — mora + punición
        "tasa_plan_facilidades":   2.5,    # % mensual — planes vigentes
    },
    "notas": "Actualizar mensualmente con datos del BCRA",
}

def cargar_tasas_referencia() -> dict:
    if os.path.exists(TASAS_REF_PATH):
        with open(TASAS_REF_PATH) as f:
            return json.load(f)
    guardar_tasas_referencia(TASAS_REF_DEFAULT)
    return TASAS_REF_DEFAULT

def guardar_tasas_referencia(tasas: dict):
    os.makedirs(os.path.dirname(TASAS_REF_PATH), exist_ok=True)
    with open(TASAS_REF_PATH, "w") as f:
        json.dump(tasas, f, indent=2)
    logger.ok("Tasas de referencia guardadas")

def analisis_rollover(prestamos: list, tasas_ref: dict) -> pd.DataFrame:
    """
    Para cada préstamo vigente, evalúa si conviene hacer rollover:
    - Compara TNA del préstamo vs tasa de mercado
    - Calcula ahorro/costo de refinanciar
    - Semáforo: verde = conviene refinanciar, rojo = mantener
    """
    tasa_mercado = float(tasas_ref.get("tasas_bcra", {}).get("prestamos_pyme", 55.0))
    rows = []

    for p in prestamos:
        if p.get("estado") != "vigente":
            continue
        tna_p        = float(p.get("tna", 0))
        capital_rest = float(p.get("capital_vigente", p.get("capital_original", 0)))
        cuota        = float(p.get("cuota_mensual", 0))
        cuotas_rest  = int(p.get("cuotas_totales", 0)) - int(p.get("cuotas_pagadas", 0))

        # Diferencia de tasa
        diff_tna = tna_p - tasa_mercado

        # Costo financiero restante con tasa actual
        interes_total_actual = cuota * cuotas_rest - capital_rest

        # Costo estimado con tasa de mercado
        tasa_m_mensual  = tasa_mercado / 100 / 12
        if tasa_m_mensual > 0 and cuotas_rest > 0:
            cuota_nueva = capital_rest * (tasa_m_mensual * (1 + tasa_m_mensual)**cuotas_rest) / \
                          ((1 + tasa_m_mensual)**cuotas_rest - 1)
            interes_total_nuevo = cuota_nueva * cuotas_rest - capital_rest
        else:
            cuota_nueva = cuota
            interes_total_nuevo = interes_total_actual

        ahorro_rollover = interes_total_actual - interes_total_nuevo

        # Recomendación
        if diff_tna > 10 and ahorro_rollover > 50000:
            recomendacion = "🟢 Conviene refinanciar"
        elif diff_tna > 5:
            recomendacion = "🟡 Evaluar refinanciación"
        elif diff_tna < -5:
            recomendacion = "🔴 Tasa OK — mantener"
        else:
            recomendacion = "⚪ Tasa en línea con mercado"

        rows.append({
            "banco":            p.get("banco", ""),
            "descripcion":      p.get("descripcion", ""),
            "capital_vigente":  capital_rest,
            "tna_actual":       tna_p,
            "tea_actual":       float(p.get("tea", 0)),
            "tna_mercado":      tasa_mercado,
            "diferencia_tna":   diff_tna,
            "cuota_actual":     cuota,
            "cuota_nueva_est":  round(cuota_nueva, 0),
            "cuotas_restantes": cuotas_rest,
            "interes_rest_actual": round(interes_total_actual, 0),
            "interes_rest_nuevo":  round(interes_total_nuevo, 0),
            "ahorro_rollover":     round(ahorro_rollover, 0),
            "recomendacion":       recomendacion,
        })

    return pd.DataFrame(rows)

def costo_financiero_total(prestamos: list, planes_afip: list) -> dict:
    """Calcula el costo financiero total de toda la deuda vigente."""
    total_deuda_bancos = sum(
        float(p.get("capital_vigente", p.get("capital_original", 0)))
        for p in prestamos if p.get("estado") == "vigente"
    )
    total_deuda_afip = sum(
        float(p.get("deuda_vigente", p.get("deuda_original", 0)))
        for p in planes_afip if p.get("estado") == "vigente"
    )
    cuotas_mens_bancos = sum(
        float(p.get("cuota_mensual", 0))
        for p in prestamos if p.get("estado") == "vigente"
    )
    cuotas_mens_afip = sum(
        float(p.get("cuota_mensual", 0))
        for p in planes_afip if p.get("estado") == "vigente"
    )

    # TNA promedio ponderada
    tna_pond = 0.0
    if total_deuda_bancos > 0:
        tna_pond = sum(
            float(p.get("tna", 0)) * float(p.get("capital_vigente", p.get("capital_original", 0)))
            for p in prestamos if p.get("estado") == "vigente"
        ) / total_deuda_bancos

    return {
        "total_deuda_bancos":     total_deuda_bancos,
        "total_deuda_afip":       total_deuda_afip,
        "total_deuda":            total_deuda_bancos + total_deuda_afip,
        "cuota_mensual_bancos":   cuotas_mens_bancos,
        "cuota_mensual_afip":     cuotas_mens_afip,
        "cuota_mensual_total":    cuotas_mens_bancos + cuotas_mens_afip,
        "tna_promedio_ponderada": round(tna_pond, 2),
        "cant_prestamos":         sum(1 for p in prestamos if p.get("estado") == "vigente"),
        "cant_planes_afip":       sum(1 for p in planes_afip if p.get("estado") == "vigente"),
    }


# ══════════════════════════════════════════════════════════════════════
# ALERTAS INTEGRALES DE DEUDA
# ══════════════════════════════════════════════════════════════════════

def alertas_deuda(
    prestamos: list,
    planes_afip: list,
    df_vencimientos: pd.DataFrame,
    fecha_hoy: date = None,
) -> list:
    """Genera alertas unificadas de deuda (préstamos + AFIP + impuestos)."""
    if fecha_hoy is None:
        fecha_hoy = date.today()
    alertas = []
    h7  = fecha_hoy + timedelta(days=7)
    h30 = fecha_hoy + timedelta(days=30)

    # ── Cuotas préstamos próximas ──
    for p in prestamos:
        if p.get("estado") != "vigente":
            continue
        cuotas_pag = int(p.get("cuotas_pagadas", 0))
        cuotas_tot = int(p.get("cuotas_totales", 0))
        if cuotas_pag >= cuotas_tot:
            continue
        dia   = int(p.get("dia_debito", 25))
        f_prox = date(fecha_hoy.year, fecha_hoy.month, min(dia, 28))
        if f_prox < fecha_hoy:
            f_prox = f_prox + relativedelta(months=1)
        dias_hasta = (f_prox - fecha_hoy).days
        cuota = float(p.get("cuota_mensual", 0))
        nivel = "critico" if dias_hasta <= 3 else "alerta" if dias_hasta <= 7 else "info"
        if dias_hasta <= 30:
            alertas.append({
                "nivel": nivel, "categoria": "prestamo",
                "titulo": f"{'🔴' if nivel=='critico' else '🟡' if nivel=='alerta' else '🔵'} Cuota {p['banco']} — {nombre_mes(f_prox.month)}",
                "detalle": f"Cuota {cuotas_pag+1}/{cuotas_tot} — {fmt_ars(cuota)} — Vence {f_prox.strftime('%d/%m/%Y')} (en {dias_hasta}d)",
                "monto": cuota, "accion": "Verificar débito automático o programar transferencia.",
            })

    # ── Cuotas AFIP próximas ──
    for p in planes_afip:
        if p.get("estado") != "vigente":
            continue
        dia   = int(p.get("dia_vencimiento", 16))
        f_prox = date(fecha_hoy.year, fecha_hoy.month, min(dia, 28))
        if f_prox < fecha_hoy:
            f_prox = f_prox + relativedelta(months=1)
        dias_hasta = (f_prox - fecha_hoy).days
        cuota = float(p.get("cuota_mensual", 0))
        if dias_hasta <= 30:
            nivel = "critico" if dias_hasta <= 3 else "alerta" if dias_hasta <= 7 else "info"
            alertas.append({
                "nivel": nivel, "categoria": "afip_plan",
                "titulo": f"{'🔴' if nivel=='critico' else '🟡'} Cuota Plan AFIP {p.get('rg','')} — {nombre_mes(f_prox.month)}",
                "detalle": f"{p.get('impuesto','')} — {fmt_ars(cuota)} — Vence {f_prox.strftime('%d/%m/%Y')}",
                "monto": cuota, "accion": "Transferir a cuenta AFIP antes del vencimiento.",
            })

    # ── Impuestos con desvío o sin pago ──
    if not df_vencimientos.empty:
        for _, r in df_vencimientos.iterrows():
            estado = str(r.get("estado", ""))
            if "Vencido" in estado or "⚠️" in estado:
                alertas.append({
                    "nivel": "critico" if "Vencido" in estado else "alerta",
                    "categoria": "impuesto",
                    "titulo": f"{'🔴' if 'Vencido' in estado else '🟡'} {r['impuesto']} {r['mes_nombre']} — {estado}",
                    "detalle": f"Proyectado: {fmt_ars(r['monto_proy'])} | Real: {fmt_ars(r['monto_real'])} | Diferencia: {fmt_ars(r['diferencia'])}",
                    "monto": abs(float(r.get("diferencia", 0))),
                    "accion": "Verificar pago en extracto bancario y AFIP portal.",
                })

    return sorted(alertas, key=lambda x: {"critico":0,"alerta":1,"info":2}.get(x["nivel"],3))


# ══════════════════════════════════════════════════════════════════════
# MUESTRA INICIAL — datos demo realistas
# ══════════════════════════════════════════════════════════════════════

def generar_datos_demo():
    """Genera datos reales de Droguería del Sud — BCRA Central Deudores 04/2026."""
    # Préstamos reales BCRA (montos en pesos, multiplicados x1000 desde central deudores)
    prestamos = []
    prestamos = agregar_prestamo(prestamos,
        banco="Banco Credicoop Cooperativo Limitado",
        descripcion="Financiación capital de trabajo / descuento",
        tipo="amortizante", capital_original=10_047_929_000, capital_vigente=10_047_929_000,
        tna=52.0, tea=66.37, cuota_mensual=1_091_437_509,
        cuotas_totales=12, cuotas_pagadas=0,
        fecha_primera_cuota="01/06/2026", fecha_vencimiento_final="2027-05-01",
        dia_debito=25, moneda="ARS", estado="vigente",
        observaciones="BCRA Central Deudores 04/2026. Situación 1.",
    )
    prestamos = agregar_prestamo(prestamos,
        banco="Banco BBVA Argentina S.A.",
        descripcion="Financiación operativa",
        tipo="amortizante", capital_original=4_569_724_000, capital_vigente=4_569_724_000,
        tna=50.0, tea=63.21, cuota_mensual=491_634_298,
        cuotas_totales=12, cuotas_pagadas=0,
        fecha_primera_cuota="01/06/2026", fecha_vencimiento_final="2027-05-01",
        dia_debito=25, moneda="ARS", estado="vigente",
        observaciones="BCRA Central Deudores 04/2026. Situación 1.",
    )
    prestamos = agregar_prestamo(prestamos,
        banco="Citibank N.A.",
        descripcion="Línea de crédito",
        tipo="amortizante", capital_original=2_326_716_000, capital_vigente=2_326_716_000,
        tna=48.0, tea=60.1, cuota_mensual=247_916_645,
        cuotas_totales=12, cuotas_pagadas=0,
        fecha_primera_cuota="01/06/2026", fecha_vencimiento_final="2027-05-01",
        dia_debito=25, moneda="ARS", estado="vigente",
        observaciones="BCRA Central Deudores 04/2026. Situación 1.",
    )
    prestamos = agregar_prestamo(prestamos,
        banco="Banco de Galicia y Buenos Aires S.A.",
        descripcion="Descuento de cheques / línea",
        tipo="amortizante", capital_original=203_971_000, capital_vigente=203_971_000,
        tna=55.0, tea=71.22, cuota_mensual=22_475_483,
        cuotas_totales=12, cuotas_pagadas=0,
        fecha_primera_cuota="01/06/2026", fecha_vencimiento_final="2027-05-01",
        dia_debito=25, moneda="ARS", estado="vigente",
        observaciones="BCRA Central Deudores 04/2026. Situación 1.",
    )
    prestamos = agregar_prestamo(prestamos,
        banco="Banco Supervielle S.A.",
        descripcion="Financiación corto plazo",
        tipo="amortizante", capital_original=195_042_000, capital_vigente=195_042_000,
        tna=58.0, tea=76.19, cuota_mensual=21_799_328,
        cuotas_totales=12, cuotas_pagadas=0,
        fecha_primera_cuota="01/06/2026", fecha_vencimiento_final="2027-05-01",
        dia_debito=25, moneda="ARS", estado="vigente",
        observaciones="BCRA Central Deudores 04/2026. Situación 1.",
    )
    prestamos = agregar_prestamo(prestamos,
        banco="American Express Argentina S.A.",
        descripcion="Tarjeta corporativa",
        tipo="amortizante", capital_original=100_113_000, capital_vigente=100_113_000,
        tna=72.0, tea=101.22, cuota_mensual=11_941_181,
        cuotas_totales=12, cuotas_pagadas=0,
        fecha_primera_cuota="01/06/2026", fecha_vencimiento_final="2027-05-01",
        dia_debito=25, moneda="ARS", estado="vigente",
        observaciones="BCRA Central Deudores 04/2026. Situación 1.",
    )
    prestamos = agregar_prestamo(prestamos,
        banco="YPF S.A.",
        descripcion="Crédito proveedor YPF",
        tipo="amortizante", capital_original=15_621_000, capital_vigente=15_621_000,
        tna=45.0, tea=55.55, cuota_mensual=1_640_397,
        cuotas_totales=12, cuotas_pagadas=0,
        fecha_primera_cuota="01/06/2026", fecha_vencimiento_final="2027-05-01",
        dia_debito=25, moneda="ARS", estado="vigente",
        observaciones="BCRA Central Deudores 04/2026. Situación 1.",
    )
    prestamos = agregar_prestamo(prestamos,
        banco="Reba Compañía Financiera S.A.",
        descripcion="Financiación menor",
        tipo="bullet", capital_original=429_000, capital_vigente=429_000,
        tna=65.0, tea=88.33, cuota_mensual=23_238,
        cuotas_totales=3, cuotas_pagadas=0,
        fecha_primera_cuota="01/06/2026", fecha_vencimiento_final="2026-08-01",
        dia_debito=25, moneda="ARS", estado="vigente",
        observaciones="BCRA Central Deudores 04/2026. Situación 1.",
    )
    prestamos = agregar_prestamo(prestamos,
        banco="Banco de la Nación Argentina",
        descripcion="Crédito residual",
        tipo="bullet", capital_original=57_000, capital_vigente=57_000,
        tna=42.0, tea=51.11, cuota_mensual=1_995,
        cuotas_totales=3, cuotas_pagadas=0,
        fecha_primera_cuota="01/06/2026", fecha_vencimiento_final="2026-08-01",
        dia_debito=25, moneda="ARS", estado="vigente",
        observaciones="BCRA Central Deudores 04/2026. Situación 1.",
    )

    # Planes AFIP
    planes = []
    planes = agregar_plan_afip(planes,
        rg="RG 5678", descripcion="Moratoria deuda IVA 2022-2023",
        tipo="moratoria", impuesto="IVA",
        deuda_original=850_000, deuda_vigente=520_000,
        tasa_interes_mensual=2.5, cuota_mensual=12_000,
        cuotas_totales=60, cuotas_pagadas=28,
        fecha_adhesion="01/01/2023", fecha_primera_cuota="01/02/2023",
        dia_vencimiento=16, estado="vigente", numero_plan="78901234",
    )
    planes = agregar_plan_afip(planes,
        rg="RG 5003", descripcion="Plan de facilidades SIPA",
        tipo="facilidades", impuesto="SIPA",
        deuda_original=320_000, deuda_vigente=160_000,
        tasa_interes_mensual=2.5, cuota_mensual=8_500,
        cuotas_totales=24, cuotas_pagadas=12,
        fecha_adhesion="01/07/2024", fecha_primera_cuota="01/08/2024",
        dia_vencimiento=16, estado="vigente", numero_plan="45678901",
    )

    return prestamos, planes


if __name__ == "__main__":
    print("=== TEST GESTOR DEUDA ===\n")

    prestamos, planes = generar_datos_demo()
    guardar_prestamos(prestamos)
    guardar_planes_afip(planes)

    # Test cronograma
    print("=== CRONOGRAMA PRÉSTAMO BANCO NACIÓN (6 cuotas) ===")
    cron = cronograma_prestamo(prestamos[0], meses=6)
    print(cron[["cuota_nro","fecha","capital_amort","interes","total_cuota","capital_rest"]].to_string(index=False))

    # Resumen mensual
    print("\n=== CUOTAS BANCOS POR MES 2025 ===")
    res_p = resumen_cuotas_mensual(prestamos, 2025)
    for _, r in res_p[res_p["total_cuotas"]>0].iterrows():
        print(f"  {r['mes_nombre']:12}: {fmt_ars(r['total_cuotas'])} ({int(r['cant_prestamos'])} cuotas)")

    # Impuestos
    config_imp = cargar_config_impuestos()
    df_venc = proyectar_vencimientos_impuestos(config_imp, 2025)
    print(f"\n=== VENCIMIENTOS IMPOSITIVOS 2025: {len(df_venc)} registros ===")
    junio = df_venc[df_venc["mes"]==6]
    print(junio[["impuesto","fecha_vto","monto_proy","estado"]].to_string(index=False))

    # Tasas y rollover
    tasas = cargar_tasas_referencia()
    df_roll = analisis_rollover(prestamos, tasas)
    print("\n=== ANÁLISIS ROLLOVER ===")
    print(df_roll[["banco","tna_actual","tna_mercado","diferencia_tna","ahorro_rollover","recomendacion"]].to_string(index=False))

    # Costo financiero total
    cft = costo_financiero_total(prestamos, planes)
    print(f"\n=== COSTO FINANCIERO TOTAL ===")
    print(f"  Deuda bancos:          {fmt_ars(cft['total_deuda_bancos'])}")
    print(f"  Deuda AFIP:            {fmt_ars(cft['total_deuda_afip'])}")
    print(f"  Deuda total:           {fmt_ars(cft['total_deuda'])}")
    print(f"  Cuota mensual total:   {fmt_ars(cft['cuota_mensual_total'])}")
    print(f"  TNA promedio pond.:    {cft['tna_promedio_ponderada']}%")

    print("\n✅ gestor_deuda.py OK")
