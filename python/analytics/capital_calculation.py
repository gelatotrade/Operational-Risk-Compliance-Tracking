"""
Capital Calculation - AMA-basierte Kapitalberechnung für operationelle Risiken
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from dataclasses import dataclass, field
import numpy as np
from scipy import stats

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class LDAResult:
    """Ergebnis der Loss Distribution Approach Berechnung"""
    geschaeftsbereich: str
    basel_kategorie: str

    # Frequenz-Verteilung
    frequency_mean: float
    frequency_distribution: str = "Poisson"

    # Severity-Verteilung
    severity_mean: float
    severity_std: float
    severity_distribution: str = "Lognormal"
    severity_params: dict = field(default_factory=dict)

    # Berechnete Werte
    expected_loss: Decimal = Decimal(0)
    unexpected_loss: Decimal = Decimal(0)
    var_999: Decimal = Decimal(0)
    capital_charge: Decimal = Decimal(0)


@dataclass
class ScenarioCapital:
    """Szenario-basierte Kapitalanforderung"""
    scenario_id: int
    scenario_name: str
    risiko_kategorie: str
    wahrscheinlichkeit: float
    auswirkung: Decimal
    erwarteter_verlust: Decimal
    var_999: Decimal
    residual_nach_controls: Decimal
    versicherung: Decimal
    capital_charge: Decimal
    validiert: bool


@dataclass
class InsuranceMitigation:
    """Versicherungs-Anrechnung"""
    risiko_kategorie: str
    brutto_verlust: Decimal
    versicherungs_erstattung: Decimal
    anerkannte_versicherung: Decimal  # Max 20% nach AMA
    netto_verlust: Decimal
    erstattungsquote: float


class CapitalCalculator:
    """Berechnet regulatorische Kapitalanforderungen nach AMA"""

    # AMA-Limits
    MAX_INSURANCE_RECOGNITION = 0.20  # Max 20% Versicherungsanrechnung
    CONFIDENCE_LEVEL = 0.999  # 99.9% VaR

    def __init__(self, db_session=None):
        self.db = db_session

    def calculate_lda_capital(
        self,
        years_history: int = 5,
        n_simulations: int = 100000
    ) -> list[LDAResult]:
        """
        Berechnet Kapitalanforderung mittels Loss Distribution Approach

        Args:
            years_history: Jahre für historische Daten
            n_simulations: Monte-Carlo-Simulationen

        Returns:
            Liste von LDAResult pro Geschäftsbereich/Kategorie
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        # Historische Daten laden
        query = """
            SELECT
                COALESCE(gb.bereich_code, 'GESAMT') as geschaeftsbereich,
                COALESCE(bc.kategorie_code, 'GESAMT') as basel_kategorie,
                EXTRACT(YEAR FROM re.meldedatum) as jahr,
                COUNT(*) as anzahl,
                re.verlust_betrag_eur
            FROM risiko_ereignisse re
            LEFT JOIN geschaeftsbereiche gb ON re.geschaeftsbereich_id = gb.bereich_id
            LEFT JOIN basel_risikokategorien bc ON re.basel_kategorie_id = bc.kategorie_id
            WHERE re.meldedatum >= CURRENT_DATE - INTERVAL ':years years'
              AND re.verlust_betrag_eur > 0
              AND re.ist_near_miss = FALSE
            GROUP BY
                COALESCE(gb.bereich_code, 'GESAMT'),
                COALESCE(bc.kategorie_code, 'GESAMT'),
                EXTRACT(YEAR FROM re.meldedatum),
                re.verlust_betrag_eur
            ORDER BY geschaeftsbereich, basel_kategorie
        """

        results = []

        with get_db_context() as db:
            rows = db.execute(text(query), {"years": years_history}).fetchall()

            # Daten gruppieren
            grouped_data = {}
            for row in rows:
                key = (row.geschaeftsbereich, row.basel_kategorie)
                if key not in grouped_data:
                    grouped_data[key] = {"losses": [], "annual_counts": {}}

                grouped_data[key]["losses"].append(float(row.verlust_betrag_eur))

                if row.jahr not in grouped_data[key]["annual_counts"]:
                    grouped_data[key]["annual_counts"][row.jahr] = 0
                grouped_data[key]["annual_counts"][row.jahr] += row.anzahl

            # Für jede Gruppe LDA berechnen
            for (bereich, kategorie), data in grouped_data.items():
                losses = np.array(data["losses"])
                annual_counts = list(data["annual_counts"].values())

                if len(losses) < 10:
                    continue

                result = self._calculate_single_lda(
                    bereich, kategorie, losses, annual_counts, n_simulations
                )
                results.append(result)

        return results

    def _calculate_single_lda(
        self,
        bereich: str,
        kategorie: str,
        losses: np.ndarray,
        annual_counts: list,
        n_simulations: int
    ) -> LDAResult:
        """Berechnet LDA für eine einzelne Gruppe"""

        # Frequenz-Parameter (Poisson)
        freq_lambda = np.mean(annual_counts)

        # Severity-Parameter (Lognormal)
        log_losses = np.log(losses)
        mu = np.mean(log_losses)
        sigma = np.std(log_losses)

        # Monte-Carlo-Simulation
        simulated_annual_losses = []

        for _ in range(n_simulations):
            n_events = np.random.poisson(freq_lambda)
            if n_events > 0:
                simulated_losses = np.random.lognormal(mu, sigma, n_events)
                annual_loss = np.sum(simulated_losses)
            else:
                annual_loss = 0
            simulated_annual_losses.append(annual_loss)

        simulated = np.array(simulated_annual_losses)

        # Metriken berechnen
        expected_loss = np.mean(simulated)
        var_999 = np.percentile(simulated, 99.9)
        unexpected_loss = var_999 - expected_loss

        return LDAResult(
            geschaeftsbereich=bereich,
            basel_kategorie=kategorie,
            frequency_mean=freq_lambda,
            frequency_distribution="Poisson",
            severity_mean=np.mean(losses),
            severity_std=np.std(losses),
            severity_distribution="Lognormal",
            severity_params={"mu": mu, "sigma": sigma},
            expected_loss=Decimal(str(round(expected_loss, 2))),
            unexpected_loss=Decimal(str(round(unexpected_loss, 2))),
            var_999=Decimal(str(round(var_999, 2))),
            capital_charge=Decimal(str(round(unexpected_loss, 2)))  # Vereinfacht
        )

    def calculate_scenario_capital(self) -> list[ScenarioCapital]:
        """
        Berechnet szenario-basierte Kapitalanforderung

        Returns:
            Liste von ScenarioCapital
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        query = """
            SELECT
                sa.scenario_id,
                sa.scenario_name,
                sa.risiko_kategorie,
                sa.wahrscheinlichkeit,
                sa.auswirkung,
                sa.erwarteter_verlust,
                sa.value_at_risk,
                sa.residual_risiko_nach_controls,
                COALESCE(sa.versicherungsschutz, 0) as versicherungsschutz,
                sa.expertenvalidierung
            FROM scenario_analysis sa
            WHERE sa.status = 'AKTIV'
              AND (sa.gueltig_bis IS NULL OR sa.gueltig_bis >= CURRENT_DATE)
        """

        results = []

        with get_db_context() as db:
            rows = db.execute(text(query)).fetchall()

            for row in rows:
                residual = Decimal(str(row.residual_risiko_nach_controls or 0))
                versicherung = Decimal(str(row.versicherungsschutz or 0))

                # Max 20% Versicherung anrechenbar
                anerkannte_versicherung = min(
                    versicherung,
                    residual * Decimal(str(self.MAX_INSURANCE_RECOGNITION))
                )

                netto = residual - anerkannte_versicherung

                # Validierungsfaktor (20% Aufschlag wenn nicht validiert)
                val_factor = Decimal("1.0") if row.expertenvalidierung else Decimal("1.2")

                capital = max(netto, Decimal(0)) * val_factor

                results.append(ScenarioCapital(
                    scenario_id=row.scenario_id,
                    scenario_name=row.scenario_name,
                    risiko_kategorie=row.risiko_kategorie or "",
                    wahrscheinlichkeit=float(row.wahrscheinlichkeit or 0),
                    auswirkung=Decimal(str(row.auswirkung or 0)),
                    erwarteter_verlust=Decimal(str(row.erwarteter_verlust or 0)),
                    var_999=Decimal(str(row.value_at_risk or 0)),
                    residual_nach_controls=residual,
                    versicherung=anerkannte_versicherung,
                    capital_charge=capital,
                    validiert=row.expertenvalidierung or False
                ))

        return results

    def calculate_insurance_mitigation(
        self,
        year: int = None
    ) -> list[InsuranceMitigation]:
        """
        Berechnet Versicherungs-Anrechnung nach AMA

        Args:
            year: Jahr für die Berechnung

        Returns:
            Liste von InsuranceMitigation pro Risikokategorie
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        year = year or date.today().year

        query = """
            SELECT
                COALESCE(bc.kategorie_name_de, 'Nicht kategorisiert') as risiko_kategorie,
                SUM(re.verlust_betrag_eur) as brutto_verlust,
                SUM(COALESCE(re.versicherungs_erstattung, 0)) as versicherungs_erstattung
            FROM risiko_ereignisse re
            LEFT JOIN basel_risikokategorien bc ON re.basel_kategorie_id = bc.kategorie_id
            WHERE EXTRACT(YEAR FROM re.meldedatum) = :year
              AND re.verlust_betrag_eur > 0
            GROUP BY bc.kategorie_name_de
            ORDER BY brutto_verlust DESC
        """

        results = []

        with get_db_context() as db:
            rows = db.execute(text(query), {"year": year}).fetchall()

            for row in rows:
                brutto = Decimal(str(row.brutto_verlust or 0))
                versicherung = Decimal(str(row.versicherungs_erstattung or 0))

                # Max 20% anerkannt
                anerkannt = min(
                    versicherung,
                    brutto * Decimal(str(self.MAX_INSURANCE_RECOGNITION))
                )

                netto = brutto - anerkannt

                erstattungsquote = float(versicherung / brutto * 100) if brutto > 0 else 0

                results.append(InsuranceMitigation(
                    risiko_kategorie=row.risiko_kategorie,
                    brutto_verlust=brutto,
                    versicherungs_erstattung=versicherung,
                    anerkannte_versicherung=anerkannt,
                    netto_verlust=netto,
                    erstattungsquote=erstattungsquote
                ))

        return results

    def get_total_capital_requirement(self) -> dict:
        """
        Berechnet die gesamte Kapitalanforderung

        Returns:
            Dict mit Gesamt-Kapitalanforderung
        """
        # LDA-Kapital
        lda_results = self.calculate_lda_capital()
        lda_total = sum(r.capital_charge for r in lda_results)

        # Szenario-Kapital
        scenario_results = self.calculate_scenario_capital()
        scenario_total = sum(s.capital_charge for s in scenario_results)

        # Versicherungs-Anrechnung
        insurance_results = self.calculate_insurance_mitigation()
        insurance_total = sum(i.anerkannte_versicherung for i in insurance_results)

        # Hybrid-Ansatz: Maximum aus LDA und Szenario + Aufschlag
        hybrid_capital = max(lda_total, scenario_total)

        # Diversifikationsabschlag (vereinfacht 10%)
        diversification_benefit = hybrid_capital * Decimal("0.10")

        net_capital = hybrid_capital - diversification_benefit

        return {
            "stichtag": date.today().isoformat(),
            "lda_capital": float(lda_total),
            "scenario_capital": float(scenario_total),
            "insurance_mitigation": float(insurance_total),
            "hybrid_capital": float(hybrid_capital),
            "diversification_benefit": float(diversification_benefit),
            "net_capital_requirement": float(net_capital),
            "lda_details": [
                {
                    "bereich": r.geschaeftsbereich,
                    "kategorie": r.basel_kategorie,
                    "expected_loss": float(r.expected_loss),
                    "var_999": float(r.var_999),
                    "capital": float(r.capital_charge)
                }
                for r in lda_results
            ],
            "scenario_details": [
                {
                    "name": s.scenario_name,
                    "kategorie": s.risiko_kategorie,
                    "capital": float(s.capital_charge),
                    "validiert": s.validiert
                }
                for s in scenario_results
            ]
        }

    def stress_test_capital(
        self,
        stress_factor: float = 1.5,
        frequency_increase: float = 1.3
    ) -> dict:
        """
        Führt Stress-Test für Kapitalanforderung durch

        Args:
            stress_factor: Multiplikator für Severity
            frequency_increase: Multiplikator für Frequenz

        Returns:
            Dict mit Stress-Test-Ergebnissen
        """
        base_capital = self.get_total_capital_requirement()

        # Stress-Szenario simulieren
        stressed_lda = Decimal(str(base_capital["lda_capital"])) * Decimal(str(stress_factor * frequency_increase))
        stressed_scenario = Decimal(str(base_capital["scenario_capital"])) * Decimal(str(stress_factor))

        stressed_total = max(stressed_lda, stressed_scenario)

        increase_pct = (
            (float(stressed_total) - base_capital["net_capital_requirement"]) /
            base_capital["net_capital_requirement"] * 100
            if base_capital["net_capital_requirement"] > 0 else 0
        )

        return {
            "stress_factor_severity": stress_factor,
            "stress_factor_frequency": frequency_increase,
            "base_capital": base_capital["net_capital_requirement"],
            "stressed_capital": float(stressed_total),
            "increase_amount": float(stressed_total) - base_capital["net_capital_requirement"],
            "increase_percent": increase_pct,
            "capital_buffer_required": float(stressed_total) - base_capital["net_capital_requirement"]
        }
