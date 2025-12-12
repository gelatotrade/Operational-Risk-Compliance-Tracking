"""
Risk Heatmap Generator - Erstellt Risiko-Heatmaps (Häufigkeit × Auswirkung)
"""

import logging
from datetime import date
from decimal import Decimal
from dataclasses import dataclass
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class HeatmapCell:
    """Eine Zelle in der Risk Heatmap"""
    ereignis_typ: str
    basel_kategorie: str
    geschaeftsbereich: str

    haeufigkeit_score: int  # 1-5
    auswirkung_score: int  # 1-5
    risiko_score: int  # 1-25

    risiko_kategorie: str  # NIEDRIG, MITTEL, HOCH, KRITISCH
    ampel_farbe: str

    anzahl_ereignisse: int
    gesamt_verlust: Decimal
    durchschnitt_verlust: Decimal
    max_verlust: Decimal


class RiskHeatmapGenerator:
    """Generiert Risk Heatmaps für verschiedene Dimensionen"""

    # Schwellwerte für Häufigkeit (Ereignisse pro Jahr)
    FREQUENCY_THRESHOLDS = [5, 10, 20, 50]  # Für Score 1-5

    # Schwellwerte für Auswirkung (EUR)
    SEVERITY_THRESHOLDS = [10000, 100000, 1000000, 10000000]  # Für Score 1-5

    # Risiko-Matrix Kategorisierung
    RISK_MATRIX = {
        (1, 1): ("NIEDRIG", "GRUEN"),
        (1, 2): ("NIEDRIG", "GRUEN"),
        (1, 3): ("MITTEL", "GELB"),
        (1, 4): ("HOCH", "ORANGE"),
        (1, 5): ("KRITISCH", "ROT"),
        (2, 1): ("NIEDRIG", "GRUEN"),
        (2, 2): ("NIEDRIG", "GRUEN"),
        (2, 3): ("MITTEL", "GELB"),
        (2, 4): ("HOCH", "ORANGE"),
        (2, 5): ("KRITISCH", "ROT"),
        (3, 1): ("MITTEL", "GELB"),
        (3, 2): ("MITTEL", "GELB"),
        (3, 3): ("MITTEL", "GELB"),
        (3, 4): ("HOCH", "ORANGE"),
        (3, 5): ("KRITISCH", "ROT"),
        (4, 1): ("HOCH", "ORANGE"),
        (4, 2): ("HOCH", "ORANGE"),
        (4, 3): ("HOCH", "ORANGE"),
        (4, 4): ("KRITISCH", "ROT"),
        (4, 5): ("KRITISCH", "ROT"),
        (5, 1): ("KRITISCH", "ROT"),
        (5, 2): ("KRITISCH", "ROT"),
        (5, 3): ("KRITISCH", "ROT"),
        (5, 4): ("KRITISCH", "ROT"),
        (5, 5): ("KRITISCH", "ROT"),
    }

    def __init__(self, db_session=None):
        self.db = db_session

    def generate_heatmap(
        self,
        years: int = 3,
        group_by: str = "ereignis_typ"  # ereignis_typ, basel_kategorie, geschaeftsbereich
    ) -> list[HeatmapCell]:
        """
        Generiert eine Risk Heatmap

        Args:
            years: Betrachtungszeitraum in Jahren
            group_by: Gruppierungsdimension

        Returns:
            Liste von HeatmapCell
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        query = f"""
            SELECT
                COALESCE(re.ereignis_typ, 'Nicht kategorisiert') as ereignis_typ,
                COALESCE(bc.kategorie_name_de, 'Nicht kategorisiert') as basel_kategorie,
                COALESCE(re.geschaeftsbereich, 'Nicht zugeordnet') as geschaeftsbereich,
                COUNT(*) as anzahl,
                COALESCE(SUM(re.verlust_betrag_eur), 0) as gesamt_verlust,
                COALESCE(AVG(re.verlust_betrag_eur), 0) as avg_verlust,
                COALESCE(MAX(re.verlust_betrag_eur), 0) as max_verlust
            FROM risiko_ereignisse re
            LEFT JOIN basel_risikokategorien bc ON re.basel_kategorie_id = bc.kategorie_id
            WHERE re.meldedatum >= CURRENT_DATE - INTERVAL ':years years'
              AND re.verlust_betrag_eur > 0
              AND re.ist_near_miss = FALSE
            GROUP BY re.ereignis_typ, bc.kategorie_name_de, re.geschaeftsbereich
            ORDER BY gesamt_verlust DESC
        """

        results = []

        with get_db_context() as db:
            rows = db.execute(text(query), {"years": years}).fetchall()

            # Annualisieren für Häufigkeits-Score
            for row in rows:
                annual_count = row.anzahl / years

                # Scores berechnen
                freq_score = self._calculate_frequency_score(annual_count)
                sev_score = self._calculate_severity_score(float(row.avg_verlust))

                risk_score = freq_score * sev_score
                risk_cat, ampel = self.RISK_MATRIX.get(
                    (freq_score, sev_score),
                    ("MITTEL", "GELB")
                )

                results.append(HeatmapCell(
                    ereignis_typ=row.ereignis_typ,
                    basel_kategorie=row.basel_kategorie,
                    geschaeftsbereich=row.geschaeftsbereich,
                    haeufigkeit_score=freq_score,
                    auswirkung_score=sev_score,
                    risiko_score=risk_score,
                    risiko_kategorie=risk_cat,
                    ampel_farbe=ampel,
                    anzahl_ereignisse=row.anzahl,
                    gesamt_verlust=Decimal(str(row.gesamt_verlust)),
                    durchschnitt_verlust=Decimal(str(row.avg_verlust)),
                    max_verlust=Decimal(str(row.max_verlust))
                ))

        return sorted(results, key=lambda x: x.risiko_score, reverse=True)

    def _calculate_frequency_score(self, annual_count: float) -> int:
        """Berechnet Häufigkeits-Score (1-5)"""
        for i, threshold in enumerate(self.FREQUENCY_THRESHOLDS):
            if annual_count < threshold:
                return i + 1
        return 5

    def _calculate_severity_score(self, avg_loss: float) -> int:
        """Berechnet Auswirkungs-Score (1-5)"""
        for i, threshold in enumerate(self.SEVERITY_THRESHOLDS):
            if avg_loss < threshold:
                return i + 1
        return 5

    def get_matrix_view(self, cells: list[HeatmapCell]) -> dict:
        """
        Konvertiert Heatmap-Daten in eine Matrix-Struktur

        Args:
            cells: Liste von HeatmapCell

        Returns:
            Dict mit Matrix-Struktur für Dashboard
        """
        matrix = {}

        for cell in cells:
            key = (cell.haeufigkeit_score, cell.auswirkung_score)
            if key not in matrix:
                matrix[key] = {
                    "frequency_score": cell.haeufigkeit_score,
                    "severity_score": cell.auswirkung_score,
                    "risk_score": cell.risiko_score,
                    "kategorie": cell.risiko_kategorie,
                    "farbe": cell.ampel_farbe,
                    "items": [],
                    "total_count": 0,
                    "total_loss": Decimal(0)
                }

            matrix[key]["items"].append({
                "typ": cell.ereignis_typ,
                "basel": cell.basel_kategorie,
                "bereich": cell.geschaeftsbereich,
                "count": cell.anzahl_ereignisse,
                "loss": float(cell.gesamt_verlust)
            })
            matrix[key]["total_count"] += cell.anzahl_ereignisse
            matrix[key]["total_loss"] += cell.gesamt_verlust

        # In Liste konvertieren für JSON-Serialisierung
        return {
            "matrix": [
                {
                    **v,
                    "total_loss": float(v["total_loss"]),
                    "key": f"{k[0]}_{k[1]}"
                }
                for k, v in matrix.items()
            ],
            "frequency_labels": ["Sehr selten", "Selten", "Gelegentlich", "Häufig", "Sehr häufig"],
            "severity_labels": ["Gering", "Moderat", "Erheblich", "Schwer", "Katastrophal"],
            "color_scale": {
                "NIEDRIG": "#28a745",
                "MITTEL": "#ffc107",
                "HOCH": "#fd7e14",
                "KRITISCH": "#dc3545"
            }
        }

    def get_summary(self, cells: list[HeatmapCell]) -> dict:
        """
        Erstellt eine Zusammenfassung der Heatmap

        Args:
            cells: Liste von HeatmapCell

        Returns:
            Dict mit Zusammenfassung
        """
        if not cells:
            return {"total": 0}

        kritisch = [c for c in cells if c.risiko_kategorie == "KRITISCH"]
        hoch = [c for c in cells if c.risiko_kategorie == "HOCH"]
        mittel = [c for c in cells if c.risiko_kategorie == "MITTEL"]
        niedrig = [c for c in cells if c.risiko_kategorie == "NIEDRIG"]

        return {
            "total_kategorien": len(cells),
            "kritisch": {
                "anzahl": len(kritisch),
                "ereignisse": sum(c.anzahl_ereignisse for c in kritisch),
                "verlust": float(sum(c.gesamt_verlust for c in kritisch))
            },
            "hoch": {
                "anzahl": len(hoch),
                "ereignisse": sum(c.anzahl_ereignisse for c in hoch),
                "verlust": float(sum(c.gesamt_verlust for c in hoch))
            },
            "mittel": {
                "anzahl": len(mittel),
                "ereignisse": sum(c.anzahl_ereignisse for c in mittel),
                "verlust": float(sum(c.gesamt_verlust for c in mittel))
            },
            "niedrig": {
                "anzahl": len(niedrig),
                "ereignisse": sum(c.anzahl_ereignisse for c in niedrig),
                "verlust": float(sum(c.gesamt_verlust for c in niedrig))
            },
            "top_risiken": [
                {
                    "typ": c.ereignis_typ,
                    "basel": c.basel_kategorie,
                    "score": c.risiko_score,
                    "kategorie": c.risiko_kategorie,
                    "verlust": float(c.gesamt_verlust)
                }
                for c in cells[:5]
            ]
        }

    def export_for_visualization(self, years: int = 3) -> dict:
        """
        Exportiert Heatmap-Daten für Visualisierungs-Tools

        Args:
            years: Betrachtungszeitraum

        Returns:
            Dict mit allen Visualisierungsdaten
        """
        cells = self.generate_heatmap(years=years)

        return {
            "generated_at": date.today().isoformat(),
            "period_years": years,
            "heatmap": self.get_matrix_view(cells),
            "summary": self.get_summary(cells),
            "by_event_type": self._group_by_dimension(cells, "ereignis_typ"),
            "by_basel_category": self._group_by_dimension(cells, "basel_kategorie"),
            "by_business_line": self._group_by_dimension(cells, "geschaeftsbereich")
        }

    def _group_by_dimension(self, cells: list[HeatmapCell], dimension: str) -> list[dict]:
        """Gruppiert Daten nach einer Dimension"""
        grouped = {}

        for cell in cells:
            key = getattr(cell, dimension)
            if key not in grouped:
                grouped[key] = {
                    "name": key,
                    "ereignisse": 0,
                    "verlust": Decimal(0),
                    "max_risk_score": 0,
                    "kategorien": set()
                }

            grouped[key]["ereignisse"] += cell.anzahl_ereignisse
            grouped[key]["verlust"] += cell.gesamt_verlust
            grouped[key]["max_risk_score"] = max(grouped[key]["max_risk_score"], cell.risiko_score)
            grouped[key]["kategorien"].add(cell.risiko_kategorie)

        return [
            {
                "name": v["name"],
                "ereignisse": v["ereignisse"],
                "verlust": float(v["verlust"]),
                "max_risk_score": v["max_risk_score"],
                "hoechste_kategorie": self._highest_category(v["kategorien"])
            }
            for v in sorted(grouped.values(), key=lambda x: x["verlust"], reverse=True)
        ]

    def _highest_category(self, categories: set) -> str:
        """Bestimmt die höchste Risikokategorie"""
        priority = {"KRITISCH": 4, "HOCH": 3, "MITTEL": 2, "NIEDRIG": 1}
        return max(categories, key=lambda x: priority.get(x, 0))
