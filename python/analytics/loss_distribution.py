"""
Loss Distribution Analysis - Verlustverteilungsanalyse
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

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class LossDistributionResult:
    """Ergebnis der Verlustverteilungsanalyse"""
    # Grundstatistiken
    count: int = 0
    total_loss: Decimal = Decimal(0)
    mean_loss: Decimal = Decimal(0)
    median_loss: Decimal = Decimal(0)
    std_dev: Decimal = Decimal(0)
    min_loss: Decimal = Decimal(0)
    max_loss: Decimal = Decimal(0)

    # Perzentile
    p75: Decimal = Decimal(0)
    p90: Decimal = Decimal(0)
    p95: Decimal = Decimal(0)
    p99: Decimal = Decimal(0)
    p999: Decimal = Decimal(0)  # 99.9% für VaR

    # Verteilungsparameter
    skewness: float = 0.0
    kurtosis: float = 0.0
    distribution_type: str = ""
    distribution_params: dict = field(default_factory=dict)

    # VaR und Expected Shortfall
    var_95: Decimal = Decimal(0)
    var_99: Decimal = Decimal(0)
    var_999: Decimal = Decimal(0)
    expected_shortfall_95: Decimal = Decimal(0)
    expected_shortfall_99: Decimal = Decimal(0)


@dataclass
class FrequencySeverityResult:
    """Ergebnis der Frequenz/Schwere-Analyse"""
    period: str
    frequency: int
    avg_severity: Decimal
    total_severity: Decimal
    frequency_trend: str  # STEIGEND, FALLEND, STABIL
    severity_trend: str


class LossDistributionAnalyzer:
    """Analysiert die Verteilung operationeller Verluste"""

    def __init__(self, db_session=None):
        self.db = db_session

    def analyze_distribution(
        self,
        losses: list[Decimal] | np.ndarray,
        confidence_level: float = 0.999
    ) -> LossDistributionResult:
        """
        Führt eine vollständige Verlustverteilungsanalyse durch

        Args:
            losses: Liste der Verlustbeträge
            confidence_level: Konfidenzniveau für VaR

        Returns:
            LossDistributionResult
        """
        if not losses or len(losses) == 0:
            return LossDistributionResult()

        # In numpy array konvertieren
        if not isinstance(losses, np.ndarray):
            losses_arr = np.array([float(l) for l in losses if l and l > 0])
        else:
            losses_arr = losses[losses > 0]

        if len(losses_arr) == 0:
            return LossDistributionResult()

        result = LossDistributionResult()

        # Grundstatistiken
        result.count = len(losses_arr)
        result.total_loss = Decimal(str(np.sum(losses_arr)))
        result.mean_loss = Decimal(str(np.mean(losses_arr)))
        result.median_loss = Decimal(str(np.median(losses_arr)))
        result.std_dev = Decimal(str(np.std(losses_arr)))
        result.min_loss = Decimal(str(np.min(losses_arr)))
        result.max_loss = Decimal(str(np.max(losses_arr)))

        # Perzentile
        result.p75 = Decimal(str(np.percentile(losses_arr, 75)))
        result.p90 = Decimal(str(np.percentile(losses_arr, 90)))
        result.p95 = Decimal(str(np.percentile(losses_arr, 95)))
        result.p99 = Decimal(str(np.percentile(losses_arr, 99)))
        result.p999 = Decimal(str(np.percentile(losses_arr, 99.9)))

        # Schiefe und Kurtosis
        if len(losses_arr) > 2:
            result.skewness = float(stats.skew(losses_arr))
            result.kurtosis = float(stats.kurtosis(losses_arr))

        # Verteilung fitten
        result.distribution_type, result.distribution_params = self._fit_distribution(losses_arr)

        # VaR berechnen
        result.var_95 = Decimal(str(np.percentile(losses_arr, 95)))
        result.var_99 = Decimal(str(np.percentile(losses_arr, 99)))
        result.var_999 = Decimal(str(np.percentile(losses_arr, 99.9)))

        # Expected Shortfall (CVaR)
        result.expected_shortfall_95 = Decimal(str(
            np.mean(losses_arr[losses_arr >= np.percentile(losses_arr, 95)])
        ))
        result.expected_shortfall_99 = Decimal(str(
            np.mean(losses_arr[losses_arr >= np.percentile(losses_arr, 99)])
        ))

        return result

    def _fit_distribution(self, data: np.ndarray) -> tuple[str, dict]:
        """
        Findet die beste passende Verteilung für die Daten

        Args:
            data: Verlustdaten

        Returns:
            Tuple aus (Verteilungsname, Parameter)
        """
        if len(data) < 10:
            return "unknown", {}

        distributions = {
            "lognorm": stats.lognorm,
            "gamma": stats.gamma,
            "weibull_min": stats.weibull_min,
            "expon": stats.expon,
            "pareto": stats.pareto
        }

        best_fit = None
        best_ks = float('inf')
        best_params = {}

        for name, dist in distributions.items():
            try:
                params = dist.fit(data)
                ks_stat, _ = stats.kstest(data, name, args=params)

                if ks_stat < best_ks:
                    best_ks = ks_stat
                    best_fit = name
                    best_params = {
                        "params": params,
                        "ks_statistic": ks_stat
                    }
            except Exception:
                continue

        return best_fit or "unknown", best_params

    def get_frequency_severity(
        self,
        start_date: date = None,
        end_date: date = None,
        group_by: str = "month"
    ) -> list[FrequencySeverityResult]:
        """
        Berechnet Frequenz/Schwere-Verteilung über Zeit

        Args:
            start_date: Startdatum
            end_date: Enddatum
            group_by: Gruppierung (month, quarter, year)

        Returns:
            Liste von FrequencySeverityResult
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        if group_by == "month":
            date_trunc = "month"
            format_str = "YYYY-MM"
        elif group_by == "quarter":
            date_trunc = "quarter"
            format_str = "YYYY-Q"
        else:
            date_trunc = "year"
            format_str = "YYYY"

        query = f"""
            SELECT
                TO_CHAR(DATE_TRUNC('{date_trunc}', meldedatum), '{format_str}') as periode,
                COUNT(*) as anzahl,
                COALESCE(AVG(verlust_betrag_eur), 0) as avg_verlust,
                COALESCE(SUM(verlust_betrag_eur), 0) as sum_verlust
            FROM risiko_ereignisse
            WHERE verlust_betrag_eur > 0
              AND ist_near_miss = FALSE
              AND (:start_date IS NULL OR meldedatum >= :start_date)
              AND (:end_date IS NULL OR meldedatum <= :end_date)
            GROUP BY DATE_TRUNC('{date_trunc}', meldedatum)
            ORDER BY DATE_TRUNC('{date_trunc}', meldedatum)
        """

        results = []
        with get_db_context() as db:
            rows = db.execute(
                text(query),
                {"start_date": start_date, "end_date": end_date}
            ).fetchall()

            prev_freq = None
            prev_sev = None

            for row in rows:
                freq_trend = "STABIL"
                sev_trend = "STABIL"

                if prev_freq is not None:
                    if row.anzahl > prev_freq * 1.1:
                        freq_trend = "STEIGEND"
                    elif row.anzahl < prev_freq * 0.9:
                        freq_trend = "FALLEND"

                if prev_sev is not None:
                    if row.avg_verlust > prev_sev * 1.1:
                        sev_trend = "STEIGEND"
                    elif row.avg_verlust < prev_sev * 0.9:
                        sev_trend = "FALLEND"

                results.append(FrequencySeverityResult(
                    period=row.periode,
                    frequency=row.anzahl,
                    avg_severity=Decimal(str(row.avg_verlust)),
                    total_severity=Decimal(str(row.sum_verlust)),
                    frequency_trend=freq_trend,
                    severity_trend=sev_trend
                ))

                prev_freq = row.anzahl
                prev_sev = row.avg_verlust

        return results

    def get_top_losses(
        self,
        n: int = 10,
        years: int = 5
    ) -> list[dict]:
        """
        Gibt die Top-N Verlustereignisse zurück

        Args:
            n: Anzahl der Top-Ereignisse
            years: Betrachtungszeitraum in Jahren

        Returns:
            Liste der Top-Verlustereignisse
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        query = """
            SELECT
                re.ereignis_id,
                re.ereignis_referenz,
                re.meldedatum,
                re.ereignis_typ,
                re.geschaeftsbereich,
                bc.kategorie_name_de as basel_kategorie,
                re.verlust_betrag_eur,
                re.wiederherstellung_betrag,
                re.netto_verlust,
                re.root_cause,
                re.status,
                RANK() OVER (ORDER BY re.verlust_betrag_eur DESC) as rang
            FROM risiko_ereignisse re
            LEFT JOIN basel_risikokategorien bc ON re.basel_kategorie_id = bc.kategorie_id
            WHERE re.meldedatum >= CURRENT_DATE - INTERVAL ':years years'
              AND re.verlust_betrag_eur > 0
              AND re.ist_near_miss = FALSE
            ORDER BY re.verlust_betrag_eur DESC
            LIMIT :n
        """

        with get_db_context() as db:
            rows = db.execute(text(query), {"n": n, "years": years}).fetchall()
            return [dict(row._mapping) for row in rows]

    def get_internal_vs_external(
        self,
        start_date: date = None,
        end_date: date = None
    ) -> dict:
        """
        Vergleicht interne vs. externe Betrugsfälle

        Returns:
            Dict mit Vergleichsdaten
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        query = """
            SELECT
                EXTRACT(YEAR FROM meldedatum) as jahr,
                CASE
                    WHEN bc.kategorie_code = 'IF' THEN 'Interner Betrug'
                    WHEN bc.kategorie_code = 'EF' THEN 'Externer Betrug'
                    ELSE 'Andere'
                END as betrugs_typ,
                COUNT(*) as anzahl_faelle,
                COALESCE(SUM(verlust_betrag_eur), 0) as gesamt_verlust,
                COALESCE(AVG(verlust_betrag_eur), 0) as durchschnitt_verlust,
                COALESCE(SUM(wiederherstellung_betrag), 0) as wiederherstellung,
                COALESCE(SUM(versicherungs_erstattung), 0) as versicherung
            FROM risiko_ereignisse re
            LEFT JOIN basel_risikokategorien bc ON re.basel_kategorie_id = bc.kategorie_id
            WHERE bc.kategorie_code IN ('IF', 'EF')
              AND (:start_date IS NULL OR meldedatum >= :start_date)
              AND (:end_date IS NULL OR meldedatum <= :end_date)
            GROUP BY
                EXTRACT(YEAR FROM meldedatum),
                CASE
                    WHEN bc.kategorie_code = 'IF' THEN 'Interner Betrug'
                    WHEN bc.kategorie_code = 'EF' THEN 'Externer Betrug'
                    ELSE 'Andere'
                END
            ORDER BY jahr, betrugs_typ
        """

        with get_db_context() as db:
            rows = db.execute(
                text(query),
                {"start_date": start_date, "end_date": end_date}
            ).fetchall()

            return {
                "data": [dict(row._mapping) for row in rows],
                "summary": self._calculate_fraud_summary(rows)
            }

    def _calculate_fraud_summary(self, rows) -> dict:
        """Berechnet Zusammenfassung für Betrugsvergleich"""
        internal = {"count": 0, "total": Decimal(0)}
        external = {"count": 0, "total": Decimal(0)}

        for row in rows:
            if row.betrugs_typ == "Interner Betrug":
                internal["count"] += row.anzahl_faelle
                internal["total"] += Decimal(str(row.gesamt_verlust))
            else:
                external["count"] += row.anzahl_faelle
                external["total"] += Decimal(str(row.gesamt_verlust))

        return {
            "internal_fraud": internal,
            "external_fraud": external,
            "internal_share_count": (
                internal["count"] / (internal["count"] + external["count"]) * 100
                if internal["count"] + external["count"] > 0 else 0
            ),
            "internal_share_amount": (
                float(internal["total"]) / float(internal["total"] + external["total"]) * 100
                if internal["total"] + external["total"] > 0 else 0
            )
        }

    def get_loss_by_business_line(
        self,
        year: int = None
    ) -> list[dict]:
        """
        Verlustverteilung nach Geschäftsbereichen (BASEL)

        Args:
            year: Jahr für die Analyse

        Returns:
            Liste mit Verlusten pro Geschäftsbereich
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        year = year or date.today().year

        query = """
            SELECT
                COALESCE(re.geschaeftsbereich, 'Nicht zugeordnet') as geschaeftsbereich,
                bc.kategorie_code as basel_code,
                bc.kategorie_name_de as basel_kategorie,
                COUNT(*) as anzahl,
                SUM(re.verlust_betrag_eur) as brutto_verlust,
                SUM(re.wiederherstellung_betrag) as wiederherstellung,
                SUM(re.versicherungs_erstattung) as versicherung,
                SUM(re.netto_verlust) as netto_verlust,
                AVG(re.verlust_betrag_eur) as avg_verlust,
                MAX(re.verlust_betrag_eur) as max_verlust
            FROM risiko_ereignisse re
            LEFT JOIN basel_risikokategorien bc ON re.basel_kategorie_id = bc.kategorie_id
            WHERE EXTRACT(YEAR FROM re.meldedatum) = :year
              AND re.verlust_betrag_eur > 0
              AND re.ist_near_miss = FALSE
            GROUP BY
                re.geschaeftsbereich,
                bc.kategorie_code,
                bc.kategorie_name_de
            ORDER BY brutto_verlust DESC
        """

        with get_db_context() as db:
            rows = db.execute(text(query), {"year": year}).fetchall()
            return [dict(row._mapping) for row in rows]

    def simulate_monte_carlo(
        self,
        n_simulations: int = 10000,
        years_history: int = 5
    ) -> dict:
        """
        Monte-Carlo-Simulation für Verlustprognose

        Args:
            n_simulations: Anzahl der Simulationen
            years_history: Jahre für historische Daten

        Returns:
            Dict mit Simulationsergebnissen
        """
        from sqlalchemy import text
        from python.models.base import get_db_context

        # Historische Daten laden
        query = """
            SELECT verlust_betrag_eur
            FROM risiko_ereignisse
            WHERE meldedatum >= CURRENT_DATE - INTERVAL ':years years'
              AND verlust_betrag_eur > 0
              AND ist_near_miss = FALSE
        """

        with get_db_context() as db:
            rows = db.execute(text(query), {"years": years_history}).fetchall()
            losses = np.array([float(row.verlust_betrag_eur) for row in rows])

        if len(losses) < 10:
            return {"error": "Nicht genug historische Daten für Simulation"}

        # Frequenz- und Severity-Verteilung fitten
        annual_count = len(losses) / years_history

        # Poisson für Frequenz
        freq_lambda = annual_count

        # Lognormal für Severity
        log_losses = np.log(losses)
        mu = np.mean(log_losses)
        sigma = np.std(log_losses)

        # Simulation
        simulated_annual_losses = []

        for _ in range(n_simulations):
            # Anzahl Ereignisse simulieren
            n_events = np.random.poisson(freq_lambda)

            if n_events > 0:
                # Verluste simulieren
                simulated_losses = np.random.lognormal(mu, sigma, n_events)
                annual_loss = np.sum(simulated_losses)
            else:
                annual_loss = 0

            simulated_annual_losses.append(annual_loss)

        simulated = np.array(simulated_annual_losses)

        return {
            "n_simulations": n_simulations,
            "mean_annual_loss": float(np.mean(simulated)),
            "median_annual_loss": float(np.median(simulated)),
            "std_dev": float(np.std(simulated)),
            "var_95": float(np.percentile(simulated, 95)),
            "var_99": float(np.percentile(simulated, 99)),
            "var_999": float(np.percentile(simulated, 99.9)),
            "max_simulated": float(np.max(simulated)),
            "percentiles": {
                "p50": float(np.percentile(simulated, 50)),
                "p75": float(np.percentile(simulated, 75)),
                "p90": float(np.percentile(simulated, 90)),
                "p95": float(np.percentile(simulated, 95)),
                "p99": float(np.percentile(simulated, 99)),
                "p999": float(np.percentile(simulated, 99.9))
            }
        }
