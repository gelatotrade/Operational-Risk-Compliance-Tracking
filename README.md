# Operational Risk & Compliance Tracking System

Ein umfassendes System zur Erfassung und Analyse operationeller Risikoereignisse mit Loss Data Collection und Compliance-Monitoring.

## Funktionsübersicht

### Kern-Funktionalitäten

- **Risiko-Ereignis-Management**: Erfassung, Klassifizierung und Tracking von operationellen Risikoereignissen nach BASEL II Kategorien
- **Loss Data Collection**: Strukturierte Erfassung von Verlustdaten inkl. Wiederherstellung und Versicherung
- **Key Risk Indicators (KRIs)**: Überwachung von Frühindikatoren mit Ampelsystem und Trendanalyse
- **Compliance Monitoring**: Tracking regulatorischer Anforderungen (MiFID II, EMIR, GDPR, SOX, BASEL III, DORA)
- **Incident Response**: Dokumentation von Eskalationen und Lessons Learned
- **Szenarioanalyse**: Bewertung von Risikoszenarien für Kapitalberechnung

### Analysen

- **Loss Distribution Analysis**: Frequenz/Severity-Verteilung, VaR, Expected Shortfall
- **Control Effectiveness**: KRI-Verlust-Korrelation, Control Gap Analysis
- **Capital Calculation**: AMA-basierte Kapitalberechnung (LDA, Szenario-basiert)
- **Risk Appetite Monitoring**: Überwachung der Risikotoleranz mit Early Warnings

### Dashboards

- **Operational Risk Heatmap**: Häufigkeit × Auswirkung Matrix
- **KRI Trend Analysis**: Zeitreihenanalyse mit Ampelstatus
- **Compliance Status Board**: Regulatorische Deadline-Überwachung
- **Executive Summary**: Management-Dashboard mit KPIs

## Projektstruktur

```
├── config/                 # Konfiguration
│   └── settings.py        # Zentrale Einstellungen
├── sql/
│   ├── schema/            # Datenbankschema
│   │   ├── 01_metadata_tables.sql
│   │   └── 02_core_tables.sql
│   ├── views/             # Analyse-Views
│   │   ├── 01_analysis_views.sql
│   │   └── 02_dashboard_views.sql
│   └── procedures/        # Stored Procedures
│       └── 01_audit_procedures.sql
├── python/
│   ├── models/            # SQLAlchemy ORM Models
│   ├── etl/               # ETL Pipeline
│   │   ├── data_loader.py
│   │   ├── transformers.py
│   │   ├── validators.py
│   │   └── pipeline.py
│   ├── analytics/         # Analyse-Module
│   │   ├── loss_distribution.py
│   │   ├── kri_analysis.py
│   │   ├── compliance_monitor.py
│   │   ├── capital_calculation.py
│   │   └── risk_appetite.py
│   └── dashboard/         # Dashboard-Komponenten
│       ├── risk_heatmap.py
│       ├── executive_dashboard.py
│       └── report_generator.py
├── data/
│   └── sample/            # Beispieldaten
└── requirements.txt
```

## Installation

### Voraussetzungen

- Python 3.10+
- PostgreSQL 14+

### Setup

```bash
# Repository klonen
git clone <repository-url>
cd Operational-Risk-Compliance-Tracking

# Virtual Environment erstellen
python -m venv venv
source venv/bin/activate  # Linux/Mac
# oder: venv\Scripts\activate  # Windows

# Dependencies installieren
pip install -r requirements.txt

# Umgebungsvariablen konfigurieren
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=oprisk_db
export DB_USER=oprisk_user
export DB_PASSWORD=your_password

# Datenbank initialisieren
psql -U postgres -c "CREATE DATABASE oprisk_db;"
psql -U postgres -d oprisk_db -f sql/schema/01_metadata_tables.sql
psql -U postgres -d oprisk_db -f sql/schema/02_core_tables.sql
psql -U postgres -d oprisk_db -f sql/views/01_analysis_views.sql
psql -U postgres -d oprisk_db -f sql/views/02_dashboard_views.sql
psql -U postgres -d oprisk_db -f sql/procedures/01_audit_procedures.sql
```

## Verwendung

### ETL Pipeline

```python
from python.etl.pipeline import RiskEventPipeline, run_daily_etl

# Einzelne Pipeline ausführen
pipeline = RiskEventPipeline()
result = pipeline.run_from_csv("data/sample/sample_risk_events.csv")
print(f"Geladen: {result.records_loaded} Datensätze")

# Täglichen ETL-Prozess starten
summary = run_daily_etl()
print(summary)
```

### Analysen

```python
from python.analytics.loss_distribution import LossDistributionAnalyzer
from python.analytics.kri_analysis import KRIAnalyzer
from python.analytics.compliance_monitor import ComplianceMonitor

# Verlustverteilung analysieren
analyzer = LossDistributionAnalyzer()
top_losses = analyzer.get_top_losses(n=10, years=5)
freq_sev = analyzer.get_frequency_severity(group_by="month")

# KRI Status abrufen
kri = KRIAnalyzer()
status = kri.get_current_kri_status()
summary = kri.get_ampel_summary()

# Compliance Report generieren
compliance = ComplianceMonitor()
report = compliance.generate_compliance_report()
```

### Dashboard

```python
from python.dashboard.executive_dashboard import ExecutiveDashboard
from python.dashboard.risk_heatmap import RiskHeatmapGenerator

# Executive Summary
dashboard = ExecutiveDashboard()
summary = dashboard.generate_executive_summary()

# Risk Heatmap
heatmap = RiskHeatmapGenerator()
data = heatmap.export_for_visualization(years=3)
```

## Datenmodell

### BASEL II Risikokategorien

| Code | Kategorie |
|------|-----------|
| IF | Interner Betrug |
| EF | Externer Betrug |
| EPWS | Beschäftigungspraxis & Arbeitsplatzsicherheit |
| CPBP | Kunden, Produkte & Geschäftspraxis |
| DPA | Sachschäden |
| BDSF | Geschäftsunterbrechung & Systemausfälle |
| EDPM | Ausführung, Lieferung & Prozessmanagement |

### Ampel-Status

- **GRÜN**: Innerhalb Toleranz
- **GELB**: Warnung, erhöhte Aufmerksamkeit
- **ROT**: Kritisch, Maßnahmen erforderlich

## Sicherheit

- **Row-Level Security**: Abteilungen sehen nur ihre Daten
- **Audit Trail**: SOX-konforme Protokollierung aller Änderungen
- **4-Augen-Prinzip**: Freigabe-Workflow für kritische Aktionen
- **Sensitive Data Masking**: Schutz personenbezogener Daten

## Lizenz

Proprietary - All Rights Reserved
