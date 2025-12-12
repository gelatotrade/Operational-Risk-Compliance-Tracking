"""
Executive Dashboard - Zusammenfassende Übersicht für Management
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import settings

logger = logging.getLogger(__name__)


class ExecutiveDashboard:
    """Generiert Executive Summary Dashboard"""

    def __init__(self, db_session=None):
        self.db = db_session

    def generate_executive_summary(self) -> dict:
        """
        Generiert vollständige Executive Summary

        Returns:
            Dict mit allen Dashboard-Daten
        """
        from python.analytics.loss_distribution import LossDistributionAnalyzer
        from python.analytics.kri_analysis import KRIAnalyzer
        from python.analytics.compliance_monitor import ComplianceMonitor
        from python.analytics.risk_appetite import RiskAppetiteMonitor
        from python.dashboard.risk_heatmap import RiskHeatmapGenerator

        # Alle Analysen durchführen
        loss_analyzer = LossDistributionAnalyzer()
        kri_analyzer = KRIAnalyzer()
        compliance_monitor = ComplianceMonitor()
        appetite_monitor = RiskAppetiteMonitor()
        heatmap_gen = RiskHeatmapGenerator()

        return {
            "report_date": date.today().isoformat(),
            "report_type": "Executive Summary",

            # KPIs
            "kpis": self._get_key_kpis(),

            # Risk Appetite Status
            "risk_appetite": appetite_monitor.get_current_status().__dict__,

            # KRI Summary
            "kri_summary": kri_analyzer.get_ampel_summary(),

            # Compliance Summary
            "compliance_summary": compliance_monitor.get_compliance_summary(),

            # Top Risks (Heatmap)
            "top_risks": heatmap_gen.get_summary(heatmap_gen.generate_heatmap()),

            # Early Warnings
            "early_warnings": [
                {
                    "typ": w.signal_typ,
                    "beschreibung": w.beschreibung,
                    "schweregrad": w.schweregrad
                }
                for w in appetite_monitor.identify_early_warnings()[:5]
            ],

            # Trend Data
            "loss_trend": loss_analyzer.get_frequency_severity(group_by="month")[-12:],

            # Actions Required
            "actions_required": self._get_required_actions()
        }

    def _get_key_kpis(self) -> dict:
        """Holt die wichtigsten KPIs"""
        from sqlalchemy import text
        from python.models.base import get_db_context

        with get_db_context() as db:
            # YTD Verluste
            ytd_query = """
                SELECT
                    COUNT(*) as anzahl,
                    COALESCE(SUM(verlust_betrag_eur), 0) as summe,
                    COALESCE(MAX(verlust_betrag_eur), 0) as maximum,
                    COALESCE(AVG(verlust_betrag_eur), 0) as durchschnitt
                FROM risiko_ereignisse
                WHERE EXTRACT(YEAR FROM meldedatum) = EXTRACT(YEAR FROM CURRENT_DATE)
                  AND verlust_betrag_eur > 0
                  AND ist_near_miss = FALSE
            """
            ytd = db.execute(text(ytd_query)).fetchone()

            # Vorjahr zum Vergleich
            prev_query = """
                SELECT COALESCE(SUM(verlust_betrag_eur), 0) as summe
                FROM risiko_ereignisse
                WHERE EXTRACT(YEAR FROM meldedatum) = EXTRACT(YEAR FROM CURRENT_DATE) - 1
                  AND verlust_betrag_eur > 0
            """
            prev = db.execute(text(prev_query)).fetchone()

            # Offene Incidents
            incidents_query = """
                SELECT COUNT(*) as anzahl
                FROM incident_response
                WHERE abschluss_datum IS NULL
            """
            incidents = db.execute(text(incidents_query)).fetchone()

            yoy_change = 0
            if prev and prev.summe and prev.summe > 0:
                yoy_change = ((ytd.summe - prev.summe) / prev.summe) * 100

            return {
                "ytd_verlust": float(ytd.summe) if ytd else 0,
                "ytd_ereignisse": ytd.anzahl if ytd else 0,
                "max_einzelverlust": float(ytd.maximum) if ytd else 0,
                "avg_verlust": float(ytd.durchschnitt) if ytd else 0,
                "vorjahr_verlust": float(prev.summe) if prev else 0,
                "yoy_change_percent": round(yoy_change, 1),
                "offene_incidents": incidents.anzahl if incidents else 0
            }

    def _get_required_actions(self) -> list[dict]:
        """Sammelt erforderliche Aktionen"""
        actions = []

        from sqlalchemy import text
        from python.models.base import get_db_context

        with get_db_context() as db:
            # Überfällige Kontrolltests
            ctrl_query = """
                SELECT COUNT(*) as anzahl
                FROM kontrolle_mechanismen
                WHERE ist_aktiv = TRUE AND naechster_test < CURRENT_DATE
            """
            ctrl = db.execute(text(ctrl_query)).fetchone()
            if ctrl and ctrl.anzahl > 0:
                actions.append({
                    "typ": "KONTROLLE",
                    "prioritaet": "HIGH",
                    "beschreibung": f"{ctrl.anzahl} Kontrollen mit überfälligem Test",
                    "aktion": "Kontrolltests durchführen"
                })

            # Überfällige Compliance
            comp_query = """
                SELECT COUNT(*) as anzahl
                FROM compliance_vorschriften
                WHERE ist_aktiv = TRUE
                  AND deadline < CURRENT_DATE
                  AND status NOT IN ('ERFUELLT', 'NICHT_ANWENDBAR')
            """
            comp = db.execute(text(comp_query)).fetchone()
            if comp and comp.anzahl > 0:
                actions.append({
                    "typ": "COMPLIANCE",
                    "prioritaet": "CRITICAL",
                    "beschreibung": f"{comp.anzahl} überfällige Compliance-Anforderungen",
                    "aktion": "Sofortige Bearbeitung erforderlich"
                })

            # Offene kritische Ereignisse
            event_query = """
                SELECT COUNT(*) as anzahl
                FROM risiko_ereignisse
                WHERE status NOT IN ('ABGESCHLOSSEN', 'ARCHIVIERT')
                  AND risiko_schwere = 'CRITICAL'
            """
            event = db.execute(text(event_query)).fetchone()
            if event and event.anzahl > 0:
                actions.append({
                    "typ": "EREIGNIS",
                    "prioritaet": "CRITICAL",
                    "beschreibung": f"{event.anzahl} offene kritische Ereignisse",
                    "aktion": "Eskalation und Bearbeitung"
                })

        return sorted(actions, key=lambda x: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}.get(x["prioritaet"], 3))


class KRIDashboard:
    """KRI-spezifisches Dashboard"""

    def __init__(self):
        from python.analytics.kri_analysis import KRIAnalyzer
        self.analyzer = KRIAnalyzer()

    def get_dashboard_data(self) -> dict:
        """Generiert KRI Dashboard Daten"""
        return {
            "summary": self.analyzer.get_ampel_summary(),
            "current_status": [s.__dict__ for s in self.analyzer.get_current_kri_status()],
            "trend_history": self.analyzer.get_kri_trend_history(months=12),
            "correlations": [c.__dict__ for c in self.analyzer.calculate_kri_loss_correlation()],
            "early_warnings": self.analyzer.get_early_warning_indicators()
        }


class ComplianceDashboard:
    """Compliance-spezifisches Dashboard"""

    def __init__(self):
        from python.analytics.compliance_monitor import ComplianceMonitor
        self.monitor = ComplianceMonitor()

    def get_dashboard_data(self) -> dict:
        """Generiert Compliance Dashboard Daten"""
        return self.monitor.generate_compliance_report()


class ReportGenerator:
    """Generiert verschiedene Reports"""

    def __init__(self):
        self.executive = ExecutiveDashboard()

    def generate_monthly_report(self, year: int, month: int) -> dict:
        """Generiert Monatsbericht"""
        return {
            "report_type": "Monthly Operational Risk Report",
            "period": f"{year}-{month:02d}",
            "generated_at": datetime.now().isoformat(),
            "executive_summary": self.executive.generate_executive_summary()
        }

    def generate_quarterly_report(self, year: int, quarter: int) -> dict:
        """Generiert Quartalsbericht"""
        return {
            "report_type": "Quarterly Operational Risk Report",
            "period": f"{year}-Q{quarter}",
            "generated_at": datetime.now().isoformat(),
            "executive_summary": self.executive.generate_executive_summary()
        }
