"""
CSR Breaktime Bot - Database Integration
Hooks into the bot to sync active sessions to SQLite for real-time dashboard.
Import this in the main bot file.
"""

import os
import sys
from datetime import datetime

# Setup path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('BASE_DIR', os.path.dirname(os.path.abspath(__file__)))

from database.db import (
    get_connection,
    get_or_create_user,
    get_break_type_by_code,
    start_session,
    end_session,
    log_break_out,
    log_break_back,
)

# Break type mapping
BREAK_TYPE_MAP = {
    '☕ Break': ('B', 1),
    '🚻 WC': ('W', 2),
    '🚽 WCP': ('P', 3),
    '⚠️ Other': ('O', 4),
}


def sync_break_out(user_id: int, username: str, full_name: str,
                   break_type: str, timestamp: str, reason: str = None,
                   group_chat_id: int = None):
    """
    Sync a break OUT action to SQLite database.
    Call this when a user starts a break.
    """
    try:
        # Get or create user in DB
        db_user_id = get_or_create_user(user_id, username, full_name)

        # Get break type ID
        _, break_type_id = BREAK_TYPE_MAP.get(break_type, ('O', 4))

        # Parse timestamp
        ts = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')

        # Start active session (for real-time dashboard)
        start_session(db_user_id, break_type_id, ts, reason, group_chat_id)

        # Log to break_logs table
        log_break_out(db_user_id, break_type_id, ts, reason, group_chat_id)

        print(f"[DB] Synced OUT: {full_name} - {break_type}")
        return True

    except Exception as e:
        print(f"[DB] Sync OUT error: {e}")
        return False


def sync_break_back(user_id: int, username: str, full_name: str,
                    break_type: str, timestamp: str, duration_minutes: float,
                    reason: str = None, group_chat_id: int = None):
    """
    Sync a break BACK action to SQLite database.
    Call this when a user ends a break.
    """
    try:
        # Get or create user in DB
        db_user_id = get_or_create_user(user_id, username, full_name)

        # Get break type ID
        _, break_type_id = BREAK_TYPE_MAP.get(break_type, ('O', 4))

        # Parse timestamp
        ts = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')

        # End active session (removes from real-time dashboard)
        end_session(db_user_id)

        # Log to break_logs table
        log_break_back(db_user_id, break_type_id, ts, duration_minutes, reason, group_chat_id)

        print(f"[DB] Synced BACK: {full_name} - {break_type} ({duration_minutes:.1f} min)")
        return True

    except Exception as e:
        print(f"[DB] Sync BACK error: {e}")
        return False


def get_active_breaks_count():
    """Get count of currently active breaks from DB."""
    try:
        with get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM active_sessions")
            return cursor.fetchone()[0]
    except:
        return 0
