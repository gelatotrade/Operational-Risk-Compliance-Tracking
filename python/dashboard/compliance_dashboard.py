"""
Compliance Dashboard - Compliance Monitoring Dashboard Komponente
"""
from python.analytics.compliance_monitor import ComplianceMonitor


class ComplianceDashboard:
    """Compliance-spezifisches Dashboard"""

    def __init__(self):
        self.monitor = ComplianceMonitor()

    def get_dashboard_data(self) -> dict:
        """Generiert Compliance Dashboard Daten"""
        return self.monitor.generate_compliance_report()
