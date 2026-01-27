"""Fast batch migration script"""
import os
import sys

os.environ['BASE_DIR'] = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ['BASE_DIR'])

import pandas as pd
from pathlib import Path
from datetime import datetime
import sqlite3

DATABASE_DIR = os.path.join(os.environ['BASE_DIR'], "database")
DB_FILE = os.path.join(DATABASE_DIR, "breaktime.db")

def main():
    print("Fast Migration Starting...")

    # Direct connection for speed
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA foreign_keys = OFF")  # Speed up
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")

    break_type_map = {'☕ Break': 1, '🚻 WC': 2, '🚽 WCP': 3, '⚠️ Other': 4}
    user_cache = {}

    # Find Excel files
    excel_files = sorted(Path(DATABASE_DIR).rglob("break_logs_*.xlsx"))
    print(f"Found {len(excel_files)} files")

    total = 0
    for excel_file in excel_files:
        df = pd.read_excel(excel_file, engine='openpyxl')
        if df.empty:
            continue

        date_str = excel_file.stem.replace('break_logs_', '')
        records = []

        for _, row in df.iterrows():
            tid = int(row['User ID'])

            # Cache users
            if tid not in user_cache:
                cursor = conn.execute("SELECT id FROM users WHERE telegram_id=?", (tid,))
                r = cursor.fetchone()
                if r:
                    user_cache[tid] = r[0]
                else:
                    cursor = conn.execute(
                        "INSERT INTO users (telegram_id, username, full_name) VALUES (?,?,?)",
                        (tid, str(row['Username']) if pd.notna(row['Username']) else None,
                         str(row['Full Name']) if pd.notna(row['Full Name']) else 'Unknown'))
                    user_cache[tid] = cursor.lastrowid

            uid = user_cache[tid]
            bt_id = break_type_map.get(str(row['Break Type']), 4)
            ts = str(row['Timestamp']).split('.')[0]
            action = str(row['Action']).upper()
            dur = float(row['Duration (minutes)']) if pd.notna(row['Duration (minutes)']) and row['Duration (minutes)'] != '' else None
            reason = str(row['Reason']) if pd.notna(row['Reason']) and row['Reason'] != '' else None

            records.append((uid, bt_id, action, ts, date_str, dur, reason))

        # Batch insert
        conn.executemany(
            "INSERT INTO break_logs (user_id, break_type_id, action, timestamp, log_date, duration_minutes, reason) VALUES (?,?,?,?,?,?,?)",
            records)
        conn.commit()
        total += len(records)
        print(f"  {excel_file.name}: {len(records)} records")

    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()

    print(f"\nDone! Total: {total} records, {len(user_cache)} users")

if __name__ == '__main__':
    main()
