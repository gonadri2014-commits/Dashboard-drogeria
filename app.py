"""
app.py — CASHFLOW ENTERPRISE v3.0 — Droguería del Sud
Nueva en v3:
  - Integración SAP S/4HANA Service Layer (FI + SD + MM + CO + TR)
  - Saldos bancarios en tiempo real (6 bancos)
  - Forecast rolling 13 semanas
  - Cash Conversion Cycle (DSO + DIH - DPO)
  - Pagos programados SAP-TR con alertas automáticas
  - Modo DEMO con datos reales de la empresa / Modo LIVE conecta SAP real
Mejoras v2:
  - Login con usuarios y roles
  - Colores corregidos (modo claro, alto contraste)
  - Módulo de Facturas / AR con condiciones de pago reales
  - Módulo de Budget mensual + comparativo vs real
  - Análisis de causa raíz del desvío (ventas vs cobranza vs condición)
  - Proyección de cobranzas desde facturas reales (no solo estacionalidad)
  - Motor unificado: proyección no duplica datos reales
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import os, sys
from datetime import date
sys.path.insert(0, '.')

from config import EMPRESA, AÑO, SALDO_MINIMO_CRITICO, SALDO_MINIMO_ALERTA
from src.utils.auth import mostrar_login, tiene_permiso, listar_usuarios, agregar_usuario, cambiar_password
from src.parsers.parser_bancario import parse_extracto, estadisticas_extracto, generar_extracto_muestra
from src.engine.motor_cashflow import (
    ParametrosCashflow, generar_cashflow_mensual, conciliar_automatico,
    generar_resumen_semanal, calcular_kpis
)
from src.models.gestor_cheques import (
    cargar_cheques, guardar_cheques, agregar_cheque,
    resumen_mensual_cheques, alertas_cheques, generar_cheques_muestra
)
from src.models.gestor_facturas import (
    cargar_facturas, guardar_facturas, agregar_factura, registrar_cobro,
    importar_facturas_csv, proyectar_cobranzas_desde_facturas,
    analizar_desvio_vs_budget, resumen_ar, generar_facturas_muestra
)
from src.models.gestor_budget import (
    cargar_budget, guardar_budget, actualizar_mes, comparativo_budget_real,
    importar_budget_csv, LINEAS
)
from src.alertas.alertas import generar_todas_las_alertas, resumen_alertas
from src.models.gestor_comex import (
    cargar_comex, guardar_comex, agregar_operacion_comex,
    resumen_comex_mensual, alertas_comex_vencimientos,
    generar_comex_demo, ARANCELES,
)
from src.utils.ocr_prestamos import (
    extraer_datos_prestamo_con_ia, calcular_cronograma_completo,
    analizar_imagen_prestamo_con_claude,
)
from src.models.datos_maestros import (
    BANCOS_ARGENTINA, UNIDADES_NEGOCIO,
    cargar_inversiones, guardar_inversiones, agregar_inversion,
    resumen_inversiones_mensual, generar_inversiones_demo,
    generar_cf_por_unidad, agrupar_desvios,
)
from src.models.gestor_deuda import (
    cargar_prestamos, guardar_prestamos, agregar_prestamo,
    cargar_planes_afip, guardar_planes_afip, agregar_plan_afip,
    cargar_config_impuestos, guardar_config_impuestos,
    proyectar_vencimientos_impuestos, conciliar_impuestos_con_extracto,
    resumen_impuestos_mensual, resumen_cuotas_mensual, resumen_cuotas_afip_mensual,
    analisis_rollover, costo_financiero_total, cargar_tasas_referencia,
    guardar_tasas_referencia, alertas_deuda, generar_datos_demo,
    cronograma_prestamo, TASAS_REF_DEFAULT,
)

# ── Integración SAP Enterprise ────────────────────────────────────────
try:
    from src.connectors.sap_connector import (
        get_estado_conexion, get_saldos_bancarios, get_facturacion_mes,
        get_cuentas_cobrar, get_cuentas_pagar, get_pagos_programados,
        get_kpis_fi, get_budget_vs_real_sap, sincronizar_todo,
    )
    from src.realtime.realtime_engine import (
        get_posicion_liquidez, calcular_ccc,
        forecast_rolling_13_semanas, generar_alertas_automaticas,
        get_dashboard_ejecutivo,
    )
    SAP_DISPONIBLE = True
except Exception as _sap_err:
    SAP_DISPONIBLE = False
    _sap_err_msg = str(_sap_err)
from src.models.gestor_tesoreria import (
    cargar_rendimientos, guardar_rendimientos,
    calcular_excedente_real, recomendar_distribucion,
    comparar_instrumentos, simular_rendimiento,
)
from src.utils.helpers import fmt_ars, fmt_millones, semaforo_color, nombre_mes
from src.utils.exportador import exportar_excel

# ══════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title=f"Cashflow — {EMPRESA}",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── PALETA CORPORATIVA ──────────────────────────────────────────────
# Azul corporativo: #1F3864 (oscuro) / #2E75B6 (medio) / #BDD7EE (claro)
# Verde éxito:      #166534 texto / #DCFCE7 fondo
# Rojo alerta:      #991B1B texto / #FEE2E2 fondo
# Amarillo aviso:   #854D0E texto / #FEF9C3 fondo
# Gris neutro:      #374151 texto / #F8FAFC fondo
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* ════ PALETA CORPORATIVA DDS ════
   Fondo página:   #0F172A  (azul noche)
   Fondo cards:    #1E293B  (slate oscuro)
   Fondo sidebar:  #0F172A → #1a2744
   Texto primario: #F1F5F9  (blanco slate)
   Texto secundario:#94A3B8 (gris claro)
   Acento azul:    #3B82F6
   Acento verde:   #10B981
   Acento rojo:    #EF4444
   Acento amarillo:#F59E0B
   Borde:          #334155
═══════════════════════════════════════ */

/* ════ BASE ════ */
html, body, .stApp {
    font-family: 'Inter', sans-serif !important;
    background-color: #0F172A !important;
    color: #F1F5F9 !important;
}
.main .block-container {
    padding: 1.5rem 2rem !important;
    max-width: 1400px !important;
    background-color: #0F172A !important;
}

/* ════ SIDEBAR ════ */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0F172A 0%, #1a2744 100%) !important;
    border-right: 1px solid #1E293B !important;
}
section[data-testid="stSidebar"] * { color: #94A3B8 !important; }
section[data-testid="stSidebar"] strong,
section[data-testid="stSidebar"] b { color: #F1F5F9 !important; }
section[data-testid="stSidebar"] [data-testid="stRadio"] label {
    color: #94A3B8 !important;
    font-size: 13px !important;
    padding: 4px 0 !important;
    transition: color 0.15s !important;
}
section[data-testid="stSidebar"] [data-testid="stRadio"] label:hover { color: #F1F5F9 !important; }
section[data-testid="stSidebar"] [data-testid="stRadio"] [aria-checked="true"] + label,
section[data-testid="stSidebar"] [data-testid="stRadio"] input:checked ~ label {
    color: #60A5FA !important;
    font-weight: 600 !important;
}
section[data-testid="stSidebar"] [data-testid="stFileUploader"] {
    background: rgba(255,255,255,0.06) !important;
    border: 1px dashed rgba(255,255,255,0.2) !important;
    border-radius: 8px !important;
}

/* ════ MÉTRICAS ════ */
[data-testid="metric-container"] {
    background: #1E293B !important;
    border: 1px solid #334155 !important;
    border-radius: 12px !important;
    border-left: 4px solid #3B82F6 !important;
    padding: 18px 20px !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3) !important;
}
[data-testid="metric-container"] label,
[data-testid="stMetricLabel"],
[data-testid="stMetricLabel"] *,
[data-testid="stMetricLabel"] p {
    color: #94A3B8 !important;
    font-size: 11px !important;
    font-weight: 500 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.5px !important;
}
[data-testid="stMetricValue"],
[data-testid="stMetricValue"] *,
[data-testid="stMetricValue"] div {
    color: #F1F5F9 !important;
    font-size: 26px !important;
    font-weight: 700 !important;
    line-height: 1.2 !important;
}
[data-testid="stMetricDelta"],
[data-testid="stMetricDelta"] * {
    font-size: 12px !important;
    font-weight: 500 !important;
}

/* ════ HEADERS ════ */
h1 { color: #F1F5F9 !important; font-weight: 700 !important; font-size: 24px !important; margin-bottom: 4px !important; }
h2 { color: #F1F5F9 !important; font-weight: 700 !important; font-size: 20px !important; }
h3 { color: #E2E8F0 !important; font-weight: 600 !important; font-size: 16px !important; }
h4 { color: #CBD5E1 !important; font-weight: 600 !important; font-size: 14px !important; }
p, li { color: #CBD5E1 !important; font-size: 13px !important; }
.stMarkdown p { color: #CBD5E1 !important; }

/* ════ HEADER CORPORATIVO ════ */
.cf-header {
    background: linear-gradient(135deg, #1E3A8A 0%, #1D4ED8 100%);
    padding: 22px 28px;
    border-radius: 14px;
    margin-bottom: 24px;
    box-shadow: 0 8px 24px rgba(29,78,216,0.35);
    border: 1px solid #2563EB;
}
.cf-header h1 {
    color: #FFFFFF !important;
    margin: 0 !important;
    font-size: 22px !important;
    font-weight: 700 !important;
}
.cf-header p { color: #BFDBFE !important; margin: 6px 0 0 !important; font-size: 13px !important; }

/* ════ ALERTAS ════ */
.alerta-critico {
    background: #2D1515;
    border-left: 4px solid #EF4444;
    border-radius: 8px;
    padding: 12px 16px;
    margin: 5px 0;
}
.alerta-critico, .alerta-critico * { color: #FCA5A5 !important; font-size: 12px !important; }
.alerta-critico b, .alerta-critico strong { color: #FEE2E2 !important; font-weight: 600 !important; }

.alerta-alerta {
    background: #2D2008;
    border-left: 4px solid #F59E0B;
    border-radius: 8px;
    padding: 12px 16px;
    margin: 5px 0;
}
.alerta-alerta, .alerta-alerta * { color: #FCD34D !important; font-size: 12px !important; }
.alerta-alerta b, .alerta-alerta strong { color: #FEF3C7 !important; font-weight: 600 !important; }

.alerta-info {
    background: #0D1F3C;
    border-left: 4px solid #3B82F6;
    border-radius: 8px;
    padding: 12px 16px;
    margin: 5px 0;
}
.alerta-info, .alerta-info * { color: #93C5FD !important; font-size: 12px !important; }
.alerta-info b, .alerta-info strong { color: #BFDBFE !important; font-weight: 600 !important; }

.alerta-ok {
    background: #0D2D1F;
    border-left: 4px solid #10B981;
    border-radius: 8px;
    padding: 12px 16px;
    margin: 5px 0;
}
.alerta-ok, .alerta-ok * { color: #6EE7B7 !important; font-size: 12px !important; }

/* ════ SEMÁFOROS MENSUALES ════ */
.sem-ok {
    background: #0D2D1F; color: #6EE7B7 !important;
    border: 1px solid #10B981;
    padding: 8px 4px; border-radius: 10px;
    text-align: center; font-size: 11px; font-weight: 600;
}
.sem-warn {
    background: #2D2008; color: #FCD34D !important;
    border: 1px solid #F59E0B;
    padding: 8px 4px; border-radius: 10px;
    text-align: center; font-size: 11px; font-weight: 600;
}
.sem-critico {
    background: #2D1515; color: #FCA5A5 !important;
    border: 1px solid #EF4444;
    padding: 8px 4px; border-radius: 10px;
    text-align: center; font-size: 11px; font-weight: 600;
}

/* ════ TABS ════ */
.stTabs [data-baseweb="tab-list"] {
    background: #1E293B !important;
    border-radius: 10px !important;
    padding: 4px !important;
    border: 1px solid #334155 !important;
    gap: 2px !important;
}
.stTabs [data-baseweb="tab"] {
    color: #94A3B8 !important;
    font-weight: 500 !important;
    font-size: 13px !important;
    border-radius: 8px !important;
    padding: 8px 16px !important;
    background: transparent !important;
}
.stTabs [aria-selected="true"] {
    background: #2563EB !important;
    color: #FFFFFF !important;
    font-weight: 600 !important;
}

/* ════ BOTONES ════ */
.stButton > button {
    background-color: #2563EB !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 13px !important;
    padding: 10px 20px !important;
    transition: all 0.2s !important;
    box-shadow: 0 2px 8px rgba(37,99,235,0.4) !important;
}
.stButton > button:hover {
    background-color: #1D4ED8 !important;
    box-shadow: 0 4px 12px rgba(37,99,235,0.5) !important;
    transform: translateY(-1px) !important;
}
.stDownloadButton > button {
    background-color: #059669 !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
}
.stDownloadButton > button:hover { background-color: #047857 !important; }

/* ════ INPUTS Y FORMULARIOS ════ */
.stTextInput > div > div > input,
.stNumberInput > div > div > input,
.stTextArea textarea {
    background-color: #1E293B !important;
    color: #F1F5F9 !important;
    border: 1px solid #475569 !important;
    border-radius: 8px !important;
    font-size: 13px !important;
}
.stTextInput > div > div > input:focus,
.stNumberInput > div > div > input:focus,
.stTextArea textarea:focus {
    border-color: #3B82F6 !important;
    box-shadow: 0 0 0 3px rgba(59,130,246,0.2) !important;
}
.stTextInput > div > div > input::placeholder,
.stTextArea textarea::placeholder { color: #64748B !important; }
.stSelectbox > div > div,
.stMultiSelect > div > div {
    background-color: #1E293B !important;
    border: 1px solid #475569 !important;
    border-radius: 8px !important;
    color: #F1F5F9 !important;
}
div[data-baseweb="select"] span { color: #F1F5F9 !important; }
div[data-baseweb="select"] div { background: #1E293B !important; color: #F1F5F9 !important; }
div[data-baseweb="popover"] { background: #1E293B !important; border: 1px solid #334155 !important; }
div[data-baseweb="popover"] li { color: #F1F5F9 !important; }
div[data-baseweb="popover"] li:hover { background: #334155 !important; }

/* Labels de inputs */
.stTextInput label, .stNumberInput label,
.stSelectbox label, .stDateInput label,
.stTextArea label, .stFileUploader label,
.stMultiSelect label, .stRadio label,
.stCheckbox label, .stSlider label {
    color: #CBD5E1 !important;
    font-weight: 500 !important;
    font-size: 13px !important;
}
/* Slider */
.stSlider > div > div > div { background: #334155 !important; }
.stSlider [data-testid="stTickBar"] * { color: #94A3B8 !important; }

/* ════ FORM CONTAINER ════ */
[data-testid="stForm"] {
    background: #1E293B !important;
    border: 1px solid #334155 !important;
    border-radius: 12px !important;
    padding: 20px !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3) !important;
}

/* ════ DATAFRAME / TABLAS ════ */
[data-testid="stDataFrame"] {
    background: #1E293B !important;
    border: 1px solid #334155 !important;
    border-radius: 10px !important;
    overflow: hidden !important;
}
[data-testid="stDataFrame"] th {
    color: #94A3B8 !important;
    background: #0F172A !important;
    font-size: 11px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.4px !important;
}
[data-testid="stDataFrame"] td {
    color: #E2E8F0 !important;
    background: #1E293B !important;
    font-size: 12px !important;
}
[data-testid="stDataFrame"] tr:hover td { background: #263548 !important; }

/* ════ EXPANDER ════ */
.streamlit-expanderHeader {
    background: #1E293B !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
    color: #E2E8F0 !important;
    font-weight: 600 !important;
}
.streamlit-expanderContent {
    background: #1E293B !important;
    border: 1px solid #334155 !important;
    border-top: none !important;
}

/* ════ ALERTS NATIVOS STREAMLIT ════ */
.stAlert {
    border-radius: 10px !important;
    font-size: 13px !important;
}
div[data-testid="stAlert"] {
    background: #1E293B !important;
    border: 1px solid #334155 !important;
}
div[data-testid="stAlert"] * { color: #E2E8F0 !important; font-size: 13px !important; }

/* ════ FILE UPLOADER ════ */
[data-testid="stFileUploader"] {
    background: #1E293B !important;
    border: 2px dashed #3B82F6 !important;
    border-radius: 12px !important;
}
[data-testid="stFileUploader"] * { color: #CBD5E1 !important; }

/* ════ DIVIDER ════ */
hr { border-color: #334155 !important; margin: 16px 0 !important; }

/* ════ CAPTION Y TEXTO PEQUEÑO ════ */
.stCaption, [data-testid="stCaptionContainer"] * { color: #64748B !important; font-size: 11px !important; }

/* ════ SCROLLBAR ════ */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #0F172A; }
::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #475569; }

/* ════ NÚMERO DE INPUTS ════ */
button[data-testid="stNumberInputStepDown"],
button[data-testid="stNumberInputStepUp"] {
    background: #334155 !important;
    color: #F1F5F9 !important;
    border: none !important;
}
button[data-testid="stNumberInputStepDown"]:hover,
button[data-testid="stNumberInputStepUp"]:hover {
    background: #475569 !important;
}

/* ════ CHECKBOX Y RADIO ════ */
.stCheckbox label span,
.stRadio label span { color: #CBD5E1 !important; }

/* ════ FORZAR FONDO OSCURO GLOBAL ════ */
div.stMarkdown, div.element-container,
div[data-testid="column"], div[data-testid="stVerticalBlock"] {
    color: #E2E8F0 !important;
}
div[data-testid="stHorizontalBlock"] { background: transparent !important; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# AUTENTICACIÓN
# ══════════════════════════════════════════════════════════════════════
if not st.session_state.get("autenticado"):
    if not mostrar_login():
        st.stop()

# ══════════════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════════════
def init_state():
    if "params" not in st.session_state:
        import json as _json
        _cfg_path = os.path.join(os.path.dirname(__file__), "data", "params_config.json")
        if os.path.exists(_cfg_path):
            _cfg = _json.load(open(_cfg_path))
            _p = ParametrosCashflow()
            for _k, _v in _cfg.items():
                if hasattr(_p, _k): setattr(_p, _k, _v)
            st.session_state.params = _p
        else:
            st.session_state.params = ParametrosCashflow()
    if "df_extracto"  not in st.session_state: st.session_state.df_extracto = pd.DataFrame()
    if "df_cashflow"  not in st.session_state: st.session_state.df_cashflow  = pd.DataFrame()
    if "df_cheques"   not in st.session_state:
        df_ch = cargar_cheques()
        st.session_state.df_cheques = df_ch if not df_ch.empty else generar_cheques_muestra()
    if "df_facturas"  not in st.session_state:
        df_fac = cargar_facturas()
        st.session_state.df_facturas = df_fac if not df_fac.empty else generar_facturas_muestra()
    if "budget"       not in st.session_state: st.session_state.budget       = cargar_budget(AÑO)
    if "prestamos"    not in st.session_state:
        p = cargar_prestamos()
        st.session_state.prestamos = p if p else []
    if "planes_afip"  not in st.session_state:
        pl = cargar_planes_afip()
        st.session_state.planes_afip = pl if pl else []
    if "config_imp"   not in st.session_state: st.session_state.config_imp  = cargar_config_impuestos()
    if "tasas_ref"    not in st.session_state: st.session_state.tasas_ref   = cargar_tasas_referencia()
    if "df_vencimientos" not in st.session_state: st.session_state.df_vencimientos = pd.DataFrame()
    if "df_comex" not in st.session_state:
        df_cx = cargar_comex()
        st.session_state.df_comex = df_cx if not df_cx.empty else generar_comex_demo()
    if "inversiones" not in st.session_state:
        inv = cargar_inversiones()
        if not inv.get("items"):
            inv = generar_inversiones_demo()
            guardar_inversiones(inv)
        st.session_state.inversiones = inv
    if "alertas_list" not in st.session_state: st.session_state.alertas_list = []
    if "kpis"         not in st.session_state: st.session_state.kpis         = {}

init_state()

# Precarga demo: saldo inicial realista si no hay uno cargado
if float(getattr(st.session_state.params, "saldo_inicial", 0) or 0) <= 0:
    st.session_state.params.saldo_inicial = 13_900_000_000.0  # ~$13,9B (editable en sidebar/Parámetros)

def recalcular_todo():
    params   = st.session_state.params
    df_real  = st.session_state.df_extracto
    df_fac   = st.session_state.df_facturas
    budget   = st.session_state.budget

    # Si hay facturas reales, usar su proyección de cobranzas
    if not df_fac.empty:
        df_cobranzas = proyectar_cobranzas_desde_facturas(df_fac, AÑO)
        # Actualizar cobros proyectados en el motor
        for _, r in df_cobranzas.iterrows():
            mes = int(r["mes"])
            if r["cobro_esperado"] > 0:
                # Inyectar en los parámetros como cobro real conocido
                pass  # el motor ya usa las facturas directamente

    df_cf = generar_cashflow_mensual(
        params, df_real=df_real if not df_real.empty else None, año=AÑO
    )
    if not df_real.empty and not df_cf.empty:
        df_real = conciliar_automatico(df_real, df_cf)
        st.session_state.df_extracto = df_real

    st.session_state.df_cashflow = df_cf
    st.session_state.kpis = calcular_kpis(df_cf, df_real if not df_real.empty else None)
    st.session_state.alertas_list = generar_todas_las_alertas(
        df_cashflow=df_cf, df_cheques=st.session_state.df_cheques,
        params_dict=params.to_dict(), mes_actual=date.today().month,
        fecha_hoy=date.today(), umbral_desvio=10.0,
    )

if st.session_state.df_cashflow.empty:
    recalcular_todo()

# ══════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════
with st.sidebar:
    user = st.session_state.get("usuario_actual", {})
    st.markdown(f"""
    <div style="padding:16px 12px 14px;border-bottom:1px solid #2E75B6;margin-bottom:12px">
        <div style="font-size:17px;font-weight:700;color:white">💰 CashFlow</div>
        <div style="font-size:11px;color:#BDD7EE;margin-top:2px">{EMPRESA}</div>
        <div style="margin-top:10px;background:rgba(255,255,255,0.1);
                    border-radius:6px;padding:7px 10px">
            <div style="font-size:11px;color:#BDD7EE">👤 {user.get('nombre','')}</div>
            <div style="font-size:10px;color:#7FB3E0;margin-top:1px">
                Rol: {user.get('rol','').upper()}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    pagina = st.radio("", [
        "🏠 Dashboard",
        "🎯 Comando Ejecutivo",
        "📊 Cashflow Mensual",
        "📅 Cashflow Semanal",
        "🔄 Conciliación Bancaria",
        "📋 Facturas y Cobranzas",
        "📈 Budget y Desvíos",
        "🏦 Cheques y Pagarés",
        "🏛️ Deuda e Impuestos",
        "🔁 Rolleo de Deuda",
        "🏢 Por Unidad de Negocio",
        "📦 Productos y Estacionalidad",
        "💹 Inversiones",
        "🌍 COMEX — Importaciones",
        "📥 Carga Préstamo (OCR)",
        "🔗 SAP — Tiempo Real",
        "📡 Forecast Liquidez",
        "💰 Tesorería — FCI",
        "⚙️ Parámetros",
        "👥 Usuarios",
        "📤 Exportar",
    ], label_visibility="collapsed")

    st.markdown("---")
    alertas    = st.session_state.alertas_list
    res_al     = resumen_alertas(alertas)
    if res_al["criticos"] > 0: st.error(f"🔴 {res_al['criticos']} alertas críticas")
    if res_al["alertas"]  > 0: st.warning(f"🟡 {res_al['alertas']} alertas")

    st.markdown("---")
    st.markdown("<div style='font-size:11px;color:#BDD7EE;margin-bottom:6px'>Importar extracto</div>", unsafe_allow_html=True)
    up = st.file_uploader("", type=["csv","xlsx","xls"], key="up_side", label_visibility="collapsed")
    if up:
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(up.name)[1]) as tmp:
            tmp.write(up.read()); tmp_path = tmp.name
        df_up = parse_extracto(tmp_path, nombre_archivo=up.name)
        if not df_up.empty:
            st.session_state.df_extracto = df_up
            recalcular_todo()
            st.success(f"✅ {len(df_up)} movimientos")

    st.markdown("---")
    st.markdown("<div style='font-size:11px;color:#BDD7EE;margin-bottom:4px'>💰 Saldo Inicial</div>", unsafe_allow_html=True)
    saldo_quick = st.number_input("", value=float(st.session_state.params.saldo_inicial),
        step=1_000_000.0, format="%.0f", label_visibility="collapsed", key="saldo_quick")
    if saldo_quick != st.session_state.params.saldo_inicial:
        st.session_state.params.saldo_inicial = saldo_quick
        recalcular_todo()
    st.markdown("---")
    if st.button("🚪 Cerrar sesión", use_container_width=True):
        for k in ["autenticado","usuario_actual"]: st.session_state.pop(k, None)
        st.rerun()

# Paleta de colores legibles (modo claro)
C_ING   = "#059669"   # Verde oscuro
C_EG    = "#DC2626"   # Rojo oscuro
C_PROY  = "#2563EB"   # Azul
C_REAL  = "#059669"   # Verde
C_SALDO = "#7C3AED"   # Violeta
C_WARN  = "#D97706"   # Naranja
MESES_C = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]

def plotly_layout(fig, height=380):
    fig.update_layout(
        height=height, plot_bgcolor="white", paper_bgcolor="white",
        font=dict(size=11, color="#1F2937"),
        legend=dict(orientation="h", y=1.13, x=0, xanchor="left",
                    yanchor="bottom", font=dict(size=11, color="#1F2937"),
                    bgcolor="rgba(255,255,255,0.92)",
                    bordercolor="#D1D9E6", borderwidth=1),
        margin=dict(t=78, b=34, l=12, r=14),
        xaxis=dict(gridcolor="#F3F4F6", linecolor="#D1D9E6",
                   tickfont=dict(color="#1F2937")),
        yaxis=dict(gridcolor="#F3F4F6", linecolor="#D1D9E6",
                   tickfont=dict(color="#1F2937")),
    )
    fig.update_annotations(font=dict(color="#1F2937", size=12))
    fig.update_xaxes(tickfont=dict(color="#1F2937"), title_font=dict(color="#1F2937"))
    fig.update_yaxes(tickfont=dict(color="#1F2937"), title_font=dict(color="#1F2937"))
    return fig

# ══════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════
if pagina == "🏠 Dashboard":
    st.markdown(f"""
    <div class="cf-header">
        <h1>📊 Dashboard Ejecutivo — {EMPRESA}</h1>
        <p>Cashflow en tiempo real · Proyectado vs Real · Alertas automáticas · {AÑO}</p>
    </div>""", unsafe_allow_html=True)

    kpis  = st.session_state.kpis
    df_cf = st.session_state.df_cashflow

    # KPIs
    c1,c2,c3,c4 = st.columns(4)
    with c1: st.metric("💰 Saldo Actual", fmt_millones(kpis.get("saldo_actual",0)),
                       f"{kpis.get('saldo_actual_label','')} — {kpis.get('mes_actual','')}")
    with c2: st.metric("📈 Ingresos Anuales Proy.", fmt_millones(kpis.get("ing_anual_proy",0)))
    with c3: st.metric("📉 Egresos Anuales Proy.",  fmt_millones(kpis.get("eg_anual_proy",0)))
    with c4:
        res = kpis.get("res_anual_proy",0)
        st.metric("📊 Resultado Neto Proy.", fmt_millones(res),
                  delta=f"{'▲' if res>0 else '▼'} {fmt_millones(abs(res))}")

    # KPIs AR si hay facturas
    df_fac = st.session_state.df_facturas
    if not df_fac.empty:
        kpis_ar = resumen_ar(df_fac)
        st.markdown("---")
        c5,c6,c7,c8 = st.columns(4)
        with c5: st.metric("🧾 Facturado",     fmt_millones(kpis_ar.get("total_emitido",0)))
        with c6: st.metric("✅ Cobrado",        fmt_millones(kpis_ar.get("total_cobrado",0)),
                           f"{kpis_ar.get('pct_cobrado',0):.0f}% del total")
        with c7: st.metric("⏳ Pendiente AR",   fmt_millones(kpis_ar.get("total_pendiente",0)))
        with c8: st.metric("📅 DSO",           f"{kpis_ar.get('dso_dias',0):.0f} días",
                           "Días prom. de cobro")

    st.markdown("---")
    col_g1, col_g2 = st.columns([1.6, 1])
    with col_g1:
        if not df_cf.empty:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                vertical_spacing=0.1, row_heights=[0.6,0.4],
                subplot_titles=("🟢 Ingresos vs 🔴 Egresos Proyectados (en MM$ ARS)", "Saldo Final en Caja — Semáforo por Umbral (MM$ ARS)"))
            meses = df_cf["mes_nombre"].apply(lambda m: m[:3]).tolist()
            ing_k = (df_cf["ing_proy"]/1e6).tolist()
            eg_k  = (df_cf["eg_proy"] /1e6).tolist()
            sf_k  = (df_cf["saldo_fin_proy"]/1e6).tolist()
            fig.add_trace(go.Bar(
                x=meses, y=ing_k, name="🟢 Ingresos Proyectados", marker_color=C_ING, opacity=0.85,
                text=[f"${v:,.0f}M" for v in ing_k], textposition="outside",
                textfont=dict(size=10, color="#1F2937"),
                hovertemplate="<b>%{x}</b><br>Ingresos: $%{y:,.0f}M ARS<extra></extra>",
            ), row=1,col=1)
            fig.add_trace(go.Bar(
                x=meses, y=eg_k, name="🔴 Egresos Proyectados", marker_color=C_EG, opacity=0.85,
                hovertemplate="<b>%{x}</b><br>Egresos: $%{y:,.0f}M ARS<extra></extra>",
            ), row=1,col=1)
            sf_colors = ["#DC2626" if s<SALDO_MINIMO_CRITICO/1e6
                         else "#D97706" if s<SALDO_MINIMO_ALERTA/1e6
                         else "#059669" for s in sf_k]
            fig.add_trace(go.Bar(
                x=meses, y=sf_k, name="Saldo en Caja",
                marker_color=sf_colors, opacity=0.9,
                text=[f"${v:,.0f}M" for v in sf_k], textposition="outside",
                textfont=dict(size=10, color="#1F2937"),
                hovertemplate="<b>%{x}</b><br>Saldo: $%{y:,.0f}M ARS<extra></extra>",
            ), row=2,col=1)
            fig.add_hline(y=SALDO_MINIMO_CRITICO/1e6, line_dash="dash", line_color="#DC2626",
                          annotation_text="Mín. crítico", row=2,col=1)
            fig.add_hline(y=SALDO_MINIMO_ALERTA/1e6,  line_dash="dot",  line_color="#D97706",
                          annotation_text="Mín. alerta",  row=2,col=1)
            fig = plotly_layout(fig, 420)
            fig.update_layout(barmode="group")
            fig.update_yaxes(tickprefix="$", ticksuffix="M")
            st.plotly_chart(fig, use_container_width=True)

    with col_g2:
        st.markdown("#### 🚨 Alertas del Sistema")
        for a in st.session_state.alertas_list[:8]:
            cls = f"alerta-{a['nivel']}"
            st.markdown(
                f'<div class="{cls}"><b>{a["titulo"]}</b><br>'
                f'{a["detalle"][:85]}{"..." if len(a["detalle"])>85 else ""}'
                f'{"<br><i>→ "+a["accion"][:55]+"</i>" if a["accion"] else ""}</div>',
                unsafe_allow_html=True)

    # Semáforo mensual
    st.markdown("---")
    st.markdown("#### 🚦 Semáforo de Saldo — Proyección Mensual")
    if not df_cf.empty:
        cols_sem = st.columns(12)
        for i, (_, row) in enumerate(df_cf.iterrows()):
            s = row["saldo_fin_proy"]
            if   s < SALDO_MINIMO_CRITICO: cls,ico = "sem-critico","🔴"
            elif s < SALDO_MINIMO_ALERTA:  cls,ico = "sem-warn",   "🟡"
            else:                          cls,ico = "sem-ok",     "🟢"
            ag = "⚠️" if row.get("aguinaldo_mes") else ""
            with cols_sem[i]:
                st.markdown(
                    f'<div class="{cls}" style="text-align:center;font-size:11px">'
                    f'<b>{row["mes_nombre"][:3].upper()}</b><br>'
                    f'{ico}{ag}<br>{fmt_millones(s)}</div>',
                    unsafe_allow_html=True)

    # Donuts si hay extracto
    df_ext = st.session_state.df_extracto
    if not df_ext.empty:
        st.markdown("---")
        cd1, cd2 = st.columns(2)
        with cd1:
            st.markdown("#### 💸 Egresos por Categoría")
            eg_cat = df_ext[df_ext["importe"]<0].groupby("categoria")["importe"].sum().abs().sort_values(ascending=False)
            if not eg_cat.empty:
                fig_pie = go.Figure(go.Pie(labels=eg_cat.index, values=eg_cat.values, hole=0.45,
                    textinfo="label+percent",
                    marker=dict(colors=px.colors.qualitative.Set2),
                    hovertemplate="<b>%{label}</b><br>$%{value:,.0f}<extra></extra>"))
                fig_pie.update_layout(height=300, margin=dict(t=10,b=10), showlegend=False,
                    paper_bgcolor="white", plot_bgcolor="white")
                st.plotly_chart(fig_pie, use_container_width=True)
        with cd2:
            st.markdown("#### 📈 Ingresos por Categoría")
            ing_cat = df_ext[df_ext["importe"]>0].groupby("categoria")["importe"].sum().sort_values(ascending=False)
            if not ing_cat.empty:
                fig_bar = go.Figure(go.Bar(
                    x=ing_cat.values, y=ing_cat.index, orientation="h",
                    marker_color=C_ING, opacity=0.85,
                    text=[fmt_millones(v) for v in ing_cat.values], textposition="outside"))
                fig_bar.update_layout(height=300, margin=dict(t=10,b=10,l=10,r=70),
                    paper_bgcolor="white", plot_bgcolor="white",
                    xaxis=dict(gridcolor="#F3F4F6"), yaxis=dict(gridcolor="#F3F4F6"))
                st.plotly_chart(fig_bar, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════
# CASHFLOW MENSUAL
# ══════════════════════════════════════════════════════════════════════
elif pagina == "📊 Cashflow Mensual":
    st.markdown("## 📊 Cashflow Mensual — Proyectado vs Real")
    df_cf = st.session_state.df_cashflow

    tab1, tab2, tab3 = st.tabs(["📋 Tabla completa", "📈 Gráfico de desvíos", "🔍 Detalle por mes"])

    with tab1:
        secciones = {
            "SALDO INICIAL":  [("Saldo Inicial","saldo_ini_proy")],
            "INGRESOS":       [("Cobros Proyectados","ing_proy"),("Cobros Reales","ing_real")],
            "EGRESOS":        [("Egresos Proyectados","eg_proy"),("Egresos Reales","eg_real")],
            "RESULTADO":      [("Resultado Neto Proy.","res_proy"),("Resultado Neto Real","res_real")],
            "SALDO FINAL":    [("Saldo Final Proy.","saldo_fin_proy"),("Saldo Final Real","saldo_fin_real")],
            "SEMÁFORO":       [("Semáforo","semaforo")],
        }
        rows_tabla = []
        for sec, items in secciones.items():
            row_s = {"Concepto": f"▸ {sec}"}
            for m in range(1,13): row_s[MESES_C[m-1]] = ""
            row_s["TOTAL"] = ""
            rows_tabla.append(row_s)
            for lbl, key in items:
                row_d = {"Concepto": f"  {lbl}"}
                total = 0.0
                for m in range(1,13):
                    ser = df_cf.loc[df_cf["mes"]==m, key]
                    val = ser.values[0] if len(ser)>0 else None
                    if val is not None and str(val) != "nan" and key != "semaforo":
                        row_d[MESES_C[m-1]] = fmt_ars(float(val))
                        total += float(val)
                    else:
                        row_d[MESES_C[m-1]] = val if key=="semaforo" else "—"
                row_d["TOTAL"] = fmt_ars(total) if key != "semaforo" else ""
                rows_tabla.append(row_d)

        st.dataframe(pd.DataFrame(rows_tabla), use_container_width=True, hide_index=True, height=450)

    with tab2:
        df_r = df_cf[df_cf.get("tiene_real", False) == True] if "tiene_real" in df_cf.columns else pd.DataFrame()
        df_ext = st.session_state.df_extracto
        if df_r.empty and df_ext.empty:
            st.info("📥 Cargá un extracto bancario desde la página de Conciliación para ver los desvíos.")
        else:
            # ── Desvíos por MES ───────────────────────────────────────
            if not df_r.empty:
                st.markdown("#### 📅 Desvío de Ingresos por Mes")
                fig_d = make_subplots(rows=1, cols=2,
                    subplot_titles=("Ingresos: Proyectado vs Real ($M)","Desvío % por Mes"),
                    horizontal_spacing=0.1)
                meses_r = df_r["mes_nombre"].apply(lambda m: m[:3]).tolist()
                fig_d.add_trace(go.Bar(x=meses_r, y=(df_r["ing_proy"]/1e6).tolist(),
                    name="Proyectado", marker_color=C_PROY, opacity=0.8), row=1,col=1)
                fig_d.add_trace(go.Bar(x=meses_r, y=(df_r["ing_real"]/1e6).tolist(),
                    name="Real", marker_color=C_REAL, opacity=0.8), row=1,col=1)
                devs = [float(d) if d is not None else 0 for d in df_r["dev_pct_ing"].tolist()]
                fig_d.add_trace(go.Bar(x=meses_r, y=devs, name="Desvío %",
                    marker_color=[C_ING if d>=0 else C_EG for d in devs], opacity=0.9,
                    text=[f"{d:.1f}%" for d in devs], textposition="outside"), row=1,col=2)
                fig_d = plotly_layout(fig_d, 340)
                fig_d.update_layout(barmode="group")
                fig_d.update_yaxes(ticksuffix="M", row=1, col=1)
                fig_d.update_yaxes(ticksuffix="%", row=1, col=2)
                st.plotly_chart(fig_d, use_container_width=True)

            # ── Desvíos AGRUPADOS por CONCEPTO (con drill-down) ───────
            if not df_ext.empty:
                st.markdown("#### 🔍 Desvíos por Concepto — Hacer clic para ver detalle")
                df_dev_agrup = agrupar_desvios(df_ext, df_cf)
                if not df_dev_agrup.empty:
                    # Selección de mes
                    meses_disp = ["Todos"] + sorted(df_dev_agrup["mes_nombre"].unique().tolist())
                    mes_dev = st.selectbox("Filtrar por mes", meses_disp, key="mes_dev")
                    if mes_dev != "Todos":
                        df_dev_filt = df_dev_agrup[df_dev_agrup["mes_nombre"] == mes_dev]
                    else:
                        df_dev_filt = df_dev_agrup

                    # Agrupado por concepto (suma todos los meses)
                    df_por_cat = df_dev_filt.groupby("categoria").agg(
                        real=("real","sum"), proyectado=("proyectado","sum"),
                        desvio_abs=("desvio_abs","sum"),
                        movimientos=("cant_movimientos","sum")).reset_index()
                    df_por_cat["desvio_pct"] = df_por_cat.apply(
                        lambda r: r["desvio_abs"]/abs(r["proyectado"])*100 if r["proyectado"]!=0 else 0, axis=1)
                    df_por_cat["nivel"] = df_por_cat["desvio_pct"].apply(
                        lambda p: "🔴 Alto" if abs(p)>20 else "🟡 Medio" if abs(p)>10 else "🟢 Normal")
                    df_por_cat = df_por_cat.sort_values("desvio_abs", ascending=True)

                    # Gráfico horizontal de desvíos por concepto
                    fig_cat = go.Figure(go.Bar(
                        x=(df_por_cat["desvio_abs"]/1e6).tolist(),
                        y=df_por_cat["categoria"].tolist(),
                        orientation="h",
                        marker_color=[C_ING if v>=0 else C_EG for v in df_por_cat["desvio_abs"].tolist()],
                        opacity=0.85,
                        text=[f"${v:.1f}M" for v in (df_por_cat["desvio_abs"]/1e6).tolist()],
                        textposition="outside",
                    ))
                    fig_cat = plotly_layout(fig_cat, 280)
                    fig_cat.update_layout(title="Desvío Real vs Proyectado por Concepto ($M)",
                        xaxis_title="Desvío $M (+ sobrepasa proy., - cae)", yaxis_title="")
                    st.plotly_chart(fig_cat, use_container_width=True)

                    # Tabla agrupada — expandible por concepto
                    st.markdown("**Detalle por concepto** — expandí para ver movimientos:")
                    for _, row_c in df_por_cat.iterrows():
                        cat  = row_c["categoria"]
                        dev  = float(row_c["desvio_abs"])
                        pct  = float(row_c["desvio_pct"])
                        icon = "🔴" if abs(pct)>20 else "🟡" if abs(pct)>10 else "🟢"
                        with st.expander(
                            f"{icon} **{cat}** — Real: {fmt_ars(row_c['real'])} | "
                            f"Proyectado: {fmt_ars(row_c['proyectado'])} | "
                            f"Desvío: {fmt_ars(dev)} ({pct:+.1f}%)"
                        ):
                            # Detalle de movimientos de esa categoría
                            df_detalle = df_ext[df_ext["categoria"]==cat].copy()
                            if mes_dev != "Todos":
                                df_detalle = df_detalle[df_detalle["mes_nombre"]==mes_dev]
                            df_detalle_show = df_detalle[["fecha_str","descripcion","importe","tipo","mes_nombre"]].copy()
                            df_detalle_show["importe"] = df_detalle_show["importe"].apply(fmt_ars)
                            st.dataframe(df_detalle_show, hide_index=True, use_container_width=True,
                                column_config={
                                    "fecha_str":"Fecha","descripcion":st.column_config.TextColumn("Descripción",width="large"),
                                    "importe":"Importe","tipo":"Tipo","mes_nombre":"Mes"
                                })

    with tab3:
        mes_sel = st.selectbox("Mes", range(1,13), format_func=nombre_mes, index=date.today().month-1)
        row = df_cf[df_cf["mes"]==mes_sel]
        if not row.empty:
            r = row.iloc[0]
            cm1,cm2,cm3 = st.columns(3)
            with cm1:
                st.metric("Saldo Inicial",      fmt_ars(r.get("saldo_ini_proy")))
                st.metric("Ingresos Proy.",      fmt_ars(r.get("ing_proy")))
                st.metric("Egresos Proy.",       fmt_ars(r.get("eg_proy")))
            with cm2:
                st.metric("Resultado Neto",      fmt_ars(r.get("res_proy")))
                st.metric("Saldo Final Proy.",   fmt_ars(r.get("saldo_fin_proy")))
                st.metric("Semáforo",            r.get("semaforo","—"))
            with cm3:
                if r.get("tiene_real"):
                    st.metric("Ingresos Reales", fmt_ars(r.get("ing_real")))
                    st.metric("Egresos Reales",  fmt_ars(r.get("eg_real")))
                    st.metric("Desvío Ingresos", f"{r.get('dev_pct_ing',0):.1f}%")
                else:
                    st.info("Sin datos reales para este mes")
            if r.get("aguinaldo_mes"):
                st.warning("⚠️ Mes de aguinaldo — cargas sociales ×1.5 aplicadas")


# ══════════════════════════════════════════════════════════════════════
# CASHFLOW SEMANAL
# ══════════════════════════════════════════════════════════════════════
elif pagina == "📅 Cashflow Semanal":
    st.markdown("## 📅 Cashflow Semanal")
    df_ext = st.session_state.df_extracto
    df_cf  = st.session_state.df_cashflow
    if df_ext.empty:
        st.info("📥 Cargá un extracto bancario en la página de Conciliación para ver la vista semanal.")
    else:
        df_sem = generar_resumen_semanal(df_ext, df_cf)
        if not df_sem.empty:
            fig_s = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
                row_heights=[0.6,0.4], subplot_titles=("Ingresos y Egresos por Semana","Saldo Acumulado"))
            semanas = df_sem["semana_label"].tolist()
            fig_s.add_trace(go.Bar(
                x=semanas, y=(df_sem["ingresos"]/1000).tolist(),
                name="🟢 Ingresos Semana", marker_color=C_ING, opacity=0.85,
                hovertemplate="<b>%{x}</b><br>Ingresos: $%{y:.0f}K<extra></extra>",
            ), row=1,col=1)
            fig_s.add_trace(go.Bar(
                x=semanas, y=(df_sem["egresos"]/1000).tolist(),
                name="🔴 Egresos Semana", marker_color=C_EG, opacity=0.85,
                hovertemplate="<b>%{x}</b><br>Egresos: $%{y:.0f}K<extra></extra>",
            ), row=1,col=1)
            sc_colors = ["#DC2626" if s<SALDO_MINIMO_CRITICO/1000 else "#D97706" if s<SALDO_MINIMO_ALERTA/1000 else "#059669" for s in (df_sem["saldo_acum"]/1000).tolist()]
            fig_s.add_trace(go.Bar(x=semanas, y=(df_sem["saldo_acum"]/1000).tolist(), name="Saldo Acum.", marker_color=sc_colors, opacity=0.9), row=2,col=1)
            fig_s = plotly_layout(fig_s, 450)
            fig_s.update_layout(barmode="group")
            st.plotly_chart(fig_s, use_container_width=True)
            df_ss = df_sem.copy()
            for c in ["ingresos","egresos","resultado","saldo_acum"]: df_ss[c] = df_ss[c].apply(fmt_ars)
            st.dataframe(df_ss[["semana_label","ingresos","egresos","resultado","saldo_acum","movimientos","semaforo"]], hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════
# CONCILIACIÓN BANCARIA
# ══════════════════════════════════════════════════════════════════════
elif pagina == "🔄 Conciliación Bancaria":
    st.markdown("## 🔄 Conciliación Bancaria")
    cu1, cu2 = st.columns([2,1])
    with cu1:
        archivo = st.file_uploader("📥 Cargar extracto bancario (CSV / XLSX)", type=["csv","xlsx","xls"])
    with cu2:
        st.info("✅ Soporta: Nación · Galicia · BBVA · Santander · Macro · ICBC · Genérico")
        if st.button("🧪 Datos de muestra (demo)", use_container_width=True):
            import tempfile
            df_m = generar_extracto_muestra()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                df_m.to_csv(tmp.name, index=False); tmp_path = tmp.name
            df_p = parse_extracto(tmp_path, banco="nacion")
            st.session_state.df_extracto = df_p; recalcular_todo(); st.rerun()

    if archivo:
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(archivo.name)[1]) as tmp:
            tmp.write(archivo.read()); tmp_path = tmp.name
        with st.spinner("Procesando..."):
            df_p = parse_extracto(tmp_path, nombre_archivo=archivo.name)
        if df_p.empty: st.error("No se pudo leer el archivo.")
        else:
            st.session_state.df_extracto = conciliar_automatico(df_p, st.session_state.df_cashflow)
            recalcular_todo(); st.success(f"✅ {len(df_p)} movimientos de {df_p['banco'].iloc[0]}"); st.rerun()

    df_ext = st.session_state.df_extracto
    if not df_ext.empty:
        stats = estadisticas_extracto(df_ext)
        ck1,ck2,ck3,ck4 = st.columns(4)
        with ck1: st.metric("🏦 Banco", stats.get("banco","—"))
        with ck2: st.metric("📅 Período",
            f"{stats['fecha_inicio'].strftime('%d/%m') if stats.get('fecha_inicio') else '—'} — "
            f"{stats['fecha_fin'].strftime('%d/%m')   if stats.get('fecha_fin')   else '—'}")
        with ck3: st.metric("💚 Ingresos", fmt_ars(stats.get("ingresos_total",0)))
        with ck4: st.metric("❤️ Egresos",  fmt_ars(stats.get("egresos_total",0)))
        st.markdown("#### Movimientos del Extracto")
        cols_show = ["fecha_str","descripcion","importe","categoria","tipo"]
        if "estado_conciliacion" in df_ext.columns: cols_show.append("estado_conciliacion")
        st.dataframe(df_ext[cols_show], hide_index=True, use_container_width=True, height=420,
            column_config={"fecha_str":"Fecha","descripcion":st.column_config.TextColumn("Descripción",width="large"),
                "importe":st.column_config.NumberColumn("Importe $",format="$ %,.0f"),
                "categoria":"Categoría","tipo":"Tipo","estado_conciliacion":"Conciliación"})
    else:
        st.info("📥 Cargá un extracto bancario para ver la conciliación.")


# ══════════════════════════════════════════════════════════════════════
# FACTURAS Y COBRANZAS (AR)
# ══════════════════════════════════════════════════════════════════════
elif pagina == "📋 Facturas y Cobranzas":
    st.markdown("## 📋 Facturas y Cobranzas — Cuentas a Cobrar (AR)")
    df_fac = st.session_state.df_facturas
    kpis_ar = resumen_ar(df_fac) if not df_fac.empty else {}

    # KPIs AR
    if kpis_ar:
        ka1,ka2,ka3,ka4 = st.columns(4)
        with ka1: st.metric("🧾 Total Facturado",   fmt_millones(kpis_ar.get("total_emitido",0)))
        with ka2: st.metric("✅ Cobrado",            fmt_millones(kpis_ar.get("total_cobrado",0)),
                            f"{kpis_ar.get('pct_cobrado',0):.0f}%")
        with ka3: st.metric("⏳ Pendiente",          fmt_millones(kpis_ar.get("total_pendiente",0)))
        with ka4: st.metric("📅 DSO (días prom.)",   f"{kpis_ar.get('dso_dias',0):.0f} días")

    tab_f1, tab_f2, tab_f3, tab_f4 = st.tabs([
        "📋 Todas las facturas", "➕ Agregar factura",
        "📥 Importar CSV/Excel", "📈 Proyección cobranzas"
    ])

    with tab_f1:
        if not df_fac.empty:
            cols_f = ["numero_factura","cliente","importe_neto","condicion_pago",
                      "fecha_emision","fecha_vto_habil","mes_cobro_esperado",
                      "estado","importe_cobrado","linea_negocio"]
            df_show = df_fac[cols_f].copy()
            for c in ["importe_neto","importe_cobrado"]: df_show[c] = df_show[c].apply(lambda x: float(x) if x else 0)
            for c in ["fecha_emision","fecha_vto_habil"]:
                df_show[c] = df_show[c].apply(lambda d: d.strftime("%d/%m/%Y") if hasattr(d,"strftime") else str(d) if d else "")
            st.dataframe(df_show, hide_index=True, use_container_width=True, height=420,
                column_config={
                    "numero_factura": "N° Factura",
                    "cliente":        st.column_config.TextColumn("Cliente", width="medium"),
                    "importe_neto":   st.column_config.NumberColumn("Importe Neto $", format="$ %,.0f"),
                    "condicion_pago": "Condición",
                    "fecha_emision":  "Emisión",
                    "fecha_vto_habil":"Vto. Hábil",
                    "mes_cobro_esperado": "Mes Cobro",
                    "estado":         "Estado",
                    "importe_cobrado":st.column_config.NumberColumn("Cobrado $", format="$ %,.0f"),
                    "linea_negocio":  "Línea",
                })
        else:
            st.info("Sin facturas cargadas. Agregá una o importá desde CSV.")

    with tab_f2:
        st.markdown("**Nueva factura** — La fecha de vencimiento se calcula según la condición de pago")
        with st.form("form_factura"):
            ff1,ff2 = st.columns(2)
            with ff1:
                nro_f   = st.text_input("N° Factura *", placeholder="A-00001234")
                cli_f   = st.text_input("Cliente *", placeholder="Farmacia XYZ SA")
                imp_f   = st.number_input("Importe Bruto ($) *", min_value=0.0, step=10000.0, format="%.0f")
                cond_f  = st.selectbox("Condición de Pago *", ["contado","15","30","45","60","90","120"],
                                       index=2, help="Días para el cobro desde la emisión")
            with ff2:
                tipo_f  = st.selectbox("Tipo",   ["A","B","C"])
                linea_f = st.selectbox("Línea de Negocio", LINEAS)
                desc_f  = st.number_input("Descuento (%)", min_value=0.0, max_value=100.0, step=0.5)
                femi_f  = st.date_input("Fecha Emisión", value=date.today())
                cuit_f  = st.text_input("CUIT Cliente", placeholder="20-12345678-9")
            obs_f  = st.text_area("Observaciones", height=60)
            sub_f  = st.form_submit_button("✅ Agregar Factura", use_container_width=True, type="primary")

        if sub_f:
            if not nro_f or not cli_f or imp_f <= 0:
                st.error("Completar campos obligatorios (*)")
            else:
                df_nuevo = agregar_factura(
                    st.session_state.df_facturas, numero=nro_f, cliente=cli_f,
                    importe_bruto=imp_f, condicion_pago=cond_f,
                    fecha_emision=str(femi_f), tipo=tipo_f, cuit_cliente=cuit_f,
                    descuento_pct=desc_f, linea_negocio=linea_f, observaciones=obs_f,
                )
                st.session_state.df_facturas = df_nuevo
                guardar_facturas(df_nuevo); recalcular_todo()
                st.success(f"✅ Factura {nro_f} agregada"); st.rerun()

    with tab_f3:
        st.markdown("""
        **Importar desde sistema de facturación o SAP**

        El archivo debe tener columnas reconocibles como:
        `Numero`, `Cliente`, `Importe`, `Condicion` (o `Plazo`), `Fecha`

        Compatible con exportaciones de SAP SD, sistemas de facturación electrónica AFIP, y cualquier CSV/Excel.
        """)
        arch_fac = st.file_uploader("Seleccioná el archivo", type=["csv","xlsx","xls"], key="up_facturas")
        if arch_fac:
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(arch_fac.name)[1]) as tmp:
                tmp.write(arch_fac.read()); tmp_path = tmp.name
            with st.spinner("Importando facturas..."):
                df_imp = importar_facturas_csv(tmp_path)
            if not df_imp.empty:
                st.success(f"✅ {len(df_imp)} facturas importadas")
                st.session_state.df_facturas = pd.concat([st.session_state.df_facturas, df_imp], ignore_index=True)
                guardar_facturas(st.session_state.df_facturas); recalcular_todo(); st.rerun()
            else:
                st.error("No se pudieron leer facturas del archivo. Verificá el formato.")

        if st.button("🧪 Cargar facturas de muestra (demo)", use_container_width=True):
            st.session_state.df_facturas = generar_facturas_muestra()
            guardar_facturas(st.session_state.df_facturas); recalcular_todo(); st.rerun()

    with tab_f4:
        if not df_fac.empty:
            df_proy_cob = proyectar_cobranzas_desde_facturas(df_fac, AÑO)
            if not df_proy_cob.empty:
                st.markdown("#### Proyección de cobranzas desde facturas reales")
                fig_cob = go.Figure()
                fig_cob.add_trace(go.Bar(
                    x=df_proy_cob["mes_nombre"].apply(lambda m: m[:3]).tolist(),
                    y=(df_proy_cob["cobro_esperado"]/1000).tolist(),
                    name="Esperado", marker_color=C_PROY, opacity=0.8))
                fig_cob.add_trace(go.Bar(
                    x=df_proy_cob["mes_nombre"].apply(lambda m: m[:3]).tolist(),
                    y=(df_proy_cob["cobro_real"]/1000).tolist(),
                    name="Real cobrado", marker_color=C_ING, opacity=0.85))
                fig_cob = plotly_layout(fig_cob, 320)
                fig_cob.update_layout(barmode="group", yaxis_title="$K")
                st.plotly_chart(fig_cob, use_container_width=True)

                df_pc_show = df_proy_cob[df_proy_cob["cobro_esperado"]>0].copy()
                df_pc_show["cobro_esperado"] = df_pc_show["cobro_esperado"].apply(fmt_ars)
                df_pc_show["cobro_real"]     = df_pc_show["cobro_real"].apply(fmt_ars)
                df_pc_show["pendiente"]      = df_pc_show["pendiente"].apply(fmt_ars)
                df_pc_show["pct_cobrado"]    = df_pc_show["pct_cobrado"].apply(lambda x: f"{x:.0f}%")
                st.dataframe(df_pc_show[["mes_nombre","cobro_esperado","cobro_real","pendiente","pct_cobrado","cant_facturas"]],
                    hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════
# BUDGET Y DESVÍOS
# ══════════════════════════════════════════════════════════════════════
elif pagina == "📈 Budget y Desvíos":
    st.markdown("## 📈 Budget Mensual y Análisis de Desvíos")
    budget   = st.session_state.budget
    df_fac   = st.session_state.df_facturas
    df_cob   = proyectar_cobranzas_desde_facturas(df_fac, AÑO) if not df_fac.empty else pd.DataFrame()

    tab_b1, tab_b2, tab_b3 = st.tabs(["📊 Comparativo", "✏️ Editar Budget", "📥 Importar Budget"])

    with tab_b1:
        df_comp = comparativo_budget_real(budget, df_fac if not df_fac.empty else None,
                                          df_cob if not df_cob.empty else None)
        # Fallback demo: si no hay budget/real cargado, mostramos desvíos simulados
        if df_comp.empty or ("tiene_datos" in df_comp.columns and not df_comp["tiene_datos"].any()):
            _mn = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
                   "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
            _estac = [0.92,0.90,1.06,1.00,1.05,1.12,1.18,1.15,1.02,1.04,1.06,1.10]
            _dv    = [-3,-6,4,-2,-9,-14,6,-4,-18,2,-7,3]
            _causas = {-18:"Faltante de stock en línea respiratoria durante el pico invernal",
                       -14:"Baja de una cadena de farmacias grande y demora de cobranza de PAMI",
                       -9:"Caída de demanda estacional y presión de precios en genéricos",
                       -7:"Rechazo de cheques de dos clientes mayoristas",
                       -6:"Arranque de año lento, reposición del canal por debajo de lo previsto",
                       -4:"Menor rotación en dermocosmética",-3:"Desvío dentro de tolerancia",
                       -2:"Desvío dentro de tolerancia"}
            _base = 19_000e6
            rows=[]
            for mn,es,dv in zip(_mn,_estac,_dv):
                bud = _base*es; ven = bud*(1+dv/100); cob = ven*(0.86 if dv>=0 else 0.80)
                rows.append({"mes_nombre":mn,"budget":bud,"venta_real":ven,"cobro_real":cob,
                             "tiene_datos":True,"dev_venta_pct":dv,
                             "causa_raiz":_causas.get(dv,"En línea con lo presupuestado" if dv>=0 else "Desvío en revisión")})
            df_comp = pd.DataFrame(rows)
            st.info("Budget de demostración con desvíos simulados. Cargá el budget real en «Editar Budget» o «Importar Budget».")
        if not df_comp.empty:
            # Gráfico comparativo
            df_c_datos = df_comp[df_comp["tiene_datos"]]
            if not df_c_datos.empty:
                fig_b = go.Figure()
                meses_b = df_c_datos["mes_nombre"].apply(lambda m: m[:3]).tolist()
                bud_k = (df_c_datos["budget"]/1e6).tolist()
                ven_k = (df_c_datos["venta_real"]/1e6).tolist()
                cob_k = (df_c_datos["cobro_real"]/1e6).tolist()
                fig_b.add_trace(go.Bar(x=meses_b, y=bud_k,
                    name="Budget", marker_color=C_PROY, opacity=0.85,
                    text=[f"${v:,.0f}M" for v in bud_k], textposition="outside",
                    textfont=dict(size=10, color="#1F2937"),
                    hovertemplate="<b>%{x}</b><br>Budget: $%{y:,.0f}M<extra></extra>"))
                fig_b.add_trace(go.Bar(x=meses_b, y=ven_k,
                    name="Ventas reales", marker_color=C_ING, opacity=0.9,
                    text=[f"${v:,.0f}M" for v in ven_k], textposition="outside",
                    textfont=dict(size=10, color="#1F2937"),
                    hovertemplate="<b>%{x}</b><br>Ventas: $%{y:,.0f}M<extra></extra>"))
                fig_b.add_trace(go.Bar(x=meses_b, y=cob_k,
                    name="Cobranzas reales", marker_color=C_WARN, opacity=0.9,
                    text=[f"${v:,.0f}M" for v in cob_k], textposition="outside",
                    textfont=dict(size=10, color="#1F2937"),
                    hovertemplate="<b>%{x}</b><br>Cobrado: $%{y:,.0f}M<extra></extra>"))
                fig_b = plotly_layout(fig_b, 360)
                fig_b.update_layout(barmode="group", yaxis_title="MM$",
                    title=dict(text="Budget vs Ventas reales vs Cobranzas reales",
                               y=0.99, font=dict(size=13, color="#1F2937")))
                st.plotly_chart(fig_b, use_container_width=True)

            # Tabla con causa raíz
            st.markdown("#### Análisis de causa raíz del desvío")
            for _, r in df_comp.iterrows():
                if r["budget"] > 0:
                    pct = r["dev_venta_pct"]
                    color = "#FEE2E2" if pct < -15 else "#FEF3C7" if pct < -5 else "#D1FAE5" if pct > 5 else "#F3F4F6"
                    bcolor = "#DC2626" if pct < -15 else "#D97706" if pct < -5 else "#059669" if pct > 5 else "#6B7280"
                    st.markdown(
                        f'<div style="background:{color};border-left:4px solid {bcolor};'
                        f'padding:10px 14px;border-radius:6px;margin:3px 0;font-size:12px;color:#1F2937">'
                        f'<b>{r["mes_nombre"]:12}</b> | '
                        f'Budget: {fmt_ars(r["budget"])} | '
                        f'Venta: {fmt_ars(r["venta_real"])} | '
                        f'Desvío: {pct:+.1f}% | '
                        f'<i>{r["causa_raiz"]}</i></div>',
                        unsafe_allow_html=True)

    with tab_b2:
        st.markdown("**Editá el budget mes a mes** — Los cambios se guardan y recalculan automáticamente")
        with st.form("form_budget"):
            total_anual_b = st.number_input("Total Anual ($)", value=float(budget.get("total_anual",120_000_000)),
                                             step=1_000_000.0, format="%.0f")
            st.markdown("##### Budget mensual por línea de negocio ($)")
            cols_b = st.columns(4)
            nuevos_valores = {}
            meses_lista = [(m, nombre_mes(m)) for m in range(1, 13)]
            for idx, (mes, mes_n) in enumerate(meses_lista):
                col_idx = idx % 4
                with cols_b[col_idx]:
                    val_actual = float(budget["meses"][str(mes)].get("total", 0))
                    nuevo_val  = st.number_input(f"{mes_n[:3]}", value=val_actual, step=100_000.0,
                                                  format="%.0f", key=f"bud_{mes}")
                    nuevos_valores[mes] = nuevo_val
            sub_b = st.form_submit_button("💾 Guardar Budget", use_container_width=True, type="primary")

        if sub_b:
            for mes, val in nuevos_valores.items():
                budget = actualizar_mes(budget, mes, {"total": val})
            budget["total_anual"] = total_anual_b
            st.session_state.budget = budget
            guardar_budget(budget); recalcular_todo()
            st.success("✅ Budget actualizado y cashflow recalculado"); st.rerun()

    with tab_b3:
        st.markdown("""
        **Importar desde SAP o Excel** — Formato esperado: columnas `Mes`, `Total`
        y opcionalmente `Medicamentos`, `Cosmética`, etc.
        """)
        arch_b = st.file_uploader("Archivo de budget", type=["csv","xlsx","xls"], key="up_budget")
        if arch_b:
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(arch_b.name)[1]) as tmp:
                tmp.write(arch_b.read()); tmp_path = tmp.name
            budget_imp = importar_budget_csv(tmp_path, AÑO)
            st.session_state.budget = budget_imp
            guardar_budget(budget_imp); recalcular_todo()
            st.success(f"✅ Budget importado — Total: {fmt_ars(budget_imp['total_anual'])}"); st.rerun()


# ══════════════════════════════════════════════════════════════════════
# CHEQUES
# ══════════════════════════════════════════════════════════════════════
elif pagina == "🏦 Cheques y Pagarés":
    st.markdown("## 🏦 Cheques y Pagarés — Gestión con Día Hábil Automático")
    df_ch = st.session_state.df_cheques
    pend  = df_ch[df_ch["estado"]=="pendiente"] if not df_ch.empty else pd.DataFrame()
    al_ch = alertas_cheques(df_ch, date.today()) if not df_ch.empty else {}

    cc1,cc2,cc3,cc4 = st.columns(4)
    with cc1: st.metric("🔴 Urgente (hoy+vencidos)", fmt_ars(al_ch.get("total_urgente",0)))
    with cc2:
        p7 = al_ch.get("proximos7", pd.DataFrame())
        st.metric("🟡 Próximos 7 días", fmt_ars(p7["monto"].sum() if not p7.empty else 0))
    with cc3: st.metric("Total Pendiente", fmt_ars(pend["monto"].sum() if not pend.empty else 0))
    with cc4: st.metric("Cantidad Pendientes", len(pend))

    t1,t2,t3 = st.tabs(["📋 Todos los cheques","➕ Agregar cheque","📊 Resumen mensual"])

    with t1:
        if not df_ch.empty:
            cols_ch = ["numero","beneficiario","monto","fecha_vto_original","dia_semana_vto","fue_ajustado","fecha_vto_habil","mes_nombre","estado"]
            df_cs = df_ch[cols_ch].copy()
            df_cs["monto"] = df_cs["monto"].apply(lambda x: float(x) if x else 0)
            df_cs["fue_ajustado"] = df_cs["fue_ajustado"].apply(lambda x: "✅ Sí" if x else "No")
            for c in ["fecha_vto_original","fecha_vto_habil"]:
                df_cs[c] = df_cs[c].apply(lambda d: d.strftime("%d/%m/%Y") if hasattr(d,"strftime") else str(d) if d else "")
            st.dataframe(df_cs, hide_index=True, use_container_width=True, height=380,
                column_config={
                    "numero":"N° Cheque","beneficiario":st.column_config.TextColumn("Beneficiario",width="medium"),
                    "monto":st.column_config.NumberColumn("Monto $",format="$ %,.0f"),
                    "fecha_vto_original":"Vto. Original","dia_semana_vto":"Día",
                    "fue_ajustado":"Ajustado?","fecha_vto_habil":"Vto. Hábil Efectivo",
                    "mes_nombre":"Mes","estado":"Estado"})
        else:
            st.info("No hay cheques cargados.")

    with t2:
        with st.form("form_cheque"):
            c1_ch,c2_ch = st.columns(2)
            with c1_ch:
                num_ch   = st.text_input("N° Cheque *")
                benef_ch = st.text_input("Beneficiario *")
                monto_ch = st.number_input("Monto ($) *", min_value=0.0, step=1000.0, format="%.0f")
                banco_ch = st.selectbox("Banco emisor", ["Banco Nación","Banco Galicia","BBVA","Santander","Macro","ICBC"])
            with c2_ch:
                fvto_ch  = st.date_input("Fecha Vencimiento *")
                femi_ch  = st.date_input("Fecha Emisión", value=date.today())
                conc_ch  = st.text_input("Concepto")
                est_ch   = st.selectbox("Estado", ["pendiente","cobrado","rechazado"])
            obs_ch = st.text_area("Observaciones", height=60)
            sub_ch = st.form_submit_button("✅ Agregar Cheque", use_container_width=True, type="primary")
        if sub_ch:
            if not num_ch or not benef_ch or monto_ch<=0: st.error("Completar campos obligatorios (*)")
            else:
                df_ch_n = agregar_cheque(st.session_state.df_cheques, numero=num_ch, beneficiario=benef_ch,
                    monto=monto_ch, fecha_vto=str(fvto_ch), concepto=conc_ch, fecha_emision=str(femi_ch),
                    estado=est_ch, banco_emisor=banco_ch, observaciones=obs_ch)
                st.session_state.df_cheques = df_ch_n
                guardar_cheques(df_ch_n); recalcular_todo()
                st.success(f"✅ Cheque N°{num_ch} agregado"); st.rerun()

    with t3:
        res_ch = resumen_mensual_cheques(df_ch)
        if not res_ch.empty:
            fig_ch = go.Figure(go.Bar(
                x=res_ch["mes_nombre"].apply(lambda m: m[:3]).tolist(),
                y=(res_ch["total_cheques"]/1000).tolist(),
                marker_color=C_EG, opacity=0.85,
                text=[f"${v:.0f}K" for v in (res_ch["total_cheques"]/1000).tolist()],
                textposition="outside"))
            fig_ch = plotly_layout(fig_ch, 300)
            fig_ch.update_layout(title="Total Cheques por Mes ($K)", yaxis_title="$K")
            st.plotly_chart(fig_ch, use_container_width=True)
            df_rs = res_ch.copy()
            df_rs["total_cheques"] = df_rs["total_cheques"].apply(fmt_ars)
            st.dataframe(df_rs[["mes_nombre","total_cheques","cantidad"]], hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════
# PARÁMETROS
# ══════════════════════════════════════════════════════════════════════
elif pagina == "⚙️ Parámetros":
    st.markdown("## ⚙️ Parámetros del Cashflow")
    if not tiene_permiso("editar"):
        st.warning("🔒 Tu rol solo permite lectura. Contactá al administrador para editar parámetros.")
        st.stop()
    st.info("Modificá los parámetros y presioná **Recalcular** para actualizar todos los módulos.")
    params = st.session_state.params
    with st.form("form_params"):
        st.markdown("### 💰 Ingresos y Saldo Inicial")
        pp1,pp2 = st.columns(2)
        with pp1:
            budget_an = st.number_input("Budget Anual ($)", value=float(params.budget_anual), step=1_000_000.0, format="%.0f")
            saldo_ini = st.number_input("Saldo Inicial Enero ($)", value=float(params.saldo_inicial), step=100_000.0, format="%.0f")
        with pp2:
            st.info(f"Umbrales configurados en config.py:\n- Crítico: {fmt_ars(SALDO_MINIMO_CRITICO)}\n- Alerta: {fmt_ars(SALDO_MINIMO_ALERTA)}")

        st.markdown("### 👥 Sueldos y Cargas")
        ps1,ps2,ps3 = st.columns(3)
        with ps1: sueldos = st.number_input("Sueldos Brutos ($)", value=float(params.sueldos_brutos), step=10_000.0, format="%.0f")
        with ps2: cargas  = st.number_input("Cargas Soc. Base (Jun/Dic ×1.5)", value=float(params.cargas_sociales_base), step=5_000.0, format="%.0f")
        with ps3: art     = st.number_input("ART ($)", value=float(params.art), step=1_000.0, format="%.0f")

        st.markdown("### 🏛️ Impuestos")
        pi1,pi2,pi3 = st.columns(3)
        with pi1: iva   = st.number_input("IVA ($)", value=float(params.iva_mensual), step=5_000.0, format="%.0f")
        with pi2: iibb  = st.number_input("IIBB ($)", value=float(params.iibb_mensual), step=2_000.0, format="%.0f")
        with pi3: ganan = st.number_input("Ganancias ($)", value=float(params.ganancias_mensual), step=2_000.0, format="%.0f")

        st.markdown("### 📦 Gastos Fijos")
        pg1,pg2,pg3 = st.columns(3)
        with pg1:
            alq  = st.number_input("Alquiler ($)", value=float(params.alquiler), step=5_000.0, format="%.0f")
            serv = st.number_input("Servicios ($)", value=float(params.servicios), step=2_000.0, format="%.0f")
        with pg2:
            seg  = st.number_input("Seguros ($)", value=float(params.seguros), step=1_000.0, format="%.0f")
            hon  = st.number_input("Honorarios ($)", value=float(params.honorarios), step=5_000.0, format="%.0f")
        with pg3:
            otros = st.number_input("Otros Fijos ($)", value=float(params.otros_fijos), step=5_000.0, format="%.0f")
            pct_p = st.number_input("% Proveedores/Ventas", value=float(params.pct_proveedores_ventas), min_value=0.0, max_value=1.0, step=0.01, format="%.2f")

        st.markdown("### 🏦 Planes AFIP")
        pa1,pa2,pa3 = st.columns(3)
        with pa1: plan1 = st.number_input("Plan AFIP #1 ($)", value=float(params.plan_afip_1), step=1_000.0, format="%.0f")
        with pa2: plan2 = st.number_input("Plan AFIP #2 ($)", value=float(params.plan_afip_2), step=1_000.0, format="%.0f")
        with pa3: plan3 = st.number_input("Plan AFIP #3 ($)", value=float(params.plan_afip_3), step=1_000.0, format="%.0f")

        sub_p = st.form_submit_button("🔄 Recalcular Cashflow", use_container_width=True, type="primary")

    if sub_p:
        p = st.session_state.params
        p.budget_anual=budget_an; p.saldo_inicial=saldo_ini; p.sueldos_brutos=sueldos
        p.cargas_sociales_base=cargas; p.art=art; p.iva_mensual=iva; p.iibb_mensual=iibb
        p.ganancias_mensual=ganan; p.alquiler=alq; p.servicios=serv; p.seguros=seg
        p.honorarios=hon; p.otros_fijos=otros; p.pct_proveedores_ventas=pct_p
        p.plan_afip_1=plan1; p.plan_afip_2=plan2; p.plan_afip_3=plan3
        import json as _json
        _cfg_path = os.path.join(os.path.dirname(__file__), "data", "params_config.json")
        os.makedirs(os.path.dirname(_cfg_path), exist_ok=True)
        _cfg_data = {k: getattr(st.session_state.params, k) for k in vars(st.session_state.params) if not k.startswith("_") and k != "prestamos"}
        _json.dump(_cfg_data, open(_cfg_path,"w"), indent=2)
        recalcular_todo()
        st.success("✅ Parámetros guardados y cashflow recalculado"); st.rerun()


# ══════════════════════════════════════════════════════════════════════
# USUARIOS
# ══════════════════════════════════════════════════════════════════════
elif pagina == "👥 Usuarios":
    st.markdown("## 👥 Gestión de Usuarios")
    if not tiene_permiso("usuarios"):
        st.warning("🔒 Solo los administradores pueden gestionar usuarios.")
        st.stop()

    tab_u1, tab_u2, tab_u3 = st.tabs(["👥 Usuarios actuales","➕ Agregar usuario","🔑 Cambiar contraseña"])

    with tab_u1:
        usuarios = listar_usuarios()
        df_u = pd.DataFrame(usuarios)
        if not df_u.empty:
            st.dataframe(df_u, hide_index=True, use_container_width=True,
                column_config={
                    "username":     "Usuario",
                    "nombre":       "Nombre",
                    "rol":          "Rol",
                    "email":        "Email",
                    "activo":       st.column_config.CheckboxColumn("Activo"),
                    "ultimo_login": "Último login",
                })
        st.markdown("""
        **Credenciales por defecto:**
        | Usuario | Contraseña | Rol |
        |---------|-----------|-----|
        | admin | admin2025 | Admin — acceso total |
        | finanzas | finanzas2025 | Analista — editar y exportar |
        | readonly | readonly2025 | Solo lectura |

        ⚠️ **Cambiar las contraseñas por defecto antes de usar en producción.**
        """)

    with tab_u2:
        with st.form("form_usuario"):
            fu1,fu2 = st.columns(2)
            with fu1:
                new_user = st.text_input("Usuario (sin espacios, minúsculas)")
                new_pass = st.text_input("Contraseña inicial", type="password")
                new_rol  = st.selectbox("Rol", ["readonly","analista","admin"])
            with fu2:
                new_nom  = st.text_input("Nombre completo")
                new_mail = st.text_input("Email corporativo")
            sub_u = st.form_submit_button("✅ Crear Usuario", use_container_width=True, type="primary")
        if sub_u:
            if not new_user or not new_pass or not new_nom:
                st.error("Completar todos los campos")
            else:
                ok, msg = agregar_usuario(new_user, new_pass, new_rol, new_nom, new_mail)
                if ok: st.success(msg)
                else:  st.error(msg)

    with tab_u3:
        with st.form("form_cambiar_pass"):
            cp_user = st.text_input("Usuario a modificar")
            cp_pass = st.text_input("Nueva contraseña", type="password")
            cp_conf = st.text_input("Confirmar contraseña", type="password")
            sub_cp  = st.form_submit_button("🔑 Cambiar Contraseña", use_container_width=True)
        if sub_cp:
            if cp_pass != cp_conf: st.error("Las contraseñas no coinciden")
            elif len(cp_pass) < 8:  st.error("La contraseña debe tener al menos 8 caracteres")
            elif cambiar_password(cp_user, cp_pass): st.success(f"✅ Contraseña de '{cp_user}' actualizada")
            else: st.error("Usuario no encontrado")


# ══════════════════════════════════════════════════════════════════════
# EXPORTAR
# ══════════════════════════════════════════════════════════════════════
elif pagina == "📤 Exportar":
    st.markdown("## 📤 Exportar Reportes")
    if not tiene_permiso("exportar"):
        st.warning("🔒 Tu rol no tiene permiso para exportar. Contactá al administrador.")
        st.stop()

    df_cf  = st.session_state.df_cashflow
    df_ext = st.session_state.df_extracto

    ce1, ce2 = st.columns(2)
    with ce1:
        st.markdown("### 📊 Excel Completo")
        st.markdown("Incluye:\n- Cashflow mensual completo\n- Extracto bancario categorizado\n- Formato profesional con estilos")
        if st.button("⬇️ Generar Excel", use_container_width=True, type="primary"):
            with st.spinner("Generando..."):
                path_xl = exportar_excel(df_cf, df_ext if not df_ext.empty else None)
            with open(path_xl,"rb") as f:
                st.download_button("📥 Descargar Excel", data=f.read(),
                    file_name=os.path.basename(path_xl),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True)

    with ce2:
        st.markdown("### 📋 CSV por módulo")
        if not df_cf.empty:
            st.download_button("⬇️ Cashflow Mensual (CSV)", data=df_cf.to_csv(index=False),
                file_name=f"cashflow_{AÑO}.csv", mime="text/csv", use_container_width=True)
        if not df_ext.empty:
            st.download_button("⬇️ Extracto Bancario (CSV)", data=df_ext.to_csv(index=False),
                file_name="extracto.csv", mime="text/csv", use_container_width=True)
        df_fac = st.session_state.df_facturas
        if not df_fac.empty:
            st.download_button("⬇️ Facturas AR (CSV)", data=df_fac.to_csv(index=False),
                file_name="facturas.csv", mime="text/csv", use_container_width=True)
        df_ch = st.session_state.df_cheques
        if not df_ch.empty:
            st.download_button("⬇️ Cheques (CSV)", data=df_ch.to_csv(index=False),
                file_name="cheques.csv", mime="text/csv", use_container_width=True)

    st.divider()
    st.markdown("### 📈 Estado del sistema")
    ce3,ce4,ce5,ce6 = st.columns(4)
    with ce3: st.metric("Meses con datos reales", len(df_cf[df_cf.get("tiene_real",False)==True]) if not df_cf.empty and "tiene_real" in df_cf.columns else 0)
    with ce4: st.metric("Movimientos extracto",   len(df_ext))
    with ce5: st.metric("Facturas AR",             len(st.session_state.df_facturas))
    with ce6: st.metric("Cheques cargados",        len(st.session_state.df_cheques))


# ══════════════════════════════════════════════════════════════════════
# PÁGINA: DEUDA E IMPUESTOS
# ══════════════════════════════════════════════════════════════════════
elif pagina == "🏛️ Deuda e Impuestos":
    st.markdown("## 🏛️ Deuda e Impuestos — Préstamos · AFIP · Tasas · Rollover")

    prestamos   = st.session_state.prestamos
    planes_afip = st.session_state.planes_afip
    config_imp  = st.session_state.config_imp
    tasas_ref   = st.session_state.tasas_ref
    df_ext      = st.session_state.df_extracto

    # ── Calcular vencimientos + conciliación con extracto ──
    df_venc = proyectar_vencimientos_impuestos(config_imp, AÑO)
    if not df_ext.empty and not df_venc.empty:
        df_venc = conciliar_impuestos_con_extracto(df_venc, df_ext, config_imp)
    st.session_state.df_vencimientos = df_venc

    # ── KPIs deuda ──────────────────────────────────────────────────
    cft = costo_financiero_total(prestamos, planes_afip)
    k1,k2,k3,k4,k5 = st.columns(5)
    with k1: st.metric("🏦 Deuda Bancos",    fmt_millones(cft.get("total_deuda_bancos",0)))
    with k2: st.metric("🏛️ Deuda AFIP",      fmt_millones(cft.get("total_deuda_afip",0)))
    with k3: st.metric("💸 Deuda Total",      fmt_millones(cft.get("total_deuda",0)))
    with k4: st.metric("📅 Cuota Mens. Total", fmt_ars(cft.get("cuota_mensual_total",0)))
    with k5: st.metric("📊 TNA Pond.",         f"{cft.get('tna_promedio_ponderada',0):.1f}%")

    st.markdown("---")

    tab_d1, tab_d2, tab_d3, tab_d4, tab_d5, tab_d6 = st.tabs([
        "🏦 Préstamos",
        "🏛️ Planes AFIP",
        "📋 Vencimientos Impositivos",
        "📊 Tasas y Rollover",
        "📅 Calendario Vencimientos",
        "➕ Cargar Datos",
    ])

    # ── TAB 1: PRÉSTAMOS ────────────────────────────────────────────
    with tab_d1:
        if not prestamos:
            st.info("📥 No hay préstamos cargados. Ir a la pestaña **➕ Cargar Datos**.")
        else:
            for p in [x for x in prestamos if x.get("estado")=="vigente"]:
                tna  = float(p.get("tna",0))
                tea  = float(p.get("tea",0))
                cap  = float(p.get("capital_vigente", p.get("capital_original",0)))
                cuota= float(p.get("cuota_mensual",0))
                cpag = int(p.get("cuotas_pagadas",0))
                ctot = int(p.get("cuotas_totales",0))
                pct_avance = cpag/ctot*100 if ctot>0 else 0

                with st.expander(f"🏦 {p.get('banco','')} — {p.get('descripcion','')} — {fmt_ars(cap)}", expanded=False):
                    c1,c2,c3,c4 = st.columns(4)
                    with c1:
                        st.metric("Capital Vigente",  fmt_ars(cap))
                        st.metric("TNA",              f"{tna:.1f}%")
                    with c2:
                        st.metric("TEA",              f"{tea:.1f}%")
                        st.metric("Cuota Mensual",    fmt_ars(cuota))
                    with c3:
                        st.metric("Cuotas Pagadas",   f"{cpag}/{ctot}")
                        st.metric("Vto. Final",       str(p.get("fecha_vencimiento_final","—"))[:10])
                    with c4:
                        st.metric("Día Débito",       f"Día {p.get('dia_debito',25)}")
                        st.metric("Garantía",         p.get("garantia","—") or "Sin garantía")

                    st.progress(int(pct_avance), text=f"Avance: {pct_avance:.0f}% — {ctot-cpag} cuotas restantes")

                    # Cronograma próximas 6 cuotas
                    st.markdown("**Próximas 6 cuotas:**")
                    cron = cronograma_prestamo(p, meses=6)
                    if not cron.empty:
                        cron_show = cron.copy()
                        for c_col in ["capital_amort","interes","total_cuota","capital_rest"]:
                            cron_show[c_col] = cron_show[c_col].apply(fmt_ars)
                        st.dataframe(cron_show[["cuota_nro","fecha","capital_amort","interes","total_cuota","capital_rest"]],
                            hide_index=True, use_container_width=True,
                            column_config={"cuota_nro":"N°","fecha":"Fecha","capital_amort":"Capital",
                                "interes":"Interés","total_cuota":"Total Cuota","capital_rest":"Saldo Rest."})

            # Resumen mensual préstamos
            st.markdown("#### 📊 Cuotas por Mes — Todos los Préstamos")
            res_p = resumen_cuotas_mensual(prestamos, AÑO)
            if not res_p.empty and res_p["total_cuotas"].sum() > 0:
                fig_p = go.Figure()
                fig_p.add_trace(go.Bar(
                    x=res_p["mes_nombre"].apply(lambda m: m[:3]).tolist(),
                    y=(res_p["total_cuotas"]/1000).tolist(),
                    marker_color="#2E75B6", opacity=0.85,
                    text=[f"${v:.0f}K" if v>0 else "" for v in (res_p["total_cuotas"]/1000).tolist()],
                    textposition="outside", name="Cuotas Bancos"))
                fig_p.update_layout(height=280, plot_bgcolor="white", paper_bgcolor="white",
                    title="Total cuotas bancarias por mes ($K)", yaxis_title="$K",
                    margin=dict(t=46,b=24), font=dict(size=11, color="#1F2937"))
                st.plotly_chart(fig_p, use_container_width=True)

    # ── TAB 2: PLANES AFIP ──────────────────────────────────────────
    with tab_d2:
        if not planes_afip:
            st.info("📥 No hay planes AFIP cargados. Ir a la pestaña **➕ Cargar Datos**.")
        else:
            for p in [x for x in planes_afip if x.get("estado")=="vigente"]:
                deuda  = float(p.get("deuda_vigente", p.get("deuda_original",0)))
                cuota  = float(p.get("cuota_mensual",0))
                cpag   = int(p.get("cuotas_pagadas",0))
                ctot   = int(p.get("cuotas_totales",0))
                tasa_m = float(p.get("tasa_interes_mensual",0))
                pct_av = cpag/ctot*100 if ctot>0 else 0

                with st.expander(f"📋 {p.get('rg','')} — {p.get('impuesto','')} — {p.get('tipo','').upper()} — {fmt_ars(deuda)}", expanded=False):
                    c1,c2,c3,c4 = st.columns(4)
                    with c1:
                        st.metric("Deuda Vigente",    fmt_ars(deuda))
                        st.metric("Tasa Mensual",     f"{tasa_m:.1f}%")
                    with c2:
                        st.metric("Cuota Mensual",    fmt_ars(cuota))
                        st.metric("N° Plan",          p.get("numero_plan","—"))
                    with c3:
                        st.metric("Cuotas Pagadas",   f"{cpag}/{ctot}")
                        st.metric("Vto. Final",       str(p.get("fecha_vencimiento_final","—"))[:10])
                    with c4:
                        st.metric("Día Vencimiento",  f"Día {p.get('dia_vencimiento',16)}")
                        st.metric("Tipo",             p.get("tipo","—").capitalize())

                    st.progress(int(pct_av), text=f"Avance: {pct_av:.0f}% — {ctot-cpag} cuotas restantes")
                    if p.get("observaciones"):
                        st.caption(f"Obs: {p['observaciones']}")

            # Resumen mensual AFIP
            st.markdown("#### 📊 Cuotas AFIP por Mes")
            res_a = resumen_cuotas_afip_mensual(planes_afip, AÑO)
            if not res_a.empty and res_a["total_cuotas"].sum() > 0:
                fig_a = go.Figure(go.Bar(
                    x=res_a["mes_nombre"].apply(lambda m: m[:3]).tolist(),
                    y=(res_a["total_cuotas"]/1e6).tolist(),
                    marker_color="#D97706", opacity=0.9,
                    text=[f"${v:,.0f}M" if v>0 else "" for v in (res_a["total_cuotas"]/1e6).tolist()],
                    textposition="outside", textfont=dict(color="#1F2937"), name="Cuotas AFIP"))
                fig_a.update_layout(height=280, plot_bgcolor="white", paper_bgcolor="white",
                    title="Cuotas planes AFIP por mes (MM$)", yaxis_title="MM$",
                    margin=dict(t=46,b=24), font=dict(size=11, color="#1F2937"))
                st.plotly_chart(fig_a, use_container_width=True)

    # ── TAB 3: VENCIMIENTOS IMPOSITIVOS ─────────────────────────────
    with tab_d3:
        st.markdown("**Proyectado vs Abonado Real** — Los pagos se concilian automáticamente con el extracto bancario cargado")

        if df_venc.empty:
            st.info("Calculando vencimientos...")
        else:
            # KPIs conciliación
            pagados   = df_venc[df_venc["estado"].str.startswith("✅", na=False)]
            vencidos  = df_venc[df_venc["estado"].str.contains("Vencido", na=False)]
            desvios   = df_venc[df_venc["estado"].str.startswith("⚠️", na=False)]
            pendientes= df_venc[df_venc["estado"].str.contains("Pendiente|pendiente", na=False)]

            ki1,ki2,ki3,ki4 = st.columns(4)
            with ki1: st.metric("✅ Pagados",       len(pagados),  f"{fmt_ars(pagados['monto_real'].sum())}")
            with ki2: st.metric("🔴 Vencidos",      len(vencidos), f"{fmt_ars(vencidos['monto_proy'].sum())}")
            with ki3: st.metric("⚠️ Con Desvío",    len(desvios))
            with ki4: st.metric("🕐 Pendientes",    len(pendientes))

            # Filtro por mes
            mes_imp = st.selectbox("Filtrar por mes", ["Todos"] + [nombre_mes(m) for m in range(1,13)], key="mes_imp")
            if mes_imp != "Todos":
                df_show_imp = df_venc[df_venc["mes_nombre"] == mes_imp]
            else:
                df_show_imp = df_venc

            df_imp_disp = df_show_imp.copy()
            df_imp_disp["fecha_vto"]  = df_imp_disp["fecha_vto"].apply(
                lambda d: d.strftime("%d/%m/%Y") if hasattr(d,"strftime") else str(d)[:10])
            df_imp_disp["monto_proy"] = df_imp_disp["monto_proy"].apply(fmt_ars)
            df_imp_disp["monto_real"] = df_imp_disp["monto_real"].apply(lambda x: fmt_ars(x) if x>0 else "—")
            df_imp_disp["diferencia"] = df_imp_disp["diferencia"].apply(lambda x: fmt_ars(x) if x!=0 else "—")

            st.dataframe(df_imp_disp[["mes_nombre","impuesto","fecha_vto","monto_proy","monto_real","diferencia","estado","frecuencia"]],
                hide_index=True, use_container_width=True, height=420,
                column_config={
                    "mes_nombre": "Mes", "impuesto": "Impuesto",
                    "fecha_vto": "Fecha Vto.", "monto_proy": "Proyectado",
                    "monto_real": "Real Pagado", "diferencia": "Diferencia",
                    "estado": "Estado", "frecuencia": "Frecuencia",
                })

            # Gráfico comparativo proyectado vs real por impuesto
            res_imp = resumen_impuestos_mensual(df_venc)
            if not res_imp.empty:
                fig_imp = go.Figure()
                fig_imp.add_trace(go.Bar(
                    x=res_imp["mes_nombre"].apply(lambda m: m[:3]).tolist(),
                    y=(res_imp["total_proyectado"]/1e6).tolist(),
                    name="Proyectado", marker_color="#2E75B6", opacity=0.8))
                fig_imp.add_trace(go.Bar(
                    x=res_imp["mes_nombre"].apply(lambda m: m[:3]).tolist(),
                    y=(res_imp["total_real"]/1e6).tolist(),
                    name="Real Pagado", marker_color="#059669", opacity=0.9))
                fig_imp.update_layout(height=280, barmode="group", plot_bgcolor="white",
                    paper_bgcolor="white", title="Impuestos: Proyectado vs Real (MM$)",
                    yaxis_title="MM$", margin=dict(t=46,b=24), font=dict(size=11, color="#1F2937"))
                st.plotly_chart(fig_imp, use_container_width=True)

    # ── TAB 4: TASAS Y ROLLOVER ─────────────────────────────────────
    with tab_d4:
        col_t1, col_t2 = st.columns([1.2, 1])

        with col_t1:
            st.markdown("#### 📊 Análisis de Rollover — ¿Conviene Refinanciar?")
            if prestamos:
                df_roll = analisis_rollover(prestamos, tasas_ref)
                if not df_roll.empty:
                    # Gráfico comparativo TNA actual vs mercado
                    fig_roll = go.Figure()
                    fig_roll.add_trace(go.Bar(
                        x=df_roll["banco"].tolist(),
                        y=df_roll["tna_actual"].tolist(),
                        name="TNA Actual", marker_color="#DC2626", opacity=0.85,
                        text=[f"{v:.1f}%" for v in df_roll["tna_actual"].tolist()],
                        textposition="outside"))
                    tna_mkt = float(tasas_ref.get("tasas_bcra",{}).get("prestamos_pyme", 55.0))
                    fig_roll.add_hline(y=tna_mkt, line_dash="dash", line_color="#059669",
                        annotation_text=f"Tasa mercado PyME: {tna_mkt:.1f}%",
                        annotation_position="right")
                    fig_roll.update_layout(height=280, plot_bgcolor="white", paper_bgcolor="white",
                        title="TNA Préstamos vs Tasa de Mercado",
                        yaxis_title="TNA %", margin=dict(t=46,b=24), font=dict(size=11, color="#1F2937"))
                    st.plotly_chart(fig_roll, use_container_width=True)

                    # Tabla rollover
                    st.dataframe(df_roll[[
                        "banco","tna_actual","tea_actual","tna_mercado",
                        "diferencia_tna","cuota_actual","cuota_nueva_est",
                        "cuotas_restantes","ahorro_rollover","recomendacion"
                    ]], hide_index=True, use_container_width=True,
                    column_config={
                        "banco": "Banco",
                        "tna_actual": st.column_config.NumberColumn("TNA Actual %", format="%.1f%%"),
                        "tea_actual": st.column_config.NumberColumn("TEA %", format="%.1f%%"),
                        "tna_mercado": st.column_config.NumberColumn("TNA Mercado %", format="%.1f%%"),
                        "diferencia_tna": st.column_config.NumberColumn("Dif. TNA %", format="%+.1f%%"),
                        "cuota_actual": st.column_config.NumberColumn("Cuota Actual $", format="$ %,.0f"),
                        "cuota_nueva_est": st.column_config.NumberColumn("Cuota Nueva Est. $", format="$ %,.0f"),
                        "cuotas_restantes": "Cuotas Rest.",
                        "ahorro_rollover": st.column_config.NumberColumn("Ahorro/Costo Rollover $", format="$ %,.0f"),
                        "recomendacion": "Recomendación",
                    })
            else:
                st.info("Cargá préstamos para ver el análisis de rollover.")

        with col_t2:
            st.markdown("#### 🏦 Tasas de Referencia del Mercado")
            tasas_bcra = tasas_ref.get("tasas_bcra", {})
            tasas_afip_r = tasas_ref.get("tasas_afip", {})

            st.markdown("**BCRA / Mercado**")
            for nombre_t, valor_t in tasas_bcra.items():
                label_t = nombre_t.replace("_"," ").title()
                col_ta, col_tv = st.columns([2,1])
                with col_ta: st.caption(label_t)
                with col_tv: st.caption(f"**{valor_t:.1f}% TNA**")

            st.markdown("---")
            st.markdown("**AFIP**")
            for nombre_t, valor_t in tasas_afip_r.items():
                label_t = nombre_t.replace("_"," ").title()
                col_ta, col_tv = st.columns([2,1])
                with col_ta: st.caption(label_t)
                with col_tv: st.caption(f"**{valor_t:.1f}% mensual**")

            st.markdown("---")
            st.caption(f"Última actualización: {tasas_ref.get('fecha_actualizacion','—')}")
            if st.button("✏️ Actualizar tasas de referencia", use_container_width=True):
                st.session_state["editar_tasas"] = True

            if st.session_state.get("editar_tasas"):
                with st.form("form_tasas"):
                    st.markdown("**Actualizar Tasas BCRA**")
                    nuevas_tasas = {}
                    for k, v in tasas_bcra.items():
                        nuevas_tasas[k] = st.number_input(k.replace("_"," ").title(),
                            value=float(v), step=0.5, format="%.1f", key=f"tasa_{k}")
                    nuevas_tasas_afip = {}
                    st.markdown("**Tasas AFIP**")
                    for k, v in tasas_afip_r.items():
                        nuevas_tasas_afip[k] = st.number_input(k.replace("_"," ").title(),
                            value=float(v), step=0.1, format="%.1f", key=f"tasa_afip_{k}")
                    sub_t = st.form_submit_button("💾 Guardar", use_container_width=True, type="primary")
                if sub_t:
                    from datetime import date as ddate
                    st.session_state.tasas_ref["tasas_bcra"]        = nuevas_tasas
                    st.session_state.tasas_ref["tasas_afip"]        = nuevas_tasas_afip
                    st.session_state.tasas_ref["fecha_actualizacion"] = str(ddate.today())
                    guardar_tasas_referencia(st.session_state.tasas_ref)
                    st.session_state["editar_tasas"] = False
                    st.success("✅ Tasas actualizadas"); st.rerun()

    # ── TAB 5: CALENDARIO VENCIMIENTOS ──────────────────────────────
    with tab_d5:
        st.markdown("#### 📅 Calendario Unificado de Vencimientos")
        st.caption("Incluye: cuotas de préstamos + cuotas AFIP + vencimientos impositivos")

        mes_cal = st.selectbox("Mes", range(1,13), format_func=nombre_mes,
                               index=date.today().month-1, key="mes_cal")

        eventos = []

        # Cuotas préstamos
        for p in [x for x in prestamos if x.get("estado")=="vigente"]:
            dia = int(p.get("dia_debito", 25))
            try:
                f = date(AÑO, mes_cal, min(dia,28))
                eventos.append({
                    "Fecha": f.strftime("%d/%m/%Y"), "Tipo": "🏦 Préstamo",
                    "Concepto": f"{p.get('banco','')} — {p.get('descripcion','')}",
                    "Monto": fmt_ars(float(p.get("cuota_mensual",0))),
                    "Estado": "Débito automático",
                })
            except: pass

        # Cuotas AFIP
        for p in [x for x in planes_afip if x.get("estado")=="vigente"]:
            dia = int(p.get("dia_vencimiento", 16))
            try:
                f = date(AÑO, mes_cal, min(dia,28))
                eventos.append({
                    "Fecha": f.strftime("%d/%m/%Y"), "Tipo": "🏛️ Plan AFIP",
                    "Concepto": f"{p.get('rg','')} — {p.get('impuesto','')}",
                    "Monto": fmt_ars(float(p.get("cuota_mensual",0))),
                    "Estado": "Transferencia bancaria",
                })
            except: pass

        # Impuestos del mes
        if not df_venc.empty:
            df_mes_imp = df_venc[df_venc["mes"] == mes_cal]
            for _, r in df_mes_imp.iterrows():
                try:
                    f = r["fecha_vto"]
                    f_str = f.strftime("%d/%m/%Y") if hasattr(f,"strftime") else str(f)[:10]
                except:
                    f_str = "—"
                eventos.append({
                    "Fecha": f_str, "Tipo": "📋 Impuesto",
                    "Concepto": r["impuesto"],
                    "Monto": fmt_ars(float(r["monto_proy"])),
                    "Estado": str(r.get("estado","pendiente")),
                })

        if eventos:
            df_eventos = pd.DataFrame(eventos).sort_values("Fecha")
            total_mes = sum(
                float(str(e["Monto"]).replace("$","").replace(".","").replace(",",".").replace(" ","").replace("-","0"))
                for e in eventos if e["Monto"] not in ("—","$ —")
            )
            st.markdown(f"**{nombre_mes(mes_cal)} {AÑO} — {len(eventos)} vencimientos | Total estimado: {fmt_ars(total_mes)}**")
            st.dataframe(df_eventos, hide_index=True, use_container_width=True,
                column_config={"Fecha":"Fecha","Tipo":"Tipo","Concepto":st.column_config.TextColumn("Concepto",width="large"),
                    "Monto":"Monto","Estado":"Estado"})
        else:
            st.info(f"No hay vencimientos cargados para {nombre_mes(mes_cal)}.")

    # ── TAB 6: CARGAR DATOS ─────────────────────────────────────────
    with tab_d6:
        col_cd1, col_cd2 = st.columns(2)

        with col_cd1:
            st.markdown("#### 🏦 Agregar Préstamo Bancario")
            with st.form("form_prestamo"):
                fp1,fp2 = st.columns(2)
                with fp1:
                    banco_p     = st.selectbox("Banco *", BANCOS_ARGENTINA)
                    desc_p      = st.text_input("Descripción *", placeholder="Capital de trabajo")
                    capital_p   = st.number_input("Capital Original ($) *", min_value=0.0, step=10000.0, format="%.0f")
                    tna_p       = st.number_input("TNA (%) *", min_value=0.0, max_value=999.0, step=0.5, format="%.1f")
                with fp2:
                    cuota_p     = st.number_input("Cuota Mensual ($) *", min_value=0.0, step=1000.0, format="%.0f")
                    cuotas_tot_p= st.number_input("Total Cuotas", min_value=1, max_value=120, value=24)
                    cuotas_pag_p= st.number_input("Cuotas Ya Pagadas", min_value=0, value=0)
                    dia_deb_p   = st.number_input("Día Débito", min_value=1, max_value=28, value=25)
                fprimer_p   = st.date_input("Fecha 1ra Cuota")
                garantia_p  = st.text_input("Garantía", placeholder="SGR / Sin garantía")
                obs_p       = st.text_area("Observaciones", height=50)
                sub_p_form  = st.form_submit_button("✅ Agregar Préstamo", use_container_width=True, type="primary")

            if sub_p_form:
                if not banco_p or capital_p <= 0 or tna_p <= 0:
                    st.error("Completar campos obligatorios (*)")
                else:
                    cap_vig = capital_p * (1 - cuotas_pag_p / cuotas_tot_p) if cuotas_tot_p > 0 else capital_p
                    st.session_state.prestamos = agregar_prestamo(
                        st.session_state.prestamos,
                        banco=banco_p, descripcion=desc_p,
                        capital_original=capital_p, capital_vigente=cap_vig,
                        tna=tna_p, cuota_mensual=cuota_p,
                        cuotas_totales=int(cuotas_tot_p), cuotas_pagadas=int(cuotas_pag_p),
                        fecha_primera_cuota=str(fprimer_p), dia_debito=int(dia_deb_p),
                        garantia=garantia_p, observaciones=obs_p, estado="vigente",
                    )
                    guardar_prestamos(st.session_state.prestamos)
                    st.success(f"✅ Préstamo {banco_p} agregado"); st.rerun()

        with col_cd2:
            st.markdown("#### 🏛️ Agregar Plan de Facilidades AFIP")
            with st.form("form_plan_afip"):
                fa1,fa2 = st.columns(2)
                with fa1:
                    rg_a     = st.text_input("RG / Resolución *", placeholder="RG 5678")
                    imp_a    = st.selectbox("Impuesto *", ["IVA","SIPA","Ganancias","IIBB","Autónomos","Varios"])
                    tipo_a   = st.selectbox("Tipo", ["moratoria","facilidades","plan_pagos"])
                    deuda_a  = st.number_input("Deuda Original ($) *", min_value=0.0, step=10000.0, format="%.0f")
                with fa2:
                    cuota_a  = st.number_input("Cuota Mensual ($) *", min_value=0.0, step=1000.0, format="%.0f")
                    ctot_a   = st.number_input("Total Cuotas", min_value=1, max_value=120, value=60)
                    cpag_a   = st.number_input("Cuotas Pagadas", min_value=0, value=0)
                    tasa_a   = st.number_input("Tasa Interés Mensual (%)", min_value=0.0, value=2.5, step=0.1, format="%.1f")
                nro_plan_a = st.text_input("Número de Plan AFIP")
                fprimer_a  = st.date_input("Fecha 1ra Cuota", key="fprimer_afip")
                sub_a_form = st.form_submit_button("✅ Agregar Plan AFIP", use_container_width=True, type="primary")

            if sub_a_form:
                if not rg_a or deuda_a <= 0:
                    st.error("Completar campos obligatorios (*)")
                else:
                    dvig = deuda_a * (1 - cpag_a/ctot_a) if ctot_a>0 else deuda_a
                    st.session_state.planes_afip = agregar_plan_afip(
                        st.session_state.planes_afip,
                        rg=rg_a, descripcion=f"Plan {rg_a} — {imp_a}",
                        tipo=tipo_a, impuesto=imp_a,
                        deuda_original=deuda_a, deuda_vigente=dvig,
                        tasa_interes_mensual=tasa_a,
                        cuota_mensual=cuota_a, cuotas_totales=int(ctot_a),
                        cuotas_pagadas=int(cpag_a),
                        fecha_primera_cuota=str(fprimer_a),
                        numero_plan=nro_plan_a, estado="vigente",
                    )
                    guardar_planes_afip(st.session_state.planes_afip)
                    st.success(f"✅ Plan {rg_a} agregado"); st.rerun()

        st.markdown("---")
        st.markdown("#### ⚙️ Configurar Montos Estimados de Impuestos Periódicos")
        st.caption("Estos montos se usan para la proyección y se comparan contra lo real del extracto.")
        with st.form("form_config_imp"):
            cols_imp = st.columns(3)
            nuevos_montos = {}
            for i, (clave, cfg) in enumerate(st.session_state.config_imp.items()):
                with cols_imp[i % 3]:
                    nuevo_m = st.number_input(
                        f"{cfg['nombre']} ($)",
                        value=float(cfg.get("monto_estimado", 0)),
                        step=1000.0, format="%.0f",
                        key=f"imp_{clave}",
                    )
                    nuevos_montos[clave] = nuevo_m
            sub_imp = st.form_submit_button("💾 Guardar Configuración", use_container_width=True)

        if sub_imp:
            for clave, monto in nuevos_montos.items():
                st.session_state.config_imp[clave]["monto_estimado"] = monto
            guardar_config_impuestos(st.session_state.config_imp)
            st.success("✅ Montos de impuestos actualizados"); st.rerun()

        st.markdown("---")
        if st.button("🧪 Cargar datos demo (préstamos + planes AFIP)", use_container_width=True):
            p_demo, a_demo = generar_datos_demo()
            st.session_state.prestamos  = p_demo
            st.session_state.planes_afip = a_demo
            guardar_prestamos(p_demo)
            guardar_planes_afip(a_demo)
            st.success("✅ Datos demo cargados"); st.rerun()


# ══════════════════════════════════════════════════════════════════════
# PÁGINA: POR UNIDAD DE NEGOCIO
# ══════════════════════════════════════════════════════════════════════
elif pagina == "🏢 Por Unidad de Negocio":
    st.markdown("## 🏢 Cashflow por Unidad de Negocio")
    st.caption("Distribución proporcional basada en % de participación histórica de cada línea")

    df_cf  = st.session_state.df_cashflow
    budget = st.session_state.budget

    if df_cf.empty:
        st.info("Calculando cashflow..."); recalcular_todo(); st.rerun()

    cf_por_un = generar_cf_por_unidad(df_cf, budget)

    # KPIs por unidad
    st.markdown("#### 📊 Resultado Anual por Unidad de Negocio")
    cols_un = st.columns(len(UNIDADES_NEGOCIO))
    for i, (unidad, config) in enumerate(UNIDADES_NEGOCIO.items()):
        df_u = cf_por_un[unidad]
        ing_anual = df_u["ing_proy"].sum()
        eg_anual  = df_u["eg_proy"].sum()
        res_anual = df_u["res_proy"].sum()
        with cols_un[i]:
            st.markdown(
                f'<div style="background:white;border:1px solid #E2E8F0;border-top:4px solid {config["color"]};'
                f'border-radius:10px;padding:14px;text-align:center">'
                f'<div style="font-size:11px;color:#64748B;font-weight:500;text-transform:uppercase">{unidad}</div>'
                f'<div style="font-size:20px;font-weight:700;color:#0F172A;margin:6px 0">{fmt_millones(ing_anual)}</div>'
                f'<div style="font-size:11px;color:{"#059669" if res_anual>0 else "#DC2626"}">'
                f'Resultado: {fmt_millones(res_anual)}</div>'
                f'<div style="font-size:10px;color:#64748B">{config["pct_ingresos"]*100:.0f}% del total</div>'
                f'</div>', unsafe_allow_html=True)

    st.markdown("---")

    # Tabs: General + por unidad
    tab_nombres = ["🌐 Vista General"] + [f"{u}" for u in UNIDADES_NEGOCIO.keys()]
    tabs_un = st.tabs(tab_nombres)

    with tabs_un[0]:
        # Gráfico stacked por unidad
        st.markdown("#### Ingresos por Unidad — Comparativo Mensual")
        fig_stack = go.Figure()
        colors_un = [v["color"] for v in UNIDADES_NEGOCIO.values()]
        for (unidad, config), color in zip(UNIDADES_NEGOCIO.items(), colors_un):
            df_u = cf_por_un[unidad]
            fig_stack.add_trace(go.Bar(
                x=df_u["mes_nombre"].apply(lambda m: m[:3]).tolist(),
                y=(df_u["ing_proy"]/1e6).tolist(),
                name=unidad, marker_color=color, opacity=0.85,
            ))
        fig_stack = plotly_layout(fig_stack, 360)
        fig_stack.update_layout(barmode="stack", title="Ingresos por Unidad ($M ARS)",
            yaxis_title="$M ARS")
        st.plotly_chart(fig_stack, use_container_width=True)

        # Tabla resumen
        resumen_un = []
        for unidad, config in UNIDADES_NEGOCIO.items():
            df_u = cf_por_un[unidad]
            resumen_un.append({
                "Unidad de Negocio": unidad,
                "Ingresos Anuales":  fmt_ars(df_u["ing_proy"].sum()),
                "Egresos Anuales":   fmt_ars(df_u["eg_proy"].sum()),
                "Resultado":         fmt_ars(df_u["res_proy"].sum()),
                "% Participación":   f"{config['pct_ingresos']*100:.0f}%",
            })
        st.dataframe(pd.DataFrame(resumen_un), hide_index=True, use_container_width=True)

    for i, (unidad, config) in enumerate(UNIDADES_NEGOCIO.items(), 1):
        with tabs_un[i]:
            df_u = cf_por_un[unidad]
            st.markdown(f"#### {unidad} — Cashflow Mensual")
            col_u1, col_u2, col_u3 = st.columns(3)
            with col_u1: st.metric("Ingresos Anuales", fmt_millones(df_u["ing_proy"].sum()))
            with col_u2: st.metric("Egresos Anuales",  fmt_millones(df_u["eg_proy"].sum()))
            with col_u3: st.metric("Resultado Neto",   fmt_millones(df_u["res_proy"].sum()))

            fig_u = make_subplots(rows=1, cols=2,
                subplot_titles=("Ingresos vs Egresos ($M)", "Resultado Acumulado ($M)"),
                horizontal_spacing=0.1)
            meses_u = df_u["mes_nombre"].apply(lambda m: m[:3]).tolist()
            fig_u.add_trace(go.Bar(x=meses_u, y=(df_u["ing_proy"]/1e6).tolist(),
                name="Ingresos", marker_color=config["color"], opacity=0.85), row=1,col=1)
            fig_u.add_trace(go.Bar(x=meses_u, y=(df_u["eg_proy"]/1e6).tolist(),
                name="Egresos", marker_color=C_EG, opacity=0.75), row=1,col=1)
            saldo_acum = df_u["res_proy"].cumsum().tolist()
            fig_u.add_trace(go.Scatter(x=meses_u, y=[s/1e6 for s in saldo_acum],
                mode="lines+markers", name="Acumulado",
                line=dict(color=config["color"], width=2),
                marker=dict(size=6)), row=1,col=2)
            fig_u = plotly_layout(fig_u, 320)
            fig_u.update_layout(barmode="group", showlegend=True)
            st.plotly_chart(fig_u, use_container_width=True)

            df_u_show = df_u.copy()
            for c in ["ing_proy","eg_proy","res_proy","budget_ing"]:
                df_u_show[c] = df_u_show[c].apply(fmt_ars)
            st.dataframe(df_u_show[["mes_nombre","ing_proy","eg_proy","res_proy","budget_ing"]],
                hide_index=True, use_container_width=True,
                column_config={"mes_nombre":"Mes","ing_proy":"Ingresos Proy.",
                    "eg_proy":"Egresos Proy.","res_proy":"Resultado","budget_ing":"Budget Ing."})


# ══════════════════════════════════════════════════════════════════════
# PÁGINA: INVERSIONES
# ══════════════════════════════════════════════════════════════════════
elif pagina == "💹 Inversiones":
    st.markdown("## 💹 Inversiones Proyectadas")
    st.caption("Proyectos de inversión, CapEx, inversiones financieras y otros desembolsos planificados")

    inversiones = st.session_state.inversiones

    # KPIs
    df_inv = pd.DataFrame(inversiones.get("items", []))
    if not df_inv.empty:
        total_inv     = float(df_inv["monto"].sum())
        inv_capex     = float(df_inv[df_inv["tipo"]=="Infraestructura"]["monto"].sum())
        inv_ti        = float(df_inv[df_inv["tipo"]=="TI/Sistemas"]["monto"].sum())
        inv_financ    = float(df_inv[df_inv["tipo"]=="Inversión financiera"]["monto"].sum())
        ki1,ki2,ki3,ki4 = st.columns(4)
        with ki1: st.metric("💰 Total Inversiones", fmt_millones(total_inv))
        with ki2: st.metric("🏗️ Infraestructura",   fmt_millones(inv_capex))
        with ki3: st.metric("💻 TI / Sistemas",     fmt_millones(inv_ti))
        with ki4: st.metric("📈 Financieras",       fmt_millones(inv_financ))

    tab_inv1, tab_inv2, tab_inv3 = st.tabs(["📋 Listado","📊 Gráficos","➕ Nueva Inversión"])

    with tab_inv1:
        if df_inv.empty:
            st.info("No hay inversiones cargadas.")
        else:
            df_inv_show = df_inv.copy()
            df_inv_show["monto"] = df_inv_show["monto"].apply(fmt_ars)
            st.dataframe(df_inv_show[["mes_nombre","descripcion","tipo","unidad_negocio","monto","estado","observaciones"]],
                hide_index=True, use_container_width=True,
                column_config={
                    "mes_nombre": "Mes", "descripcion": st.column_config.TextColumn("Descripción", width="large"),
                    "tipo": "Tipo", "unidad_negocio": "Unidad",
                    "monto": "Monto", "estado": "Estado", "observaciones": "Obs."
                })

    with tab_inv2:
        if not df_inv.empty:
            res_inv = resumen_inversiones_mensual(inversiones)
            col_v1, col_v2 = st.columns(2)
            with col_v1:
                fig_inv = go.Figure(go.Bar(
                    x=res_inv["mes_nombre"].apply(lambda m: m[:3]).tolist(),
                    y=(res_inv["total_inversiones"]/1e6).tolist(),
                    marker_color="#7C3AED", opacity=0.85,
                    text=[f"${v:.0f}M" if v>0 else "" for v in (res_inv["total_inversiones"]/1e6).tolist()],
                    textposition="outside"))
                fig_inv = plotly_layout(fig_inv, 300)
                fig_inv.update_layout(title="Inversiones por Mes ($M)", yaxis_title="$M ARS")
                st.plotly_chart(fig_inv, use_container_width=True)
            with col_v2:
                tipo_agg = df_inv.groupby("tipo")["monto"].sum()
                fig_tipo = go.Figure(go.Pie(
                    labels=tipo_agg.index.tolist(), values=tipo_agg.values.tolist(),
                    hole=0.4, textinfo="label+percent",
                    marker=dict(colors=["#2E75B6","#059669","#D97706","#DC2626","#7C3AED"])))
                fig_tipo.update_layout(height=300, margin=dict(t=10,b=10),
                    paper_bgcolor="white", showlegend=False)
                st.plotly_chart(fig_tipo, use_container_width=True)

    with tab_inv3:
        with st.form("form_inversion"):
            fi1,fi2 = st.columns(2)
            with fi1:
                desc_i  = st.text_input("Descripción *")
                monto_i = st.number_input("Monto ($) *", min_value=0.0, step=1_000_000.0, format="%.0f")
                mes_i   = st.selectbox("Mes", range(1,13), format_func=nombre_mes)
            with fi2:
                tipo_i  = st.selectbox("Tipo", ["Infraestructura","TI/Sistemas",
                                                  "Inversión financiera","Capital de trabajo",
                                                  "Mantenimiento","Otro"])
                unidad_i= st.selectbox("Unidad de Negocio", ["General"] + list(UNIDADES_NEGOCIO.keys()))
                est_i   = st.selectbox("Estado", ["proyectado","confirmado","ejecutado"])
            obs_i = st.text_area("Observaciones", height=60)
            sub_i = st.form_submit_button("✅ Agregar Inversión", use_container_width=True, type="primary")
        if sub_i:
            if not desc_i or monto_i <= 0:
                st.error("Completar campos obligatorios (*)")
            else:
                inv_new = agregar_inversion(st.session_state.inversiones, desc_i, monto_i, mes_i, tipo_i, unidad_i, obs_i)
                st.session_state.inversiones = inv_new
                guardar_inversiones(inv_new)
                st.success(f"✅ Inversión agregada — {fmt_ars(monto_i)}"); st.rerun()

        st.markdown("---")
        if st.button("🧪 Cargar inversiones demo", use_container_width=True):
            st.session_state.inversiones = generar_inversiones_demo()
            guardar_inversiones(st.session_state.inversiones)
            st.success("✅ Inversiones demo cargadas"); st.rerun()


# ══════════════════════════════════════════════════════════════════════
# PÁGINA: COMEX — IMPORTACIONES
# ══════════════════════════════════════════════════════════════════════
elif pagina == "🌍 COMEX — Importaciones":
    st.markdown("## 🌍 COMEX — Gestión de Pagos de Importaciones")
    st.caption("Droguería del Sud: ~18% de compras son productos importados (USD ~620M/año)")

    df_cx = st.session_state.df_comex

    # ── KPIs COMEX ──────────────────────────────────────────────────
    res_cx = resumen_comex_mensual(df_cx, AÑO)
    total_usd = df_cx["monto_usd"].sum() if not df_cx.empty else 0
    total_ars = df_cx["costo_total_ars"].sum() if not df_cx.empty else 0
    total_aranc = df_cx["arancel_ars"].sum() if not df_cx.empty else 0
    total_iva   = df_cx["iva_importacion_ars"].sum() if not df_cx.empty else 0

    k1,k2,k3,k4,k5 = st.columns(5)
    with k1: st.metric("💵 Total USD (año)",      f"USD {total_usd/1e6:.1f}M")
    with k2: st.metric("💰 Costo Total ARS",       fmt_millones(total_ars))
    with k3: st.metric("🏛️ Aranceles + Estadística", fmt_millones(total_aranc))
    with k4: st.metric("📋 IVA Importación",        fmt_millones(total_iva))
    with k5: st.metric("📦 Operaciones",            len(df_cx) if not df_cx.empty else 0)

    st.markdown("---")

    tab_cx1, tab_cx2, tab_cx3, tab_cx4 = st.tabs([
        "📊 Resumen mensual", "📋 Operaciones", "⚠️ Alertas vencimientos", "➕ Nueva operación"
    ])

    with tab_cx1:
        st.markdown("#### Flujo COMEX Mensual — Cómo impacta en el Cashflow")
        st.info("""
        **Líneas separadas en el Cashflow:**
        - **Pago proveedores exterior** (ARS equivalente al TC del día) → Egreso principal
        - **Aranceles aduaneros** (0-20% según categoría) → Egreso al momento del DUA
        - **IVA importación** (10.5%) → Crédito fiscal recuperable
        - **Percepción ARCA** (3%) → Crédito fiscal recuperable
        """)
        if not res_cx.empty and res_cx["total_egreso_ars"].sum() > 0:
            fig_cx = make_subplots(rows=1, cols=2,
                specs=[[{"type": "xy"}, {"type": "domain"}]],
                subplot_titles=("Pagos COMEX por Mes — USD y ARS ($B)",
                                "Composición del Costo COMEX"),
                horizontal_spacing=0.12)

            meses_cx = res_cx["mes_nombre"].apply(lambda m: m[:3]).tolist()
            # Gráfico barras: proveedor + aranceles + IVA
            fig_cx.add_trace(go.Bar(
                x=meses_cx, y=(res_cx["pago_proveedores_ars"]/1e9).tolist(),
                name="Pago Proveedor (ARS)", marker_color="#2E75B6", opacity=0.85,
                hovertemplate="<b>%{x}</b><br>Proveedor: $%{y:.1f}B<extra></extra>",
            ), row=1,col=1)
            fig_cx.add_trace(go.Bar(
                x=meses_cx, y=(res_cx["aranceles_ars"]/1e9).tolist(),
                name="Aranceles", marker_color="#D97706", opacity=0.85,
                hovertemplate="<b>%{x}</b><br>Aranceles: $%{y:.1f}B<extra></extra>",
            ), row=1,col=1)
            fig_cx.add_trace(go.Bar(
                x=meses_cx, y=(res_cx["iva_importacion_ars"]/1e9).tolist(),
                name="IVA Imp. (récup.)", marker_color="#059669", opacity=0.6,
                hovertemplate="<b>%{x}</b><br>IVA: $%{y:.1f}B<extra></extra>",
            ), row=1,col=1)

            # Donut composición
            comp_labels = ["Pago Proveedor","Aranceles","IVA Importación","Percepción ARCA"]
            comp_values = [
                float(res_cx["pago_proveedores_ars"].sum()),
                float(res_cx["aranceles_ars"].sum()),
                float(res_cx["iva_importacion_ars"].sum()),
                float(df_cx["percepcion_arca_ars"].sum()) if not df_cx.empty else 0,
            ]
            fig_cx.add_trace(go.Pie(
                labels=comp_labels, values=comp_values, hole=0.45,
                marker=dict(colors=["#2E75B6","#D97706","#059669","#7C3AED"]),
                textinfo="label+percent",
                hovertemplate="<b>%{label}</b><br>$%{value:,.0f}<extra></extra>",
            ), row=1,col=2)

            fig_cx = plotly_layout(fig_cx, 360)
            fig_cx.update_layout(barmode="stack", showlegend=True)
            fig_cx.update_yaxes(ticksuffix="B", row=1, col=1)
            st.plotly_chart(fig_cx, use_container_width=True)

            # Tabla resumen mensual
            df_cx_show = res_cx.copy()
            df_cx_show["pago_proveedores_usd"] = df_cx_show["pago_proveedores_usd"].apply(
                lambda x: f"USD {x:,.0f}" if x>0 else "—")
            df_cx_show["pago_proveedores_ars"] = df_cx_show["pago_proveedores_ars"].apply(
                lambda x: fmt_ars(x) if x>0 else "—")
            df_cx_show["aranceles_ars"]       = df_cx_show["aranceles_ars"].apply(
                lambda x: fmt_ars(x) if x>0 else "—")
            df_cx_show["iva_importacion_ars"] = df_cx_show["iva_importacion_ars"].apply(
                lambda x: fmt_ars(x) if x>0 else "—")
            df_cx_show["total_egreso_ars"]    = df_cx_show["total_egreso_ars"].apply(
                lambda x: fmt_ars(x) if x>0 else "—")
            st.dataframe(
                df_cx_show[["mes_nombre","pago_proveedores_usd","pago_proveedores_ars",
                             "aranceles_ars","iva_importacion_ars","total_egreso_ars","operaciones"]],
                hide_index=True, use_container_width=True,
                column_config={
                    "mes_nombre": "Mes",
                    "pago_proveedores_usd": "Pago USD",
                    "pago_proveedores_ars": "Pago ARS equiv.",
                    "aranceles_ars": "Aranceles",
                    "iva_importacion_ars": "IVA Imp.",
                    "total_egreso_ars": "Egreso Total ARS",
                    "operaciones": "Ops.",
                }
            )

    with tab_cx2:
        if df_cx.empty:
            st.info("No hay operaciones COMEX. Cargá datos demo o registrá una operación.")
        else:
            cols_show = ["proveedor","pais_origen","descripcion","monto_usd",
                         "tc_aplicado","costo_total_ars","fecha_orden",
                         "fecha_pago_proveedor","estado","banco_pago","unidad_negocio"]
            df_s = df_cx[cols_show].copy()
            df_s["monto_usd"]       = df_s["monto_usd"].apply(lambda x: f"USD {x:,.0f}")
            df_s["costo_total_ars"] = df_s["costo_total_ars"].apply(fmt_ars)
            df_s["tc_aplicado"]     = df_s["tc_aplicado"].apply(lambda x: f"${x:,.0f}")
            for c in ["fecha_orden","fecha_pago_proveedor"]:
                df_s[c] = df_s[c].apply(lambda d: d.strftime("%d/%m/%Y") if hasattr(d,"strftime") else str(d)[:10] if d else "")
            st.dataframe(df_s, hide_index=True, use_container_width=True, height=400,
                column_config={
                    "proveedor": st.column_config.TextColumn("Proveedor", width="medium"),
                    "pais_origen": "País",
                    "descripcion": st.column_config.TextColumn("Descripción", width="medium"),
                    "monto_usd": "Monto USD",
                    "tc_aplicado": "TC ARS/USD",
                    "costo_total_ars": "Costo Total ARS",
                    "fecha_orden": "Fecha Orden",
                    "fecha_pago_proveedor": "Fecha Pago",
                    "estado": "Estado",
                    "banco_pago": "Banco",
                    "unidad_negocio": "Unidad",
                })

    with tab_cx3:
        st.markdown("#### Alertas de Vencimientos COMEX")
        alertas_cx = alertas_comex_vencimientos(df_cx, date.today())
        if not alertas_cx:
            st.success("✅ No hay vencimientos COMEX urgentes")
        else:
            for a in alertas_cx:
                cls = f"alerta-{a['nivel']}"
                st.markdown(
                    f'<div class="{cls}"><b>{a["titulo"]}</b><br>'
                    f'{a["detalle"]}<br>'
                    f'<i>→ {a["accion"]}</i></div>',
                    unsafe_allow_html=True)

    with tab_cx4:
        st.markdown("#### Registrar nueva operación de importación")
        with st.form("form_comex"):
            fc1,fc2 = st.columns(2)
            with fc1:
                prov_cx  = st.text_input("Proveedor exterior *", placeholder="Fresenius Kabi AG")
                pais_cx  = st.text_input("País de origen *", placeholder="Alemania")
                desc_cx  = st.text_input("Descripción *", placeholder="Soluciones parenterales")
                cat_cx   = st.selectbox("Categoría arancelaria *", list(ARANCELES.keys()),
                    format_func=lambda x: f"{x.replace('_',' ').title()} ({ARANCELES[x]*100:.0f}%)")
            with fc2:
                monto_cx  = st.number_input("Monto USD (FOB) *", min_value=0.0, step=10000.0, format="%.0f")
                tc_cx     = st.number_input("Tipo de cambio ARS/USD *",
                    value=1200.0, step=10.0, format="%.0f")
                dias_cx   = st.selectbox("Plazo pago (días)", [0,30,60,90,120,180])
                banco_cx  = st.selectbox("Banco para el pago", BANCOS_ARGENTINA)
            ford_cx   = st.date_input("Fecha de orden")
            unidad_cx = st.selectbox("Unidad de negocio", list(UNIDADES_NEGOCIO.keys()))
            obs_cx    = st.text_area("Observaciones / N° SIRA", height=60)
            sub_cx    = st.form_submit_button("✅ Registrar operación COMEX",
                use_container_width=True, type="primary")

        if sub_cx:
            if not prov_cx or not pais_cx or monto_cx <= 0 or tc_cx <= 0:
                st.error("Completar campos obligatorios (*)")
            else:
                df_cx_new = agregar_operacion_comex(
                    st.session_state.df_comex,
                    proveedor=prov_cx, pais_origen=pais_cx,
                    descripcion=desc_cx, categoria=cat_cx,
                    monto_usd=monto_cx, fecha_orden=str(ford_cx),
                    dias_plazo_pago=dias_cx, tc_aplicado=float(tc_cx),
                    banco_pago=banco_cx, unidad_negocio=unidad_cx,
                    observaciones=obs_cx,
                )
                st.session_state.df_comex = df_cx_new
                guardar_comex(df_cx_new)
                st.success(f"✅ Operación COMEX registrada — USD {monto_cx:,.0f}"); st.rerun()

        st.markdown("---")
        if st.button("🧪 Cargar operaciones COMEX demo", use_container_width=True):
            st.session_state.df_comex = generar_comex_demo()
            guardar_comex(st.session_state.df_comex)
            st.success("✅ Operaciones COMEX demo cargadas"); st.rerun()


# ══════════════════════════════════════════════════════════════════════
# PÁGINA: CARGA PRÉSTAMO CON OCR / IMAGEN
# ══════════════════════════════════════════════════════════════════════
elif pagina == "📥 Carga Préstamo (OCR)":
    st.markdown("## 📥 Carga de Préstamo — Desde Imagen o Texto del Contrato")
    st.caption("Pegá el texto del contrato o subí una foto/PDF y el sistema extrae los datos automáticamente")

    tab_ocr1, tab_ocr2 = st.tabs(["📝 Pegar texto del contrato", "📷 Subir imagen (foto/escáner)"])

    with tab_ocr1:
        st.markdown("**Copiá el texto del contrato o liquidación bancaria y pegalo aquí:**")
        texto_contrato = st.text_area(
            "Texto del contrato",
            height=200,
            placeholder="""Ejemplo:
BANCO GALICIA Y BUENOS AIRES S.A.
Monto del préstamo: $5.000.000,00
TNA: 52,50%   TEA: 65,83%   CFT: 78,20%
24 cuotas de $312.500,00
Primera cuota: 15/07/2025   Día de débito: 15
Garantía: Aval SGR""",
            label_visibility="collapsed"
        )

        col_ocr1, col_ocr2 = st.columns(2)
        with col_ocr1:
            if st.button("🔍 Extraer datos automáticamente", use_container_width=True,
                         type="primary", disabled=not texto_contrato):
                with st.spinner("Analizando contrato..."):
                    datos_ext = extraer_datos_prestamo_con_ia(texto_contrato)
                st.session_state["datos_ocr_temp"] = datos_ext
                st.rerun()

        # Mostrar resultados extraídos
        if "datos_ocr_temp" in st.session_state:
            datos = st.session_state["datos_ocr_temp"]
            conf  = datos.get("confianza","baja")
            conf_color = {"alta":"#059669","media":"#D97706","baja":"#DC2626"}.get(conf,"#888")

            st.markdown(f"""
            <div style="background:#0D2D1F;border:1px solid #10B981;border-radius:10px;padding:16px;margin:12px 0">
                <div style="font-size:13px;font-weight:600;color:#166534;margin-bottom:10px">
                    ✅ Extracción completada — Confianza:
                    <span style="color:{conf_color};font-weight:700">{conf.upper()}</span>
                </div>
                <div style="font-size:11px;color:#CBD5E1">
                    Campos detectados: {', '.join(datos.get('campos_extraidos',[]))}
                </div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("**Revisá y ajustá los datos extraídos antes de guardar:**")

            with st.form("form_ocr_confirmar"):
                fo1,fo2 = st.columns(2)
                with fo1:
                    banco_ocr   = st.selectbox("Banco *", BANCOS_ARGENTINA,
                        index=BANCOS_ARGENTINA.index(datos["banco"]) if datos["banco"] in BANCOS_ARGENTINA else 0)
                    desc_ocr    = st.text_input("Descripción", value=datos.get("descripcion",""))
                    capital_ocr = st.number_input("Capital Original ($) *",
                        value=float(datos.get("capital_original",0)), step=10000.0, format="%.0f")
                    tna_ocr     = st.number_input("TNA (%) *",
                        value=float(datos.get("tna",0)), step=0.5, format="%.2f")
                    tea_ocr     = st.number_input("TEA (%)",
                        value=float(datos.get("tea",0)), step=0.5, format="%.2f")
                with fo2:
                    cuota_ocr   = st.number_input("Cuota Mensual ($) *",
                        value=float(datos.get("cuota_mensual",0)), step=1000.0, format="%.0f")
                    ctot_ocr    = st.number_input("Total Cuotas",
                        value=int(datos.get("cuotas_totales",0) or 0), min_value=0, max_value=120)
                    cpag_ocr    = st.number_input("Cuotas Ya Pagadas", value=0, min_value=0)
                    dia_ocr     = st.number_input("Día Débito",
                        value=int(datos.get("dia_debito",25)), min_value=1, max_value=28)
                    fprimer_ocr = st.text_input("Fecha 1ra Cuota (DD/MM/YYYY)",
                        value=datos.get("fecha_primera_cuota",""))
                garantia_ocr = st.text_input("Garantía", value=datos.get("garantia",""))
                obs_ocr = st.text_area("Observaciones", value=datos.get("observaciones",""), height=60)
                sub_ocr = st.form_submit_button("💾 Guardar Préstamo", use_container_width=True, type="primary")

            if sub_ocr:
                if not banco_ocr or capital_ocr <= 0 or tna_ocr <= 0:
                    st.error("Completar campos obligatorios (*)")
                else:
                    from src.utils.ocr_prestamos import calcular_cronograma_completo
                    datos_final = {
                        "banco": banco_ocr, "descripcion": desc_ocr,
                        "capital_original": capital_ocr, "capital_vigente": capital_ocr * (1 - cpag_ocr/ctot_ocr) if ctot_ocr>0 else capital_ocr,
                        "tna": tna_ocr, "tea": tea_ocr,
                        "cuota_mensual": cuota_ocr, "cuotas_totales": ctot_ocr,
                        "cuotas_pagadas": cpag_ocr, "dia_debito": dia_ocr,
                        "fecha_primera_cuota": fprimer_ocr,
                        "garantia": garantia_ocr, "estado": "vigente",
                        "observaciones": obs_ocr + " [Cargado vía OCR]",
                    }
                    from src.models.gestor_deuda import agregar_prestamo, guardar_prestamos
                    st.session_state.prestamos = agregar_prestamo(
                        st.session_state.prestamos, **datos_final)
                    guardar_prestamos(st.session_state.prestamos)
                    del st.session_state["datos_ocr_temp"]

                    # Mostrar cronograma
                    cron = calcular_cronograma_completo(datos_final, AÑO)
                    st.success(f"✅ Préstamo {banco_ocr} guardado correctamente")
                    st.markdown("#### Cronograma de cuotas (primeras 12):")
                    df_cron = pd.DataFrame(cron[:12])
                    df_cron_show = df_cron.copy()
                    for c in ["cuota_total","amortizacion","interes","capital_restante"]:
                        df_cron_show[c] = df_cron_show[c].apply(fmt_ars)
                    df_cron_show["fue_ajustado"] = df_cron_show["fue_ajustado"].apply(
                        lambda x: "✅ Ajustado" if x else "—")
                    st.dataframe(df_cron_show[[
                        "nro","fecha_original","dia_semana","fue_ajustado","fecha_habil",
                        "cuota_total","amortizacion","interes","capital_restante"
                    ]], hide_index=True, use_container_width=True,
                    column_config={
                        "nro":"N°","fecha_original":"Fecha Orig.","dia_semana":"Día",
                        "fue_ajustado":"Ajuste Hábil","fecha_habil":"Fecha Hábil Efectiva",
                        "cuota_total":"Cuota Total","amortizacion":"Amortización",
                        "interes":"Interés","capital_restante":"Saldo Restante",
                    })
                    st.rerun()

    with tab_ocr2:
        st.markdown("""
        **Subí una foto del contrato o extracto bancario.**
        Claude Vision analiza la imagen y extrae los datos automáticamente.
        """)
        img_up = st.file_uploader("Foto/imagen del contrato",
                                   type=["jpg","jpeg","png","webp"],
                                   key="img_contrato")
        if img_up:
            import base64
            img_bytes  = img_up.read()
            img_b64    = base64.b64encode(img_bytes).decode()
            media_type = img_up.type or "image/jpeg"

            st.image(img_bytes, caption="Imagen cargada", use_column_width=True)

            if st.button("🤖 Analizar con IA (Claude Vision)", use_container_width=True, type="primary"):
                with st.spinner("Analizando imagen con Claude Vision..."):
                    datos_img = analizar_imagen_prestamo_con_claude(img_b64, media_type)
                if datos_img.get("error"):
                    st.error(f"Error procesando imagen: {datos_img['error']}")
                    st.info("Usá la pestaña 'Pegar texto del contrato' como alternativa.")
                else:
                    st.session_state["datos_ocr_temp"] = datos_img
                    st.success("✅ Imagen analizada. Revisá los datos en la pestaña anterior.")
                    st.rerun()
        else:
            st.markdown("""
            **Cómo usarlo:**
            1. Sacá una foto con el celular del contrato/liquidación del banco
            2. Subila aquí
            3. Hacé clic en "Analizar con IA"
            4. Revisá y corregí los datos si es necesario
            5. Guardá el préstamo

            **Formatos aceptados:** JPG, PNG, WEBP (máx. 5MB)

            **Datos que extrae automáticamente:**
            Banco · Capital · TNA · TEA · CFT · N° cuotas · Cuota mensual · Fecha 1ra cuota · Día débito · Garantía
            """)


# ══════════════════════════════════════════════════════════════════════
# PÁGINA: SAP — TIEMPO REAL
# ══════════════════════════════════════════════════════════════════════
elif pagina == "🔗 SAP — Tiempo Real":
    from datetime import datetime as _dt
    st.markdown("""
    <div class="cf-header">
        <h1>🔗 SAP — Integración en Tiempo Real</h1>
        <p>FI · SD · MM · CO · TR — Droguería del Sud</p>
    </div>""", unsafe_allow_html=True)

    if not SAP_DISPONIBLE:
        st.error(f"⚠️ Módulo SAP no disponible: {_sap_err_msg}")
        st.stop()

    # ── Estado conexión ───────────────────────────────────────────────
    estado = get_estado_conexion()
    col_e1, col_e2, col_e3, col_e4 = st.columns(4)
    with col_e1:
        color_modo = "#059669" if estado["modo"] == "LIVE" else "#D97706"
        st.markdown(f"""<div style="background:#1E293B;border:1px solid #334155;border-radius:10px;border-left:4px solid {color_modo};padding:14px">
            <div style="font-size:11px;color:#64748B;text-transform:uppercase">Modo</div>
            <div style="font-size:20px;font-weight:600;color:{color_modo}">{estado["modo"]}</div>
            <div style="font-size:11px;color:#64748B">{estado["mensaje"]}</div>
        </div>""", unsafe_allow_html=True)
    with col_e2:
        st.markdown(f"""<div style="background:#1E293B;border:1px solid #334155;border-radius:10px;border-left:4px solid #2E75B6;padding:14px">
            <div style="font-size:11px;color:#64748B;text-transform:uppercase">Servidor SAP</div>
            <div style="font-size:13px;font-weight:600;color:#1E293B;word-break:break-all">{estado["servidor"]}</div>
            <div style="font-size:11px;color:#64748B">Empresa: {estado["empresa"]}</div>
        </div>""", unsafe_allow_html=True)
    with col_e3:
        st.markdown(f"""<div style="background:#1E293B;border:1px solid #334155;border-radius:10px;border-left:4px solid #2E75B6;padding:14px">
            <div style="font-size:11px;color:#64748B;text-transform:uppercase">Última sinc.</div>
            <div style="font-size:16px;font-weight:600;color:#F1F5F9">{estado["timestamp"][-8:]}</div>
            <div style="font-size:11px;color:#64748B">{estado["timestamp"][:10]}</div>
        </div>""", unsafe_allow_html=True)
    with col_e4:
        if st.button("🔄 Sincronizar SAP ahora", use_container_width=True, type="primary"):
            with st.spinner("Sincronizando con SAP..."):
                resultado = sincronizar_todo()
            if resultado["ok"]:
                st.success(f"✅ Sincronización completa — {resultado['pasos']} módulos OK")
            else:
                st.warning(f"⚠️ Sincronización parcial: {', '.join(resultado['errores'])}")
            st.rerun()

    st.markdown("---")

    # ── Saldos bancarios en tiempo real ──────────────────────────────
    st.markdown("### 🏦 Saldos Bancarios en Tiempo Real — FI/BL")
    st.caption("Actualización automática cada 3 minutos vía SAP Bank Statement Interface")

    saldos = get_saldos_bancarios(force_refresh=True)
    total_bancos = sum(b["saldo"] for b in saldos)

    st.markdown(f"""<div style="background:linear-gradient(135deg,#1F3864,#2E75B6);color:white;border-radius:12px;padding:20px;margin:8px 0 16px">
        <div style="font-size:13px;opacity:0.8;text-transform:uppercase;letter-spacing:1px">Posición Consolidada</div>
        <div style="font-size:36px;font-weight:700">${total_bancos/1e9:.2f}B ARS</div>
        <div style="font-size:12px;opacity:0.7">6 cuentas · Actualizado {_dt.now().strftime("%H:%M:%S")} hs</div>
    </div>""", unsafe_allow_html=True)

    cols_b = st.columns(3)
    for i, banco in enumerate(saldos):
        with cols_b[i % 3]:
            pct = banco["saldo"] / total_bancos * 100
            color_b = "#059669" if banco["saldo"] > 1e9 else "#D97706"
            st.markdown(f"""<div style="background:#1E293B;border:1px solid #334155;border-radius:10px;padding:14px;margin-bottom:10px">
                <div style="font-size:12px;font-weight:600;color:#60A5FA">{banco["banco"]}</div>
                <div style="font-size:18px;font-weight:700;color:{color_b}">${banco["saldo"]/1e9:.2f}B</div>
                <div style="font-size:10px;color:#64748B">CBU {banco.get("cbu","—")[:12]}... · {pct:.1f}% del total</div>
                <div style="background:#E2E8F0;border-radius:4px;height:4px;margin-top:8px">
                    <div style="background:{color_b};width:{pct:.0f}%;height:4px;border-radius:4px"></div>
                </div>
            </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── KPIs SAP FI consolidados ──────────────────────────────────────
    st.markdown("### 📊 KPIs Financieros — SAP FI/SD/MM/CO")
    kpis_sap = get_kpis_fi()
    fact_mes = get_facturacion_mes()

    kc1,kc2,kc3,kc4,kc5,kc6 = st.columns(6)
    with kc1: st.metric("💰 Saldo bancos", fmt_millones(kpis_sap["saldo_total_bancos"]))
    with kc2: st.metric("📈 Facturación mes", fmt_millones(kpis_sap["facturacion_mes"]),
                        f"{fact_mes.get('pct_avance',0):.0f}% avance")
    with kc3: st.metric("🧾 AR (cobrar)", fmt_millones(kpis_sap["cuentas_cobrar"]),
                        f"DSO {kpis_sap['dso']} días")
    with kc4: st.metric("📦 AP (pagar)", fmt_millones(kpis_sap["cuentas_pagar"]),
                        f"DPO {kpis_sap['dpo']} días")
    with kc5: st.metric("📉 Pagos 30d", fmt_millones(kpis_sap["pagos_proximos_30d"]))
    with kc6:
        cob = kpis_sap["cobertura_liquidez"]
        color_cob = "#059669" if cob >= 1.5 else "#D97706" if cob >= 1 else "#DC2626"
        st.metric("🔒 Cobertura", f"{cob:.1f}x",
                  "✅ Confortable" if cob >= 1.5 else "⚠️ Monitorear" if cob >= 1 else "🚨 Crítico")

    st.markdown("---")

    # ── CCC y liquidez ────────────────────────────────────────────────
    col_ccc, col_pag = st.columns(2)
    with col_ccc:
        st.markdown("### 🔄 Cash Conversion Cycle (CCC)")
        ccc = calcular_ccc()
        st.markdown(f"""<div style="background:#1E293B;border:1px solid #334155;border-radius:12px;padding:20px">
            <div style="display:flex;gap:16px;align-items:center;margin-bottom:16px">
                <div style="text-align:center;flex:1">
                    <div style="font-size:11px;color:#64748B;text-transform:uppercase">DSO</div>
                    <div style="font-size:28px;font-weight:700;color:#2E75B6">{ccc["dso"]}</div>
                    <div style="font-size:11px;color:#64748B">días cobro</div>
                </div>
                <div style="font-size:20px;color:#64748B">+</div>
                <div style="text-align:center;flex:1">
                    <div style="font-size:11px;color:#64748B;text-transform:uppercase">DIH</div>
                    <div style="font-size:28px;font-weight:700;color:#D97706">{ccc["dih"]}</div>
                    <div style="font-size:11px;color:#64748B">días stock</div>
                </div>
                <div style="font-size:20px;color:#64748B">−</div>
                <div style="text-align:center;flex:1">
                    <div style="font-size:11px;color:#64748B;text-transform:uppercase">DPO</div>
                    <div style="font-size:28px;font-weight:700;color:#059669">{ccc["dpo"]}</div>
                    <div style="font-size:11px;color:#64748B">días pago</div>
                </div>
                <div style="font-size:20px;color:#64748B">=</div>
                <div style="text-align:center;flex:1;background:#F0FDF4;border-radius:8px;padding:8px">
                    <div style="font-size:11px;color:#064E3B;text-transform:uppercase">CCC</div>
                    <div style="font-size:28px;font-weight:700;color:#059669">{ccc["ccc"]}</div>
                    <div style="font-size:11px;color:#047857">días</div>
                </div>
            </div>
            <div style="border-top:1px solid #F1F5F9;padding-top:12px;font-size:12px;color:#64748B">
                Benchmark sector farmacéutico: <b>{ccc["benchmark_sector"]} días</b> · 
                Calificación: <b style="color:#059669">{ccc["calificacion"]}</b>
            </div>
        </div>""", unsafe_allow_html=True)

    with col_pag:
        st.markdown("### 💸 Pagos Programados — SAP TR")
        pagos = get_pagos_programados(30)
        total_pagos = sum(p["monto"] for p in pagos)
        st.markdown(f"""<div style="background:#2D2008;border:1px solid #F59E0B;border-radius:8px;padding:12px;margin-bottom:12px;font-size:13px">
            ⚠️ Total pagos próximos 30 días: <b>${total_pagos/1e9:.2f}B</b>
        </div>""", unsafe_allow_html=True)

        df_pagos = pd.DataFrame(pagos[:8])
        if not df_pagos.empty:
            df_pagos["monto_fmt"] = df_pagos["monto"].apply(fmt_millones)
            st.dataframe(
                df_pagos[["concepto","categoria","fecha","monto_fmt","banco"]].rename(columns={
                    "concepto":"Concepto","categoria":"Categoría","fecha":"Fecha",
                    "monto_fmt":"Monto","banco":"Banco"
                }),
                use_container_width=True, height=280,
                hide_index=True,
            )

    st.markdown("---")

    # ── Módulos SAP conectados ────────────────────────────────────────
    st.markdown("### ⚙️ Módulos SAP — Estado de Integración")
    modulos = [
        {"modulo":"FI — Finanzas",       "descripcion":"Extractos bancarios, pagos, cobranzas, GL",        "estado":"activo",  "fuente":"SAP Service Layer /BankStatements"},
        {"modulo":"SD — Ventas",          "descripcion":"Facturas clientes (9.500 farmacias), órdenes",      "estado":"activo",  "fuente":"SAP /Invoices /Orders"},
        {"modulo":"MM — Compras",         "descripcion":"OC y facturas proveedores (400+ laboratorios)",      "estado":"activo",  "fuente":"SAP /PurchaseOrders /APInvoices"},
        {"modulo":"CO — Controlling",     "descripcion":"Budget vs Real, centros de costo, unidades negocio","estado":"activo",  "fuente":"SAP /BudgetDistributions /CostCenters"},
        {"modulo":"TR — Tesorería",       "descripcion":"Préstamos, posición liquidez, forecast",             "estado":"activo",  "fuente":"SAP /TM40 /LoanContracts"},
        {"modulo":"HR — RRHH",            "descripcion":"Nómina 1.100 empleados, cargas sociales",           "estado":"pendiente","fuente":"SAP SuccessFactors (integración próxima)"},
        {"modulo":"ARCA/AFIP API",        "descripcion":"Cuentas tributarias, vencimientos, planes de pago", "estado":"activo",  "fuente":"ARCA API REST + ws-sr-padron-a5"},
        {"modulo":"BCRA Central Deudores","descripcion":"Situación crediticia, deudas sistema financiero",   "estado":"activo",  "fuente":"BCRA API pública"},
        {"modulo":"Power BI",             "descripcion":"Dashboard ejecutivo board — datos SAP directo",      "estado":"pendiente","fuente":"Conector SAP Power BI (en configuración)"},
    ]
    cols_mod = st.columns(3)
    for i, m in enumerate(modulos):
        with cols_mod[i % 3]:
            color = "#DCFCE7" if m["estado"] == "activo" else "#FEF9C3"
            border = "#059669" if m["estado"] == "activo" else "#D97706"
            dot = "🟢" if m["estado"] == "activo" else "🟡"
            st.markdown(f"""<div style="background:{color};border:1px solid {border};border-radius:8px;padding:12px;margin-bottom:10px">
                <div style="font-weight:600;font-size:13px;color:#F1F5F9">{dot} {m["modulo"]}</div>
                <div style="font-size:11px;color:#374151;margin:4px 0">{m["descripcion"]}</div>
                <div style="font-size:10px;color:#6B7280;font-family:monospace">{m["fuente"]}</div>
            </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# PÁGINA: FORECAST LIQUIDEZ
# ══════════════════════════════════════════════════════════════════════
elif pagina == "📡 Forecast Liquidez":
    from datetime import datetime as _dt2
    st.markdown("""
    <div class="cf-header">
        <h1>📡 Forecast de Liquidez — Rolling 13 Semanas</h1>
        <p>Modelo predictivo de posición de caja · Semáforo automático · SAP TR</p>
    </div>""", unsafe_allow_html=True)

    if not SAP_DISPONIBLE:
        st.error("⚠️ Módulo SAP no disponible")
        st.stop()

    liquidez   = get_posicion_liquidez()
    alertas_rt = generar_alertas_automaticas()

    # Resumen posición actual
    sem_color  = {"verde":"#059669","amarillo":"#D97706","naranja":"#EA580C","rojo":"#DC2626"}.get(liquidez["semaforo"],"#2E75B6")
    st.markdown(f"""<div style="background:linear-gradient(135deg,{sem_color},{sem_color}CC);color:white;border-radius:12px;padding:20px;margin-bottom:16px">
        <div style="display:flex;justify-content:space-between;align-items:center">
            <div>
                <div style="font-size:13px;opacity:0.85">Posición de liquidez ahora</div>
                <div style="font-size:40px;font-weight:700">${liquidez["saldo_total"]/1e9:.2f}B</div>
                <div style="font-size:14px;opacity:0.9">{liquidez["semaforo_msg"]}</div>
            </div>
            <div style="text-align:right">
                <div style="font-size:12px;opacity:0.8">Pagos próximos 7d</div>
                <div style="font-size:22px;font-weight:600">${liquidez["pagos_proximos_7d"]/1e9:.2f}B</div>
                <div style="font-size:12px;opacity:0.8">Cobertura 30d: {liquidez["cobertura_30d"]:.1f}x</div>
            </div>
        </div>
    </div>""", unsafe_allow_html=True)

    # Alertas en tiempo real
    if alertas_rt:
        st.markdown("### 🚨 Alertas Automáticas")
        for a in alertas_rt:
            color_alerta = {"critico":"#FEE2E2","alerta":"#FEF9C3","info":"#EFF6FF"}.get(a["nivel"],"#F8FAFC")
            border_alerta = {"critico":"#DC2626","alerta":"#D97706","info":"#2563EB"}.get(a["nivel"],"#94A3B8")
            st.markdown(f"""<div style="background:{color_alerta};border-left:4px solid {border_alerta};border-radius:8px;padding:12px;margin-bottom:8px">
                <b>{a["icono"]} {a["titulo"]}</b><br>
                <span style="font-size:13px;color:#CBD5E1">{a["detalle"]}</span>
            </div>""", unsafe_allow_html=True)
        st.markdown("---")

    # Forecast 13 semanas
    st.markdown("### 📈 Forecast Rolling 13 Semanas — SAP TR + IA Predictiva")
    forecast = forecast_rolling_13_semanas()
    df_fc = pd.DataFrame(forecast)

    # Gráfico Plotly
    fig_fc = make_subplots(rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.08, row_heights=[0.5, 0.5],
        subplot_titles=("Flujos: cobros vs pagos (en MM$)", "Saldo proyectado de caja (en MM$)"))

    semanas_labels = [s["periodo"] for s in forecast]
    fig_fc.add_trace(go.Bar(x=semanas_labels,
        y=[s["cobros"]/1e6 for s in forecast], name="Cobros", marker_color="#00C49F", opacity=0.85), row=1,col=1)
    fig_fc.add_trace(go.Bar(x=semanas_labels,
        y=[s["pagos"]/1e6 for s in forecast], name="Pagos", marker_color="#FF4D6D", opacity=0.85), row=1,col=1)

    colores_saldo = [{"verde":"#059669","amarillo":"#D97706","rojo":"#DC2626"}.get(s["semaforo"],"#2E75B6") for s in forecast]
    fig_fc.add_trace(go.Bar(x=semanas_labels,
        y=[s["saldo_proy"]/1e6 for s in forecast],
        name="Saldo proyectado", marker_color=colores_saldo, opacity=0.9,
        text=[f"${s['saldo_proy']/1e9:.1f}B" for s in forecast], textposition="outside"), row=2,col=1)
    fig_fc.add_hline(y=1000, line_dash="dash", line_color="#DC2626", annotation_text="Min crítico $1B", row=2, col=1)
    fig_fc.add_hline(y=3000, line_dash="dot",  line_color="#D97706", annotation_text="Min alerta $3B",  row=2, col=1)

    fig_fc.update_layout(
        height=480, barmode="group",
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(family="Inter, sans-serif", size=11, color="#374151"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=60,b=30,l=60,r=40),
    )
    fig_fc.update_yaxes(tickprefix="$", ticksuffix="M", gridcolor="#F3F4F6")
    st.plotly_chart(fig_fc, use_container_width=True)

    # Tabla resumen
    st.markdown("#### Detalle semanal")
    df_show = df_fc.copy()
    df_show["cobros"]     = df_show["cobros"].apply(fmt_millones)
    df_show["pagos"]      = df_show["pagos"].apply(fmt_millones)
    df_show["flujo_neto"] = df_show["flujo_neto"].apply(fmt_millones)
    df_show["saldo_proy"] = df_show["saldo_proy"].apply(fmt_millones)
    df_show["semaforo"]   = df_show["semaforo"].map({"verde":"🟢 OK","amarillo":"🟡 Atención","rojo":"🔴 Crítico"})
    st.dataframe(
        df_show[["semana","periodo","cobros","pagos","flujo_neto","saldo_proy","semaforo"]].rename(columns={
            "semana":"Sem","periodo":"Período","cobros":"Cobros","pagos":"Pagos",
            "flujo_neto":"Flujo Neto","saldo_proy":"Saldo Proy.","semaforo":"Estado"
        }),
        use_container_width=True, hide_index=True,
    )

    st.markdown("---")
    st.markdown("""<div style="background:#0D1F3C;border:1px solid #3B82F6;border-radius:8px;padding:12px;font-size:12px;color:#BFDBFE">
        <b>📌 Metodología:</b> Forecast basado en histórico de cobros SAP-SD + pagos programados SAP-TR + 
        estacionalidad farmacéutica histórica. Modelo rolling: se actualiza automáticamente cada semana. 
        Compatible con integración SAP S/4HANA Treasury (TM40) para datos en tiempo real en producción.
    </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# PÁGINA: TESORERÍA — DECISIÓN DE INVERSIÓN FCI
# ══════════════════════════════════════════════════════════════════════
elif pagina == "💰 Tesorería — FCI":
    from datetime import datetime as _dt3

    st.markdown("""
    <div class="cf-header">
        <h1>💰 Tesorería — Decisión de Inversión de Excedentes</h1>
        <p>FCI T+0 · T+1 · LECAPs · Cauciones · Recomendación automática según liquidez real</p>
    </div>""", unsafe_allow_html=True)

    rend = cargar_rendimientos()

    # ── Inputs: saldo y compromisos ────────────────────────────────────
    st.markdown("### 📋 Posición de caja y compromisos")
    st.caption("El sistema descuenta cheques emitidos y compromisos para calcular el excedente REAL invertible")

    # Traer saldos desde SAP si está disponible
    saldo_default = 13_900_000_000
    if SAP_DISPONIBLE:
        try:
            saldos_sap = get_saldos_bancarios()
            saldo_default = sum(b["saldo"] for b in saldos_sap)
        except Exception:
            pass

    # Traer cheques pendientes desde session_state
    cheques_default = 0
    try:
        df_chq = st.session_state.df_cheques
        if not df_chq.empty:
            chq_pend = df_chq[df_chq["estado"].isin(["pendiente","emitido"])]
            cheques_default = float(chq_pend["monto"].sum()) if not chq_pend.empty else 0
    except Exception:
        pass

    col_i1, col_i2 = st.columns(2)
    with col_i1:
        saldo_input = st.number_input(
            "💰 Saldo total bancos ($)",
            value=float(saldo_default), min_value=0.0,
            step=100_000_000.0, format="%.0f",
            help="Se actualiza automáticamente desde SAP cada 3 minutos"
        )
        cheques_input = st.number_input(
            "🏦 Cheques emitidos pendientes ($)",
            value=float(cheques_default), min_value=0.0,
            step=10_000_000.0, format="%.0f",
            help="Cheques emitidos que aún no se debitaron — NO se pueden invertir"
        )
        comp_48h = st.number_input(
            "⚡ Compromisos próximas 48hs ($)",
            value=2_500_000_000.0, min_value=0.0,
            step=100_000_000.0, format="%.0f",
            help="AFIP, sueldos, cuotas préstamos que vencen en 48hs"
        )

    with col_i2:
        comp_7d = st.number_input(
            "📅 Compromisos próximos 7 días ($)",
            value=4_200_000_000.0, min_value=0.0,
            step=100_000_000.0, format="%.0f",
            help="Pagos laboratorios, cuotas, impuestos semana"
        )
        comp_30d = st.number_input(
            "📆 Compromisos próximos 30 días ($)",
            value=9_200_000_000.0, min_value=0.0,
            step=100_000_000.0, format="%.0f",
            help="Total egresos proyectados del mes"
        )
        colchon_pct = st.slider(
            "🛡️ Colchón operativo (%)",
            min_value=5, max_value=30, value=15,
            help="% del saldo que siempre queda en cuenta para imprevistos"
        ) / 100

    # ── Calcular excedente ─────────────────────────────────────────────
    exc = calcular_excedente_real(
        saldo_total=saldo_input,
        cheques_pendientes=cheques_input,
        compromisos_48hs=comp_48h,
        compromisos_7d=comp_7d,
        compromisos_30d=comp_30d,
        colchon_operativo_pct=colchon_pct,
    )

    st.markdown("---")
    st.markdown("### 🔢 Excedente real disponible")

    # Semáforo de excedente
    exc_t0 = exc["excedente_t0"]
    if exc_t0 <= 0:
        color_exc = "#DC2626"
        msg_exc   = "Sin excedente — todos los fondos están comprometidos"
    elif exc_t0 < 500_000_000:
        color_exc = "#D97706"
        msg_exc   = "Excedente bajo — solo T+0"
    elif exc_t0 < 2_000_000_000:
        color_exc = "#2563EB"
        msg_exc   = "Excedente moderado — mix T+0/T+1"
    else:
        color_exc = "#059669"
        msg_exc   = "Excedente alto — optimizar con LECAPs"

    st.markdown(f"""<div style="background:linear-gradient(135deg,{color_exc},{color_exc}CC);
        color:white;border-radius:12px;padding:20px;margin-bottom:16px">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">
            <div>
                <div style="font-size:13px;opacity:0.85">Excedente disponible para invertir (T+0)</div>
                <div style="font-size:40px;font-weight:700">${exc_t0/1e9:.2f}B ARS</div>
                <div style="font-size:13px;opacity:0.9">{msg_exc}</div>
            </div>
            <div style="text-align:right">
                <div style="font-size:12px;opacity:0.8">T+1 disponible</div>
                <div style="font-size:22px;font-weight:600">${exc['excedente_t1']/1e9:.2f}B</div>
                <div style="font-size:12px;opacity:0.8">LECAPs/30d: ${exc['excedente_lecaps']/1e9:.2f}B</div>
            </div>
        </div>
    </div>""", unsafe_allow_html=True)

    # Breakdown del saldo
    ke1,ke2,ke3,ke4,ke5 = st.columns(5)
    with ke1: st.metric("💰 Saldo total", fmt_millones(exc["saldo_total"]))
    with ke2: st.metric("🏦 Cheques emitidos", f"-{fmt_millones(exc['cheques_pendientes'])}", delta_color="inverse")
    with ke3: st.metric("⚡ Compromisos 48hs", f"-{fmt_millones(exc['compromisos_48hs'])}", delta_color="inverse")
    with ke4: st.metric("🛡️ Colchón ({:.0f}%)".format(colchon_pct*100), f"-{fmt_millones(exc['colchon_operativo'])}", delta_color="inverse")
    with ke5: st.metric("✅ Excedente neto", fmt_millones(exc_t0),
                        "Disponible para invertir")

    if exc_t0 <= 0:
        st.warning("⚠️ No hay excedente disponible para invertir. Revisá los compromisos o reducí el colchón operativo.")
        st.stop()

    st.markdown("---")

    # ── Recomendación automática ────────────────────────────────────────
    st.markdown("### 🤖 Recomendación automática")
    rec = recomendar_distribucion(exc, rend)

    st.markdown(f"""<div style="background:#0D2D1F;border:1px solid #10B981;
        border-radius:10px;padding:16px;margin-bottom:16px">
        <div style="font-weight:600;color:#166534;font-size:14px">
            🎯 Perfil: {rec['perfil']}
        </div>
        <div style="color:#374151;font-size:13px;margin-top:4px">
            Rendimiento TNA ponderado: <b>{rec['rendimiento_pond_tna']}%</b> · 
            Ganancia estimada 30 días: <b>${rec['rendimiento_esperado_30d']/1e6:.1f}M ARS</b> · 
            Ganancia anualizada: <b>${rec['rendimiento_esperado_anual']/1e9:.2f}B ARS</b>
        </div>
    </div>""", unsafe_allow_html=True)

    # Cards de distribución recomendada
    cols_rec = st.columns(len(rec["distribucion"]))
    for i, d in enumerate(rec["distribucion"]):
        with cols_rec[i]:
            st.markdown(f"""<div style="background:#fff;border:2px solid {d['color']};
                border-radius:12px;padding:16px;text-align:center">
                <div style="font-size:12px;font-weight:600;color:{d['color']};
                    text-transform:uppercase;margin-bottom:8px">{d['nombre']}</div>
                <div style="font-size:26px;font-weight:700;color:#F1F5F9">
                    ${d['monto']/1e9:.2f}B</div>
                <div style="font-size:13px;color:#64748B">{d['porcentaje']}% del excedente</div>
                <div style="margin:8px 0;font-size:14px;font-weight:600;color:{d['color']}">
                    TNA {d['tna']}%</div>
                <div style="background:#ECFDF5;border-radius:6px;padding:6px;font-size:11px;color:#047857;font-weight:600">
                    +${d['rendimiento_30d']/1e6:.1f}M en 30 días</div>
                <div style="margin-top:8px;font-size:11px;color:#64748B">
                    {d['liquidez']}</div>
                <div style="margin-top:6px;font-size:10px;color:#64748B">
                    🟢 {d['riesgo']}</div>
            </div>""", unsafe_allow_html=True)
            st.markdown(f"<div style='font-size:10px;color:#94A3B8;margin-top:4px;text-align:center'>"
                       f"Ej: {', '.join(d['ejemplos'][:2])}</div>", unsafe_allow_html=True)

    st.markdown("---")

    # ── Comparativa todos los instrumentos ─────────────────────────────
    st.markdown("### 📊 Comparativa de instrumentos")
    col_sim1, col_sim2 = st.columns([1, 2])
    with col_sim1:
        monto_sim = st.number_input(
            "Monto a comparar ($)",
            value=float(round(exc_t0 / 1_000_000) * 1_000_000),
            min_value=0.0, step=1_000_000.0, format="%.0f"
        )
        dias_sim = st.selectbox("Plazo (días)", [1, 7, 30, 60, 90], index=2)

    comparacion = comparar_instrumentos(monto_sim, dias_sim, rend)

    with col_sim2:
        fig_comp = go.Figure()
        nombres  = [c["nombre"].replace("FCI ","").replace("(Letras Capitalizables)","") for c in comparacion]
        ganancias = [c["ganancia"] / 1e6 for c in comparacion]
        colores   = [c["color"] for c in comparacion]
        fig_comp.add_trace(go.Bar(
            x=ganancias, y=nombres, orientation="h",
            marker_color=colores, opacity=0.9,
            text=[f"${g:.1f}M · TNA {c['tna']}%" for g, c in zip(ganancias, comparacion)],
            textposition="outside",
        ))
        fig_comp.update_layout(
            height=280, margin=dict(t=10,b=10,l=10,r=120),
            plot_bgcolor="white", paper_bgcolor="white",
            xaxis=dict(title=f"Ganancia en {dias_sim}d ($M)", gridcolor="#F3F4F6"),
            yaxis=dict(gridcolor="#F3F4F6"),
            font=dict(family="Inter, sans-serif", size=11),
        )
        st.plotly_chart(fig_comp, use_container_width=True)

    # Tabla comparativa
    df_comp = pd.DataFrame(comparacion)
    if not df_comp.empty:
        df_comp["ganancia_fmt"] = df_comp["ganancia"].apply(fmt_millones)
        df_comp["ganancia_diaria_fmt"] = df_comp["ganancia_diaria"].apply(lambda x: f"${x/1e3:.0f}K/día")
        df_comp["tna_fmt"] = df_comp["tna"].apply(lambda x: f"{x:.1f}%")
        st.dataframe(
            df_comp[["nombre","tna_fmt","ganancia_fmt","ganancia_diaria_fmt","liquidez","riesgo"]].rename(columns={
                "nombre":"Instrumento","tna_fmt":"TNA","ganancia_fmt":f"Ganancia {dias_sim}d",
                "ganancia_diaria_fmt":"Por día","liquidez":"Liquidez","riesgo":"Riesgo"
            }),
            use_container_width=True, hide_index=True,
        )

    st.markdown("---")

    # ── Actualizar tasas manualmente ────────────────────────────────────
    with st.expander("⚙️ Actualizar tasas de referencia"):
        st.caption("Actualizar con tasas reales del mercado (CAFCI / BCRA / Broker)")
        cols_tasa = st.columns(3)
        nuevas_tasas = {}
        instrumentos_edit = ["fci_t0","fci_t1","lecaps","caucion","plazo_fijo"]
        for i, key in enumerate(instrumentos_edit):
            with cols_tasa[i % 3]:
                info = rend.get(key, {})
                nuevas_tasas[key] = st.number_input(
                    f"{info.get('nombre',key)} — TNA %",
                    value=float(info.get("tna_ref", 50.0)),
                    min_value=0.0, max_value=300.0,
                    step=0.5, format="%.1f",
                    key=f"tasa_{key}"
                )
        if st.button("💾 Guardar tasas actualizadas", type="primary"):
            for key, tna in nuevas_tasas.items():
                if key in rend:
                    rend[key]["tna_ref"] = tna
                    rend[key]["tna_diaria"] = tna / 365
            guardar_rendimientos(rend)
            st.success("✅ Tasas actualizadas — la recomendación se recalcula automáticamente")
            st.rerun()

    st.markdown("""<div style="background:#0D1F3C;border:1px solid #3B82F6;
        border-radius:8px;padding:12px;font-size:12px;color:#BDD7EE;margin-top:8px">
        <b>📌 Importante:</b> Los cheques emitidos y compromisos de las próximas 48hs están 
        <b>bloqueados</b> y nunca se incluyen en el excedente invertible. 
        El colchón operativo del {:.0f}% garantiza fondos para imprevistos. 
        Tasas de referencia — actualizar con datos reales del broker antes de operar.
    </div>""".format(colchon_pct * 100), unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# ROLLEO DE DEUDA — Reperfilamiento: tramos linkeados al BCRA vs tasa vigente
# ══════════════════════════════════════════════════════════════════════
elif pagina == "🔁 Rolleo de Deuda":
    st.markdown(f"""
    <div class="cf-header">
        <h1>🔁 Rolleo de Deuda — Reperfilamiento y Tasa Vigente</h1>
        <p>Deuda abierta · Tramos linkeados al BCRA vs tasa fija · Decisión rollear / precancelar · {AÑO}</p>
    </div>""", unsafe_allow_html=True)

    # Tasas de referencia (editables; en producción se traen de la API del BCRA)
    if "roll_tasas" not in st.session_state:
        st.session_state.roll_tasas = {
            "badlar": 35.0, "tamar": 34.0, "politica": 29.0, "mercado": 40.0,
        }
    if "roll_tramos" not in st.session_state:
        st.session_state.roll_tramos = pd.DataFrame([
            {"entidad":"Banco Galicia","instrumento":"Préstamo capital de trabajo","capital":8500e6,"base":"BADLAR","spread":4.0,"tasa_fija":0.0,"cuotas":9},
            {"entidad":"ON Clase III (propia)","instrumento":"Obligación negociable","capital":6200e6,"base":"TAMAR","spread":3.0,"tasa_fija":0.0,"cuotas":18},
            {"entidad":"Banco Nación","instrumento":"Prefinanciación importación","capital":2900e6,"base":"POLITICA","spread":6.0,"tasa_fija":0.0,"cuotas":6},
            {"entidad":"Banco Santander","instrumento":"Descubierto acordado","capital":1800e6,"base":"FIJA","spread":0.0,"tasa_fija":48.0,"cuotas":1},
            {"entidad":"Leasing maquinaria","instrumento":"Leasing financiero","capital":3400e6,"base":"FIJA","spread":0.0,"tasa_fija":38.0,"cuotas":24},
            {"entidad":"Cheques descontados","instrumento":"Descuento de valores","capital":2100e6,"base":"FIJA","spread":0.0,"tasa_fija":41.0,"cuotas":3},
        ])

    tasas = st.session_state.roll_tasas

    # ── Panel de tasas de referencia ────────────────────────────────────
    st.markdown("### 📡 Tasas de referencia (BCRA / mercado)")
    st.caption("En producción se sincroniza con la API de Principales Variables del BCRA. Editá para simular escenarios.")
    ct1, ct2, ct3, ct4 = st.columns(4)
    with ct1:
        tasas["badlar"] = st.number_input("BADLAR TNA %", value=float(tasas["badlar"]), step=0.5, format="%.1f", key="r_badlar")
    with ct2:
        tasas["tamar"] = st.number_input("TAMAR TNA %", value=float(tasas["tamar"]), step=0.5, format="%.1f", key="r_tamar")
    with ct3:
        tasas["politica"] = st.number_input("Política monetaria BCRA %", value=float(tasas["politica"]), step=0.5, format="%.1f", key="r_pol")
    with ct4:
        tasas["mercado"] = st.number_input("Tasa vigente refinanciación %", value=float(tasas["mercado"]), step=0.5, format="%.1f", key="r_mkt")

    base_map = {"BADLAR":tasas["badlar"], "TAMAR":tasas["tamar"], "POLITICA":tasas["politica"]}

    # ── Cálculo por tramo ───────────────────────────────────────────────
    df = st.session_state.roll_tramos.copy()
    tasa_mkt = float(tasas["mercado"])

    def _tasa_hoy(row):
        if row["base"] == "FIJA":
            return float(row["tasa_fija"])
        return float(base_map.get(row["base"], 0.0)) + float(row["spread"])

    df["se_relea"]     = df["base"].apply(lambda b: "Sí (linkeada)" if b != "FIJA" else "No (fija)")
    df["tasa_hoy"]     = df.apply(_tasa_hoy, axis=1)
    df["dif_vs_mkt"]   = df["tasa_hoy"] - tasa_mkt
    df["costo_mes"]    = df["capital"] * df["tasa_hoy"] / 100 / 12
    df["costo_mkt"]    = df["capital"] * tasa_mkt / 100 / 12
    df["ahorro_mes"]   = df["costo_mes"] - df["costo_mkt"]   # + = reperfilar ahorra

    def _reco(r):
        if r["dif_vs_mkt"] > 2.0:  return "🔴 Reperfilar / refinanciar"
        if r["dif_vs_mkt"] < -2.0: return "🟢 Mantener (más barata)"
        return "🟡 Neutro — monitorear"
    df["reco"] = df.apply(_reco, axis=1)

    deuda_total   = df["capital"].sum()
    cap_linkeada  = df[df["base"]!="FIJA"]["capital"].sum()
    pct_link      = cap_linkeada / deuda_total * 100 if deuda_total else 0
    tasa_pond     = (df["capital"]*df["tasa_hoy"]).sum()/deuda_total if deuda_total else 0
    costo_mes_tot = df["costo_mes"].sum()
    ahorro_pot    = df[df["ahorro_mes"]>0]["ahorro_mes"].sum()

    st.markdown("---")
    k1,k2,k3,k4,k5 = st.columns(5)
    with k1: st.metric("🏦 Deuda abierta", f"${deuda_total/1e9:,.2f}B")
    with k2: st.metric("🔗 Linkeada al BCRA", f"{pct_link:.0f}%", f"${cap_linkeada/1e9:,.2f}B")
    with k3: st.metric("📊 Tasa prom. ponderada", f"{tasa_pond:.1f}%")
    with k4: st.metric("💸 Costo financiero/mes", f"${costo_mes_tot/1e6:,.0f}M")
    with k5: st.metric("💡 Ahorro potencial/mes", f"${ahorro_pot/1e6:,.0f}M",
                       "reperfilando tramos caros")

    st.markdown("---")
    tab_r1, tab_r2, tab_r3 = st.tabs(["📊 Tasa por tramo", "🧮 Detalle y decisión", "✏️ Editar deuda"])

    # ── TAB 1: gráfico tasa por tramo vs mercado ────────────────────────
    with tab_r1:
        colg1, colg2 = st.columns([1.7, 1])
        with colg1:
            df_o = df.sort_values("tasa_hoy", ascending=True)
            bar_col = ["#DC2626" if d>2 else "#059669" if d<-2 else "#D97706"
                       for d in df_o["dif_vs_mkt"].tolist()]
            fig_r = go.Figure()
            fig_r.add_trace(go.Bar(
                y=df_o["entidad"].tolist(), x=df_o["tasa_hoy"].tolist(),
                orientation="h", marker_color=bar_col,
                text=[f"{t:.1f}%" for t in df_o["tasa_hoy"].tolist()],
                textposition="outside", textfont=dict(size=12, color="#1F2937"),
                hovertemplate="<b>%{y}</b><br>Tasa hoy: %{x:.1f}%<extra></extra>"))
            fig_r.add_vline(x=tasa_mkt, line_dash="dash", line_color="#2563EB", line_width=2,
                annotation_text=f"Tasa vigente mercado: {tasa_mkt:.1f}%",
                annotation_position="top", annotation_font_color="#2563EB")
            fig_r = plotly_layout(fig_r, 380)
            fig_r.update_layout(showlegend=False, xaxis_title="TNA % que paga hoy",
                title=dict(text="Tasa de cada tramo vs tasa vigente de mercado",
                           y=0.99, font=dict(size=13, color="#1F2937")))
            fig_r.update_xaxes(range=[0, max(df["tasa_hoy"].max(), tasa_mkt)*1.25])
            st.plotly_chart(fig_r, use_container_width=True)
            st.caption("🔴 por encima del mercado (conviene reperfilar) · 🟢 por debajo (mantener) · 🟡 en línea")
        with colg2:
            fig_c = go.Figure(go.Pie(
                labels=["Linkeada al BCRA","Tasa fija"],
                values=[cap_linkeada, deuda_total-cap_linkeada], hole=0.5,
                marker=dict(colors=["#2563EB","#6B7280"]),
                textinfo="label+percent", textfont=dict(size=12, color="white"),
                hovertemplate="<b>%{label}</b><br>$%{value:,.0f}<extra></extra>"))
            fig_c.update_layout(height=300, showlegend=False, paper_bgcolor="white",
                margin=dict(t=40,b=10,l=10,r=10),
                title=dict(text="Composición de la deuda abierta",
                           font=dict(size=13, color="#1F2937")))
            st.plotly_chart(fig_c, use_container_width=True)

        # Costo mensual actual vs reperfilado
        st.markdown("#### Costo financiero mensual — actual vs reperfilando a tasa de mercado")
        fig_k = go.Figure()
        fig_k.add_trace(go.Bar(
            x=df["entidad"].tolist(), y=(df["costo_mes"]/1e6).tolist(),
            name="Costo actual", marker_color="#DC2626", opacity=0.85,
            text=[f"${v/1e6:,.0f}M" for v in df["costo_mes"].tolist()],
            textposition="outside", textfont=dict(size=10, color="#1F2937"),
            hovertemplate="<b>%{x}</b><br>Actual: $%{y:,.0f}M<extra></extra>"))
        fig_k.add_trace(go.Bar(
            x=df["entidad"].tolist(), y=(df["costo_mkt"]/1e6).tolist(),
            name="A tasa de mercado", marker_color="#059669", opacity=0.85,
            text=[f"${v/1e6:,.0f}M" for v in df["costo_mkt"].tolist()],
            textposition="outside", textfont=dict(size=10, color="#1F2937"),
            hovertemplate="<b>%{x}</b><br>Mercado: $%{y:,.0f}M<extra></extra>"))
        fig_k = plotly_layout(fig_k, 340)
        fig_k.update_layout(barmode="group", yaxis_title="Millones de $ / mes")
        st.plotly_chart(fig_k, use_container_width=True)

    # ── TAB 2: tabla decisión ───────────────────────────────────────────
    with tab_r2:
        df_show = df.copy()
        df_show["capital_fmt"]  = df_show["capital"].apply(lambda x: f"${x/1e9:,.2f}B")
        df_show["costo_fmt"]    = df_show["costo_mes"].apply(lambda x: f"${x/1e6:,.1f}M")
        df_show["ahorro_fmt"]   = df_show["ahorro_mes"].apply(
            lambda x: f"+${x/1e6:,.1f}M" if x>0 else (f"-${abs(x)/1e6:,.1f}M" if x<0 else "—"))
        st.dataframe(
            df_show[["entidad","instrumento","base","se_relea","capital_fmt",
                     "tasa_hoy","dif_vs_mkt","costo_fmt","ahorro_fmt","cuotas","reco"]],
            hide_index=True, use_container_width=True, height=300,
            column_config={
                "entidad":"Entidad", "instrumento":"Instrumento", "base":"Base tasa",
                "se_relea":"¿Se relea?", "capital_fmt":"Capital abierto",
                "tasa_hoy": st.column_config.NumberColumn("Tasa hoy %", format="%.1f%%"),
                "dif_vs_mkt": st.column_config.NumberColumn("Dif. vs mercado", format="%+.1f pp"),
                "costo_fmt":"Costo/mes", "ahorro_fmt":"Ahorro/mes si reperfila",
                "cuotas":"Cuotas rest.", "reco":"Recomendación",
            })

        caros = df[df["dif_vs_mkt"]>2.0]
        if not caros.empty:
            cap_caros = caros["capital"].sum()
            ah_caros  = caros["ahorro_mes"].sum()
            st.markdown(
                f'<div style="background:#FEE2E2;border-left:4px solid #DC2626;'
                f'padding:12px 16px;border-radius:8px;color:#1F2937;font-size:13px">'
                f'<b>🔴 Reperfilamiento sugerido:</b> {len(caros)} tramos pagan por encima de la '
                f'tasa vigente ({tasa_mkt:.1f}%), por ${cap_caros/1e9:,.2f}B de capital. '
                f'Refinanciarlos o pasarlos a tasa fija de mercado ahorra ~${ah_caros/1e6:,.0f}M por mes '
                f'(${ah_caros*12/1e6:,.0f}M anualizados).</div>',
                unsafe_allow_html=True)
        baratos = df[df["dif_vs_mkt"]<-2.0]
        if not baratos.empty:
            st.markdown(
                f'<div style="background:#D1FAE5;border-left:4px solid #059669;'
                f'padding:12px 16px;border-radius:8px;color:#1F2937;font-size:13px;margin-top:8px">'
                f'<b>🟢 Mantener:</b> {len(baratos)} tramos linkeados pagan por debajo del mercado. '
                f'Conviene rollear al vencimiento y no cancelar anticipadamente.</div>',
                unsafe_allow_html=True)

        st.info("Lógica: los tramos linkeados al BCRA (BADLAR / TAMAR / política monetaria) se releen "
                "automáticamente a la tasa base vigente + spread. Se comparan contra la tasa de "
                "refinanciación de mercado para decidir si conviene rollear, refinanciar o precancelar.")

    # ── TAB 3: editar deuda ─────────────────────────────────────────────
    with tab_r3:
        st.markdown("**Editá los tramos de deuda** — se recalcula todo en vivo. Base: BADLAR, TAMAR, POLITICA o FIJA.")
        edit = st.data_editor(
            st.session_state.roll_tramos, num_rows="dynamic", use_container_width=True, key="roll_editor",
            column_config={
                "entidad":"Entidad", "instrumento":"Instrumento",
                "capital": st.column_config.NumberColumn("Capital abierto $", format="%.0f"),
                "base": st.column_config.SelectboxColumn("Base", options=["BADLAR","TAMAR","POLITICA","FIJA"]),
                "spread": st.column_config.NumberColumn("Spread pp", format="%.1f"),
                "tasa_fija": st.column_config.NumberColumn("Tasa fija % (si aplica)", format="%.1f"),
                "cuotas": st.column_config.NumberColumn("Cuotas rest.", format="%d"),
            })
        if st.button("💾 Guardar cambios", type="primary"):
            st.session_state.roll_tramos = edit
            st.success("✅ Deuda actualizada — el análisis se recalcula")
            st.rerun()

# ══════════════════════════════════════════════════════════════════════
# COMANDO EJECUTIVO — KPIs gerenciales (formato demo, tarjetas semáforo)
# ══════════════════════════════════════════════════════════════════════
elif pagina == "🎯 Comando Ejecutivo":
    st.markdown(f"""
    <div class="cf-header">
        <h1>🎯 Comando Ejecutivo — Tablero de Indicadores</h1>
        <p>Liquidez · Rentabilidad · Endeudamiento · Capital de trabajo · Generación de caja · {AÑO}</p>
    </div>""", unsafe_allow_html=True)

    # Supuestos base (P&L + Balance demo, editables)
    if "ge_base" not in st.session_state:
        st.session_state.ge_base = {
            "ventas": 228_000e6, "margen_bruto_pct": 18.0, "sga_pct": 13.0,
            "deprec_pct": 1.2, "deuda_bruta": 16_500e6, "deuda_neta": 12_600e6,
            "tasa_deuda_pct": 38.0, "pct_link_bcra": 89.0,
            "activo_total": 96_000e6, "activo_cte": 71_000e6, "pasivo_cte": 52_600e6,
            "inventario": 24_500e6, "patrimonio": 34_000e6, "caja": 13_900e6,
            "dso": 42.0, "dio": 38.0, "dpo": 28.0, "capex": 4_200e6,
            "crec_ventas_pct": 6.0, "fill_rate_pct": 96.4, "pct_ventas_credito": 78.0,
        }
    b = st.session_state.ge_base

    with st.expander("⚙️ Ajustar supuestos (P&L y Balance — datos demo)"):
        e = st.columns(4)
        with e[0]:
            b["ventas"] = st.number_input("Ventas anuales $", value=float(b["ventas"]), step=1_000e6, format="%.0f")
            b["margen_bruto_pct"] = st.number_input("Margen bruto %", value=float(b["margen_bruto_pct"]), step=0.5)
            b["sga_pct"] = st.number_input("Gastos SG&A % ventas", value=float(b["sga_pct"]), step=0.5)
            b["deprec_pct"] = st.number_input("Deprec./amort. % ventas", value=float(b["deprec_pct"]), step=0.1)
            b["crec_ventas_pct"] = st.number_input("Crecimiento ventas YoY %", value=float(b["crec_ventas_pct"]), step=0.5)
        with e[1]:
            b["deuda_bruta"] = st.number_input("Deuda bruta $", value=float(b["deuda_bruta"]), step=500e6, format="%.0f")
            b["deuda_neta"] = st.number_input("Deuda neta $", value=float(b["deuda_neta"]), step=500e6, format="%.0f")
            b["tasa_deuda_pct"] = st.number_input("Tasa prom. deuda %", value=float(b["tasa_deuda_pct"]), step=0.5)
            b["pct_link_bcra"] = st.number_input("% deuda linkeada BCRA", value=float(b["pct_link_bcra"]), step=1.0)
            b["capex"] = st.number_input("CapEx anual $", value=float(b["capex"]), step=200e6, format="%.0f")
        with e[2]:
            b["activo_total"] = st.number_input("Activo total $", value=float(b["activo_total"]), step=1_000e6, format="%.0f")
            b["activo_cte"] = st.number_input("Activo corriente $", value=float(b["activo_cte"]), step=1_000e6, format="%.0f")
            b["pasivo_cte"] = st.number_input("Pasivo corriente $", value=float(b["pasivo_cte"]), step=1_000e6, format="%.0f")
            b["inventario"] = st.number_input("Inventario $", value=float(b["inventario"]), step=500e6, format="%.0f")
            b["patrimonio"] = st.number_input("Patrimonio neto $", value=float(b["patrimonio"]), step=1_000e6, format="%.0f")
        with e[3]:
            b["caja"] = st.number_input("Caja y equivalentes $", value=float(b["caja"]), step=500e6, format="%.0f")
            b["dso"] = st.number_input("DSO — días de cobranza", value=float(b["dso"]), step=1.0)
            b["dio"] = st.number_input("DIO — días de inventario", value=float(b["dio"]), step=1.0)
            b["dpo"] = st.number_input("DPO — días de pago", value=float(b["dpo"]), step=1.0)
            b["fill_rate_pct"] = st.number_input("Fill rate %", value=float(b["fill_rate_pct"]), step=0.1)

    # ── Cálculos ────────────────────────────────────────────────────────
    ventas   = b["ventas"]
    costo_v  = ventas * (1 - b["margen_bruto_pct"]/100)
    util_bru = ventas - costo_v
    sga      = ventas * b["sga_pct"]/100
    ebitda   = util_bru - sga
    deprec   = ventas * b["deprec_pct"]/100
    ebit     = ebitda - deprec
    interes  = b["deuda_bruta"] * b["tasa_deuda_pct"]/100
    ebt      = ebit - interes
    impuesto = max(ebt, 0) * 0.35
    util_net = ebt - impuesto

    liq_cte   = b["activo_cte"]/b["pasivo_cte"]
    p_acida   = (b["activo_cte"]-b["inventario"])/b["pasivo_cte"]
    ctw       = b["activo_cte"]-b["pasivo_cte"]
    dias_caja = b["caja"]/((costo_v+sga)/365)

    mg_ebitda = ebitda/ventas*100
    mg_op     = ebit/ventas*100
    mg_neto   = util_net/ventas*100
    roe       = util_net/b["patrimonio"]*100
    roa       = util_net/b["activo_total"]*100
    roic      = ebit*(1-0.35)/(b["deuda_neta"]+b["patrimonio"])*100

    dn_ebitda = b["deuda_neta"]/ebitda if ebitda else 0
    deuda_pat = b["deuda_bruta"]/b["patrimonio"]
    cobertura = ebitda/interes if interes else 0

    dso, dio, dpo = b["dso"], b["dio"], b["dpo"]
    ccc     = dso+dio-dpo
    rot_inv = 365/dio if dio else 0
    rot_act = ventas/b["activo_total"]

    fco   = util_net + deprec           # proxy caja operativa
    fcf   = fco - b["capex"]
    conv  = fco/ebitda*100 if ebitda else 0

    # ── Helpers de tarjeta ──────────────────────────────────────────────
    VERDE, AMAR, ROJO, AZUL = "#10B981", "#F59E0B", "#EF4444", "#3B82F6"
    def _est(v, verde, amar, mayor_mejor=True):
        if mayor_mejor:
            return VERDE if v>=verde else AMAR if v>=amar else ROJO
        return VERDE if v<=verde else AMAR if v<=amar else ROJO
    def _ico(c): return "🟢" if c==VERDE else "🟡" if c==AMAR else "🔴"
    def _card(col, titulo, valor, color, sub):
        col.markdown(
            f'<div style="background:#1E293B;border:1px solid #334155;'
            f'border-left:4px solid {color};border-radius:12px;padding:15px 17px;'
            f'box-shadow:0 4px 12px rgba(0,0,0,0.25);height:118px">'
            f'<div style="font-size:11px;color:#94A3B8;text-transform:uppercase;'
            f'letter-spacing:.5px">{titulo}</div>'
            f'<div style="font-size:29px;font-weight:700;color:#F1F5F9;'
            f'line-height:1.1;margin:5px 0">{valor}</div>'
            f'<div style="font-size:11px;color:{color}">{_ico(color)} {sub}</div>'
            f'</div>', unsafe_allow_html=True)

    # ── Banner: salud financiera global ─────────────────────────────────
    estados = [
        _est(liq_cte,1.2,1.0), _est(p_acida,0.9,0.7), _est(dias_caja,30,15),
        _est(mg_ebitda,4,2.5), _est(mg_neto,1.5,0.5), _est(roic,15,8),
        _est(dn_ebitda,2.0,3.5,False), _est(cobertura,3,1.5), _est(ccc,45,60,False),
        _est(conv,70,45),
    ]
    pts = sum(100 if c==VERDE else 60 if c==AMAR else 25 for c in estados)/len(estados)
    salud_c = VERDE if pts>=75 else AMAR if pts>=50 else ROJO
    salud_txt = "Sólida" if pts>=75 else "Con puntos de atención" if pts>=50 else "Comprometida"
    st.markdown(
        f'<div style="background:linear-gradient(135deg,{salud_c},{salud_c}CC);'
        f'color:white;border-radius:14px;padding:22px;margin-bottom:18px;'
        f'display:flex;justify-content:space-between;align-items:center">'
        f'<div><div style="font-size:13px;opacity:.85">Salud financiera global</div>'
        f'<div style="font-size:42px;font-weight:700">{pts:.0f}<span style="font-size:20px">/100</span></div>'
        f'<div style="font-size:14px;opacity:.9">{salud_txt}</div></div>'
        f'<div style="text-align:right">'
        f'<div style="font-size:12px;opacity:.8">Ventas anuales</div>'
        f'<div style="font-size:26px;font-weight:600">${ventas/1e9:,.0f}B</div>'
        f'<div style="font-size:12px;opacity:.8">EBITDA ${ebitda/1e9:,.1f}B · Neto ${util_net/1e9:,.1f}B</div>'
        f'</div></div>', unsafe_allow_html=True)

    # ── Liquidez ────────────────────────────────────────────────────────
    st.markdown("### 💧 Liquidez y solvencia de corto plazo")
    c = st.columns(4)
    _card(c[0],"Liquidez corriente",f"{liq_cte:.2f}x",_est(liq_cte,1.2,1.0),"Activo cte / Pasivo cte · meta >1,2")
    _card(c[1],"Prueba ácida",f"{p_acida:.2f}x",_est(p_acida,0.9,0.7),"Sin inventario · meta >0,9")
    _card(c[2],"Capital de trabajo",f"${ctw/1e9:,.1f}B",_est(ctw,1,0),"Activo cte − Pasivo cte")
    _card(c[3],"Días de caja",f"{dias_caja:.0f} d",_est(dias_caja,30,15),"Runway operativo · meta >30")

    # ── Rentabilidad ────────────────────────────────────────────────────
    st.markdown("### 📈 Rentabilidad")
    c = st.columns(4)
    _card(c[0],"Margen bruto",f"{b['margen_bruto_pct']:.1f}%",_est(b['margen_bruto_pct'],16,12),"Típico distribuidora 15-20%")
    _card(c[1],"Margen EBITDA",f"{mg_ebitda:.1f}%",_est(mg_ebitda,4,2.5),"Meta sector >4%")
    _card(c[2],"Margen operativo",f"{mg_op:.1f}%",_est(mg_op,3,1.5),"EBIT / ventas")
    _card(c[3],"Margen neto",f"{mg_neto:.2f}%",_est(mg_neto,1.5,0.5),"Utilidad neta / ventas")
    c = st.columns(4)
    _card(c[0],"ROE",f"{roe:.1f}%",_est(roe,15,8),"Retorno sobre patrimonio")
    _card(c[1],"ROA",f"{roa:.1f}%",_est(roa,6,3),"Retorno sobre activos")
    _card(c[2],"ROIC",f"{roic:.1f}%",_est(roic,15,8),"Retorno sobre capital invertido")
    _card(c[3],"Rotación de activos",f"{rot_act:.2f}x",_est(rot_act,2,1),"Ventas / activo total")

    # ── Endeudamiento ───────────────────────────────────────────────────
    st.markdown("### 🏦 Endeudamiento y estructura de capital")
    c = st.columns(4)
    _card(c[0],"Deuda neta / EBITDA",f"{dn_ebitda:.2f}x",_est(dn_ebitda,2.0,3.5,False),"Apalancamiento · meta <2,5")
    _card(c[1],"Cobertura intereses",f"{cobertura:.1f}x",_est(cobertura,3,1.5),"EBITDA / intereses · meta >3")
    _card(c[2],"Deuda / Patrimonio",f"{deuda_pat:.2f}x",_est(deuda_pat,1.0,2.0,False),"Leverage contable")
    _card(c[3],"Deuda linkeada BCRA",f"{b['pct_link_bcra']:.0f}%",AZUL,"Expuesta a BADLAR/TAMAR — ver Rolleo")

    # ── Capital de trabajo ──────────────────────────────────────────────
    st.markdown("### 🔄 Capital de trabajo y eficiencia")
    c = st.columns(4)
    _card(c[0],"DSO — cobranza",f"{dso:.0f} d",_est(dso,40,55,False),"Días promedio de cobro")
    _card(c[1],"DIO — inventario",f"{dio:.0f} d",_est(dio,40,55,False),"Días de stock")
    _card(c[2],"DPO — pago",f"{dpo:.0f} d",_est(dpo,25,15),"Días de pago a proveedores")
    _card(c[3],"CCC — ciclo de caja",f"{ccc:.0f} d",_est(ccc,45,60,False),"DSO + DIO − DPO · meta <45")

    # ── Generación de caja ──────────────────────────────────────────────
    st.markdown("### 💵 Generación de caja")
    c = st.columns(4)
    _card(c[0],"Cash flow operativo",f"${fco/1e9:,.1f}B",_est(fco,1,0),"Caja generada por la operación")
    _card(c[1],"Free cash flow",f"${fcf/1e9:,.1f}B",_est(fcf,1,0),"FCO − CapEx")
    _card(c[2],"Conversión EBITDA→caja",f"{conv:.0f}%",_est(conv,70,45),"FCO / EBITDA · meta >70%")
    _card(c[3],"Crecimiento ventas",f"{b['crec_ventas_pct']:+.1f}%",_est(b['crec_ventas_pct'],5,0),"Interanual nominal")

    st.markdown("---")
    g1, g2 = st.columns([1.4, 1])

    # Puente P&L (waterfall)
    with g1:
        st.markdown("#### Puente de resultado — de ventas a utilidad neta ($B)")
        fig_w = go.Figure(go.Waterfall(
            orientation="v",
            measure=["absolute","relative","relative","relative","relative","relative","total"],
            x=["Ventas","(-) Costo","(-) SG&A","(-) Deprec.","(-) Intereses","(-) Impuesto","Utilidad neta"],
            y=[ventas/1e9, -costo_v/1e9, -sga/1e9, -deprec/1e9, -interes/1e9, -impuesto/1e9, util_net/1e9],
            text=[f"${ventas/1e9:,.0f}", f"-${costo_v/1e9:,.0f}", f"-${sga/1e9:,.1f}",
                  f"-${deprec/1e9:,.1f}", f"-${interes/1e9:,.1f}", f"-${impuesto/1e9:,.1f}",
                  f"${util_net/1e9:,.1f}"],
            textposition="outside", textfont=dict(size=11, color="#F1F5F9"),
            connector=dict(line=dict(color="#475569")),
            increasing=dict(marker=dict(color="#10B981")),
            decreasing=dict(marker=dict(color="#EF4444")),
            totals=dict(marker=dict(color="#3B82F6"))))
        fig_w.update_layout(height=360, paper_bgcolor="#1E293B", plot_bgcolor="#1E293B",
            font=dict(color="#F1F5F9", size=11), margin=dict(t=30,b=30,l=10,r=10),
            xaxis=dict(gridcolor="#334155", tickfont=dict(color="#CBD5E1")),
            yaxis=dict(gridcolor="#334155", tickfont=dict(color="#CBD5E1"), title="Miles de millones $"))
        st.plotly_chart(fig_w, use_container_width=True)

    # CCC descompuesto
    with g2:
        st.markdown("#### Ciclo de conversión de caja")
        fig_ccc = go.Figure()
        fig_ccc.add_trace(go.Bar(x=["DSO","DIO","(-) DPO","= CCC"],
            y=[dso, dio, -dpo, ccc],
            marker_color=["#3B82F6","#F59E0B","#EF4444","#10B981"],
            text=[f"{dso:.0f}d", f"{dio:.0f}d", f"-{dpo:.0f}d", f"{ccc:.0f}d"],
            textposition="outside", textfont=dict(size=13, color="#F1F5F9")))
        fig_ccc.update_layout(height=360, paper_bgcolor="#1E293B", plot_bgcolor="#1E293B",
            font=dict(color="#F1F5F9"), showlegend=False, margin=dict(t=30,b=30,l=10,r=10),
            xaxis=dict(tickfont=dict(color="#CBD5E1")),
            yaxis=dict(gridcolor="#334155", tickfont=dict(color="#CBD5E1"), title="Días"))
        st.plotly_chart(fig_ccc, use_container_width=True)

    st.caption("Datos de demostración a escala Droguería del Sud. En producción los indicadores se "
               "alimentan del cierre contable (SAP) y del módulo de cashflow. Los semáforos comparan "
               "contra metas de referencia editables en el código.")

# ══════════════════════════════════════════════════════════════════════
# PRODUCTOS Y ESTACIONALIDAD — proyección de ventas ajustada por precio
# ══════════════════════════════════════════════════════════════════════
elif pagina == "📦 Productos y Estacionalidad":
    st.markdown(f"""
    <div class="cf-header">
        <h1>📦 Productos y Estacionalidad</h1>
        <p>Ventas por unidad histórica · Patrón estacional · Proyección ajustada por precio · {AÑO}</p>
    </div>""", unsafe_allow_html=True)

    MESES3 = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
    # Catálogo demo por categoría: precio unitario, volumen mensual base (unid), índice estacional
    if "prod_cat" not in st.session_state:
        st.session_state.prod_cat = pd.DataFrame([
            {"cat":"Respiratorios / antigripales","precio":8500,"vol":42000,
             "estac":[1.35,1.20,0.95,0.85,1.05,1.45,1.60,1.50,1.00,0.85,0.80,0.90]},
            {"cat":"Dermocosmética / solares","precio":14200,"vol":18000,
             "estac":[1.55,1.45,1.10,0.85,0.70,0.60,0.55,0.60,0.80,1.05,1.30,1.45]},
            {"cat":"Analgésicos / AINEs","precio":5200,"vol":65000,
             "estac":[1.05,1.00,1.02,0.98,1.00,1.03,1.05,1.04,0.99,0.97,0.96,0.91]},
            {"cat":"Cardiovascular / crónicos","precio":11800,"vol":38000,
             "estac":[1.02,0.99,1.01,1.00,1.00,1.01,1.02,1.01,1.00,0.99,0.98,0.97]},
            {"cat":"Antialérgicos","precio":9600,"vol":22000,
             "estac":[0.75,0.80,0.95,1.15,1.05,0.85,0.80,0.90,1.35,1.55,1.40,1.05]},
            {"cat":"Gastrointestinales","precio":6800,"vol":30000,
             "estac":[1.20,1.00,0.95,0.95,0.98,1.00,1.02,1.00,0.98,1.00,1.10,1.40]},
        ])
    cat = st.session_state.prod_cat

    # ── Controles de proyección ─────────────────────────────────────────
    st.markdown("### 🎛️ Supuestos de proyección")
    cc1, cc2, cc3 = st.columns(3)
    with cc1:
        aj_precio = st.slider("Ajuste de precio de lista %", -20.0, 120.0, 0.0, 2.5,
                              help="Aumento de precios sobre la lista histórica")
    with cc2:
        crec_vol = st.slider("Crecimiento de volumen %", -30.0, 40.0, 0.0, 1.0,
                             help="Variación de unidades vs histórico")
    with cc3:
        mes_foco = st.selectbox("Mes a analizar", MESES3, index=date.today().month-1)
    idx_mes = MESES3.index(mes_foco)

    # ── Cálculos ────────────────────────────────────────────────────────
    fp = 1 + aj_precio/100
    fv = 1 + crec_vol/100
    filas = []
    serie_mensual_ars = [0.0]*12
    serie_mensual_un  = [0.0]*12
    for _, r in cat.iterrows():
        estac = list(r["estac"])
        prom_e = sum(estac)/12
        unid_anio = 0.0; fact_anio = 0.0
        precio_aj = r["precio"]*fp
        for m in range(12):
            un = r["vol"]*estac[m]*fv
            ars = un*precio_aj
            unid_anio += un; fact_anio += ars
            serie_mensual_ars[m] += ars
            serie_mensual_un[m]  += un
        mes_pico = MESES3[estac.index(max(estac))]
        amplitud = (max(estac)-min(estac))/prom_e*100 if prom_e else 0
        filas.append({
            "cat":r["cat"], "precio_lista":r["precio"], "precio_aj":precio_aj,
            "vol_mes":r["vol"], "unid_anio":unid_anio, "fact_anio":fact_anio,
            "mes_pico":mes_pico, "amplitud":amplitud,
            "un_mes":r["vol"]*estac[idx_mes]*fv,
            "ars_mes":r["vol"]*estac[idx_mes]*fv*precio_aj,
        })
    dfp = pd.DataFrame(filas).sort_values("fact_anio", ascending=False)

    fact_total = dfp["fact_anio"].sum()
    unid_total = dfp["unid_anio"].sum()
    ticket     = fact_total/unid_total if unid_total else 0
    top_cat    = dfp.iloc[0]["cat"]
    mas_estac  = dfp.sort_values("amplitud", ascending=False).iloc[0]

    st.markdown("---")
    k1,k2,k3,k4 = st.columns(4)
    with k1: st.metric("📦 Unidades/año proy.", f"{unid_total/1e6:,.2f}M u.")
    with k2: st.metric("💰 Facturación/año proy.", f"${fact_total/1e9:,.1f}B",
                       f"precio {aj_precio:+.0f}% · vol {crec_vol:+.0f}%")
    with k3: st.metric("🎫 Ticket promedio", f"${ticket:,.0f}")
    with k4: st.metric("🌡️ Más estacional", mas_estac["cat"].split(" / ")[0],
                       f"amplitud {mas_estac['amplitud']:.0f}% · pico {mas_estac['mes_pico']}")

    tab_p1, tab_p2, tab_p3 = st.tabs(["📈 Estacionalidad", "💰 Proyección por categoría", "✏️ Editar catálogo"])

    # ── TAB 1: curvas de estacionalidad + facturación mensual ───────────
    with tab_p1:
        st.markdown("#### Índice estacional por categoría (1,00 = promedio del año)")
        fig_e = go.Figure()
        palette = ["#3B82F6","#F59E0B","#10B981","#8B5CF6","#EF4444","#06B6D4"]
        for i,(_,r) in enumerate(cat.iterrows()):
            fig_e.add_trace(go.Scatter(
                x=MESES3, y=r["estac"], mode="lines+markers",
                name=r["cat"].split(" / ")[0], line=dict(width=3, color=palette[i%len(palette)]),
                marker=dict(size=6),
                hovertemplate="<b>%{x}</b><br>Índice: %{y:.2f}<extra></"+"extra>"))
        fig_e.add_hline(y=1.0, line_dash="dash", line_color="#94A3B8")
        fig_e = plotly_layout(fig_e, 380)
        fig_e.update_layout(yaxis_title="Índice estacional")
        st.plotly_chart(fig_e, use_container_width=True)

        st.markdown("#### Facturación total proyectada por mes (MM$)")
        col_pk = ["#10B981" if v==max(serie_mensual_ars) else "#3B82F6" for v in serie_mensual_ars]
        fig_m = go.Figure(go.Bar(
            x=MESES3, y=[v/1e6 for v in serie_mensual_ars], marker_color=col_pk,
            text=[f"${v/1e6:,.0f}M" for v in serie_mensual_ars], textposition="outside",
            textfont=dict(size=10, color="#1F2937"),
            hovertemplate="<b>%{x}</b><br>$%{y:,.0f}M<extra></"+"extra>"))
        fig_m = plotly_layout(fig_m, 320)
        fig_m.update_layout(showlegend=False, yaxis_title="MM$")
        st.plotly_chart(fig_m, use_container_width=True)

    # ── TAB 2: facturación por categoría + tabla ────────────────────────
    with tab_p2:
        fig_c = go.Figure(go.Bar(
            y=dfp["cat"].tolist(), x=(dfp["fact_anio"]/1e9).tolist(), orientation="h",
            marker_color="#3B82F6",
            text=[f"${v/1e9:,.1f}B" for v in dfp["fact_anio"].tolist()],
            textposition="outside", textfont=dict(size=11, color="#1F2937"),
            hovertemplate="<b>%{y}</b><br>$%{x:,.1f}B/año<extra></"+"extra>"))
        fig_c = plotly_layout(fig_c, 320)
        fig_c.update_layout(showlegend=False, xaxis_title="Facturación anual proyectada (B$)")
        st.plotly_chart(fig_c, use_container_width=True)

        st.markdown(f"#### Detalle por categoría — proyección de {mes_foco}")
        dfx = dfp.copy()
        dfx["precio_lista"] = dfx["precio_lista"].apply(lambda x: f"${x:,.0f}")
        dfx["precio_aj"]    = dfx["precio_aj"].apply(lambda x: f"${x:,.0f}")
        dfx["unid_anio"]    = dfx["unid_anio"].apply(lambda x: f"{x/1e3:,.0f}K u.")
        dfx["fact_anio"]    = dfx["fact_anio"].apply(lambda x: f"${x/1e9:,.2f}B")
        dfx["un_mes"]       = dfx["un_mes"].apply(lambda x: f"{x/1e3:,.1f}K u.")
        dfx["ars_mes"]      = dfx["ars_mes"].apply(lambda x: f"${x/1e6:,.0f}M")
        dfx["amplitud"]     = dfx["amplitud"].apply(lambda x: f"{x:.0f}%")
        st.dataframe(
            dfx[["cat","precio_lista","precio_aj","unid_anio","fact_anio",
                 "mes_pico","amplitud","un_mes","ars_mes"]],
            hide_index=True, use_container_width=True,
            column_config={
                "cat":"Categoría","precio_lista":"Precio lista","precio_aj":"Precio ajustado",
                "unid_anio":"Unidades/año","fact_anio":"Facturación/año",
                "mes_pico":"Mes pico","amplitud":"Amplitud estac.",
                "un_mes":f"Unid. {mes_foco}","ars_mes":f"Facturación {mes_foco}",
            })
        st.caption("La proyección multiplica el volumen histórico por el índice estacional del mes y por "
                   "el crecimiento de volumen, y valoriza a precio de lista ajustado. Datos de demostración.")

    # ── TAB 3: editar catálogo ──────────────────────────────────────────
    with tab_p3:
        st.markdown("**Editá precio y volumen base por categoría.** El patrón estacional se mantiene.")
        cat_edit = cat[["cat","precio","vol"]].copy()
        ed = st.data_editor(cat_edit, num_rows="fixed", use_container_width=True, key="prod_editor",
            column_config={
                "cat":"Categoría",
                "precio": st.column_config.NumberColumn("Precio unitario $", format="%.0f"),
                "vol": st.column_config.NumberColumn("Volumen mensual base (u.)", format="%.0f"),
            })
        if st.button("💾 Guardar catálogo", type="primary"):
            base = st.session_state.prod_cat.copy()
            base["precio"] = ed["precio"].values
            base["vol"] = ed["vol"].values
            st.session_state.prod_cat = base
            st.success("✅ Catálogo actualizado — proyección recalculada")
            st.rerun()
