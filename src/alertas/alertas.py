"""
alertas.py — Sistema de alertas automáticas
Genera alertas inteligentes para:
  - Saldo bancario bajo umbral crítico o de alerta
  - Cheques próximos a vencer (hoy, 7 días, 30 días)
  - Vencimientos AFIP / impositivos
  - Desvíos significativos respecto al proyectado
  - Préstamos con cuota próxima
Devuelve lista estructurada de alertas para el dashboard
y puede enviar emails (configuración SMTP opcional).
"""
import pandas as pd
from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import List, Optional
import sys
sys.path.insert(0, '.')
from config import SALDO_MINIMO_CRITICO, SALDO_MINIMO_ALERTA
from src.utils.helpers import fmt_ars, fmt_pct, nombre_mes, logger


# ══════════════════════════════════════════════════════════════════════
# MODELO DE ALERTA
# ══════════════════════════════════════════════════════════════════════

@dataclass
class Alerta:
    nivel:       str          # "critico" | "alerta" | "info" | "ok"
    categoria:   str          # "saldo" | "cheque" | "afip" | "desvio" | "prestamo"
    titulo:      str
    detalle:     str
    monto:       Optional[float] = None
    fecha:       Optional[date]  = None
    icono:       str             = "ℹ️"
    accion:      str             = ""   # Qué hacer al respecto

    def to_dict(self) -> dict:
        return {
            "nivel":     self.nivel,
            "categoria": self.categoria,
            "titulo":    self.titulo,
            "detalle":   self.detalle,
            "monto":     self.monto,
            "monto_fmt": fmt_ars(self.monto) if self.monto is not None else "—",
            "fecha":     self.fecha.strftime("%d/%m/%Y") if self.fecha else "",
            "icono":     self.icono,
            "accion":    self.accion,
        }

    @property
    def color(self) -> str:
        return {
            "critico": "#FF4D6D",
            "alerta":  "#FFB347",
            "info":    "#2E75B6",
            "ok":      "#00C49F",
        }.get(self.nivel, "#888888")


# ══════════════════════════════════════════════════════════════════════
# GENERADORES DE ALERTAS
# ══════════════════════════════════════════════════════════════════════

def alertas_saldo(df_cashflow: pd.DataFrame) -> List[Alerta]:
    """Genera alertas de saldo para todos los meses proyectados."""
    alertas = []
    if df_cashflow.empty:
        return alertas

    for _, row in df_cashflow.iterrows():
        saldo = row.get("saldo_fin_proy", 0)
        mes   = row.get("mes_nombre", "")

        if saldo < SALDO_MINIMO_CRITICO:
            alertas.append(Alerta(
                nivel     = "critico",
                categoria = "saldo",
                titulo    = f"🔴 Saldo CRÍTICO — {mes}",
                detalle   = (f"Saldo proyectado {fmt_ars(saldo)} está por debajo del "
                             f"mínimo crítico ({fmt_ars(SALDO_MINIMO_CRITICO)}). "
                             "Riesgo de iliquidez."),
                monto     = saldo,
                icono     = "🔴",
                accion    = "Revisar cobranzas adelantadas o línea de crédito de corto plazo.",
            ))
        elif saldo < SALDO_MINIMO_ALERTA:
            alertas.append(Alerta(
                nivel     = "alerta",
                categoria = "saldo",
                titulo    = f"🟡 Saldo en ALERTA — {mes}",
                detalle   = (f"Saldo proyectado {fmt_ars(saldo)} está entre el mínimo alerta "
                             f"({fmt_ars(SALDO_MINIMO_ALERTA)}) y el crítico. "
                             "Requiere atención."),
                monto     = saldo,
                icono     = "🟡",
                accion    = "Monitorear cobranzas y postponer pagos no urgentes si es posible.",
            ))

    return alertas


def alertas_cheques_df(df_cheques: pd.DataFrame, fecha_hoy: date = None) -> List[Alerta]:
    """Genera alertas de cheques próximos a vencer."""
    alertas = []
    if df_cheques.empty or fecha_hoy is None:
        fecha_hoy = date.today()

    df_pend = df_cheques[df_cheques["estado"] == "pendiente"].copy()
    if df_pend.empty:
        return alertas

    def _d(v):
        if isinstance(v, date): return v
        if hasattr(v, 'date'):  return v.date()
        try:
            from src.utils.helpers import parse_fecha
            return parse_fecha(str(v))
        except:
            return None

    df_pend["_vto_date"] = df_pend["fecha_vto_habil"].apply(_d)

    hoy_7   = fecha_hoy + timedelta(days=7)
    hoy_30  = fecha_hoy + timedelta(days=30)

    for _, ch in df_pend.iterrows():
        vto = ch["_vto_date"]
        if vto is None:
            continue
        dias_diff = (vto - fecha_hoy).days

        if vto < fecha_hoy:
            alertas.append(Alerta(
                nivel     = "critico",
                categoria = "cheque",
                titulo    = f"🔴 Cheque VENCIDO N°{ch['numero']}",
                detalle   = (f"{ch['beneficiario']} — {fmt_ars(ch['monto'])}. "
                             f"Vencimiento: {vto.strftime('%d/%m/%Y')} "
                             f"({abs(dias_diff)} días vencido)"),
                monto     = ch["monto"],
                fecha     = vto,
                icono     = "🔴",
                accion    = "Verificar si fue debitado. Si no, contactar al banco.",
            ))
        elif vto == fecha_hoy:
            alertas.append(Alerta(
                nivel     = "critico",
                categoria = "cheque",
                titulo    = f"🔴 Cheque vence HOY N°{ch['numero']}",
                detalle   = (f"{ch['beneficiario']} — {fmt_ars(ch['monto'])}. "
                             f"Fondos deben estar disponibles hoy."),
                monto     = ch["monto"],
                fecha     = vto,
                icono     = "🔴",
                accion    = "Verificar disponibilidad de fondos en cuenta bancaria.",
            ))
        elif vto <= hoy_7:
            alertas.append(Alerta(
                nivel     = "alerta",
                categoria = "cheque",
                titulo    = f"🟡 Cheque vence en {dias_diff}d — N°{ch['numero']}",
                detalle   = (f"{ch['beneficiario']} — {fmt_ars(ch['monto'])}. "
                             f"Vence el {vto.strftime('%d/%m/%Y')} ({ch.get('dia_semana_vto','')})"),
                monto     = ch["monto"],
                fecha     = vto,
                icono     = "🟡",
                accion    = "Asegurarse de tener fondos suficientes para esa fecha.",
            ))
        elif vto <= hoy_30:
            alertas.append(Alerta(
                nivel     = "info",
                categoria = "cheque",
                titulo    = f"🔵 Cheque en 30d — N°{ch['numero']}",
                detalle   = (f"{ch['beneficiario']} — {fmt_ars(ch['monto'])}. "
                             f"Vence el {vto.strftime('%d/%m/%Y')}"),
                monto     = ch["monto"],
                fecha     = vto,
                icono     = "🔵",
                accion    = "Incluir en la planificación semanal de cash.",
            ))

    return alertas


def alertas_vencimientos_afip(mes_actual: int = None, año: int = 2025) -> List[Alerta]:
    """
    Genera alertas de vencimientos impositivos del mes actual y próximo.
    Calendario AFIP estándar Argentina.
    """
    if mes_actual is None:
        mes_actual = date.today().month

    alertas = []

    # Vencimientos típicos AFIP por tipo de obligación
    vencimientos_afip = [
        # (obligacion, dia_aprox, descripcion_detalle)
        ("IVA Mensual",           20, "Presentación y pago IVA. Según terminación CUIT."),
        ("Ingresos Brutos",       15, "Anticipo mensual Ingresos Brutos CABA/PBA."),
        ("Ganancias - Anticipos", 20, "Anticipos mensuales Impuesto a las Ganancias."),
        ("Cargas Sociales SIPA",  14, "SIPA / Aportes y contribuciones. Terminación 0-4 día 12; 5-9 día 13."),
        ("Obra Social",           14, "Pago Obra Social empleados."),
        ("ART",                   20, "Prima mensual ART."),
    ]

    mes_actual_nombre = nombre_mes(mes_actual)
    sig_mes = (mes_actual % 12) + 1

    for obligacion, dia, detalle in vencimientos_afip:
        try:
            fecha_vcto = date(año, mes_actual, min(dia, 28))
        except ValueError:
            continue

        dias_hasta = (fecha_vcto - date.today()).days

        if dias_hasta < 0:
            nivel = "info"; icono = "📋"
            titulo = f"📋 {obligacion} {mes_actual_nombre} — Vencido"
        elif dias_hasta <= 5:
            nivel = "critico"; icono = "🔴"
            titulo = f"🔴 {obligacion} — Vence en {dias_hasta}d"
        elif dias_hasta <= 10:
            nivel = "alerta"; icono = "🟡"
            titulo = f"🟡 {obligacion} — Vence en {dias_hasta}d"
        else:
            nivel = "info"; icono = "📅"
            titulo = f"📅 {obligacion} {mes_actual_nombre}"

        alertas.append(Alerta(
            nivel     = nivel,
            categoria = "afip",
            titulo    = titulo,
            detalle   = f"{detalle} Mes: {mes_actual_nombre} {año}. Vence aprox. día {dia}.",
            fecha     = fecha_vcto,
            icono     = icono,
            accion    = "Verificar declaración jurada y programar débito/transferencia.",
        ))

    return alertas


def alertas_desvios(df_cashflow: pd.DataFrame, umbral_pct: float = 10.0) -> List[Alerta]:
    """
    Genera alertas cuando el desvío real vs proyectado supera el umbral.
    umbral_pct: porcentaje de desvío que dispara la alerta (default 10%)
    """
    alertas = []
    if df_cashflow.empty:
        return alertas

    df_con_real = df_cashflow[df_cashflow.get("tiene_real", False) == True] if "tiene_real" in df_cashflow.columns else pd.DataFrame()
    if df_con_real.empty:
        return alertas

    for _, row in df_con_real.iterrows():
        mes = row.get("mes_nombre", "")
        dev_pct = row.get("dev_pct_ing")
        dev_abs = row.get("dev_ing")
        ing_proy = row.get("ing_proy", 0)

        if dev_pct is None or ing_proy == 0:
            continue

        abs_pct = abs(dev_pct)
        if abs_pct >= umbral_pct:
            signo = "+" if dev_abs >= 0 else ""
            nivel = "critico" if abs_pct >= 20 else "alerta"
            alertas.append(Alerta(
                nivel     = nivel,
                categoria = "desvio",
                titulo    = f"{'🔴' if nivel=='critico' else '🟡'} Desvío ingresos {mes}: {signo}{dev_pct:.1f}%",
                detalle   = (f"Ingresos reales {fmt_ars(row.get('ing_real',0))} vs "
                             f"proyectado {fmt_ars(ing_proy)}. "
                             f"Diferencia: {signo}{fmt_ars(dev_abs)}"),
                monto     = dev_abs,
                icono     = "🔴" if nivel == "critico" else "🟡",
                accion    = ("Revisar pipeline de cobranzas y ajustar forecast del mes siguiente."
                             if dev_abs < 0 else
                             "Actualizar el presupuesto con la nueva base de ingresos."),
            ))

    return alertas


def alertas_prestamos(params_dict: dict, mes_actual: int = None) -> List[Alerta]:
    """Genera alertas de cuotas de préstamos próximas a vencer."""
    alertas = []
    if mes_actual is None:
        mes_actual = date.today().month

    prestamos = params_dict.get("prestamos", [])
    for p in prestamos:
        if p.get("mes_ini", 1) <= mes_actual <= p.get("mes_fin", 12):
            cuota = p.get("cuota", 0)
            nombre = p.get("nombre", "Préstamo")
            try:
                dia_vto = date(2025, mes_actual, 25)  # asumimos día 25
            except:
                continue
            dias_hasta = (dia_vto - date.today()).days
            nivel = "alerta" if dias_hasta <= 7 else "info"
            alertas.append(Alerta(
                nivel     = nivel,
                categoria = "prestamo",
                titulo    = f"{'🟡' if nivel=='alerta' else '🔵'} Cuota {nombre} — {nombre_mes(mes_actual)}",
                detalle   = f"Cuota mensual {fmt_ars(cuota)}. Vence aprox. día 25 del mes.",
                monto     = cuota,
                fecha     = dia_vto,
                icono     = "🟡" if nivel == "alerta" else "🔵",
                accion    = "Verificar débito automático o programar transferencia.",
            ))

    return alertas


# ══════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL: TODAS LAS ALERTAS
# ══════════════════════════════════════════════════════════════════════

def generar_todas_las_alertas(
    df_cashflow:  pd.DataFrame,
    df_cheques:   pd.DataFrame = None,
    params_dict:  dict = None,
    mes_actual:   int = None,
    fecha_hoy:    date = None,
    umbral_desvio: float = 10.0,
) -> List[dict]:
    """
    Genera todas las alertas del sistema y las devuelve ordenadas por urgencia.
    Retorna lista de dicts listos para el dashboard.
    """
    if fecha_hoy is None:
        fecha_hoy = date.today()
    if mes_actual is None:
        mes_actual = fecha_hoy.month

    todas: List[Alerta] = []

    # 1. Alertas de saldo
    todas += alertas_saldo(df_cashflow)

    # 2. Alertas de cheques
    if df_cheques is not None and not df_cheques.empty:
        todas += alertas_cheques_df(df_cheques, fecha_hoy)

    # 3. Vencimientos AFIP
    todas += alertas_vencimientos_afip(mes_actual)

    # 4. Desvíos
    todas += alertas_desvios(df_cashflow, umbral_desvio)

    # 5. Préstamos
    if params_dict:
        todas += alertas_prestamos(params_dict, mes_actual)

    # Ordenar: crítico primero, luego alerta, luego info
    orden = {"critico": 0, "alerta": 1, "info": 2, "ok": 3}
    todas.sort(key=lambda a: orden.get(a.nivel, 99))

    logger.info(f"Alertas generadas: {len(todas)} "
                f"({sum(1 for a in todas if a.nivel=='critico')} críticas, "
                f"{sum(1 for a in todas if a.nivel=='alerta')} alertas, "
                f"{sum(1 for a in todas if a.nivel=='info')} informativas)")

    return [a.to_dict() for a in todas]


# ══════════════════════════════════════════════════════════════════════
# RESUMEN DE ALERTAS PARA HEADER DEL DASHBOARD
# ══════════════════════════════════════════════════════════════════════

def resumen_alertas(alertas: List[dict]) -> dict:
    """Resumen numérico de alertas para mostrar en el header."""
    return {
        "total":    len(alertas),
        "criticos": sum(1 for a in alertas if a["nivel"] == "critico"),
        "alertas":  sum(1 for a in alertas if a["nivel"] == "alerta"),
        "infos":    sum(1 for a in alertas if a["nivel"] == "info"),
        "monto_urgente": sum(
            a["monto"] for a in alertas
            if a["nivel"] == "critico" and a["monto"] and a["monto"] > 0
        ),
    }


if __name__ == "__main__":
    print("=== TEST SISTEMA DE ALERTAS ===\n")

    from src.engine.motor_cashflow import ParametrosCashflow, generar_cashflow_mensual
    from src.parsers.parser_bancario import generar_extracto_muestra, parse_extracto
    from src.models.gestor_cheques import generar_cheques_muestra

    params = ParametrosCashflow()
    df_m   = generar_extracto_muestra()
    df_m.to_csv("/tmp/test_ext.csv", index=False)
    df_real = parse_extracto("/tmp/test_ext.csv", banco="nacion")
    df_cf   = generar_cashflow_mensual(params, df_real=df_real)
    df_ch   = generar_cheques_muestra()

    alertas = generar_todas_las_alertas(
        df_cashflow  = df_cf,
        df_cheques   = df_ch,
        params_dict  = params.to_dict(),
        mes_actual   = 6,
        fecha_hoy    = date(2025, 6, 10),
        umbral_desvio= 5.0,
    )

    print(f"\nTotal alertas: {len(alertas)}\n")
    for a in alertas:
        print(f"  [{a['nivel'].upper():8}] {a['titulo']}")
        print(f"           {a['detalle'][:80]}{'...' if len(a['detalle'])>80 else ''}")
        if a['monto_fmt'] != '—':
            print(f"           Monto: {a['monto_fmt']}")
        print()

    resumen = resumen_alertas(alertas)
    print(f"RESUMEN: {resumen['criticos']} críticos | {resumen['alertas']} alertas | {resumen['infos']} informativas")
    print(f"Monto urgente total: {fmt_ars(resumen['monto_urgente'])}")
    print("\n✅ alertas.py OK")
