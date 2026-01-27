"""
CSR Breaktime Database Package
"""

from .db import (
    init_database,
    get_connection,
    get_or_create_user,
    get_break_type_by_code,
    get_all_break_types,
    log_break_out,
    log_break_back,
    start_session,
    end_session,
    get_active_session,
    get_all_active_sessions,
    get_overdue_sessions,
    get_realtime_metrics,
    get_compliance_today,
    calculate_daily_summary,
)

__all__ = [
    'init_database',
    'get_connection',
    'get_or_create_user',
    'get_break_type_by_code',
    'get_all_break_types',
    'log_break_out',
    'log_break_back',
    'start_session',
    'end_session',
    'get_active_session',
    'get_all_active_sessions',
    'get_overdue_sessions',
    'get_realtime_metrics',
    'get_compliance_today',
    'calculate_daily_summary',
]
