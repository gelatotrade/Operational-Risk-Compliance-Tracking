"""
Operational Risk & Compliance Tracking System
Konfigurationseinstellungen
"""

import os
from dataclasses import dataclass
from typing import Optional
from pathlib import Path


@dataclass
class DatabaseConfig:
    """Datenbank-Konfiguration"""
    host: str = os.getenv("DB_HOST", "localhost")
    port: int = int(os.getenv("DB_PORT", "5432"))
    database: str = os.getenv("DB_NAME", "oprisk_db")
    user: str = os.getenv("DB_USER", "oprisk_user")
    password: str = os.getenv("DB_PASSWORD", "")
    schema: str = os.getenv("DB_SCHEMA", "public")

    @property
    def connection_string(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"

    @property
    def connection_string_masked(self) -> str:
        return f"postgresql://{self.user}:***@{self.host}:{self.port}/{self.database}"


@dataclass
class RiskConfig:
    """Risikomanagement-Konfiguration"""
    # Risk Appetite Limits (in EUR)
    max_single_loss: float = 5_000_000
    max_annual_loss: float = 50_000_000

    # Eskalationsschwellwerte
    escalation_l1: float = 100_000
    escalation_l2: float = 500_000
    escalation_l3: float = 1_000_000

    # KRI-Einstellungen
    kri_refresh_days: int = 1
    kri_history_months: int = 24

    # VaR-Konfidenzlevel
    var_confidence: float = 0.999

    # Aufbewahrungsfrist
    retention_years: int = 10


@dataclass
class ComplianceConfig:
    """Compliance-Konfiguration"""
    # Regulatorische Rahmenwerke
    regulatory_frameworks: tuple = ("MiFID II", "EMIR", "GDPR", "SOX", "BASEL III", "DORA")

    # Deadline-Warnungen (Tage vor Fälligkeit)
    warning_critical: int = 30
    warning_attention: int = 90

    # Audit-Einstellungen
    audit_enabled: bool = True
    four_eyes_enabled: bool = True


@dataclass
class ETLConfig:
    """ETL-Prozess-Konfiguration"""
    batch_size: int = 1000
    parallel_workers: int = 4
    retry_attempts: int = 3
    retry_delay_seconds: int = 5

    # Staging-Verzeichnisse
    staging_dir: Path = Path("data/staging")
    archive_dir: Path = Path("data/archive")
    error_dir: Path = Path("data/errors")

    # Datenquellen
    source_encoding: str = "utf-8"
    date_format: str = "%Y-%m-%d"
    decimal_separator: str = "."
    thousand_separator: str = ","


@dataclass
class DashboardConfig:
    """Dashboard-Konfiguration"""
    refresh_interval_minutes: int = 15
    cache_ttl_seconds: int = 300
    max_export_rows: int = 100_000

    # Chart-Einstellungen
    heatmap_colors: tuple = ("#00ff00", "#ffff00", "#ffa500", "#ff0000")
    trend_colors: dict = None

    def __post_init__(self):
        if self.trend_colors is None:
            self.trend_colors = {
                "positive": "#28a745",
                "negative": "#dc3545",
                "neutral": "#6c757d"
            }


@dataclass
class SecurityConfig:
    """Sicherheits-Konfiguration"""
    # Verschlüsselung
    encryption_algorithm: str = "AES-256-GCM"

    # Session-Einstellungen
    session_timeout_minutes: int = 30
    max_failed_logins: int = 5
    lockout_duration_minutes: int = 15

    # Passwort-Richtlinien
    min_password_length: int = 12
    require_special_char: bool = True
    require_number: bool = True
    password_expiry_days: int = 90

    # Row-Level Security
    rls_enabled: bool = True

    # Sensitive Data Masking
    mask_pii: bool = True
    masked_fields: tuple = ("email", "telefon", "kontonummer", "steuer_id")


class Settings:
    """Zentrale Einstellungsklasse"""

    def __init__(self):
        self.database = DatabaseConfig()
        self.risk = RiskConfig()
        self.compliance = ComplianceConfig()
        self.etl = ETLConfig()
        self.dashboard = DashboardConfig()
        self.security = SecurityConfig()

        # Umgebung
        self.environment = os.getenv("ENVIRONMENT", "development")
        self.debug = self.environment == "development"
        self.log_level = os.getenv("LOG_LEVEL", "INFO" if not self.debug else "DEBUG")

        # Pfade
        self.base_dir = Path(__file__).parent.parent
        self.data_dir = self.base_dir / "data"
        self.logs_dir = self.base_dir / "logs"

    def validate(self) -> list[str]:
        """Validiert die Konfiguration und gibt Warnungen zurück"""
        warnings = []

        if not self.database.password:
            warnings.append("Datenbankpasswort nicht gesetzt (DB_PASSWORD)")

        if self.environment == "production":
            if self.debug:
                warnings.append("Debug-Modus in Produktion aktiviert")
            if not self.security.rls_enabled:
                warnings.append("Row-Level Security in Produktion deaktiviert")

        return warnings


# Singleton-Instanz
settings = Settings()


# BASEL II Event Type Kategorien
BASEL_EVENT_TYPES = {
    "IF": "Interner Betrug",
    "EF": "Externer Betrug",
    "EPWS": "Beschäftigungspraxis & Arbeitsplatzsicherheit",
    "CPBP": "Kunden, Produkte & Geschäftspraxis",
    "DPA": "Sachschäden",
    "BDSF": "Geschäftsunterbrechung & Systemausfälle",
    "EDPM": "Ausführung, Lieferung & Prozessmanagement"
}

# Risiko-Schweregrade
RISK_SEVERITY_LEVELS = {
    "LOW": {"label": "Niedrig", "color": "#28a745", "factor": 1},
    "MEDIUM": {"label": "Mittel", "color": "#ffc107", "factor": 2},
    "HIGH": {"label": "Hoch", "color": "#fd7e14", "factor": 3},
    "CRITICAL": {"label": "Kritisch", "color": "#dc3545", "factor": 4}
}

# Ampel-Status
TRAFFIC_LIGHT_STATUS = {
    "GRUEN": {"label": "Grün", "color": "#28a745", "priority": 3},
    "GELB": {"label": "Gelb", "color": "#ffc107", "priority": 2},
    "ROT": {"label": "Rot", "color": "#dc3545", "priority": 1}
}

# Control Types
CONTROL_TYPES = {
    "PREVENTIV": "Präventive Kontrolle - verhindert Eintritt des Risikos",
    "DETEKTIV": "Detektive Kontrolle - erkennt eingetretene Risiken",
    "KORREKTIV": "Korrektive Kontrolle - behebt eingetretene Risiken"
}

# Maturity Levels (CMMI-basiert)
MATURITY_LEVELS = {
    1: {"name": "Initial", "description": "Ad-hoc, chaotisch"},
    2: {"name": "Managed", "description": "Geplant und verfolgt"},
    3: {"name": "Defined", "description": "Standardisierte Prozesse"},
    4: {"name": "Quantitatively Managed", "description": "Quantitativ gesteuert"},
    5: {"name": "Optimizing", "description": "Kontinuierliche Verbesserung"}
}
