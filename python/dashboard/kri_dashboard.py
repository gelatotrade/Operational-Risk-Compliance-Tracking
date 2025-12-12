"""
KRI Dashboard - Key Risk Indicator Dashboard Komponente
"""
from python.analytics.kri_analysis import KRIAnalyzer


class KRIDashboard:
    """KRI-spezifisches Dashboard"""

    def __init__(self):
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
