# 💰 CASHFLOW INTELIGENTE — Droguería del Sud
## Sistema de Gestión Financiera Automatizada — Fase 1

---

## 📋 Índice
1. [Descripción del sistema](#descripción)
2. [Arquitectura y módulos](#arquitectura)
3. [Instalación y ejecución](#instalación)
4. [Manual de uso rápido](#manual)
5. [Descripción de cada módulo](#módulos)
6. [Datos de configuración](#configuración)
7. [Tests ejecutados](#tests)
8. [Roadmap Fase 2](#roadmap)

---

## 1. Descripción del sistema <a name="descripción"></a>

Sistema de cashflow inteligente construido en Python, inspirado en el
estándar de tesorería de **Cencora / McKesson** (los mayores distribuidores
farmacéuticos del mundo), adaptado a:

- Economía argentina (ARS, inflación, AFIP, feriados nacionales)
- SAP ERP (base de Droguería del Sud)
- Bancos argentinos (Nación, Galicia, BBVA, Santander, Macro, ICBC)

### ¿Qué hace la Fase 1?
| Función | Estado |
|---------|--------|
| Importar extracto bancario (CSV/XLSX) | ✅ |
| Auto-detectar banco y normalizar formato | ✅ |
| Clasificar movimientos automáticamente | ✅ |
| Generar cashflow mensual proyectado | ✅ |
| Comparar proyectado vs real | ✅ |
| Calcular desvíos por categoría | ✅ |
| Conciliación automática extracto vs proyectado | ✅ |
| Gestión de cheques con ajuste día hábil | ✅ |
| Alertas automáticas (saldo, vencimientos, AFIP) | ✅ |
| Dashboard ejecutivo web (Streamlit) | ✅ |
| Exportación a Excel profesional | ✅ |
| Estacionalidad y cobranza escalonada | ✅ |
| Lógica aguinaldo (Jun/Dic x1.5) | ✅ |

---

## 2. Arquitectura y módulos <a name="arquitectura"></a>

```
cashflow_app/
│
├── app.py                          # App Streamlit principal (dashboard)
├── config.py                       # Configuración central del sistema
│
├── src/
│   ├── parsers/
│   │   └── parser_bancario.py      # Parser inteligente de extractos
│   │                               # Soporta: Nación, Galicia, BBVA,
│   │                               # Santander, Macro, ICBC, genérico
│   │
│   ├── engine/
│   │   └── motor_cashflow.py       # Motor central del cashflow
│   │                               # Proyección, real, desvíos, KPIs
│   │
│   ├── models/
│   │   └── gestor_cheques.py       # Gestión de cheques y pagarés
│   │                               # Ajuste automático día hábil
│   │
│   ├── alertas/
│   │   └── alertas.py              # Sistema de alertas automáticas
│   │                               # Saldo, cheques, AFIP, préstamos
│   │
│   └── utils/
│       ├── helpers.py              # Utilidades: días hábiles, formato,
│       │                           # clasificación, logging
│       └── exportador.py           # Exportación Excel profesional
│
├── data/
│   ├── samples/                    # Datos de muestra para demo
│   └── cheques.csv                 # Persistencia de cheques
│
├── exports/                        # Excel generados
├── tests/                          # Tests unitarios (Fase 2)
└── docs/
    └── README.md                   # Este archivo
```

---

## 3. Instalación y ejecución <a name="instalación"></a>

### Requisitos
- Python 3.10 o superior
- pip

### Instalación de dependencias
```bash
pip install streamlit pandas openpyxl plotly xlrd python-dateutil numpy scipy
```

### Ejecutar la app
```bash
cd cashflow_app
streamlit run app.py
```
La app abre en `http://localhost:8501`

### Ejecutar tests individuales
```bash
# Desde la carpeta raíz del proyecto
PYTHONPATH=. python src/utils/helpers.py
PYTHONPATH=. python src/parsers/parser_bancario.py
PYTHONPATH=. python src/engine/motor_cashflow.py
PYTHONPATH=. python src/models/gestor_cheques.py
PYTHONPATH=. python src/alertas/alertas.py
PYTHONPATH=. python src/utils/exportador.py
```

---

## 4. Manual de uso rápido <a name="manual"></a>

### Primer uso
1. Ejecutar `streamlit run app.py`
2. Ir a **⚙️ Parámetros** → Ingresar Budget Anual y Saldo Inicial
3. Ir a **🔄 Conciliación** → Cargar el CSV del extracto bancario
4. El **🏠 Dashboard** se actualiza automáticamente
5. Revisar alertas en el sidebar

### Cargar extracto bancario
1. Exportar el extracto desde el portal del banco (CSV o Excel)
2. En la app, ir a **🔄 Conciliación** o usar el uploader del sidebar
3. El sistema detecta automáticamente el banco y normaliza el formato
4. La conciliación automática corre sola (matching por categoría + monto)

### Agregar cheques
1. Ir a **🏦 Cheques** → Tab "➕ Agregar cheque"
2. Ingresar: N° cheque, beneficiario, monto, fecha de vencimiento
3. La fecha hábil efectiva se calcula automáticamente
4. Si cae en sábado → lunes; domingo → lunes; feriado → día siguiente

### Exportar
1. Ir a **📤 Exportar**
2. Descargar Excel o CSV según necesidad

---

## 5. Descripción detallada de módulos <a name="módulos"></a>

### `config.py`
Configuración central. Contiene:
- Datos de la empresa y año
- Umbrales de alerta (crítico: $500K, alerta: $2M)
- Feriados nacionales 2025 (17 feriados)
- Coeficientes de estacionalidad por mes (suma = 12)
- Condiciones de cobro (contado 40%, 30d 35%, 60d 15%, 90d 10%)
- Meses de aguinaldo (junio y diciembre → cargas x1.5)
- Keywords para clasificación automática de movimientos (11 categorías)
- Formatos de banco soportados (6 bancos + genérico)

### `parser_bancario.py`
Parser inteligente de extractos bancarios.
- `detectar_banco()`: auto-detección por nombre de archivo y columnas
- `parse_extracto()`: función principal, devuelve DataFrame normalizado
- Maneja formatos: Debe/Haber separados (Galicia, Macro), columna única
- Limpieza de importes: maneja punto/coma ARS, paréntesis negativos
- Parseo de fechas en múltiples formatos (DD/MM/YYYY, YYYY-MM-DD, etc.)
- `estadisticas_extracto()`: totales, categorías, período
- `generar_extracto_muestra()`: datos de demo realistas

### `motor_cashflow.py`
Motor central del cashflow.
- `ParametrosCashflow`: clase con todos los parámetros editables
- `proyectar_ingresos()`: budget × estacionalidad + cobros escalonados
- `proyectar_egresos()`: sueldos, cargas, AFIP, préstamos, proveedores
  - Lógica aguinaldo automática (Jun/Dic × 1.5 en cargas sociales)
  - Préstamos activos solo en el rango mes_ini → mes_fin
- `generar_cashflow_mensual()`: combina proyectado + real + desvíos
  - Encadena el saldo final de cada mes como inicial del siguiente
  - Calcula semáforo (🔴🟡🟢) por mes automáticamente
- `conciliar_automatico()`: matching extracto vs proyectado
  - Tolerancia 5% para match perfecto, 20% para desvío
- `generar_resumen_semanal()`: agrupa movimientos por semana ISO
- `calcular_kpis()`: saldo actual, totales anuales, meses críticos

### `gestor_cheques.py`
Gestión completa de cheques.
- `agregar_cheque()`: calcula fecha hábil efectiva automáticamente
  - Sábado → lunes (+2 días)
  - Domingo → lunes (+1 día)
  - Feriado nacional → siguiente día hábil
- `actualizar_estado_cheque()`: pendiente/cobrado/rechazado/vencido
- `marcar_cheques_vencidos()`: batch update automático
- `alertas_cheques()`: clasifica por urgencia (hoy/7d/30d/vencidos)
- `resumen_mensual_cheques()`: totales por mes para el cashflow

### `alertas.py`
Sistema de alertas inteligentes.
- `Alerta` dataclass: nivel, categoría, título, detalle, monto, acción
- `alertas_saldo()`: detecta meses críticos y en alerta
- `alertas_cheques_df()`: por cheque individual con urgencia
- `alertas_vencimientos_afip()`: calendario AFIP estándar Argentina
  - IVA (día 20), IIBB (día 15), Ganancias (día 20), SIPA (día 14)
- `alertas_desvios()`: umbral configurable (default 10%)
- `alertas_prestamos()`: cuotas próximas a vencer
- `generar_todas_las_alertas()`: función maestra, ordena por urgencia
- `resumen_alertas()`: conteo para el header del dashboard

### `exportador.py`
Generación de Excel profesional.
- Hoja CASHFLOW_MENSUAL: tabla completa con formato
  - Colores por tipo (ingresos verde, egresos rojo, totales amarillo)
  - Highlight aguinaldo (junio y diciembre)
  - Formato moneda ARS con separadores locales
- Hoja EXTRACTO_BANCARIO: movimientos categorizados con estado conciliación
- Metadatos: empresa, fecha generación, sistema

### `app.py` (Streamlit)
Dashboard web completo con 7 páginas:
1. **Dashboard**: KPIs, gráficos ingresos/egresos, semáforo 12 meses,
   alertas, donuts por categoría
2. **Cashflow Mensual**: tabla completa, gráfico desvíos, detalle por mes
3. **Cashflow Semanal**: evolución semanal con semáforo
4. **Conciliación**: upload extracto, matching automático, tabla detallada
5. **Cheques**: gestión completa, agregar con formulario, resumen mensual
6. **Parámetros**: todos los inputs editables con recálculo en tiempo real
7. **Exportar**: Excel, CSV por módulo, estado del sistema

---

## 6. Datos de configuración <a name="configuración"></a>

### Parámetros base cargados
```python
Budget anual:          $120,000,000
Saldo inicial Enero:    $2,100,000
Sueldos brutos:           $420,000/mes
Cargas sociales:          $134,400/mes (Jun/Dic: $201,600)
IVA mensual:               $98,400
IIBB mensual:              $34,500
Cuota Banco Galicia:       $42,000 (meses 1-12)
Cuota Banco Nación:        $85,000 (meses 3-12)
Alquiler:                  $95,000
Proveedores:               55% de ventas del mes
```

### Estacionalidad calibrada
Los coeficientes reflejan el patrón típico de una droguería argentina:
- Pico diciembre (1.35): fiestas + stock fin de año
- Pico junio (1.10): mitad de año, vacunas invierno
- Valle febrero (0.92): verano, menos actividad

---

## 7. Tests ejecutados <a name="tests"></a>

Todos los módulos fueron testeados individualmente y en pipeline completo.

| Test | Resultado |
|------|-----------|
| Días hábiles — feriados y fines de semana | ✅ |
| Formato moneda ARS | ✅ |
| Clasificación automática de movimientos (5 categorías) | ✅ |
| Parser extracto Banco Nación (29 movimientos) | ✅ |
| Auto-detección de banco por columnas | ✅ |
| Limpieza importes formato ARS (puntos/comas) | ✅ |
| Cashflow mensual 12 meses proyectado | ✅ |
| Lógica aguinaldo Jun/Dic | ✅ |
| Cálculo de cobros escalonados (0/30/60/90d) | ✅ |
| Conciliación automática | ✅ |
| Cheques con ajuste día hábil (14 cheques, 12 ajustados) | ✅ |
| Alertas — 18 alertas generadas y clasificadas | ✅ |
| Pipeline end-to-end completo | ✅ |
| Exportación Excel (2 hojas, formato profesional) | ✅ |

---

## 8. Roadmap Fase 2 <a name="roadmap"></a>

### Fase 2 — SAP + Base de Datos + Forecast 13 Semanas
- Conexión SAP Service Layer API (extracción automática AR/AP/Banking)
- Base de datos PostgreSQL para historial
- Forecast rolling 13 semanas con IA
- Módulo de deuda financiera (préstamos, cancelaciones, TEA/TNA)
- Análisis de escenarios what-if (optimista/base/pesimista)
- KPIs farmacéuticos: DSO, DPO, Cash Conversion Cycle
- Alertas por email y WhatsApp

### Fase 3 — Reporting Financiero
- Estado de Resultados automático desde SAP
- Balance General mensual
- Flujo de fondos (directo + indirecto)
- Reporte de gestión board-ready (PDF + PowerPoint automático)
- Dashboard para el board con drill-down

### Fase 4 — API Bancaria en Tiempo Real
- Conexión API Banco Galicia (ya disponible)
- Posición bancaria actualizada cada 2 horas
- Notificaciones push por movimiento significativo
- Inversión automática de excedentes en plazo fijo digital

---

## 🏆 Contexto competitivo

Este sistema implementa en una droguería argentina el mismo estándar de
tesorería que usan **Cencora** (#10 Fortune 500, $290B revenue) y
**McKesson** (mayor distribuidor farmacéutico del mundo).

**Ninguna empresa del sector farmacéutico/droguería en Argentina tiene
esto implementado hoy.** La oportunidad es ser el primero y definir
el estándar del sector.

---
*Generado: Fase 1 — Sistema Cashflow Inteligente v1.0*
*Droguería del Sud — Implementación 2025*
