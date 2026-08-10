# CASHFLOW ENTERPRISE v3.0 — Droguería del Sud
## Sistema de Gestión Financiera con Integración SAP

---

### Datos reales de la empresa
- **CUIT:** 30-53888062-7
- **Facturación anual:** ~$108B ARS (≈ USD 90M)
- **Empleados:** 1.100
- **Clientes:** 9.500 farmacias en todo el país
- **Proveedores:** 400+ laboratorios
- **Pedidos diarios:** 8.500
- **Market share:** 24% distribución farmacéutica Argentina
- **SAP implementado desde:** 2006

---

### Nuevos módulos v3.0

#### 🔗 Integración SAP (src/connectors/sap_connector.py)
| Módulo SAP | Función | Endpoint |
|------------|---------|----------|
| FI — Finanzas | Saldos bancarios, GL, pagos | /b1s/v1/BankStatements |
| SD — Ventas | Facturas farmacias, AR | /b1s/v1/Invoices |
| MM — Compras | Facturas laboratorios, AP | /b1s/v1/PurchaseInvoices |
| CO — Controlling | Budget vs Real | /b1s/v1/BudgetDistributions |
| TR — Tesorería | Préstamos, liquidez | /b1s/v1/LoanContracts |
| HR — Nómina | Sueldos 1.100 empleados | SAP SuccessFactors (próximo) |

#### 📡 Motor Tiempo Real (src/realtime/realtime_engine.py)
- Saldos bancarios (6 bancos) actualizados cada 3 minutos
- Cash Conversion Cycle: DSO (28d) + DIH (22d) - DPO (45d) = 5d
- Forecast rolling 13 semanas con semáforo automático
- Alertas automáticas: liquidez + AFIP + laboratorios + mora farmacias

---

### Credenciales demo
| Usuario | Password | Rol |
|---------|----------|-----|
| admin | admin2025 | Administrador completo |
| finanzas | finanzas2025 | Analista financiero |
| readonly | readonly2025 | Solo lectura |

---

### Ejecución
```bash
pip install -r requirements.txt
streamlit run app.py
```

### Para conectar SAP real (producción)
Crear archivo `.env`:
```
SAP_HOST=https://sap-server.delsud.com.ar:50000
SAP_COMPANY=DROGDELSUD
SAP_USER=finanzas_api
SAP_PASS=tu_password
SAP_MODE=live
```

---

### Arquitectura
```
cashflow_enterprise/
├── app.py                          # App principal Streamlit (2.600+ líneas)
├── config.py                       # Configuración con datos reales DdS
├── src/
│   ├── connectors/
│   │   └── sap_connector.py        # SAP S/4HANA Service Layer REST
│   ├── realtime/
│   │   └── realtime_engine.py      # Motor TR: forecast + alertas + CCC
│   ├── engine/motor_cashflow.py    # Motor cashflow proyectado/real
│   ├── models/
│   │   ├── gestor_deuda.py         # Préstamos (datos BCRA reales)
│   │   ├── gestor_facturas.py      # AR: 9.500 farmacias
│   │   ├── gestor_budget.py        # Budget $108B anual
│   │   ├── gestor_cheques.py       # Cheques con día hábil
│   │   └── gestor_comex.py         # COMEX importaciones labs
│   ├── parsers/parser_bancario.py  # Parser 8 bancos argentinos
│   ├── alertas/alertas.py          # Sistema de alertas
│   └── utils/
│       ├── auth.py                 # Login + roles (admin/analista/readonly)
│       └── exportador.py           # Excel profesional
└── data/
    ├── prestamos.json              # 9 préstamos (datos BCRA Central Deudores)
    ├── impuestos_config.json       # AFIP: IVA, Ganancias, SICORE, IIBB
    └── sap_cache/                  # Caché local datos SAP (TTL 3-30 min)
```
