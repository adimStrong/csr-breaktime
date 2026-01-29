"""
CSR Breaktime - Start both Bot and Dashboard
For Railway deployment to share the same data volume.
"""

import os
import sys
import subprocess
import threading
import time
import pytz
from datetime import datetime, timedelta

os.environ['BASE_DIR'] = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ['BASE_DIR'])

# Philippine Timezone
PH_TZ = pytz.timezone('Asia/Manila')


def get_timestamp():
    """Get current timestamp in Philippine timezone for logging."""
    return datetime.now(PH_TZ).strftime('%Y-%m-%d %H:%M:%S')


def run_bot():
    """Run the Telegram bot."""
    print(f"[{get_timestamp()}] [Bot] Starting Telegram bot...")
    subprocess.run([sys.executable, "-u", "breaktime_tracker_bot.py"])


def run_dashboard():
    """Run the dashboard server."""
    print(f"[{get_timestamp()}] [Dashboard] Starting dashboard server...")
    import uvicorn
    uvicorn.run(
        "dashboard.api:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=False
    )


def run_health_check():
    """Periodically log health status. Runs in a background thread."""
    HEALTH_CHECK_INTERVAL = 300  # 5 minutes

    while True:
        try:
            time.sleep(HEALTH_CHECK_INTERVAL)

            # Count today's breaks from database
            break_count = 0
            try:
                from database.db import get_connection
                with get_connection() as conn:
                    today = datetime.now(PH_TZ).strftime('%Y-%m-%d')
                    cursor = conn.execute(
                        "SELECT COUNT(*) FROM break_logs WHERE date(timestamp) = ?",
                        (today,)
                    )
                    break_count = cursor.fetchone()[0]
            except Exception:
                pass

            print(f"[{get_timestamp()}] [HEALTH] Heartbeat - System OK | Breaks logged today: {break_count}")

        except Exception as e:
            print(f"[{get_timestamp()}] [HEALTH] Health check error: {e}")


def run_auto_sync():
    """Run auto-sync loop to sync Excel to SQLite."""
    print("[Sync] Starting auto-sync service...")
    time.sleep(5)  # Wait for services to start

    try:
        from database.sync import sync_all
        from database.db import init_database

        # Initialize database
        init_database()

        # Sync loop
        interval = int(os.getenv('SYNC_INTERVAL', 30))
        while True:
            try:
                sync_all()
            except Exception as e:
                print(f"[Sync] Error: {e}")
            time.sleep(interval)
    except Exception as e:
        print(f"[Sync] Failed to start: {e}")


def auto_close_orphaned_breaks():
    """
    Auto-close all OUT entries without BACK in Excel files.
    Adds BACK entries with reason 'Auto-closed by system'.
    """
    print(f"[{get_timestamp()}] [Startup] Checking for orphaned breaks (OUT without BACK)...")
    try:
        import pandas as pd
        from pathlib import Path

        data_dir = os.getenv('DATA_DIR', os.path.join(os.environ['BASE_DIR'], 'database'))
        close_time = datetime.now(PH_TZ)
        close_timestamp = close_time.strftime('%Y-%m-%d %H:%M:%S')
        total_closed = 0

        # Check all recent Excel files (today and yesterday)
        for days_back in range(2):  # Today and yesterday
            check_date = close_time - timedelta(days=days_back)
            year_month = check_date.strftime('%Y-%m')
            date_str = check_date.strftime('%Y-%m-%d')
            log_file = Path(data_dir) / year_month / f"break_logs_{date_str}.xlsx"

            if not log_file.exists():
                continue

            try:
                df = pd.read_excel(log_file, engine='openpyxl')
                if df.empty:
                    continue

                # Find orphaned OUT entries (OUT without matching BACK)
                orphaned = []
                for user_id in df['User ID'].unique():
                    user_df = df[df['User ID'] == user_id]

                    for break_type in user_df['Break Type'].unique():
                        type_df = user_df[user_df['Break Type'] == break_type]
                        out_entries = type_df[type_df['Action'] == 'OUT']
                        back_entries = type_df[type_df['Action'] == 'BACK']

                        out_count = len(out_entries)
                        back_count = len(back_entries)

                        if out_count > back_count:
                            # Get the last OUT entry that doesn't have a BACK
                            last_out = out_entries.iloc[-1]
                            orphaned.append({
                                'user_id': last_out['User ID'],
                                'username': last_out['Username'],
                                'full_name': last_out['Full Name'],
                                'break_type': break_type,
                                'out_time': str(last_out['Timestamp'])
                            })

                if not orphaned:
                    continue

                # Add BACK entries for orphaned breaks
                new_rows = []
                for entry in orphaned:
                    # Calculate duration
                    try:
                        out_time = datetime.strptime(entry['out_time'].split('.')[0], '%Y-%m-%d %H:%M:%S')
                        duration_minutes = round((close_time.replace(tzinfo=None) - out_time).total_seconds() / 60, 1)
                    except:
                        duration_minutes = 0

                    new_rows.append({
                        'User ID': entry['user_id'],
                        'Username': entry['username'],
                        'Full Name': entry['full_name'],
                        'Break Type': entry['break_type'],
                        'Action': 'BACK',
                        'Timestamp': close_timestamp,
                        'Duration (minutes)': duration_minutes,
                        'Reason': 'Auto-closed by system'
                    })
                    print(f"[{get_timestamp()}] [Auto-close] {entry['full_name']} - {entry['break_type']} (was out since {entry['out_time']})")

                # Append new rows to Excel
                if new_rows:
                    new_df = pd.DataFrame(new_rows)
                    df = pd.concat([df, new_df], ignore_index=True)
                    df.to_excel(log_file, index=False, engine='openpyxl')
                    total_closed += len(new_rows)

            except Exception as e:
                print(f"[{get_timestamp()}] [Auto-close] Error processing {log_file.name}: {e}")

        if total_closed > 0:
            print(f"[{get_timestamp()}] [Auto-close] Closed {total_closed} orphaned breaks")
        else:
            print(f"[{get_timestamp()}] [Auto-close] No orphaned breaks found")

        return total_closed
    except Exception as e:
        print(f"[{get_timestamp()}] [Auto-close] Error: {e}")
        import traceback
        traceback.print_exc()
        return 0


def clear_stuck_active_breaks():
    """Clear only truly stuck active breaks (8+ hours old) on startup. Preserves recent sessions."""
    print(f"[{get_timestamp()}] [Startup] Checking for stuck active breaks...")
    try:
        from database.db import get_connection

        with get_connection() as conn:
            # Only delete sessions older than 8 hours (truly stuck/forgotten)
            # This preserves recent sessions across restarts
            cursor = conn.execute("""
                SELECT COUNT(*) FROM active_sessions
                WHERE start_time < datetime('now', '-8 hours')
            """)
            stale_count = cursor.fetchone()[0]

            if stale_count > 0:
                conn.execute("DELETE FROM active_sessions WHERE start_time < datetime('now', '-8 hours')")
                conn.commit()
                print(f"[{get_timestamp()}] [Startup] Cleared {stale_count} stale breaks (8+ hours old)")

            # Count remaining active sessions
            cursor = conn.execute("SELECT COUNT(*) FROM active_sessions")
            remaining = cursor.fetchone()[0]
            if remaining > 0:
                print(f"[{get_timestamp()}] [Startup] Preserved {remaining} recent active sessions")
            else:
                print(f"[{get_timestamp()}] [Startup] No active sessions")

        return stale_count
    except Exception as e:
        print(f"[{get_timestamp()}] [Startup] Error clearing active breaks (continuing anyway): {e}")
        return 0


def initial_full_sync():
    """One-time full sync of all historical Excel files to SQLite."""
    print("[Startup] Running initial full sync of Excel data...")
    try:
        from database.db import init_database, get_connection
        from database.sync import sync_excel_to_db
        from pathlib import Path
        from datetime import datetime, timedelta, timezone

        # Initialize database
        init_database()

        # Get data directory
        data_dir = os.getenv('DATA_DIR', os.path.join(os.environ['BASE_DIR'], 'data'))

        # Find all Excel files
        total_synced = 0
        for month_dir in Path(data_dir).glob('202*-*'):
            if month_dir.is_dir():
                for excel_file in month_dir.glob('break_logs_*.xlsx'):
                    try:
                        new = sync_excel_to_db(excel_file)
                        if new > 0:
                            print(f"  Synced {new} records from {excel_file.name}")
                            total_synced += new
                    except Exception as e:
                        print(f"  Error syncing {excel_file.name}: {e}")

        print(f"[Startup] Initial sync complete: {total_synced} total records synced")
        return total_synced
    except Exception as e:
        print(f"[Startup] Initial sync error: {e}")
        import traceback
        traceback.print_exc()
        return 0


if __name__ == "__main__":
    print(f"[{get_timestamp()}] " + "=" * 50)
    print(f"[{get_timestamp()}] CSR Breaktime - Startup v2")
    print(f"[{get_timestamp()}] " + "=" * 50)

    mode = os.getenv("RUN_MODE", "both").lower()

    if mode == "bot":
        print(f"[{get_timestamp()}] Mode: bot only")
        run_bot()
    elif mode == "dashboard":
        print(f"[{get_timestamp()}] Mode: dashboard only")
        run_dashboard()
    elif mode == "sync":
        print(f"[{get_timestamp()}] Mode: sync only")
        run_auto_sync()
    else:
        # Run all services together
        print(f"[{get_timestamp()}] Mode: bot + dashboard + sync")
        print()

        # Auto-close orphaned breaks (OUT without BACK) in Excel
        auto_close_orphaned_breaks()

        # Clear stuck active breaks from database (fail-safe)
        clear_stuck_active_breaks()

        # Initial full sync of historical data
        initial_full_sync()

        # Start health check in background thread
        health_thread = threading.Thread(target=run_health_check, daemon=True)
        health_thread.start()
        print(f"[{get_timestamp()}] [HEALTH] Health check started (every 5 minutes)")

        # Start sync in background thread
        sync_thread = threading.Thread(target=run_auto_sync, daemon=True)
        sync_thread.start()

        # Start bot in background thread
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()

        # Run dashboard in main thread (handles signals properly)
        run_dashboard()
