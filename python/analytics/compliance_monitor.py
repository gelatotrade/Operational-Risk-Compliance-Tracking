"""
Compliance Monitoring - Überwachung regulatorischer Anforderungen
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class ComplianceStatus:
    """Status einer Compliance-Anforderung"""
    vorschrift_id: int
    vorschrift_referenz: str
    reg_werk: str
    reg_artikel: str
    anforderung_kurz: str
    deadline: date
    status: str
    erfuellungsgrad: float
    verantwortlicher: str
    abteilung: str

    # Berechnete Felder
    tage_bis_deadline: int = None
    dringlichkeit: str = ""
    ampel_farbe: str = ""
    risiko_level: str = ""
    potentielle_strafe: Decimal = None


@dataclass
class DepartmentCompliance:
    """Compliance-Status einer Abteilung"""
    abteilung: str
    total_anforderungen: int = 0
    erfuellt: int = 0
    offen: int = 0
    verletzt: int = 0
    ueberfaellig: int = 0
    erfuellungsrate: float = 0.0
    potentielle_strafen: Decimal = Decimal(0)
    kritische_deadlines: list = field(default_factory=list)


@dataclass
class RepeatViolation:
    """Wiederholte Compliance-Verstöße"""
    reg_werk: str
    abteilung: str
    anzahl_verstoesse: int
    betroffene_vorschriften: list
    wiederholungs_status: str
    empfohlene_massnahmen: list


class ComplianceMonitor:
    """Überwacht Compliance-Status und Deadlines"""

    def __init__(self, db_session=None):
        self.db = db_session

    def get_regulatory_deadlines(
        self,
        days_ahead: int = 90,
        include_completed: bool = False
    ) -> list[ComplianceStatus]:
        """
        Gibt anstehende regulatorische Deadlines zurück

        Args:
            days_ahead: Tage in die Zukunft
            include_completed: Auch erfüllte einbeziehen

        Returns:
            Liste von ComplianceStatus
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        status_filter = """
            AND cv.status NOT IN ('ERFUELLT', 'NICHT_ANWENDBAR')
        """ if not include_completed else ""

        query = f"""
            SELECT
                cv.vorschrift_id,
                cv.vorschrift_referenz,
                cv.reg_werk,
                cv.reg_artikel,
                cv.anforderung_kurz,
                cv.deadline,
                cv.status,
                cv.erfuellungsgrad,
                cv.verantwortlicher_name,
                cv.abteilung,
                cv.risiko_bei_nichterfuellung,
                cv.potentielle_strafe,
                cv.deadline - CURRENT_DATE as tage_bis_deadline
            FROM compliance_vorschriften cv
            WHERE cv.ist_aktiv = TRUE
              AND cv.deadline IS NOT NULL
              AND cv.deadline <= CURRENT_DATE + INTERVAL ':days days'
              {status_filter}
            ORDER BY
                CASE
                    WHEN cv.status = 'VERLETZT' THEN 1
                    WHEN cv.deadline < CURRENT_DATE THEN 2
                    WHEN cv.deadline < CURRENT_DATE + INTERVAL '30 days' THEN 3
                    ELSE 4
                END,
                cv.deadline
        """

        results = []
        with get_db_context() as db:
            rows = db.execute(text(query), {"days": days_ahead}).fetchall()

            for row in rows:
                status = ComplianceStatus(
                    vorschrift_id=row.vorschrift_id,
                    vorschrift_referenz=row.vorschrift_referenz or "",
                    reg_werk=row.reg_werk,
                    reg_artikel=row.reg_artikel or "",
                    anforderung_kurz=row.anforderung_kurz or "",
                    deadline=row.deadline,
                    status=row.status,
                    erfuellungsgrad=float(row.erfuellungsgrad or 0),
                    verantwortlicher=row.verantwortlicher_name or "",
                    abteilung=row.abteilung or "",
                    tage_bis_deadline=row.tage_bis_deadline,
                    risiko_level=row.risiko_bei_nichterfuellung or "MEDIUM",
                    potentielle_strafe=Decimal(str(row.potentielle_strafe)) if row.potentielle_strafe else None
                )

                # Dringlichkeit und Ampel berechnen
                status.dringlichkeit, status.ampel_farbe = self._calculate_urgency(status)

                results.append(status)

        return results

    def _calculate_urgency(self, status: ComplianceStatus) -> tuple[str, str]:
        """Berechnet Dringlichkeit und Ampelfarbe"""
        if status.status == "ERFUELLT":
            return "ABGESCHLOSSEN", "GRUEN"

        if status.status == "VERLETZT":
            return "KRITISCH", "ROT"

        days = status.tage_bis_deadline

        if days is None:
            return "UNBEKANNT", "GELB"

        if days < 0:
            return "ÜBERFÄLLIG", "ROT"
        elif days <= 30:
            return "KRITISCH", "ORANGE"
        elif days <= 90:
            return "AUFMERKSAMKEIT", "GELB"
        else:
            return "IM_PLAN", "GRUEN"

    def get_open_findings_by_department(self) -> list[DepartmentCompliance]:
        """
        Gruppiert offene Findings nach Abteilung

        Returns:
            Liste von DepartmentCompliance
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        query = """
            SELECT
                COALESCE(cv.abteilung, 'Nicht zugeordnet') as abteilung,
                COUNT(*) as total,
                COUNT(CASE WHEN cv.status = 'ERFUELLT' THEN 1 END) as erfuellt,
                COUNT(CASE WHEN cv.status = 'OFFEN' THEN 1 END) as offen,
                COUNT(CASE WHEN cv.status = 'VERLETZT' THEN 1 END) as verletzt,
                COUNT(CASE WHEN cv.deadline < CURRENT_DATE
                           AND cv.status NOT IN ('ERFUELLT', 'NICHT_ANWENDBAR') THEN 1 END) as ueberfaellig,
                COALESCE(SUM(cv.potentielle_strafe), 0) as potentielle_strafen,
                ARRAY_AGG(cv.vorschrift_referenz)
                    FILTER (WHERE cv.deadline < CURRENT_DATE + INTERVAL '30 days'
                            AND cv.status NOT IN ('ERFUELLT', 'NICHT_ANWENDBAR'))
                    as kritische_refs
            FROM compliance_vorschriften cv
            WHERE cv.ist_aktiv = TRUE
            GROUP BY cv.abteilung
            ORDER BY verletzt DESC, ueberfaellig DESC
        """

        results = []
        with get_db_context() as db:
            rows = db.execute(text(query)).fetchall()

            for row in rows:
                dept = DepartmentCompliance(
                    abteilung=row.abteilung,
                    total_anforderungen=row.total,
                    erfuellt=row.erfuellt or 0,
                    offen=row.offen or 0,
                    verletzt=row.verletzt or 0,
                    ueberfaellig=row.ueberfaellig or 0,
                    potentielle_strafen=Decimal(str(row.potentielle_strafen or 0)),
                    kritische_deadlines=row.kritische_refs or []
                )

                # Erfüllungsrate berechnen
                if dept.total_anforderungen > 0:
                    dept.erfuellungsrate = dept.erfuellt / dept.total_anforderungen * 100

                results.append(dept)

        return results

    def analyze_repeat_violations(self) -> list[RepeatViolation]:
        """
        Analysiert wiederholte Compliance-Verstöße

        Returns:
            Liste von RepeatViolation
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        query = """
            WITH violation_counts AS (
                SELECT
                    reg_werk,
                    abteilung,
                    COUNT(*) as anzahl,
                    ARRAY_AGG(vorschrift_referenz) as refs
                FROM compliance_vorschriften
                WHERE status = 'VERLETZT'
                  AND ist_aktiv = TRUE
                GROUP BY reg_werk, abteilung
                HAVING COUNT(*) > 1
            )
            SELECT
                reg_werk,
                COALESCE(abteilung, 'Nicht zugeordnet') as abteilung,
                anzahl,
                refs
            FROM violation_counts
            ORDER BY anzahl DESC
        """

        results = []
        with get_db_context() as db:
            rows = db.execute(text(query)).fetchall()

            for row in rows:
                # Wiederholungsstatus bestimmen
                if row.anzahl >= 5:
                    status = "KRITISCH_SYSTEMISCH"
                    massnahmen = [
                        "Sofortige Eskalation an Vorstand",
                        "Externe Compliance-Prüfung einleiten",
                        "Prozess-Reengineering erforderlich"
                    ]
                elif row.anzahl >= 3:
                    status = "KRITISCH_WIEDERHOLEND"
                    massnahmen = [
                        "Eskalation an Bereichsleitung",
                        "Root-Cause-Analyse durchführen",
                        "Schulungsmaßnahmen intensivieren"
                    ]
                else:
                    status = "WIEDERHOLEND"
                    massnahmen = [
                        "Prozesse überprüfen",
                        "Awareness-Training durchführen"
                    ]

                results.append(RepeatViolation(
                    reg_werk=row.reg_werk,
                    abteilung=row.abteilung,
                    anzahl_verstoesse=row.anzahl,
                    betroffene_vorschriften=row.refs or [],
                    wiederholungs_status=status,
                    empfohlene_massnahmen=massnahmen
                ))

        return results

    def get_compliance_by_regulation(self) -> dict:
        """
        Gibt Compliance-Status gruppiert nach Regulierung zurück

        Returns:
            Dict mit Status pro Regulierung
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        query = """
            SELECT
                cv.reg_werk,
                COUNT(*) as total,
                COUNT(CASE WHEN cv.status = 'ERFUELLT' THEN 1 END) as erfuellt,
                COUNT(CASE WHEN cv.status = 'OFFEN' THEN 1 END) as offen,
                COUNT(CASE WHEN cv.status = 'VERLETZT' THEN 1 END) as verletzt,
                COUNT(CASE WHEN cv.status = 'IN_BEARBEITUNG' THEN 1 END) as in_bearbeitung,
                MIN(cv.deadline) FILTER (WHERE cv.status NOT IN ('ERFUELLT', 'NICHT_ANWENDBAR')) as naechste_deadline,
                COALESCE(SUM(cv.potentielle_strafe), 0) as potentielle_strafen
            FROM compliance_vorschriften cv
            WHERE cv.ist_aktiv = TRUE
            GROUP BY cv.reg_werk
            ORDER BY verletzt DESC, offen DESC
        """

        with get_db_context() as db:
            rows = db.execute(text(query)).fetchall()

            result = {}
            for row in rows:
                total = row.total
                erfuellt = row.erfuellt or 0

                result[row.reg_werk] = {
                    "total": total,
                    "erfuellt": erfuellt,
                    "offen": row.offen or 0,
                    "verletzt": row.verletzt or 0,
                    "in_bearbeitung": row.in_bearbeitung or 0,
                    "erfuellungsrate": erfuellt / total * 100 if total > 0 else 0,
                    "naechste_deadline": row.naechste_deadline.isoformat() if row.naechste_deadline else None,
                    "potentielle_strafen": float(row.potentielle_strafen or 0)
                }

            return result

    def get_compliance_summary(self) -> dict:
        """
        Gibt eine Gesamtzusammenfassung des Compliance-Status

        Returns:
            Dict mit Zusammenfassung
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        query = """
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN status = 'ERFUELLT' THEN 1 END) as erfuellt,
                COUNT(CASE WHEN status = 'OFFEN' THEN 1 END) as offen,
                COUNT(CASE WHEN status = 'VERLETZT' THEN 1 END) as verletzt,
                COUNT(CASE WHEN status = 'IN_BEARBEITUNG' THEN 1 END) as in_bearbeitung,
                COUNT(CASE WHEN deadline < CURRENT_DATE
                           AND status NOT IN ('ERFUELLT', 'NICHT_ANWENDBAR') THEN 1 END) as ueberfaellig,
                COUNT(CASE WHEN deadline BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days'
                           AND status NOT IN ('ERFUELLT', 'NICHT_ANWENDBAR') THEN 1 END) as deadline_30d,
                COALESCE(SUM(potentielle_strafe)
                    FILTER (WHERE status = 'VERLETZT'), 0) as aktuelle_strafrisiko,
                COALESCE(SUM(potentielle_strafe)
                    FILTER (WHERE status NOT IN ('ERFUELLT', 'NICHT_ANWENDBAR')), 0) as potentielles_strafrisiko
            FROM compliance_vorschriften
            WHERE ist_aktiv = TRUE
        """

        with get_db_context() as db:
            row = db.execute(text(query)).fetchone()

            total = row.total or 1  # Prevent division by zero
            erfuellt = row.erfuellt or 0

            return {
                "total_anforderungen": total,
                "erfuellt": erfuellt,
                "offen": row.offen or 0,
                "verletzt": row.verletzt or 0,
                "in_bearbeitung": row.in_bearbeitung or 0,
                "ueberfaellig": row.ueberfaellig or 0,
                "deadline_naechste_30_tage": row.deadline_30d or 0,
                "erfuellungsrate_prozent": erfuellt / total * 100,
                "compliance_score": self._calculate_compliance_score(row),
                "aktuelle_strafrisiko_eur": float(row.aktuelle_strafrisiko or 0),
                "potentielles_strafrisiko_eur": float(row.potentielles_strafrisiko or 0),
                "ampel_status": self._get_overall_ampel(row)
            }

    def _calculate_compliance_score(self, row) -> float:
        """Berechnet einen Compliance-Score (0-100)"""
        if not row.total or row.total == 0:
            return 100.0

        # Gewichtung: Erfüllt=100%, Offen=50%, In Bearbeitung=70%, Verletzt=0%
        score = (
            (row.erfuellt or 0) * 100 +
            (row.in_bearbeitung or 0) * 70 +
            (row.offen or 0) * 50 +
            (row.verletzt or 0) * 0
        ) / row.total

        # Abzug für überfällige
        penalty = min((row.ueberfaellig or 0) * 5, 30)

        return max(0, score - penalty)

    def _get_overall_ampel(self, row) -> str:
        """Bestimmt die Gesamt-Ampelfarbe"""
        if (row.verletzt or 0) > 0:
            return "ROT"

        if (row.ueberfaellig or 0) > 0:
            return "ROT"

        if (row.deadline_30d or 0) > 0:
            return "GELB"

        erfuellungsrate = (row.erfuellt or 0) / (row.total or 1) * 100

        if erfuellungsrate >= 90:
            return "GRUEN"
        elif erfuellungsrate >= 70:
            return "GELB"
        else:
            return "ROT"

    def generate_compliance_report(self) -> dict:
        """
        Generiert einen umfassenden Compliance-Report

        Returns:
            Dict mit vollständigem Report
        """
        return {
            "report_date": date.today().isoformat(),
            "summary": self.get_compliance_summary(),
            "by_regulation": self.get_compliance_by_regulation(),
            "by_department": [
                {
                    "abteilung": d.abteilung,
                    "total": d.total_anforderungen,
                    "erfuellt": d.erfuellt,
                    "erfuellungsrate": d.erfuellungsrate,
                    "verletzt": d.verletzt,
                    "ueberfaellig": d.ueberfaellig,
                    "potentielle_strafen": float(d.potentielle_strafen)
                }
                for d in self.get_open_findings_by_department()
            ],
            "upcoming_deadlines": [
                {
                    "referenz": d.vorschrift_referenz,
                    "reg_werk": d.reg_werk,
                    "deadline": d.deadline.isoformat(),
                    "tage_bis_deadline": d.tage_bis_deadline,
                    "status": d.status,
                    "dringlichkeit": d.dringlichkeit,
                    "verantwortlicher": d.verantwortlicher
                }
                for d in self.get_regulatory_deadlines(days_ahead=90)[:20]
            ],
            "repeat_violations": [
                {
                    "reg_werk": v.reg_werk,
                    "abteilung": v.abteilung,
                    "anzahl": v.anzahl_verstoesse,
                    "status": v.wiederholungs_status,
                    "massnahmen": v.empfohlene_massnahmen
                }
                for v in self.analyze_repeat_violations()
            ]
        }
