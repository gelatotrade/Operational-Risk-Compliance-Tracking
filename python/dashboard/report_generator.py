"""
Report Generator - Generiert verschiedene Berichte
"""
from datetime import datetime


class ReportGenerator:
    """Generiert verschiedene Reports"""

    def __init__(self):
        from python.dashboard.executive_dashboard import ExecutiveDashboard
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
