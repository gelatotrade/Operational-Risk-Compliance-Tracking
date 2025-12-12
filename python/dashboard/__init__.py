"""
Dashboard-Komponenten für Operational Risk & Compliance Tracking System
"""

from .risk_heatmap import RiskHeatmapGenerator
from .kri_dashboard import KRIDashboard
from .compliance_dashboard import ComplianceDashboard
from .executive_dashboard import ExecutiveDashboard
from .report_generator import ReportGenerator

__all__ = [
    "RiskHeatmapGenerator",
    "KRIDashboard",
    "ComplianceDashboard",
    "ExecutiveDashboard",
    "ReportGenerator"
]
