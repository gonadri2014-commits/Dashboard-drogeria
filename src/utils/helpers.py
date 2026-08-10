"""
utils.py — Utilidades del sistema
- Cálculo de días hábiles Argentina
- Formato de moneda ARS
- Clasificación automática de movimientos
- Logging del sistema
"""
import pandas as pd
from datetime import datetime, timedelta, date
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import FERIADOS_2025, CATEGORIAS_KEYWORDS, COLORES


# ══════════════════════════════════════════════════════════════════════
# DÍAS HÁBILES
# ══════════════════════════════════════════════════════════════════════

FERIADOS_SET = set(FERIADOS_2025)

def es_habil(fecha) -> bool:
    """Devuelve True si la fecha es día hábil (lunes-viernes, no feriado)."""
    if isinstance(fecha, (datetime, pd.Timestamp)):
        fecha = fecha.date()
    if isinstance(fecha, str):
        fecha = datetime.strptime(fecha[:10], "%Y-%m-%d").date()
    if fecha.weekday() >= 5:  # Sábado=5, Domingo=6
        return False
    if fecha.strftime("%Y-%m-%d") in FERIADOS_SET:
        return False
    return True

def siguiente_dia_habil(fecha) -> date:
    """
    Devuelve el próximo día hábil.
    - Sábado → Lunes
    - Domingo → Lunes
    - Feriado → día siguiente hábil
    """
    if isinstance(fecha, str):
        fecha = datetime.strptime(fecha[:10], "%Y-%m-%d").date()
    elif isinstance(fecha, (datetime, pd.Timestamp)):
        fecha = fecha.date()

    candidato = fecha
    if not es_habil(candidato):
        candidato = candidato + timedelta(days=1)
        while not es_habil(candidato):
            candidato = candidato + timedelta(days=1)
    return candidato

def ajustar_fecha_cobro(fecha) -> date:
    """
    Si el vencimiento cae en fin de semana o feriado,
    lo mueve al próximo día hábil (lógica cheques Argentina).
    """
    return siguiente_dia_habil(fecha)

def dias_habiles_entre(fecha_inicio, fecha_fin) -> int:
    """Cuenta días hábiles entre dos fechas."""
    if isinstance(fecha_inicio, str):
        fecha_inicio = datetime.strptime(fecha_inicio[:10], "%Y-%m-%d").date()
    if isinstance(fecha_fin, str):
        fecha_fin = datetime.strptime(fecha_fin[:10], "%Y-%m-%d").date()
    count = 0
    current = fecha_inicio
    while current <= fecha_fin:
        if es_habil(current):
            count += 1
        current += timedelta(days=1)
    return count


# ══════════════════════════════════════════════════════════════════════
# FORMATO MONEDA
# ══════════════════════════════════════════════════════════════════════

def fmt_ars(valor, decimales=0) -> str:
    """Formatea un número como moneda ARS con puntos de miles."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return "$ —"
    try:
        valor = float(valor)
        if decimales == 0:
            return f"$ {valor:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
        else:
            return f"$ {valor:,.{decimales}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return str(valor)

def fmt_millones(valor) -> str:
    """Formatea en millones para KPIs del dashboard."""
    if valor is None:
        return "—"
    try:
        v = float(valor)
        if abs(v) >= 1_000_000_000:
            return f"${v/1_000_000_000:.1f}B"
        elif abs(v) >= 1_000_000:
            return f"${v/1_000_000:.1f}M"
        elif abs(v) >= 1_000:
            return f"${v/1_000:.0f}K"
        else:
            return fmt_ars(v)
    except:
        return "—"

def fmt_pct(valor) -> str:
    """Formatea como porcentaje."""
    try:
        return f"{float(valor)*100:.1f}%"
    except:
        return "—"


# ══════════════════════════════════════════════════════════════════════
# CLASIFICACIÓN AUTOMÁTICA DE MOVIMIENTOS
# ══════════════════════════════════════════════════════════════════════

def clasificar_movimiento(descripcion: str, importe: float = None) -> str:
    """
    Clasifica automáticamente un movimiento bancario por su descripción.
    Usa keywords definidas en config.py.
    """
    if not descripcion or not isinstance(descripcion, str):
        return "Otros Egresos" if (importe and importe < 0) else "Otros Ingresos"

    desc_upper = descripcion.upper().strip()

    for categoria, keywords in CATEGORIAS_KEYWORDS.items():
        if not keywords:
            continue
        for kw in keywords:
            if kw.upper() in desc_upper:
                return categoria

    # Fallback por importe
    if importe is not None:
        return "Otros Ingresos" if float(importe) > 0 else "Otros Egresos"

    return "Sin clasificar"

def semaforo(saldo: float, critico: float, alerta: float) -> str:
    """Devuelve emoji semáforo según el saldo."""
    if saldo < critico:
        return "🔴"
    elif saldo < alerta:
        return "🟡"
    else:
        return "🟢"

def semaforo_label(saldo: float, critico: float, alerta: float) -> str:
    """Devuelve label de semáforo."""
    if saldo < critico:
        return "CRÍTICO"
    elif saldo < alerta:
        return "ALERTA"
    else:
        return "OK"

def semaforo_color(saldo: float, critico: float, alerta: float) -> str:
    """Devuelve color hex para el semáforo."""
    if saldo < critico:
        return COLORES["rojo"]
    elif saldo < alerta:
        return COLORES["amarillo"]
    else:
        return COLORES["verde"]


# ══════════════════════════════════════════════════════════════════════
# UTILIDADES DE FECHA
# ══════════════════════════════════════════════════════════════════════

MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}
MESES_CORTO = {
    1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"
}

def nombre_mes(num: int, corto=False) -> str:
    """Devuelve el nombre del mes en español."""
    d = MESES_CORTO if corto else MESES_ES
    return d.get(num, str(num))

def parse_fecha(valor) -> date:
    """Parsea una fecha en múltiples formatos comunes en Argentina."""
    if isinstance(valor, (datetime, pd.Timestamp)):
        return valor.date() if hasattr(valor, 'date') else valor
    if isinstance(valor, date):
        return valor
    if pd.isna(valor) if not isinstance(valor, str) else False:
        return None

    s = str(valor).strip()
    formatos = [
        "%d/%m/%Y", "%d/%m/%y",
        "%Y-%m-%d",
        "%d-%m-%Y", "%d-%m-%y",
        "%d.%m.%Y",
        "%Y%m%d",
    ]
    for fmt in formatos:
        try:
            return datetime.strptime(s[:10], fmt).date()
        except:
            continue
    return None


# ══════════════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════════════

class Logger:
    """Logger simple para registrar acciones del sistema."""
    def __init__(self):
        self.logs = []

    def info(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] ℹ️  {msg}"
        self.logs.append(entry)
        print(entry)

    def ok(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] ✅ {msg}"
        self.logs.append(entry)
        print(entry)

    def warn(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] ⚠️  {msg}"
        self.logs.append(entry)
        print(entry)

    def error(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] ❌ {msg}"
        self.logs.append(entry)
        print(entry)

    def get_logs(self):
        return "\n".join(self.logs)

logger = Logger()


if __name__ == "__main__":
    # Tests básicos
    print("=== TEST DÍAS HÁBILES ===")
    print(f"01/01/2025 (feriado): es_habil = {es_habil('2025-01-01')}")
    print(f"05/01/2025 (dom):  es_habil = {es_habil(date(2025,1,5))}")
    print(f"06/01/2025 (lun):  es_habil = {es_habil(date(2025,1,6))}")
    print(f"Cheque sáb 05/04/2025 → hábil: {siguiente_dia_habil(date(2025,4,5))}")
    print(f"Cheque dom 06/04/2025 → hábil: {siguiente_dia_habil(date(2025,4,6))}")
    print(f"Feriado 25/05/2025 → hábil: {siguiente_dia_habil(date(2025,5,25))}")

    print("\n=== TEST FORMATO ===")
    print(fmt_ars(1234567.89))
    print(fmt_millones(2_847_320))
    print(fmt_millones(12_400_000_000))

    print("\n=== TEST CLASIFICACIÓN ===")
    casos = [
        ("TRANSF RECIB FARMACIA CENTRAL", 150000),
        ("DEBITO AFIP IVA MAYO", -98400),
        ("CUOTA PRESTAMO BANCO GALICIA", -42000),
        ("SUELDO MAYO 2025", -300000),
        ("CHEQUE 00124", -185000),
    ]
    for desc, imp in casos:
        print(f"  '{desc}' → {clasificar_movimiento(desc, imp)}")

    print("\n✅ utils.py OK")
