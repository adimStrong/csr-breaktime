"""
CSR Breaktime Dashboard - Database Module
SQLite database wrapper with helper functions for bot and dashboard integration.
"""

import os
import sqlite3
from datetime import datetime, date, timedelta, timezone
from contextlib import contextmanager
from typing import Optional, Dict, List, Any, Tuple
import json

# Philippine Timezone (UTC+8)
PH_TIMEZONE = timezone(timedelta(hours=8))

def get_ph_now():
    """Get current datetime in Philippine timezone."""
    return datetime.now(PH_TIMEZONE)

def get_ph_date():
    """Get current date in Philippine timezone."""
    return get_ph_now().date()

# Database configuration
BASE_DIR = os.getenv('BASE_DIR', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATABASE_DIR = os.path.join(BASE_DIR, "database")  # Python module directory
# Data directory - always use DATA_DIR env var or create data/ directory
DATA_DIR = os.getenv('DATA_DIR', os.path.join(BASE_DIR, 'data'))
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(DATA_DIR, "breaktime.db")
SCHEMA_FILE = os.path.join(DATABASE_DIR, "schema.sql")  # Schema stays in module directory

# Register adapters and converters for Python 3.12+ compatibility
def adapt_datetime(val):
    """Adapt datetime.datetime to ISO format string."""
    return val.isoformat(" ")

def adapt_date(val):
    """Adapt datetime.date to ISO format string."""
    return val.isoformat()

def convert_datetime(val):
    """Convert ISO format string to datetime.datetime."""
    return datetime.fromisoformat(val.decode())

def convert_date(val):
    """Convert ISO format string to datetime.date."""
    return date.fromisoformat(val.decode())

# Register the adapters and converters
sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_adapter(date, adapt_date)
sqlite3.register_converter("TIMESTAMP", convert_datetime)
sqlite3.register_converter("DATE", convert_date)


@contextmanager
def get_connection(timeout: int = 30):
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_FILE, detect_types=sqlite3.PARSE_DECLTYPES, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # Enable concurrent access
    conn.execute(f"PRAGMA busy_timeout = {timeout * 1000}")  # Convert to milliseconds
    conn.execute("PRAGMA synchronous = NORMAL")  # Balance between safety and speed
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


@contextmanager
def get_fast_connection():
    """Fast connection for dashboard queries with shorter timeout (5 seconds)."""
    conn = sqlite3.connect(DB_FILE, detect_types=sqlite3.PARSE_DECLTYPES, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")  # 5 second timeout
    conn.execute("PRAGMA synchronous = NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def init_database():
    """Initialize the database with schema."""
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.exists(SCHEMA_FILE):
        print(f"Schema file not found: {SCHEMA_FILE}")
        return False

    with open(SCHEMA_FILE, 'r', encoding='utf-8') as f:
        schema_sql = f.read()

    with get_connection() as conn:
        conn.executescript(schema_sql)

        # Add source column to active_sessions if it doesn't exist (migration)
        try:
            cursor = conn.execute("PRAGMA table_info(active_sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'source' not in columns:
                conn.execute("ALTER TABLE active_sessions ADD COLUMN source TEXT DEFAULT 'bot'")
                print("Added 'source' column to active_sessions table")
        except Exception as e:
            print(f"Migration check: {e}")

        # Add unique constraint on break_logs to prevent duplicates (migration)
        try:
            # Check if unique index exists
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_break_logs_unique'")
            if not cursor.fetchone():
                # First, remove any existing duplicates (keep lowest rowid)
                cursor = conn.execute("""
                    DELETE FROM break_logs
                    WHERE rowid NOT IN (
                        SELECT MIN(rowid)
                        FROM break_logs
                        GROUP BY user_id, timestamp, action
                    )
                """)
                deleted = cursor.rowcount
                if deleted > 0:
                    print(f"Removed {deleted} duplicate break_logs entries")

                # Create unique index to prevent future duplicates
                conn.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_break_logs_unique
                    ON break_logs(user_id, timestamp, action)
                """)
                print("Added unique constraint to break_logs table")
        except Exception as e:
            print(f"Break logs migration: {e}")

        print(f"Database initialized: {DB_FILE}")

    return True


# ============================================
# USER OPERATIONS
# ============================================

def get_or_create_user(telegram_id: int, username: str, full_name: str) -> int:
    """Get existing user or create new one. Returns user ID."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        row = cursor.fetchone()

        if row:
            # Update last activity and possibly username/name
            conn.execute("""
                UPDATE users
                SET username = ?, full_name = ?, last_active_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE telegram_id = ?
            """, (username, full_name, telegram_id))
            return row['id']
        else:
            cursor = conn.execute("""
                INSERT INTO users (telegram_id, username, full_name, last_active_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (telegram_id, username, full_name))
            return cursor.lastrowid


def get_user_by_telegram_id(telegram_id: int) -> Optional[Dict]:
    """Get user by Telegram ID."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


# ============================================
# BREAK TYPE OPERATIONS
# ============================================

def get_break_type_by_code(code: str) -> Optional[Dict]:
    """Get break type by code (B, W, P, O)."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM break_types WHERE code = ?",
            (code.upper(),)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_break_types() -> List[Dict]:
    """Get all break types."""
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM break_types ORDER BY id")
        return [dict(row) for row in cursor.fetchall()]


# ============================================
# BREAK LOG OPERATIONS
# ============================================

def log_break_out(user_id: int, break_type_id: int, timestamp: datetime,
                  reason: str = None, group_chat_id: int = None) -> int:
    """Log a break OUT action. Returns log ID."""
    log_date = timestamp.date() if isinstance(timestamp, datetime) else timestamp

    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO break_logs (user_id, break_type_id, action, timestamp, log_date, reason, group_chat_id)
            VALUES (?, ?, 'OUT', ?, ?, ?, ?)
        """, (user_id, break_type_id, timestamp, log_date, reason, group_chat_id))
        return cursor.lastrowid


def log_break_back(user_id: int, break_type_id: int, timestamp: datetime,
                   duration_minutes: float, reason: str = None, group_chat_id: int = None) -> int:
    """Log a break BACK action. Returns log ID."""
    log_date = timestamp.date() if isinstance(timestamp, datetime) else timestamp

    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO break_logs (user_id, break_type_id, action, timestamp, log_date, duration_minutes, reason, group_chat_id)
            VALUES (?, ?, 'BACK', ?, ?, ?, ?, ?)
        """, (user_id, break_type_id, timestamp, log_date, duration_minutes, reason, group_chat_id))
        return cursor.lastrowid


def get_user_breaks_for_date(user_id: int, log_date: date) -> List[Dict]:
    """Get all breaks for a user on a specific date."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT bl.*, bt.display_name as break_type_name, bt.time_limit_minutes
            FROM break_logs bl
            JOIN break_types bt ON bl.break_type_id = bt.id
            WHERE bl.user_id = ? AND bl.log_date = ?
            ORDER BY bl.timestamp
        """, (user_id, log_date))
        return [dict(row) for row in cursor.fetchall()]


# ============================================
# ACTIVE SESSION OPERATIONS
# ============================================

def start_session(user_id: int, break_type_id: int, start_time: datetime,
                  reason: str = None, group_chat_id: int = None, source: str = 'bot') -> int:
    """Start a new break session. Returns session ID. Source tracks origin (bot/excel)."""
    with get_connection() as conn:
        # Remove any existing session for this user
        conn.execute("DELETE FROM active_sessions WHERE user_id = ?", (user_id,))

        cursor = conn.execute("""
            INSERT INTO active_sessions (user_id, break_type_id, start_time, reason, group_chat_id, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, break_type_id, start_time, reason, group_chat_id, source))
        return cursor.lastrowid


def end_session(user_id: int) -> Optional[Dict]:
    """End a break session. Returns session data or None."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT s.*, bt.display_name as break_type_name, bt.time_limit_minutes
            FROM active_sessions s
            JOIN break_types bt ON s.break_type_id = bt.id
            WHERE s.user_id = ?
        """, (user_id,))
        row = cursor.fetchone()

        if row:
            session_data = dict(row)
            conn.execute("DELETE FROM active_sessions WHERE user_id = ?", (user_id,))
            return session_data
        return None


def get_active_session(user_id: int) -> Optional[Dict]:
    """Get active session for a user."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT s.*, bt.display_name as break_type_name, bt.code as break_type_code, bt.time_limit_minutes
            FROM active_sessions s
            JOIN break_types bt ON s.break_type_id = bt.id
            WHERE s.user_id = ?
        """, (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_active_sessions() -> List[Dict]:
    """Get all active break sessions with user details."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT
                s.*,
                u.telegram_id,
                u.username,
                u.full_name,
                bt.display_name as break_type_name,
                bt.time_limit_minutes,
                ROUND((julianday('now') - julianday(s.start_time)) * 24 * 60, 1) as duration_minutes
            FROM active_sessions s
            JOIN users u ON s.user_id = u.id
            JOIN break_types bt ON s.break_type_id = bt.id
            ORDER BY s.start_time
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_overdue_sessions() -> List[Dict]:
    """Get all sessions that are over their time limit."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT
                s.*,
                u.telegram_id,
                u.username,
                u.full_name,
                bt.display_name as break_type_name,
                bt.time_limit_minutes,
                ROUND((julianday('now') - julianday(s.start_time)) * 24 * 60, 1) as duration_minutes,
                ROUND((julianday('now') - julianday(s.start_time)) * 24 * 60 - bt.time_limit_minutes, 1) as over_limit_minutes
            FROM active_sessions s
            JOIN users u ON s.user_id = u.id
            JOIN break_types bt ON s.break_type_id = bt.id
            WHERE bt.time_limit_minutes IS NOT NULL
              AND (julianday('now') - julianday(s.start_time)) * 24 * 60 > bt.time_limit_minutes
            ORDER BY over_limit_minutes DESC
        """)
        return [dict(row) for row in cursor.fetchall()]


def update_session_reminder(user_id: int):
    """Mark that a reminder was sent for a session."""
    with get_connection() as conn:
        conn.execute("""
            UPDATE active_sessions
            SET reminder_sent = 1, last_reminder_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (user_id,))


# ============================================
# DASHBOARD METRICS
# ============================================

def get_realtime_metrics() -> Dict:
    """Get real-time dashboard metrics."""
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM v_dashboard_realtime")
        row = cursor.fetchone()
        return dict(row) if row else {}


def get_compliance_today() -> Dict:
    """Get compliance metrics for today."""
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM v_compliance_today")
        row = cursor.fetchone()
        return dict(row) if row else {
            'total_completed_breaks': 0,
            'within_limit': 0,
            'over_limit': 0,
            'compliance_rate': 100.0
        }


def get_break_distribution_today() -> List[Dict]:
    """Get break counts by type for today."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT
                bt.display_name as break_type,
                bt.code,
                COUNT(CASE WHEN bl.action = 'BACK' THEN 1 END) as count,
                COALESCE(SUM(bl.duration_minutes), 0) as total_duration
            FROM break_types bt
            LEFT JOIN break_logs bl ON bt.id = bl.break_type_id AND bl.log_date = DATE('now')
            GROUP BY bt.id
            ORDER BY bt.id
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_hourly_distribution(log_date: date = None) -> List[Dict]:
    """Get hourly break distribution for peak time analysis."""
    if log_date is None:
        log_date = get_ph_date()

    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT hour, break_outs, break_backs
            FROM hourly_metrics
            WHERE metric_date = ?
            ORDER BY hour
        """, (log_date,))
        return [dict(row) for row in cursor.fetchall()]


def get_agent_performance_today() -> List[Dict]:
    """Get performance metrics for all agents today."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT
                u.id as user_id,
                u.telegram_id,
                u.full_name,
                COUNT(CASE WHEN bl.action = 'BACK' THEN 1 END) as total_breaks,
                COALESCE(SUM(CASE WHEN bl.action = 'BACK' AND bt.is_counted_in_total = 1 THEN bl.duration_minutes ELSE 0 END), 0) as total_duration,
                COALESCE(AVG(CASE WHEN bl.action = 'BACK' THEN bl.duration_minutes END), 0) as avg_duration,
                SUM(CASE
                    WHEN bl.action = 'BACK' AND bt.time_limit_minutes IS NOT NULL AND bl.duration_minutes <= bt.time_limit_minutes THEN 1
                    WHEN bl.action = 'BACK' AND bt.time_limit_minutes IS NULL THEN 1
                    ELSE 0
                END) as within_limit,
                SUM(CASE
                    WHEN bl.action = 'BACK' AND bt.time_limit_minutes IS NOT NULL AND bl.duration_minutes > bt.time_limit_minutes THEN 1
                    ELSE 0
                END) as over_limit
            FROM users u
            LEFT JOIN break_logs bl ON u.id = bl.user_id AND bl.log_date = DATE('now')
            LEFT JOIN break_types bt ON bl.break_type_id = bt.id
            WHERE u.last_active_at >= DATE('now')
            GROUP BY u.id
            ORDER BY total_breaks DESC
        """)
        results = []
        for row in cursor.fetchall():
            r = dict(row)
            total = (r['within_limit'] or 0) + (r['over_limit'] or 0)
            r['compliance_rate'] = round(100 * (r['within_limit'] or 0) / total, 1) if total > 0 else 100.0
            results.append(r)
        return results


# ============================================
# DAILY SUMMARY OPERATIONS
# ============================================

def calculate_daily_summary(user_id: int, summary_date: date) -> Dict:
    """Calculate and store daily summary for a user."""
    with get_connection() as conn:
        # Get break counts and durations by type
        cursor = conn.execute("""
            SELECT
                bt.code,
                COUNT(CASE WHEN bl.action = 'BACK' THEN 1 END) as count,
                COALESCE(SUM(bl.duration_minutes), 0) as total_duration,
                COALESCE(AVG(bl.duration_minutes), 0) as avg_duration,
                SUM(CASE
                    WHEN bl.action = 'BACK' AND bt.time_limit_minutes IS NOT NULL AND bl.duration_minutes <= bt.time_limit_minutes THEN 1
                    WHEN bl.action = 'BACK' AND bt.time_limit_minutes IS NULL THEN 1
                    ELSE 0
                END) as within_limit,
                SUM(CASE
                    WHEN bl.action = 'BACK' AND bt.time_limit_minutes IS NOT NULL AND bl.duration_minutes > bt.time_limit_minutes THEN 1
                    ELSE 0
                END) as over_limit,
                MAX(CASE
                    WHEN bl.action = 'BACK' AND bt.time_limit_minutes IS NOT NULL
                    THEN bl.duration_minutes - bt.time_limit_minutes
                    ELSE 0
                END) as max_overdue
            FROM break_types bt
            LEFT JOIN break_logs bl ON bt.id = bl.break_type_id
                AND bl.user_id = ? AND bl.log_date = ?
            GROUP BY bt.id
        """, (user_id, summary_date))

        summary = {
            'break_count': 0, 'break_duration_total': 0, 'break_duration_avg': 0,
            'wc_count': 0, 'wc_duration_total': 0, 'wc_duration_avg': 0,
            'wcp_count': 0, 'wcp_duration_total': 0, 'wcp_duration_avg': 0,
            'other_count': 0, 'other_duration_total': 0, 'other_duration_avg': 0,
            'breaks_within_limit': 0, 'breaks_over_limit': 0, 'max_overdue_minutes': 0
        }

        for row in cursor.fetchall():
            code = row['code']
            if code == 'B':
                summary['break_count'] = row['count']
                summary['break_duration_total'] = row['total_duration']
                summary['break_duration_avg'] = row['avg_duration']
            elif code == 'W':
                summary['wc_count'] = row['count']
                summary['wc_duration_total'] = row['total_duration']
                summary['wc_duration_avg'] = row['avg_duration']
            elif code == 'P':
                summary['wcp_count'] = row['count']
                summary['wcp_duration_total'] = row['total_duration']
                summary['wcp_duration_avg'] = row['avg_duration']
            elif code == 'O':
                summary['other_count'] = row['count']
                summary['other_duration_total'] = row['total_duration']
                summary['other_duration_avg'] = row['avg_duration']

            summary['breaks_within_limit'] += row['within_limit'] or 0
            summary['breaks_over_limit'] += row['over_limit'] or 0
            if row['max_overdue'] and row['max_overdue'] > summary['max_overdue_minutes']:
                summary['max_overdue_minutes'] = row['max_overdue']

        # Calculate totals
        summary['total_breaks'] = (summary['break_count'] + summary['wc_count'] +
                                   summary['wcp_count'] + summary['other_count'])
        summary['total_duration'] = (summary['break_duration_total'] +
                                     summary['wcp_duration_total'] + summary['other_duration_total'])
        summary['total_duration_all'] = summary['total_duration'] + summary['wc_duration_total']

        total_completed = summary['breaks_within_limit'] + summary['breaks_over_limit']
        summary['compliance_rate'] = round(100 * summary['breaks_within_limit'] / total_completed, 1) if total_completed > 0 else 100.0

        # Check for missing clock-backs
        cursor = conn.execute("""
            SELECT
                SUM(CASE WHEN action = 'OUT' THEN 1 ELSE 0 END) -
                SUM(CASE WHEN action = 'BACK' THEN 1 ELSE 0 END) as missing
            FROM break_logs
            WHERE user_id = ? AND log_date = ?
        """, (user_id, summary_date))
        missing_row = cursor.fetchone()
        summary['missing_clock_backs'] = max(0, missing_row['missing'] or 0)

        # Insert or update summary
        conn.execute("""
            INSERT INTO daily_summaries (
                user_id, summary_date,
                break_count, wc_count, wcp_count, other_count, total_breaks,
                break_duration_total, wc_duration_total, wcp_duration_total, other_duration_total,
                total_duration, total_duration_all,
                break_duration_avg, wc_duration_avg, wcp_duration_avg, other_duration_avg,
                breaks_within_limit, breaks_over_limit, compliance_rate, max_overdue_minutes,
                missing_clock_backs, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, summary_date) DO UPDATE SET
                break_count = excluded.break_count,
                wc_count = excluded.wc_count,
                wcp_count = excluded.wcp_count,
                other_count = excluded.other_count,
                total_breaks = excluded.total_breaks,
                break_duration_total = excluded.break_duration_total,
                wc_duration_total = excluded.wc_duration_total,
                wcp_duration_total = excluded.wcp_duration_total,
                other_duration_total = excluded.other_duration_total,
                total_duration = excluded.total_duration,
                total_duration_all = excluded.total_duration_all,
                break_duration_avg = excluded.break_duration_avg,
                wc_duration_avg = excluded.wc_duration_avg,
                wcp_duration_avg = excluded.wcp_duration_avg,
                other_duration_avg = excluded.other_duration_avg,
                breaks_within_limit = excluded.breaks_within_limit,
                breaks_over_limit = excluded.breaks_over_limit,
                compliance_rate = excluded.compliance_rate,
                max_overdue_minutes = excluded.max_overdue_minutes,
                missing_clock_backs = excluded.missing_clock_backs,
                updated_at = CURRENT_TIMESTAMP
        """, (
            user_id, summary_date,
            summary['break_count'], summary['wc_count'], summary['wcp_count'], summary['other_count'], summary['total_breaks'],
            summary['break_duration_total'], summary['wc_duration_total'], summary['wcp_duration_total'], summary['other_duration_total'],
            summary['total_duration'], summary['total_duration_all'],
            summary['break_duration_avg'], summary['wc_duration_avg'], summary['wcp_duration_avg'], summary['other_duration_avg'],
            summary['breaks_within_limit'], summary['breaks_over_limit'], summary['compliance_rate'], summary['max_overdue_minutes'],
            summary['missing_clock_backs']
        ))

        return summary


def get_daily_summary(user_id: int, summary_date: date) -> Optional[Dict]:
    """Get daily summary for a user."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT * FROM daily_summaries
            WHERE user_id = ? AND summary_date = ?
        """, (user_id, summary_date))
        row = cursor.fetchone()
        return dict(row) if row else None


# ============================================
# COMPLIANCE ALERT OPERATIONS
# ============================================

def log_compliance_alert(user_id: int, break_type_id: int, alert_type: str,
                         duration_at_alert: float, over_limit_minutes: float,
                         message: str, sent_to_group: bool = False,
                         break_log_id: int = None) -> int:
    """Log a compliance alert. Returns alert ID."""
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO compliance_alerts (
                user_id, break_log_id, break_type_id, alert_type,
                alert_timestamp, duration_at_alert, over_limit_minutes,
                message_sent, sent_to_group, sent_to_user
            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, 0)
        """, (user_id, break_log_id, break_type_id, alert_type,
              duration_at_alert, over_limit_minutes, message, sent_to_group))
        return cursor.lastrowid


def get_alerts_for_date(log_date: date) -> List[Dict]:
    """Get all alerts for a specific date."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT ca.*, u.full_name, bt.display_name as break_type_name
            FROM compliance_alerts ca
            JOIN users u ON ca.user_id = u.id
            JOIN break_types bt ON ca.break_type_id = bt.id
            WHERE DATE(ca.alert_timestamp) = ?
            ORDER BY ca.alert_timestamp DESC
        """, (log_date,))
        return [dict(row) for row in cursor.fetchall()]


# ============================================
# TREND & HISTORICAL DATA
# ============================================

def get_compliance_trend(days: int = 7) -> List[Dict]:
    """Get compliance trend for the last N days."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT
                summary_date,
                SUM(breaks_within_limit) as within_limit,
                SUM(breaks_over_limit) as over_limit,
                ROUND(100.0 * SUM(breaks_within_limit) /
                    NULLIF(SUM(breaks_within_limit) + SUM(breaks_over_limit), 0), 1) as compliance_rate,
                COUNT(DISTINCT user_id) as agents
            FROM daily_summaries
            WHERE summary_date >= DATE('now', ? || ' days')
            GROUP BY summary_date
            ORDER BY summary_date
        """, (f'-{days}',))
        return [dict(row) for row in cursor.fetchall()]


def get_user_trend(user_id: int, days: int = 7) -> List[Dict]:
    """Get trend data for a specific user."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT *
            FROM daily_summaries
            WHERE user_id = ? AND summary_date >= DATE('now', ? || ' days')
            ORDER BY summary_date
        """, (user_id, f'-{days}'))
        return [dict(row) for row in cursor.fetchall()]


# ============================================
# INITIALIZATION
# ============================================

if __name__ == '__main__':
    # Initialize database when run directly
    print("Initializing CSR Breaktime Database...")
    init_database()
    print("Done!")
