"""
CSR Breaktime Dashboard Package
"""

from .aggregations import (
    get_realtime_dashboard_metrics,
    get_active_breaks_list,
    get_overdue_breaks_list,
    get_break_distribution_today,
    get_agent_performance_today,
    get_hourly_distribution_today,
    get_compliance_trend,
    get_full_dashboard_data,
    generate_daily_report,
    generate_weekly_report,
)

__all__ = [
    'get_realtime_dashboard_metrics',
    'get_active_breaks_list',
    'get_overdue_breaks_list',
    'get_break_distribution_today',
    'get_agent_performance_today',
    'get_hourly_distribution_today',
    'get_compliance_trend',
    'get_full_dashboard_data',
    'generate_daily_report',
    'generate_weekly_report',
]
