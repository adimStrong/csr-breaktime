"""
CSR Breaktime Dashboard - Data Aggregation Layer
Provides aggregated metrics, trend analysis, and report generation for the dashboard.
"""

import os
import sys
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import get_connection, get_all_break_types


# ============================================
# DATA CLASSES FOR STRUCTURED RESPONSES
# ============================================

@dataclass
class RealtimeMetrics:
    """Real-time dashboard header metrics."""
    active_breaks: int = 0
    overdue_breaks: int = 0
    agents_active_today: int = 0
    completed_breaks_today: int = 0
    total_break_time_today: float = 0.0
    compliance_rate: float = 100.0
    timestamp: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class BreakDistribution:
    """Break distribution by type."""
    break_type: str
    code: str
    count: int
    total_duration: float
    avg_duration: float
    percentage: float


@dataclass
class AgentPerformance:
    """Individual agent performance metrics."""
    user_id: int
    telegram_id: int
    full_name: str
    total_breaks: int
    total_duration: float
    avg_duration: float
    within_limit: int
    over_limit: int
    compliance_rate: float
    status: str  # 'on_break', 'available', 'offline'
    current_break_type: Optional[str] = None
    current_break_duration: Optional[float] = None


@dataclass
class ActiveBreak:
    """Active break session details."""
    session_id: int
    user_id: int
    telegram_id: int
    username: str
    full_name: str
    break_type: str
    time_limit: Optional[int]
    start_time: str
    duration_minutes: float
    is_overdue: bool
    over_limit_minutes: float
    reason: Optional[str]


@dataclass
class HourlyData:
    """Hourly break distribution."""
    hour: int
    hour_label: str  # "9 AM", "12 PM", etc.
    break_outs: int
    break_backs: int
    net_active: int


@dataclass
class ComplianceTrend:
    """Daily compliance trend data point."""
    date: str
    compliance_rate: float
    total_breaks: int
    within_limit: int
    over_limit: int
    agents_count: int


# ============================================
# REAL-TIME METRICS
# ============================================

def get_realtime_dashboard_metrics() -> RealtimeMetrics:
    """Get all real-time metrics for dashboard header."""
    with get_connection() as conn:
        # Active breaks count
        cursor = conn.execute("SELECT COUNT(*) as count FROM active_sessions")
        active_breaks = cursor.fetchone()['count']

        # Overdue breaks count
        cursor = conn.execute("""
            SELECT COUNT(*) as count
            FROM active_sessions s
            JOIN break_types bt ON s.break_type_id = bt.id
            WHERE bt.time_limit_minutes IS NOT NULL
              AND (julianday(datetime('now', '+8 hours')) - julianday(s.start_time)) * 24 * 60 > bt.time_limit_minutes
        """)
        overdue_breaks = cursor.fetchone()['count']

        # Agents active today
        cursor = conn.execute("""
            SELECT COUNT(DISTINCT user_id) as count
            FROM break_logs
            WHERE log_date = DATE('now')
        """)
        agents_active = cursor.fetchone()['count']

        # Completed breaks today
        cursor = conn.execute("""
            SELECT COUNT(*) as count
            FROM break_logs
            WHERE log_date = DATE('now') AND action = 'BACK'
        """)
        completed = cursor.fetchone()['count']

        # Total break time today (excluding WC)
        cursor = conn.execute("""
            SELECT COALESCE(SUM(bl.duration_minutes), 0) as total
            FROM break_logs bl
            JOIN break_types bt ON bl.break_type_id = bt.id
            WHERE bl.log_date = DATE('now')
              AND bl.action = 'BACK'
              AND bt.is_counted_in_total = 1
        """)
        total_time = cursor.fetchone()['total']

        # Compliance rate today
        cursor = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE
                    WHEN bl.duration_minutes <= bt.time_limit_minutes THEN 1
                    WHEN bt.time_limit_minutes IS NULL THEN 1
                    ELSE 0
                END) as within_limit
            FROM break_logs bl
            JOIN break_types bt ON bl.break_type_id = bt.id
            WHERE bl.log_date = DATE('now') AND bl.action = 'BACK'
        """)
        compliance_row = cursor.fetchone()
        total = compliance_row['total'] or 0
        within = compliance_row['within_limit'] or 0
        compliance_rate = round(100 * within / total, 1) if total > 0 else 100.0

        return RealtimeMetrics(
            active_breaks=active_breaks,
            overdue_breaks=overdue_breaks,
            agents_active_today=agents_active,
            completed_breaks_today=completed,
            total_break_time_today=round(total_time, 1),
            compliance_rate=compliance_rate,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )


# ============================================
# ACTIVE BREAKS
# ============================================

def get_active_breaks_list() -> List[ActiveBreak]:
    """Get all currently active breaks with full details."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT
                s.id as session_id,
                u.id as user_id,
                u.telegram_id,
                u.username,
                u.full_name,
                bt.display_name as break_type,
                bt.time_limit_minutes as time_limit,
                s.start_time,
                s.reason,
                ROUND((julianday(datetime('now', '+8 hours')) - julianday(s.start_time)) * 24 * 60, 1) as duration_minutes
            FROM active_sessions s
            JOIN users u ON s.user_id = u.id
            JOIN break_types bt ON s.break_type_id = bt.id
            ORDER BY s.start_time
        """)

        breaks = []
        for row in cursor.fetchall():
            duration = row['duration_minutes']
            time_limit = row['time_limit']
            is_overdue = time_limit is not None and duration > time_limit
            over_limit = round(duration - time_limit, 1) if is_overdue else 0

            # Convert start_time to string if it's a datetime object
            start_time = row['start_time']
            if hasattr(start_time, 'isoformat'):
                start_time = start_time.isoformat()

            breaks.append(ActiveBreak(
                session_id=row['session_id'],
                user_id=row['user_id'],
                telegram_id=row['telegram_id'],
                username=row['username'] or 'N/A',
                full_name=row['full_name'],
                break_type=row['break_type'],
                time_limit=time_limit,
                start_time=start_time,
                duration_minutes=duration,
                is_overdue=is_overdue,
                over_limit_minutes=over_limit,
                reason=row['reason']
            ))

        return breaks


def get_overdue_breaks_list() -> List[ActiveBreak]:
    """Get only overdue breaks, sorted by severity."""
    all_breaks = get_active_breaks_list()
    overdue = [b for b in all_breaks if b.is_overdue]
    return sorted(overdue, key=lambda x: x.over_limit_minutes, reverse=True)


# ============================================
# BREAK DISTRIBUTION
# ============================================

def get_break_distribution_today() -> List[BreakDistribution]:
    """Get break distribution by type for today."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT
                bt.display_name as break_type,
                bt.code,
                COUNT(CASE WHEN bl.action = 'BACK' THEN 1 END) as count,
                COALESCE(SUM(CASE WHEN bl.action = 'BACK' THEN bl.duration_minutes END), 0) as total_duration,
                COALESCE(AVG(CASE WHEN bl.action = 'BACK' THEN bl.duration_minutes END), 0) as avg_duration
            FROM break_types bt
            LEFT JOIN break_logs bl ON bt.id = bl.break_type_id AND bl.log_date = DATE('now')
            GROUP BY bt.id
            ORDER BY bt.id
        """)

        results = []
        total_count = 0
        rows = cursor.fetchall()

        # First pass: calculate total
        for row in rows:
            total_count += row['count'] or 0

        # Second pass: build distribution
        for row in rows:
            count = row['count'] or 0
            results.append(BreakDistribution(
                break_type=row['break_type'],
                code=row['code'],
                count=count,
                total_duration=round(row['total_duration'] or 0, 1),
                avg_duration=round(row['avg_duration'] or 0, 1),
                percentage=round(100 * count / total_count, 1) if total_count > 0 else 0
            ))

        return results


def get_break_distribution_for_period(start_date: date, end_date: date) -> List[BreakDistribution]:
    """Get break distribution for a date range."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT
                bt.display_name as break_type,
                bt.code,
                COUNT(CASE WHEN bl.action = 'BACK' THEN 1 END) as count,
                COALESCE(SUM(CASE WHEN bl.action = 'BACK' THEN bl.duration_minutes END), 0) as total_duration,
                COALESCE(AVG(CASE WHEN bl.action = 'BACK' THEN bl.duration_minutes END), 0) as avg_duration
            FROM break_types bt
            LEFT JOIN break_logs bl ON bt.id = bl.break_type_id
                AND bl.log_date BETWEEN ? AND ?
            GROUP BY bt.id
            ORDER BY bt.id
        """, (start_date, end_date))

        results = []
        total_count = 0
        rows = list(cursor.fetchall())

        for row in rows:
            total_count += row['count'] or 0

        for row in rows:
            count = row['count'] or 0
            results.append(BreakDistribution(
                break_type=row['break_type'],
                code=row['code'],
                count=count,
                total_duration=round(row['total_duration'] or 0, 1),
                avg_duration=round(row['avg_duration'] or 0, 1),
                percentage=round(100 * count / total_count, 1) if total_count > 0 else 0
            ))

        return results


# ============================================
# AGENT PERFORMANCE
# ============================================

def get_agent_performance_today() -> List[AgentPerformance]:
    """Get performance metrics for all agents today."""
    with get_connection() as conn:
        # Get all agents who were active today or have active sessions
        cursor = conn.execute("""
            SELECT
                u.id as user_id,
                u.telegram_id,
                u.full_name,
                COUNT(CASE WHEN bl.action = 'BACK' THEN 1 END) as total_breaks,
                COALESCE(SUM(CASE WHEN bl.action = 'BACK' AND bt.is_counted_in_total = 1
                    THEN bl.duration_minutes ELSE 0 END), 0) as total_duration,
                COALESCE(AVG(CASE WHEN bl.action = 'BACK' THEN bl.duration_minutes END), 0) as avg_duration,
                SUM(CASE
                    WHEN bl.action = 'BACK' AND bt.time_limit_minutes IS NOT NULL
                         AND bl.duration_minutes <= bt.time_limit_minutes THEN 1
                    WHEN bl.action = 'BACK' AND bt.time_limit_minutes IS NULL THEN 1
                    ELSE 0
                END) as within_limit,
                SUM(CASE
                    WHEN bl.action = 'BACK' AND bt.time_limit_minutes IS NOT NULL
                         AND bl.duration_minutes > bt.time_limit_minutes THEN 1
                    ELSE 0
                END) as over_limit
            FROM users u
            LEFT JOIN break_logs bl ON u.id = bl.user_id AND bl.log_date = DATE('now')
            LEFT JOIN break_types bt ON bl.break_type_id = bt.id
            WHERE u.last_active_at >= DATE('now', '-1 day')
               OR u.id IN (SELECT user_id FROM active_sessions)
            GROUP BY u.id
            ORDER BY total_breaks DESC, u.full_name
        """)

        # Get active sessions for status
        active_cursor = conn.execute("""
            SELECT
                s.user_id,
                bt.display_name as break_type,
                ROUND((julianday(datetime('now', '+8 hours')) - julianday(s.start_time)) * 24 * 60, 1) as duration
            FROM active_sessions s
            JOIN break_types bt ON s.break_type_id = bt.id
        """)
        active_sessions = {row['user_id']: row for row in active_cursor.fetchall()}

        results = []
        for row in cursor.fetchall():
            user_id = row['user_id']
            within = row['within_limit'] or 0
            over = row['over_limit'] or 0
            total = within + over
            compliance = round(100 * within / total, 1) if total > 0 else 100.0

            # Determine status
            if user_id in active_sessions:
                status = 'on_break'
                current_break = active_sessions[user_id]
                current_type = current_break['break_type']
                current_duration = current_break['duration']
            else:
                status = 'available'
                current_type = None
                current_duration = None

            results.append(AgentPerformance(
                user_id=user_id,
                telegram_id=row['telegram_id'],
                full_name=row['full_name'],
                total_breaks=row['total_breaks'] or 0,
                total_duration=round(row['total_duration'] or 0, 1),
                avg_duration=round(row['avg_duration'] or 0, 1),
                within_limit=within,
                over_limit=over,
                compliance_rate=compliance,
                status=status,
                current_break_type=current_type,
                current_break_duration=current_duration
            ))

        return results


def get_agent_detail(user_id: int, days: int = 7) -> Dict:
    """Get detailed metrics for a specific agent."""
    with get_connection() as conn:
        # Basic info
        cursor = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = dict(cursor.fetchone())

        # Daily summaries for trend
        cursor = conn.execute("""
            SELECT * FROM daily_summaries
            WHERE user_id = ? AND summary_date >= DATE('now', ? || ' days')
            ORDER BY summary_date
        """, (user_id, f'-{days}'))
        daily_trend = [dict(row) for row in cursor.fetchall()]

        # Break logs for today
        cursor = conn.execute("""
            SELECT bl.*, bt.display_name as break_type_name
            FROM break_logs bl
            JOIN break_types bt ON bl.break_type_id = bt.id
            WHERE bl.user_id = ? AND bl.log_date = DATE('now')
            ORDER BY bl.timestamp
        """, (user_id,))
        today_logs = [dict(row) for row in cursor.fetchall()]

        # Current session if any
        cursor = conn.execute("""
            SELECT s.*, bt.display_name as break_type_name
            FROM active_sessions s
            JOIN break_types bt ON s.break_type_id = bt.id
            WHERE s.user_id = ?
        """, (user_id,))
        session_row = cursor.fetchone()
        active_session = dict(session_row) if session_row else None

        return {
            'user': user,
            'daily_trend': daily_trend,
            'today_logs': today_logs,
            'active_session': active_session
        }


# ============================================
# HOURLY ANALYSIS (PEAK TIMES)
# ============================================

def get_hourly_distribution_today() -> List[HourlyData]:
    """Get hourly break distribution for today."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT hour, break_outs, break_backs
            FROM hourly_metrics
            WHERE metric_date = DATE('now')
            ORDER BY hour
        """)

        # Initialize all hours
        hourly_data = {h: {'outs': 0, 'backs': 0} for h in range(24)}

        for row in cursor.fetchall():
            hour = row['hour']
            hourly_data[hour] = {
                'outs': row['break_outs'],
                'backs': row['break_backs']
            }

        results = []
        for hour in range(24):
            data = hourly_data[hour]
            # Format hour label
            if hour == 0:
                label = "12 AM"
            elif hour < 12:
                label = f"{hour} AM"
            elif hour == 12:
                label = "12 PM"
            else:
                label = f"{hour - 12} PM"

            results.append(HourlyData(
                hour=hour,
                hour_label=label,
                break_outs=data['outs'],
                break_backs=data['backs'],
                net_active=data['outs'] - data['backs']
            ))

        return results


def get_peak_hours(days: int = 7, top_n: int = 5) -> List[Dict]:
    """Get the busiest hours for breaks over a period."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT
                hour,
                SUM(break_outs) as total_outs,
                SUM(break_backs) as total_backs,
                AVG(break_outs) as avg_outs
            FROM hourly_metrics
            WHERE metric_date >= DATE('now', ? || ' days')
            GROUP BY hour
            ORDER BY total_outs DESC
            LIMIT ?
        """, (f'-{days}', top_n))

        results = []
        for row in cursor.fetchall():
            hour = row['hour']
            if hour == 0:
                label = "12 AM"
            elif hour < 12:
                label = f"{hour} AM"
            elif hour == 12:
                label = "12 PM"
            else:
                label = f"{hour - 12} PM"

            results.append({
                'hour': hour,
                'hour_label': label,
                'total_breaks': row['total_outs'],
                'avg_per_day': round(row['avg_outs'], 1)
            })

        return results


# ============================================
# COMPLIANCE TRENDS
# ============================================

def get_compliance_trend(days: int = 7) -> List[ComplianceTrend]:
    """Get compliance trend over the last N days."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT
                summary_date,
                SUM(breaks_within_limit) as within_limit,
                SUM(breaks_over_limit) as over_limit,
                COUNT(DISTINCT user_id) as agents_count
            FROM daily_summaries
            WHERE summary_date >= DATE('now', ? || ' days')
            GROUP BY summary_date
            ORDER BY summary_date
        """, (f'-{days}',))

        results = []
        for row in cursor.fetchall():
            within = row['within_limit'] or 0
            over = row['over_limit'] or 0
            total = within + over
            rate = round(100 * within / total, 1) if total > 0 else 100.0

            results.append(ComplianceTrend(
                date=str(row['summary_date']),
                compliance_rate=rate,
                total_breaks=total,
                within_limit=within,
                over_limit=over,
                agents_count=row['agents_count']
            ))

        return results


def get_compliance_summary(start_date: date, end_date: date) -> Dict:
    """Get compliance summary for a date range."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT
                SUM(breaks_within_limit) as within_limit,
                SUM(breaks_over_limit) as over_limit,
                SUM(total_breaks) as total_breaks,
                SUM(total_duration) as total_duration,
                COUNT(DISTINCT user_id) as unique_agents,
                AVG(compliance_rate) as avg_compliance,
                SUM(missing_clock_backs) as missing_backs
            FROM daily_summaries
            WHERE summary_date BETWEEN ? AND ?
        """, (start_date, end_date))

        row = cursor.fetchone()
        within = row['within_limit'] or 0
        over = row['over_limit'] or 0
        total = within + over

        return {
            'period': f"{start_date} to {end_date}",
            'total_breaks': row['total_breaks'] or 0,
            'within_limit': within,
            'over_limit': over,
            'compliance_rate': round(100 * within / total, 1) if total > 0 else 100.0,
            'avg_compliance': round(row['avg_compliance'] or 100, 1),
            'total_duration_minutes': round(row['total_duration'] or 0, 1),
            'unique_agents': row['unique_agents'] or 0,
            'missing_clock_backs': row['missing_backs'] or 0
        }


# ============================================
# REPORT GENERATION
# ============================================

def generate_daily_report(report_date: date = None) -> Dict:
    """Generate a complete daily report."""
    if report_date is None:
        report_date = date.today()

    with get_connection() as conn:
        # Team summary
        cursor = conn.execute("""
            SELECT
                COUNT(DISTINCT user_id) as total_agents,
                SUM(total_breaks) as total_breaks,
                SUM(total_duration) as total_duration,
                SUM(breaks_within_limit) as within_limit,
                SUM(breaks_over_limit) as over_limit,
                SUM(missing_clock_backs) as missing_backs
            FROM daily_summaries
            WHERE summary_date = ?
        """, (report_date,))
        team_row = cursor.fetchone()

        within = team_row['within_limit'] or 0
        over = team_row['over_limit'] or 0
        total = within + over
        compliance = round(100 * within / total, 1) if total > 0 else 100.0

        team_summary = {
            'date': str(report_date),
            'total_agents': team_row['total_agents'] or 0,
            'total_breaks': team_row['total_breaks'] or 0,
            'total_duration': round(team_row['total_duration'] or 0, 1),
            'compliance_rate': compliance,
            'within_limit': within,
            'over_limit': over,
            'missing_backs': team_row['missing_backs'] or 0
        }

        # By break type
        cursor = conn.execute("""
            SELECT
                bt.display_name,
                COUNT(*) as count,
                SUM(bl.duration_minutes) as total_duration,
                AVG(bl.duration_minutes) as avg_duration
            FROM break_logs bl
            JOIN break_types bt ON bl.break_type_id = bt.id
            WHERE bl.log_date = ? AND bl.action = 'BACK'
            GROUP BY bt.id
        """, (report_date,))
        by_type = [dict(row) for row in cursor.fetchall()]

        # Individual summaries
        cursor = conn.execute("""
            SELECT
                u.full_name,
                ds.*
            FROM daily_summaries ds
            JOIN users u ON ds.user_id = u.id
            WHERE ds.summary_date = ?
            ORDER BY ds.total_breaks DESC
        """, (report_date,))
        individual = [dict(row) for row in cursor.fetchall()]

        # Missing clock-backs detail
        cursor = conn.execute("""
            SELECT
                u.full_name,
                bt.display_name as break_type,
                COUNT(CASE WHEN bl.action = 'OUT' THEN 1 END) -
                COUNT(CASE WHEN bl.action = 'BACK' THEN 1 END) as missing
            FROM break_logs bl
            JOIN users u ON bl.user_id = u.id
            JOIN break_types bt ON bl.break_type_id = bt.id
            WHERE bl.log_date = ?
            GROUP BY bl.user_id, bl.break_type_id
            HAVING missing > 0
        """, (report_date,))
        missing_details = [dict(row) for row in cursor.fetchall()]

        return {
            'team_summary': team_summary,
            'by_type': by_type,
            'individual_summaries': individual,
            'missing_clock_backs': missing_details
        }


def generate_weekly_report(end_date: date = None) -> Dict:
    """Generate a weekly summary report."""
    if end_date is None:
        end_date = date.today()
    start_date = end_date - timedelta(days=6)

    compliance_trend = get_compliance_trend(7)
    distribution = get_break_distribution_for_period(start_date, end_date)
    peak_hours = get_peak_hours(7, 5)
    summary = get_compliance_summary(start_date, end_date)

    # Top compliant agents
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT
                u.full_name,
                AVG(ds.compliance_rate) as avg_compliance,
                SUM(ds.total_breaks) as total_breaks
            FROM daily_summaries ds
            JOIN users u ON ds.user_id = u.id
            WHERE ds.summary_date BETWEEN ? AND ?
            GROUP BY ds.user_id
            HAVING total_breaks >= 5
            ORDER BY avg_compliance DESC
            LIMIT 5
        """, (start_date, end_date))
        top_agents = [dict(row) for row in cursor.fetchall()]

    return {
        'period': {'start': str(start_date), 'end': str(end_date)},
        'summary': summary,
        'compliance_trend': [asdict(t) for t in compliance_trend],
        'break_distribution': [asdict(d) for d in distribution],
        'peak_hours': peak_hours,
        'top_compliant_agents': top_agents
    }


# ============================================
# DASHBOARD API HELPERS
# ============================================

def get_full_dashboard_data() -> Dict:
    """Get all data needed for the main dashboard in one call."""
    return {
        'realtime': get_realtime_dashboard_metrics().to_dict(),
        'active_breaks': [asdict(b) for b in get_active_breaks_list()],
        'overdue_breaks': [asdict(b) for b in get_overdue_breaks_list()],
        'break_distribution': [asdict(d) for d in get_break_distribution_today()],
        'agent_performance': [asdict(a) for a in get_agent_performance_today()],
        'hourly_distribution': [asdict(h) for h in get_hourly_distribution_today()],
        'compliance_trend': [asdict(t) for t in get_compliance_trend(7)],
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }


# ============================================
# TEST / DEMO
# ============================================

if __name__ == '__main__':
    print("Testing Aggregation Layer...")
    print("\n1. Real-time Metrics:")
    metrics = get_realtime_dashboard_metrics()
    print(f"   Active breaks: {metrics.active_breaks}")
    print(f"   Compliance rate: {metrics.compliance_rate}%")

    print("\n2. Break Distribution Today:")
    for dist in get_break_distribution_today():
        print(f"   {dist.break_type}: {dist.count} breaks ({dist.percentage}%)")

    print("\n3. Agent Performance Today:")
    for agent in get_agent_performance_today()[:5]:
        print(f"   {agent.full_name}: {agent.total_breaks} breaks, {agent.compliance_rate}% compliance")

    print("\n4. Peak Hours (last 7 days):")
    for peak in get_peak_hours():
        print(f"   {peak['hour_label']}: {peak['total_breaks']} breaks")

    print("\nAggregation layer test complete!")
