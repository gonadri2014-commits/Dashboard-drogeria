"""
gestor_tesoreria.py — Droguería del Sud
Motor de decisión de inversión de excedentes de tesorería
-----------------------------------------------------------
Lógica enterprise:
  1. Calcula excedente REAL = saldo bancos - cheques emitidos - compromisos 48hs/7d/30d
  2. Compara rendimientos: T+0, T+1, LECAPs, Plazo Fijo, Cauciones
  3. Recomienda distribución óptima según horizonte y monto
  4. Nunca sugiere invertir fondos comprometidos

Instrumentos cubiertos (mercado argentino):
  - FCI Money Market T+0  (ej: Mercado Fondo, Sigma, Pellegrini)
  - FCI Renta Fija T+1    (ej: Balanz, IOL, PPI)
  - LECAPs                (Letras Capitalizables del Tesoro)
  - Cauciones bursátiles  (1-7 días)
  - Plazo fijo UVA / tradicional
"""

import json
import os
from datetime import datetime, timedelta
from typing import Optional

# ── Rendimientos de referencia (actualizables manualmente o vía API) ──
# Fuente: CAFCI + BCRA + mercado secundario
RENDIMIENTOS_REFERENCIA = {
    "fci_t0": {
        "nombre":      "FCI Money Market T+0",
        "descripcion": "Rescate mismo día hábil. Invierte en plazos fijos, cauciones y cuentas remuneradas.",
        "tna_ref":     52.0,
        "tea_ref":     67.2,
        "tna_diaria":  52.0 / 365,
        "liquidez":    "Mismo día (antes de las 15hs)",
        "riesgo":      "Muy bajo",
        "minimo":      100_000,
        "ejemplos":    ["Mercado Fondo (ML)", "Sigma Pesos", "Pellegrini Pesos", "Balanz Money Market"],
        "color":       "#059669",
    },
    "fci_t1": {
        "nombre":      "FCI Renta Fija CP T+1",
        "descripcion": "Rescate día hábil siguiente. Mayor rendimiento que T+0. Invierte en Lecaps y bonos cortos.",
        "tna_ref":     58.0,
        "tea_ref":     75.8,
        "tna_diaria":  58.0 / 365,
        "liquidez":    "Día hábil siguiente",
        "riesgo":      "Bajo",
        "minimo":      500_000,
        "ejemplos":    ["Balanz Capital RF", "IOL Premier Renta Pesos", "PPI Renta en Pesos"],
        "color":       "#2563EB",
    },
    "lecaps": {
        "nombre":      "LECAPs (Letras Capitalizables)",
        "descripcion": "Letras del Tesoro Nacional a tasa fija. Vencimientos 30-180 días. Mercado secundario líquido.",
        "tna_ref":     55.0,
        "tea_ref":     71.0,
        "tna_diaria":  55.0 / 365,
        "liquidez":    "Mercado secundario (mismo día) o vencimiento",
        "riesgo":      "Bajo (soberano ARS)",
        "minimo":      1_000_000,
        "ejemplos":    ["S16J5", "S31J5", "S29A5 — vía BYMA / MAE"],
        "color":       "#7C3AED",
    },
    "caucion": {
        "nombre":      "Caución Bursátil",
        "descripcion": "Préstamo garantizado en bolsa. Plazo 1-7 días. Muy alta liquidez.",
        "tna_ref":     48.0,
        "tea_ref":     61.0,
        "tna_diaria":  48.0 / 365,
        "liquidez":    "Al vencimiento (1-7 días)",
        "riesgo":      "Muy bajo (garantía BYMA)",
        "minimo":      100_000,
        "ejemplos":    ["Caución tomadora 1d", "Caución tomadora 7d"],
        "color":       "#D97706",
    },
    "plazo_fijo": {
        "nombre":      "Plazo Fijo Tradicional",
        "descripcion": "Depósito bancario 30 días mínimo. Sin liquidez anticipada.",
        "tna_ref":     38.0,
        "tea_ref":     46.4,
        "tna_diaria":  38.0 / 365,
        "liquidez":    "Al vencimiento (30+ días)",
        "riesgo":      "Muy bajo (garantía SEDESA $50M)",
        "minimo":      1_000_000,
        "ejemplos":    ["BNA", "Galicia", "BBVA", "Credicoop"],
        "color":       "#64748B",
    },
    "plazo_fijo_uva": {
        "nombre":      "Plazo Fijo UVA",
        "descripcion": "Ajustado por inflación + spread. Mínimo 90 días. Para cobertura inflacionaria.",
        "tna_ref":     3.0,   # spread sobre UVA
        "tea_ref":     None,  # depende de inflación
        "tna_diaria":  None,
        "liquidez":    "Al vencimiento (90+ días) o precancelación 30d",
        "riesgo":      "Bajo (riesgo inflación cubierto)",
        "minimo":      1_000_000,
        "ejemplos":    ["BNA UVA", "Galicia UVA"],
        "color":       "#0891B2",
    },
}

# ── Archivo de configuración de rendimientos (actualizables) ──────────
REND_PATH = os.path.join(os.path.dirname(__file__), "../../data/rendimientos_fci.json")

def cargar_rendimientos() -> dict:
    """Carga rendimientos del archivo o usa los de referencia."""
    if os.path.exists(REND_PATH):
        try:
            with open(REND_PATH) as f:
                guardados = json.load(f)
            # Merge con los de referencia (los guardados tienen prioridad)
            resultado = dict(RENDIMIENTOS_REFERENCIA)
            for k, v in guardados.items():
                if k in resultado:
                    resultado[k].update(v)
            return resultado
        except Exception:
            pass
    return dict(RENDIMIENTOS_REFERENCIA)

def guardar_rendimientos(rend: dict):
    """Guarda rendimientos actualizados."""
    os.makedirs(os.path.dirname(REND_PATH), exist_ok=True)
    # Solo guardar las tasas (no los metadatos estáticos)
    a_guardar = {k: {"tna_ref": v["tna_ref"], "tea_ref": v.get("tea_ref"), "actualizado": datetime.now().strftime("%d/%m/%Y %H:%M")}
                 for k, v in rend.items()}
    with open(REND_PATH, "w") as f:
        json.dump(a_guardar, f, indent=2)


def calcular_excedente_real(
    saldo_total: float,
    cheques_pendientes: float = 0,
    compromisos_48hs: float = 0,
    compromisos_7d: float = 0,
    compromisos_30d: float = 0,
    colchon_operativo_pct: float = 0.15,
) -> dict:
    """
    Calcula el excedente REAL disponible para invertir.
    
    Lógica:
      - Saldo total bancos
      - Menos cheques emitidos pendientes de débito
      - Menos compromisos próximas 48hs (AFIP, sueldos, cuotas)
      - Menos colchón operativo (15% por defecto — para imprevistos)
      - El resto se puede invertir, segmentado por horizonte
    """
    colchon = saldo_total * colchon_operativo_pct
    
    # Saldo neto después de compromisos inmediatos
    saldo_neto_48hs = saldo_total - cheques_pendientes - compromisos_48hs - colchon
    saldo_neto_7d   = saldo_total - cheques_pendientes - compromisos_48hs - compromisos_7d - colchon
    saldo_neto_30d  = saldo_total - cheques_pendientes - compromisos_48hs - compromisos_7d - compromisos_30d - colchon

    return {
        "saldo_total":          saldo_total,
        "cheques_pendientes":   cheques_pendientes,
        "compromisos_48hs":     compromisos_48hs,
        "compromisos_7d":       compromisos_7d,
        "compromisos_30d":      compromisos_30d,
        "colchon_operativo":    colchon,
        "colchon_pct":          colchon_operativo_pct,
        # Excedentes por horizonte
        "excedente_t0":         max(0, saldo_neto_48hs),   # Invertir en T+0
        "excedente_t1":         max(0, saldo_neto_7d),     # Invertir en T+1
        "excedente_lecaps":     max(0, saldo_neto_30d),    # Invertir en LECAPs / PF
        "excedente_total":      max(0, saldo_neto_48hs),   # Total disponible
        "pct_excedente":        round(max(0, saldo_neto_48hs) / saldo_total * 100, 1) if saldo_total > 0 else 0,
    }


def recomendar_distribucion(excedente: dict, rend: dict = None) -> dict:
    """
    Recomienda cómo distribuir el excedente entre instrumentos.
    
    Reglas de decisión (lógica tesorero corporativo):
      - Excedente < $100M    → Todo T+0 (liquidez máxima)
      - $100M - $500M        → 60% T+0 / 40% T+1
      - $500M - $2B          → 40% T+0 / 40% T+1 / 20% LECAPs
      - > $2B                → 30% T+0 / 30% T+1 / 30% LECAPs / 10% Caución
    """
    if rend is None:
        rend = cargar_rendimientos()

    exc_t0    = excedente["excedente_t0"]
    exc_t1    = excedente["excedente_t1"]
    exc_lecap = excedente["excedente_lecaps"]

    if exc_t0 <= 0:
        return {
            "recomendacion": "sin_excedente",
            "mensaje": "No hay excedente disponible para invertir — todos los fondos están comprometidos.",
            "distribucion": [],
            "rendimiento_esperado_anual": 0,
            "rendimiento_esperado_30d": 0,
        }

    # Determinar distribución según monto
    if exc_t0 < 100_000_000:
        dist = [("fci_t0", exc_t0, 1.0)]
        perfil = "Liquidez total — monto bajo"
    elif exc_t0 < 500_000_000:
        dist = [
            ("fci_t0", exc_t0 * 0.60, 0.60),
            ("fci_t1", exc_t1 * 0.40, 0.40),
        ]
        perfil = "Liquidez alta — mix T+0/T+1"
    elif exc_t0 < 2_000_000_000:
        dist = [
            ("fci_t0",  exc_t0    * 0.40, 0.40),
            ("fci_t1",  exc_t1    * 0.40, 0.40),
            ("lecaps",  exc_lecap * 0.20, 0.20),
        ]
        perfil = "Balance liquidez/rendimiento"
    else:
        dist = [
            ("fci_t0",  exc_t0    * 0.30, 0.30),
            ("fci_t1",  exc_t1    * 0.30, 0.30),
            ("lecaps",  exc_lecap * 0.30, 0.30),
            ("caucion", exc_t0    * 0.10, 0.10),
        ]
        perfil = "Optimización rendimiento — excedente alto"

    # Calcular rendimiento esperado ponderado
    rendimiento_pond = 0
    distribucion_detalle = []
    for instrumento, monto, pct in dist:
        if monto <= 0:
            continue
        info = rend.get(instrumento, {})
        tna = info.get("tna_ref", 0)
        rendimiento_30d = monto * (tna / 100) * (30 / 365)
        rendimiento_pond += tna * pct
        distribucion_detalle.append({
            "instrumento":    instrumento,
            "nombre":         info.get("nombre", instrumento),
            "monto":          round(monto),
            "porcentaje":     round(pct * 100, 1),
            "tna":            tna,
            "liquidez":       info.get("liquidez", "—"),
            "riesgo":         info.get("riesgo", "—"),
            "rendimiento_30d": round(rendimiento_30d),
            "ejemplos":       info.get("ejemplos", []),
            "color":          info.get("color", "#2E75B6"),
        })

    rend_total_30d = sum(d["rendimiento_30d"] for d in distribucion_detalle)

    return {
        "recomendacion":          "invertir",
        "perfil":                 perfil,
        "excedente_total":        exc_t0,
        "distribucion":           distribucion_detalle,
        "rendimiento_pond_tna":   round(rendimiento_pond, 2),
        "rendimiento_esperado_30d": rend_total_30d,
        "rendimiento_esperado_anual": round(exc_t0 * rendimiento_pond / 100),
        "mensaje":                f"Excedente ${exc_t0/1e9:.2f}B disponible — rendimiento esperado 30d: ${rend_total_30d/1e6:.1f}M",
        "timestamp":              datetime.now().strftime("%d/%m/%Y %H:%M"),
    }


def comparar_instrumentos(monto: float, dias: int = 30, rend: dict = None) -> list:
    """
    Compara todos los instrumentos para un monto y plazo dados.
    Retorna lista ordenada por rendimiento.
    """
    if rend is None:
        rend = cargar_rendimientos()

    comparacion = []
    for key, info in rend.items():
        tna = info.get("tna_ref", 0)
        if not tna:
            continue
        if monto < info.get("minimo", 0):
            continue
        ganancia = round(monto * (tna / 100) * (dias / 365))
        comparacion.append({
            "instrumento": key,
            "nombre":      info["nombre"],
            "tna":         tna,
            "tea":         info.get("tea_ref"),
            "ganancia":    ganancia,
            "ganancia_diaria": round(monto * (tna / 100) / 365),
            "liquidez":    info["liquidez"],
            "riesgo":      info["riesgo"],
            "ejemplos":    info.get("ejemplos", []),
            "color":       info.get("color", "#2E75B6"),
            "apto":        monto >= info.get("minimo", 0),
        })

    comparacion.sort(key=lambda x: x["tna"], reverse=True)
    return comparacion


def simular_rendimiento(monto: float, instrumento: str, dias: int = 30, rend: dict = None) -> dict:
    """Simula el rendimiento de un instrumento para un monto y plazo."""
    if rend is None:
        rend = cargar_rendimientos()
    info = rend.get(instrumento, {})
    tna = info.get("tna_ref", 0)
    ganancia = monto * (tna / 100) * (dias / 365)
    monto_final = monto + ganancia
    return {
        "instrumento":  instrumento,
        "nombre":       info.get("nombre", instrumento),
        "monto_inicial": monto,
        "dias":         dias,
        "tna":          tna,
        "ganancia":     round(ganancia),
        "monto_final":  round(monto_final),
        "ganancia_diaria": round(monto * tna / 100 / 365),
    }


if __name__ == "__main__":
    print("=== TEST GESTOR TESORERÍA ===")
    # Simular DdS: saldo $13.9B, cheques $800M, compromisos 48hs $2.5B
    exc = calcular_excedente_real(
        saldo_total=13_900_000_000,
        cheques_pendientes=800_000_000,
        compromisos_48hs=2_500_000_000,
        compromisos_7d=4_200_000_000,
        compromisos_30d=9_200_000_000,
    )
    print(f"Saldo total:      ${exc['saldo_total']/1e9:.2f}B")
    print(f"Comprometido:     ${(exc['cheques_pendientes']+exc['compromisos_48hs']+exc['colchon_operativo'])/1e9:.2f}B")
    print(f"Excedente T+0:    ${exc['excedente_t0']/1e9:.2f}B")
    print(f"Excedente T+1:    ${exc['excedente_t1']/1e9:.2f}B")
    print(f"Excedente LECAPs: ${exc['excedente_lecaps']/1e9:.2f}B")

    rec = recomendar_distribucion(exc)
    print(f"\nPerfil: {rec['perfil']}")
    print(f"Rendimiento TNA pond.: {rec['rendimiento_pond_tna']}%")
    print(f"Ganancia esperada 30d: ${rec['rendimiento_esperado_30d']/1e6:.1f}M")
    for d in rec["distribucion"]:
        print(f"  {d['nombre']}: ${d['monto']/1e9:.2f}B ({d['porcentaje']}%) — TNA {d['tna']}%")

    comp = comparar_instrumentos(1_000_000_000, dias=30)
    print(f"\nComparativa $1B / 30 días:")
    for c in comp:
        print(f"  {c['nombre']}: TNA {c['tna']}% → +${c['ganancia']/1e6:.1f}M")

    print("\n✅ Gestor Tesorería OK")
