"""
Risk Appetite Monitoring - Überwachung der Risikotoleranz
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional
from dataclasses import dataclass, field

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class RiskAppetiteStatus:
    """Aktueller Risk Appetite Status"""
    jahr: int
    max_jahresverlust_limit: Decimal
    max_einzelverlust_limit: Decimal

    # Aktuelle Werte
    ytd_verlust: Decimal
    max_einzelverlust_ytd: Decimal
    anzahl_ereignisse: int

    # Auslastung
    auslastung_prozent: float
    einzelverlust_auslastung: float

    # Status
    status: str  # IM_RAHMEN, WARNUNG, KRITISCH, UEBERSCHRITTEN
    ampel: str
    eskalation_erforderlich: bool
    verbleibend: Decimal


@dataclass
class RiskCultureMetric:
    """Metriken zur Risikokultur"""
    metrik_name: str
    aktueller_wert: float
    ziel_wert: float
    trend: str
    kategorie: str  # AWARENESS, REPORTING, RESPONSE, GOVERNANCE


@dataclass
class EarlyWarningSignal:
    """Frühwarn-Signal"""
    signal_typ: str
    beschreibung: str
    quelle: str  # KRI, LOSS_TREND, COMPLIANCE, EXTERNAL
    schweregrad: str
    empfohlene_massnahme: str
    erkannt_am: date


class RiskAppetiteMonitor:
    """Überwacht Risk Appetite und Risikokultur"""

    # Schwellwerte für Auslastung
    WARNING_THRESHOLD = 0.5  # 50%
    CRITICAL_THRESHOLD = 0.8  # 80%

    def __init__(self, db_session=None):
        self.db = db_session

    def get_current_status(self, year: int = None) -> RiskAppetiteStatus:
        """
        Gibt den aktuellen Risk Appetite Status zurück

        Args:
            year: Jahr (default: aktuelles Jahr)

        Returns:
            RiskAppetiteStatus
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        year = year or date.today().year

        query = """
            WITH aktuelle_limits AS (
                SELECT
                    max_jahresverlust,
                    max_einzelverlust
                FROM risk_appetite
                WHERE ist_aktiv = TRUE
                  AND gueltigkeits_jahr = :year
                LIMIT 1
            ),
            aktuelle_verluste AS (
                SELECT
                    COALESCE(SUM(verlust_betrag_eur), 0) as ytd_verlust,
                    COALESCE(MAX(verlust_betrag_eur), 0) as max_einzelverlust,
                    COUNT(*) as anzahl
                FROM risiko_ereignisse
                WHERE EXTRACT(YEAR FROM meldedatum) = :year
                  AND verlust_betrag_eur > 0
                  AND ist_near_miss = FALSE
            )
            SELECT
                al.max_jahresverlust,
                al.max_einzelverlust,
                av.ytd_verlust,
                av.max_einzelverlust as max_einzel_ytd,
                av.anzahl
            FROM aktuelle_limits al, aktuelle_verluste av
        """

        with get_db_context() as db:
            row = db.execute(text(query), {"year": year}).fetchone()

            if not row or not row.max_jahresverlust:
                # Fallback auf Konfigurationswerte
                max_jahr = Decimal(str(settings.risk.max_annual_loss))
                max_einzel = Decimal(str(settings.risk.max_single_loss))
                ytd = Decimal(0)
                max_einzel_ytd = Decimal(0)
                anzahl = 0
            else:
                max_jahr = Decimal(str(row.max_jahresverlust))
                max_einzel = Decimal(str(row.max_einzelverlust))
                ytd = Decimal(str(row.ytd_verlust))
                max_einzel_ytd = Decimal(str(row.max_einzel_ytd))
                anzahl = row.anzahl

            # Auslastung berechnen
            auslastung = float(ytd / max_jahr * 100) if max_jahr > 0 else 0
            einzel_auslastung = float(max_einzel_ytd / max_einzel * 100) if max_einzel > 0 else 0

            # Status bestimmen
            if auslastung >= 100:
                status = "UEBERSCHRITTEN"
                ampel = "ROT"
                eskalation = True
            elif auslastung >= self.CRITICAL_THRESHOLD * 100:
                status = "KRITISCH"
                ampel = "ROT"
                eskalation = True
            elif auslastung >= self.WARNING_THRESHOLD * 100:
                status = "WARNUNG"
                ampel = "GELB"
                eskalation = False
            else:
                status = "IM_RAHMEN"
                ampel = "GRUEN"
                eskalation = False

            return RiskAppetiteStatus(
                jahr=year,
                max_jahresverlust_limit=max_jahr,
                max_einzelverlust_limit=max_einzel,
                ytd_verlust=ytd,
                max_einzelverlust_ytd=max_einzel_ytd,
                anzahl_ereignisse=anzahl,
                auslastung_prozent=auslastung,
                einzelverlust_auslastung=einzel_auslastung,
                status=status,
                ampel=ampel,
                eskalation_erforderlich=eskalation,
                verbleibend=max_jahr - ytd
            )

    def get_appetite_trend(self, months: int = 12) -> list[dict]:
        """
        Gibt den Risk Appetite Verlauf über Zeit zurück

        Args:
            months: Anzahl Monate

        Returns:
            Liste mit monatlichen Werten
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        query = """
            WITH monthly_losses AS (
                SELECT
                    DATE_TRUNC('month', meldedatum) as monat,
                    SUM(verlust_betrag_eur) as monatsverlust,
                    SUM(SUM(verlust_betrag_eur)) OVER (
                        PARTITION BY EXTRACT(YEAR FROM meldedatum)
                        ORDER BY DATE_TRUNC('month', meldedatum)
                    ) as kumuliert_ytd,
                    COUNT(*) as anzahl
                FROM risiko_ereignisse
                WHERE meldedatum >= CURRENT_DATE - INTERVAL ':months months'
                  AND verlust_betrag_eur > 0
                  AND ist_near_miss = FALSE
                GROUP BY DATE_TRUNC('month', meldedatum)
            )
            SELECT
                ml.*,
                ra.max_jahresverlust as limit_jahr
            FROM monthly_losses ml
            LEFT JOIN risk_appetite ra ON ra.gueltigkeits_jahr = EXTRACT(YEAR FROM ml.monat)
                                       AND ra.ist_aktiv = TRUE
            ORDER BY ml.monat
        """

        with get_db_context() as db:
            rows = db.execute(text(query), {"months": months}).fetchall()

            return [
                {
                    "monat": row.monat.isoformat(),
                    "monatsverlust": float(row.monatsverlust),
                    "kumuliert_ytd": float(row.kumuliert_ytd),
                    "anzahl_ereignisse": row.anzahl,
                    "limit_jahr": float(row.limit_jahr) if row.limit_jahr else None,
                    "auslastung_prozent": (
                        float(row.kumuliert_ytd / row.limit_jahr * 100)
                        if row.limit_jahr else None
                    )
                }
                for row in rows
            ]

    def get_risk_culture_metrics(self) -> list[RiskCultureMetric]:
        """
        Berechnet Risikokultur-Metriken

        Returns:
            Liste von RiskCultureMetric
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        metrics = []

        with get_db_context() as db:
            # 1. Meldegeschwindigkeit (Tage zwischen Entdeckung und Meldung)
            query_reporting = """
                SELECT
                    AVG(meldedatum - entdeckungsdatum) as avg_meldezeit,
                    AVG(CASE WHEN meldedatum - entdeckungsdatum <= 1 THEN 1 ELSE 0 END) * 100 as pct_schnell
                FROM risiko_ereignisse
                WHERE meldedatum >= CURRENT_DATE - INTERVAL '12 months'
                  AND entdeckungsdatum IS NOT NULL
            """
            row = db.execute(text(query_reporting)).fetchone()
            if row:
                metrics.append(RiskCultureMetric(
                    metrik_name="Durchschnittliche Meldezeit (Tage)",
                    aktueller_wert=float(row.avg_meldezeit or 0),
                    ziel_wert=1.0,
                    trend="STABIL",
                    kategorie="REPORTING"
                ))
                metrics.append(RiskCultureMetric(
                    metrik_name="Anteil schnelle Meldungen (<24h)",
                    aktueller_wert=float(row.pct_schnell or 0),
                    ziel_wert=80.0,
                    trend="STABIL",
                    kategorie="REPORTING"
                ))

            # 2. Root Cause Dokumentation
            query_rootcause = """
                SELECT
                    AVG(CASE WHEN root_cause IS NOT NULL AND root_cause != '' THEN 1 ELSE 0 END) * 100 as pct_dokumentiert
                FROM risiko_ereignisse
                WHERE meldedatum >= CURRENT_DATE - INTERVAL '12 months'
            """
            row = db.execute(text(query_rootcause)).fetchone()
            if row:
                metrics.append(RiskCultureMetric(
                    metrik_name="Root Cause Dokumentationsrate",
                    aktueller_wert=float(row.pct_dokumentiert or 0),
                    ziel_wert=95.0,
                    trend="STABIL",
                    kategorie="AWARENESS"
                ))

            # 3. Near-Miss Reporting Rate
            query_nearmiss = """
                SELECT
                    COUNT(CASE WHEN ist_near_miss = TRUE THEN 1 END) * 100.0 /
                    NULLIF(COUNT(*), 0) as pct_near_miss
                FROM risiko_ereignisse
                WHERE meldedatum >= CURRENT_DATE - INTERVAL '12 months'
            """
            row = db.execute(text(query_nearmiss)).fetchone()
            if row:
                metrics.append(RiskCultureMetric(
                    metrik_name="Near-Miss Meldeanteil",
                    aktueller_wert=float(row.pct_near_miss or 0),
                    ziel_wert=20.0,  # Mindestens 20% Near-Misses zeigt gute Kultur
                    trend="STABIL",
                    kategorie="AWARENESS"
                ))

            # 4. Incident Response Zeit
            query_response = """
                SELECT
                    AVG(EXTRACT(EPOCH FROM erstreaktion_zeit) / 3600) as avg_response_hours
                FROM incident_response
                WHERE response_start >= CURRENT_DATE - INTERVAL '12 months'
                  AND erstreaktion_zeit IS NOT NULL
            """
            row = db.execute(text(query_response)).fetchone()
            if row and row.avg_response_hours:
                metrics.append(RiskCultureMetric(
                    metrik_name="Durchschnittliche Reaktionszeit (Stunden)",
                    aktueller_wert=float(row.avg_response_hours),
                    ziel_wert=4.0,
                    trend="STABIL",
                    kategorie="RESPONSE"
                ))

            # 5. Kontroll-Test-Rate
            query_controls = """
                SELECT
                    COUNT(CASE WHEN letzter_test >= CURRENT_DATE - INTERVAL '12 months' THEN 1 END) * 100.0 /
                    NULLIF(COUNT(*), 0) as pct_getestet
                FROM kontrolle_mechanismen
                WHERE ist_aktiv = TRUE
            """
            row = db.execute(text(query_controls)).fetchone()
            if row:
                metrics.append(RiskCultureMetric(
                    metrik_name="Kontroll-Testabdeckung (12M)",
                    aktueller_wert=float(row.pct_getestet or 0),
                    ziel_wert=100.0,
                    trend="STABIL",
                    kategorie="GOVERNANCE"
                ))

        return metrics

    def identify_early_warnings(self) -> list[EarlyWarningSignal]:
        """
        Identifiziert Frühwarn-Signale

        Returns:
            Liste von EarlyWarningSignal
        """
        warnings = []

        # 1. KRI-basierte Warnungen
        from python.analytics.kri_analysis import KRIAnalyzer
        kri_analyzer = KRIAnalyzer()
        kri_warnings = kri_analyzer.get_early_warning_indicators()

        for kri in kri_warnings:
            warnings.append(EarlyWarningSignal(
                signal_typ="KRI_ROT",
                beschreibung=f"KRI '{kri['kri_name']}' im roten Bereich",
                quelle="KRI",
                schweregrad="HIGH" if kri.get("ist_persistent_rot") else "MEDIUM",
                empfohlene_massnahme="KRI überprüfen und Gegenmaßnahmen einleiten",
                erkannt_am=date.today()
            ))

        # 2. Loss Trend Warnungen
        current_status = self.get_current_status()
        if current_status.auslastung_prozent >= 50:
            warnings.append(EarlyWarningSignal(
                signal_typ="RISK_APPETITE_WARNING",
                beschreibung=f"Risk Appetite zu {current_status.auslastung_prozent:.1f}% ausgelastet",
                quelle="LOSS_TREND",
                schweregrad="HIGH" if current_status.auslastung_prozent >= 80 else "MEDIUM",
                empfohlene_massnahme="Verlustentwicklung überwachen, präventive Maßnahmen verstärken",
                erkannt_am=date.today()
            ))

        # 3. Compliance-Warnungen
        from python.analytics.compliance_monitor import ComplianceMonitor
        compliance = ComplianceMonitor()
        comp_summary = compliance.get_compliance_summary()

        if comp_summary.get("verletzt", 0) > 0:
            warnings.append(EarlyWarningSignal(
                signal_typ="COMPLIANCE_VIOLATION",
                beschreibung=f"{comp_summary['verletzt']} Compliance-Verstöße aktiv",
                quelle="COMPLIANCE",
                schweregrad="HIGH",
                empfohlene_massnahme="Sofortige Behebung und Root-Cause-Analyse",
                erkannt_am=date.today()
            ))

        if comp_summary.get("ueberfaellig", 0) > 0:
            warnings.append(EarlyWarningSignal(
                signal_typ="COMPLIANCE_OVERDUE",
                beschreibung=f"{comp_summary['ueberfaellig']} überfällige Compliance-Anforderungen",
                quelle="COMPLIANCE",
                schweregrad="MEDIUM",
                empfohlene_massnahme="Deadlines priorisieren und Ressourcen zuweisen",
                erkannt_am=date.today()
            ))

        return sorted(warnings, key=lambda x: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(x.schweregrad, 3))

    def generate_dashboard_data(self) -> dict:
        """
        Generiert Daten für das Risk Appetite Dashboard

        Returns:
            Dict mit Dashboard-Daten
        """
        current_status = self.get_current_status()
        trend = self.get_appetite_trend(12)
        culture_metrics = self.get_risk_culture_metrics()
        warnings = self.identify_early_warnings()

        return {
            "stichtag": date.today().isoformat(),
            "current_status": {
                "year": current_status.jahr,
                "ytd_verlust": float(current_status.ytd_verlust),
                "limit": float(current_status.max_jahresverlust_limit),
                "auslastung_prozent": current_status.auslastung_prozent,
                "status": current_status.status,
                "ampel": current_status.ampel,
                "verbleibend": float(current_status.verbleibend),
                "anzahl_ereignisse": current_status.anzahl_ereignisse,
                "max_einzelverlust": float(current_status.max_einzelverlust_ytd),
                "einzelverlust_limit": float(current_status.max_einzelverlust_limit)
            },
            "trend": trend,
            "risk_culture": [
                {
                    "name": m.metrik_name,
                    "wert": m.aktueller_wert,
                    "ziel": m.ziel_wert,
                    "kategorie": m.kategorie,
                    "erfuellt": m.aktueller_wert >= m.ziel_wert if m.ziel_wert <= m.aktueller_wert else m.aktueller_wert <= m.ziel_wert
                }
                for m in culture_metrics
            ],
            "early_warnings": [
                {
                    "typ": w.signal_typ,
                    "beschreibung": w.beschreibung,
                    "quelle": w.quelle,
                    "schweregrad": w.schweregrad,
                    "massnahme": w.empfohlene_massnahme
                }
                for w in warnings
            ],
            "warning_count": len(warnings),
            "high_priority_warnings": sum(1 for w in warnings if w.schweregrad == "HIGH")
        }
