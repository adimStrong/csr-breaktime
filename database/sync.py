"""
CSR Breaktime - Auto Sync Module
Syncs Excel data from original bot to SQLite database.
Also detects active breaks (OUT without BACK) for real-time dashboard.
"""

import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('BASE_DIR', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from database.db import get_connection, get_or_create_user

# Import DATA_DIR from db module for consistent path handling
from database.db import DATA_DIR

# Excel source directory - use DATA_DIR for Railway volume
EXCEL_SOURCE_DIR = os.environ.get('EXCEL_SOURCE_DIR', DATA_DIR)

BREAK_TYPE_MAP = {
    '☕ Break': 1,
    '🚻 WC': 2,
    '🚽 WCP': 3,
    '⚠️ Other': 4
}


def get_last_synced_timestamp():
    """Get the last synced timestamp from the database."""
    with get_connection() as conn:
        cursor = conn.execute("SELECT MAX(timestamp) FROM break_logs")
        result = cursor.fetchone()[0]
        return result if result else "1970-01-01 00:00:00"


def sync_excel_to_db(excel_file: Path) -> int:
    """Sync a single Excel file to the database. Returns count of new records."""
    try:
        df = pd.read_excel(excel_file, engine='openpyxl')
        if df.empty:
            return 0

        date_str = excel_file.stem.replace('break_logs_', '')
        last_sync = get_last_synced_timestamp()

        # Convert last_sync to string for comparison
        if hasattr(last_sync, 'strftime'):
            last_sync = last_sync.strftime('%Y-%m-%d %H:%M:%S')

        new_records = 0

        with get_connection() as conn:
            for _, row in df.iterrows():
                ts = str(row['Timestamp']).split('.')[0]

                # Skip if already synced
                if ts <= str(last_sync):
                    continue

                # Get or create user
                tid = int(row['User ID'])
                username = str(row['Username']) if pd.notna(row['Username']) else None
                full_name = str(row['Full Name']) if pd.notna(row['Full Name']) else 'Unknown'
                user_id = get_or_create_user(tid, username, full_name)

                # Get break type
                bt_id = BREAK_TYPE_MAP.get(str(row['Break Type']), 4)

                # Get other fields
                action = str(row['Action']).upper()
                duration = None
                if pd.notna(row['Duration (minutes)']) and row['Duration (minutes)'] != '':
                    try:
                        duration = float(row['Duration (minutes)'])
                    except:
                        pass
                reason = str(row['Reason']) if pd.notna(row['Reason']) and row['Reason'] != '' else None

                # Insert
                conn.execute("""
                    INSERT INTO break_logs (user_id, break_type_id, action, timestamp, log_date, duration_minutes, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_id, bt_id, action, ts, date_str, duration, reason))
                new_records += 1

        return new_records

    except Exception as e:
        print(f"Error syncing {excel_file}: {e}")
        import traceback
        traceback.print_exc()
        return 0


def detect_active_breaks_from_excel():
    """
    Detect active breaks by finding OUT entries without matching BACK entries.
    Updates the active_sessions table in real-time.
    """
    today = date.today()
    year_month = today.strftime('%Y-%m')
    excel_file = Path(EXCEL_SOURCE_DIR) / year_month / f"break_logs_{today}.xlsx"

    if not excel_file.exists():
        return 0

    try:
        df = pd.read_excel(excel_file, engine='openpyxl')
        if df.empty:
            return 0

        # Group by User ID and find active sessions
        # An active session = last action for that user is OUT
        active_users = {}

        for _, row in df.iterrows():
            user_id = int(row['User ID'])
            action = str(row['Action']).upper()

            if action == 'OUT':
                active_users[user_id] = {
                    'telegram_id': user_id,
                    'username': str(row['Username']) if pd.notna(row['Username']) else None,
                    'full_name': str(row['Full Name']) if pd.notna(row['Full Name']) else 'Unknown',
                    'break_type': str(row['Break Type']),
                    'timestamp': str(row['Timestamp']).split('.')[0],
                    'reason': str(row['Reason']) if pd.notna(row['Reason']) and row['Reason'] != '' else None
                }
            elif action == 'BACK' and user_id in active_users:
                del active_users[user_id]

        # Update active_sessions table
        with get_connection() as conn:
            # Clear old active sessions
            conn.execute("DELETE FROM active_sessions")

            # Insert current active sessions
            for telegram_id, session in active_users.items():
                # Get or create user
                db_user_id = get_or_create_user(
                    telegram_id,
                    session['username'],
                    session['full_name']
                )

                # Get break type ID
                bt_id = BREAK_TYPE_MAP.get(session['break_type'], 4)

                # Insert active session
                conn.execute("""
                    INSERT INTO active_sessions (user_id, break_type_id, start_time, reason)
                    VALUES (?, ?, ?, ?)
                """, (db_user_id, bt_id, session['timestamp'], session['reason']))

        return len(active_users)

    except Exception as e:
        print(f"Error detecting active breaks: {e}")
        import traceback
        traceback.print_exc()
        return 0


def sync_all():
    """Sync all Excel files to database and detect active breaks."""
    print(f"[{datetime.now()}] Starting sync from {EXCEL_SOURCE_DIR}...")

    # Find today's and yesterday's Excel files
    today = date.today()
    year_month = today.strftime('%Y-%m')
    month_dir = Path(EXCEL_SOURCE_DIR) / year_month

    if not month_dir.exists():
        print(f"No Excel files found in {month_dir}")
        return 0

    total_new = 0

    # Sync recent files (last 2 days)
    for days_ago in range(2):
        check_date = today - timedelta(days=days_ago)

        # Handle month boundary
        check_month = check_date.strftime('%Y-%m')
        check_dir = Path(EXCEL_SOURCE_DIR) / check_month

        excel_file = check_dir / f"break_logs_{check_date}.xlsx"
        if excel_file.exists():
            new = sync_excel_to_db(excel_file)
            if new > 0:
                print(f"  Synced {new} new records from {excel_file.name}")
            total_new += new

    # Detect active breaks from today's Excel
    active_count = detect_active_breaks_from_excel()
    print(f"  Active breaks detected: {active_count}")

    print(f"[{datetime.now()}] Sync complete. {total_new} new records.")
    return total_new


def start_auto_sync(interval_seconds=30):
    """Start auto-sync loop."""
    import time
    print(f"Starting auto-sync (every {interval_seconds}s)...")
    print(f"Excel source: {EXCEL_SOURCE_DIR}")

    while True:
        try:
            sync_all()
        except Exception as e:
            print(f"Sync error: {e}")
            import traceback
            traceback.print_exc()
        time.sleep(interval_seconds)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Sync Excel to SQLite')
    parser.add_argument('--watch', action='store_true', help='Run continuous sync')
    parser.add_argument('--interval', type=int, default=30, help='Sync interval in seconds')
    args = parser.parse_args()

    if args.watch:
        start_auto_sync(args.interval)
    else:
        sync_all()
