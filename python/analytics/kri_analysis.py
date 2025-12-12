"""
KRI Analysis - Key Risk Indicator Analyse
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional
from dataclasses import dataclass, field
import numpy as np
from scipy import stats

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import settings, TRAFFIC_LIGHT_STATUS

logger = logging.getLogger(__name__)


@dataclass
class KRIStatus:
    """Status eines einzelnen KRI"""
    kri_id: int
    kri_referenz: str
    kri_name: str
    risiko_kategorie: str
    geschaeftsbereich: str

    aktueller_wert: Decimal
    ziel_wert: Decimal
    ampel_status: str
    trend: str

    # Historische Daten
    wert_vor_1m: Decimal = None
    wert_vor_3m: Decimal = None
    wert_vor_12m: Decimal = None

    # Abweichungen
    abweichung_absolut: Decimal = None
    abweichung_prozent: float = None

    # Flags
    ist_early_warning: bool = False
    ist_persistent_rot: bool = False
    erfordert_massnahme: bool = False


@dataclass
class KRICorrelation:
    """Korrelation zwischen KRI und Verlusten"""
    kri_name: str
    correlation_coefficient: float
    p_value: float
    lag_months: int
    interpretation: str


class KRIAnalyzer:
    """Analysiert Key Risk Indicators"""

    def __init__(self, db_session=None):
        self.db = db_session

    def get_current_kri_status(self) -> list[KRIStatus]:
        """
        Gibt den aktuellen Status aller KRIs zurück

        Returns:
            Liste von KRIStatus
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        query = """
            WITH latest_values AS (
                SELECT DISTINCT ON (kri_id)
                    km.kri_id,
                    km.mess_datum,
                    km.ist_wert,
                    km.ziel_wert,
                    km.ampel_status,
                    km.trend
                FROM kri_messwerte km
                ORDER BY kri_id, mess_datum DESC
            ),
            historical AS (
                SELECT
                    kri_id,
                    MAX(CASE WHEN mess_datum = CURRENT_DATE - INTERVAL '1 month' THEN ist_wert END) as wert_1m,
                    MAX(CASE WHEN mess_datum = CURRENT_DATE - INTERVAL '3 months' THEN ist_wert END) as wert_3m,
                    MAX(CASE WHEN mess_datum = CURRENT_DATE - INTERVAL '12 months' THEN ist_wert END) as wert_12m
                FROM kri_messwerte
                GROUP BY kri_id
            ),
            red_streak AS (
                SELECT
                    kri_id,
                    COUNT(*) as consecutive_red
                FROM (
                    SELECT
                        kri_id,
                        ampel_status,
                        mess_datum,
                        ROW_NUMBER() OVER (PARTITION BY kri_id ORDER BY mess_datum DESC) as rn
                    FROM kri_messwerte
                    WHERE ampel_status = 'ROT'
                ) sub
                WHERE rn <= 3
                GROUP BY kri_id
                HAVING COUNT(*) >= 3
            )
            SELECT
                kri.kri_id,
                kri.kri_referenz,
                kri.kri_name,
                kri.risiko_kategorie,
                kri.geschaeftsbereich,
                lv.ist_wert as aktueller_wert,
                COALESCE(lv.ziel_wert, kri.ziel_wert) as ziel_wert,
                lv.ampel_status,
                lv.trend,
                h.wert_1m,
                h.wert_3m,
                h.wert_12m,
                CASE WHEN rs.kri_id IS NOT NULL THEN TRUE ELSE FALSE END as ist_persistent_rot
            FROM key_risk_indicators kri
            JOIN latest_values lv ON kri.kri_id = lv.kri_id
            LEFT JOIN historical h ON kri.kri_id = h.kri_id
            LEFT JOIN red_streak rs ON kri.kri_id = rs.kri_id
            WHERE kri.ist_aktiv = TRUE
            ORDER BY
                CASE lv.ampel_status WHEN 'ROT' THEN 1 WHEN 'GELB' THEN 2 ELSE 3 END,
                kri.kri_name
        """

        results = []
        with get_db_context() as db:
            rows = db.execute(text(query)).fetchall()

            for row in rows:
                aktuell = Decimal(str(row.aktueller_wert)) if row.aktueller_wert else Decimal(0)
                ziel = Decimal(str(row.ziel_wert)) if row.ziel_wert else None

                abw_abs = None
                abw_pct = None
                if ziel and ziel != 0:
                    abw_abs = aktuell - ziel
                    abw_pct = float(abw_abs / ziel * 100)

                status = KRIStatus(
                    kri_id=row.kri_id,
                    kri_referenz=row.kri_referenz,
                    kri_name=row.kri_name,
                    risiko_kategorie=row.risiko_kategorie or "",
                    geschaeftsbereich=row.geschaeftsbereich or "",
                    aktueller_wert=aktuell,
                    ziel_wert=ziel,
                    ampel_status=row.ampel_status or "GRUEN",
                    trend=row.trend or "STABIL",
                    wert_vor_1m=Decimal(str(row.wert_1m)) if row.wert_1m else None,
                    wert_vor_3m=Decimal(str(row.wert_3m)) if row.wert_3m else None,
                    wert_vor_12m=Decimal(str(row.wert_12m)) if row.wert_12m else None,
                    abweichung_absolut=abw_abs,
                    abweichung_prozent=abw_pct,
                    ist_persistent_rot=row.ist_persistent_rot,
                    ist_early_warning=row.ampel_status == 'ROT' or row.ist_persistent_rot,
                    erfordert_massnahme=row.ampel_status in ('ROT', 'GELB')
                )
                results.append(status)

        return results

    def get_kri_trend_history(
        self,
        kri_id: int = None,
        months: int = 12
    ) -> dict:
        """
        Gibt die KRI-Trendhistorie zurück

        Args:
            kri_id: Optional spezifischer KRI
            months: Anzahl Monate Historie

        Returns:
            Dict mit Trenddaten
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        query = """
            SELECT
                kri.kri_id,
                kri.kri_referenz,
                kri.kri_name,
                km.mess_datum,
                km.ist_wert,
                km.ziel_wert,
                km.ampel_status,
                km.trend
            FROM key_risk_indicators kri
            JOIN kri_messwerte km ON kri.kri_id = km.kri_id
            WHERE kri.ist_aktiv = TRUE
              AND km.mess_datum >= CURRENT_DATE - INTERVAL ':months months'
              AND (:kri_id IS NULL OR kri.kri_id = :kri_id)
            ORDER BY kri.kri_id, km.mess_datum
        """

        with get_db_context() as db:
            rows = db.execute(text(query), {"months": months, "kri_id": kri_id}).fetchall()

            # Nach KRI gruppieren
            kri_data = {}
            for row in rows:
                if row.kri_id not in kri_data:
                    kri_data[row.kri_id] = {
                        "kri_referenz": row.kri_referenz,
                        "kri_name": row.kri_name,
                        "history": []
                    }

                kri_data[row.kri_id]["history"].append({
                    "datum": row.mess_datum.isoformat(),
                    "ist_wert": float(row.ist_wert),
                    "ziel_wert": float(row.ziel_wert) if row.ziel_wert else None,
                    "ampel_status": row.ampel_status,
                    "trend": row.trend
                })

            return kri_data

    def calculate_kri_loss_correlation(
        self,
        lag_months: list[int] = None
    ) -> list[KRICorrelation]:
        """
        Berechnet die Korrelation zwischen KRIs und tatsächlichen Verlusten

        Args:
            lag_months: Liste der Verzögerungen in Monaten zu testen

        Returns:
            Liste von KRICorrelation
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        if lag_months is None:
            lag_months = [0, 1, 2, 3]

        results = []

        # KRI-Daten laden
        kri_query = """
            SELECT
                kri.kri_name,
                DATE_TRUNC('month', km.mess_datum) as monat,
                AVG(km.ist_wert) as avg_wert
            FROM key_risk_indicators kri
            JOIN kri_messwerte km ON kri.kri_id = km.kri_id
            WHERE kri.ist_aktiv = TRUE
            GROUP BY kri.kri_name, DATE_TRUNC('month', km.mess_datum)
            ORDER BY kri.kri_name, monat
        """

        # Verlust-Daten laden
        loss_query = """
            SELECT
                DATE_TRUNC('month', meldedatum) as monat,
                SUM(verlust_betrag_eur) as gesamt_verlust
            FROM risiko_ereignisse
            WHERE verlust_betrag_eur > 0
              AND ist_near_miss = FALSE
            GROUP BY DATE_TRUNC('month', meldedatum)
            ORDER BY monat
        """

        with get_db_context() as db:
            kri_rows = db.execute(text(kri_query)).fetchall()
            loss_rows = db.execute(text(loss_query)).fetchall()

            # In DataFrames konvertieren für einfachere Verarbeitung
            import pandas as pd

            loss_df = pd.DataFrame([
                {"monat": row.monat, "verlust": float(row.gesamt_verlust)}
                for row in loss_rows
            ])
            loss_df["monat"] = pd.to_datetime(loss_df["monat"])
            loss_df = loss_df.set_index("monat")

            # Für jeden KRI Korrelation berechnen
            kri_data = {}
            for row in kri_rows:
                if row.kri_name not in kri_data:
                    kri_data[row.kri_name] = []
                kri_data[row.kri_name].append({
                    "monat": row.monat,
                    "wert": float(row.avg_wert)
                })

            for kri_name, values in kri_data.items():
                kri_df = pd.DataFrame(values)
                kri_df["monat"] = pd.to_datetime(kri_df["monat"])
                kri_df = kri_df.set_index("monat")

                best_corr = None
                best_lag = 0
                best_pvalue = 1.0

                for lag in lag_months:
                    # KRI um lag Monate verschieben
                    shifted_kri = kri_df.shift(lag)

                    # Merge mit Verlusten
                    merged = pd.merge(
                        shifted_kri, loss_df,
                        left_index=True, right_index=True,
                        how="inner"
                    ).dropna()

                    if len(merged) >= 10:
                        corr, pvalue = stats.pearsonr(merged["wert"], merged["verlust"])

                        if abs(corr) > abs(best_corr or 0):
                            best_corr = corr
                            best_lag = lag
                            best_pvalue = pvalue

                if best_corr is not None:
                    # Interpretation
                    if abs(best_corr) >= 0.7:
                        interp = "Starke Korrelation"
                    elif abs(best_corr) >= 0.4:
                        interp = "Moderate Korrelation"
                    elif abs(best_corr) >= 0.2:
                        interp = "Schwache Korrelation"
                    else:
                        interp = "Keine signifikante Korrelation"

                    if best_corr > 0:
                        interp += " (positiv)"
                    else:
                        interp += " (negativ)"

                    if best_pvalue < 0.05:
                        interp += " - statistisch signifikant"

                    results.append(KRICorrelation(
                        kri_name=kri_name,
                        correlation_coefficient=best_corr,
                        p_value=best_pvalue,
                        lag_months=best_lag,
                        interpretation=interp
                    ))

        return sorted(results, key=lambda x: abs(x.correlation_coefficient), reverse=True)

    def get_early_warning_indicators(self) -> list[dict]:
        """
        Identifiziert KRIs die als Early Warning dienen

        Returns:
            Liste der Early Warning KRIs mit Details
        """
        status_list = self.get_current_kri_status()

        warnings = []
        for status in status_list:
            if status.ist_early_warning:
                warnings.append({
                    "kri_referenz": status.kri_referenz,
                    "kri_name": status.kri_name,
                    "risiko_kategorie": status.risiko_kategorie,
                    "geschaeftsbereich": status.geschaeftsbereich,
                    "aktueller_wert": float(status.aktueller_wert),
                    "ziel_wert": float(status.ziel_wert) if status.ziel_wert else None,
                    "ampel_status": status.ampel_status,
                    "trend": status.trend,
                    "ist_persistent_rot": status.ist_persistent_rot,
                    "grund": self._get_warning_reason(status)
                })

        return warnings

    def _get_warning_reason(self, status: KRIStatus) -> str:
        """Gibt den Grund für das Early Warning zurück"""
        reasons = []

        if status.ampel_status == "ROT":
            reasons.append("Aktueller Status ROT")

        if status.ist_persistent_rot:
            reasons.append("Persistierend ROT (3+ Perioden)")

        if status.trend == "VERSCHLECHTERT":
            reasons.append("Verschlechterungstrend")

        if status.abweichung_prozent and abs(status.abweichung_prozent) > 20:
            reasons.append(f"Hohe Abweichung vom Ziel ({status.abweichung_prozent:.1f}%)")

        return "; ".join(reasons) if reasons else "Keine spezifischen Gründe"

    def get_ampel_summary(self) -> dict:
        """
        Gibt eine Zusammenfassung der Ampelstatus aller KRIs

        Returns:
            Dict mit Ampel-Zusammenfassung
        """
        status_list = self.get_current_kri_status()

        summary = {
            "GRUEN": 0,
            "GELB": 0,
            "ROT": 0,
            "total": len(status_list),
            "early_warnings": 0,
            "by_category": {}
        }

        for status in status_list:
            ampel = status.ampel_status
            if ampel in summary:
                summary[ampel] += 1

            if status.ist_early_warning:
                summary["early_warnings"] += 1

            # Nach Kategorie
            cat = status.risiko_kategorie or "Nicht kategorisiert"
            if cat not in summary["by_category"]:
                summary["by_category"][cat] = {"GRUEN": 0, "GELB": 0, "ROT": 0}
            if ampel in summary["by_category"][cat]:
                summary["by_category"][cat][ampel] += 1

        # Prozentsätze
        if summary["total"] > 0:
            summary["gruen_pct"] = summary["GRUEN"] / summary["total"] * 100
            summary["gelb_pct"] = summary["GELB"] / summary["total"] * 100
            summary["rot_pct"] = summary["ROT"] / summary["total"] * 100

        return summary
