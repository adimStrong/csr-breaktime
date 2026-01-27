"""
CSR Breaktime - Excel to SQLite Migration Script
Imports all existing Excel break logs into the new database.
"""

import os
import sys
import pandas as pd
from datetime import datetime, date
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import (
    init_database, get_connection, get_or_create_user,
    get_break_type_by_code, calculate_daily_summary
)

# Configuration
BASE_DIR = os.getenv('BASE_DIR', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATABASE_DIR = os.path.join(BASE_DIR, "database")


def get_break_type_from_display(display_name: str) -> str:
    """Convert display name to break type code."""
    mapping = {
        '☕ Break': 'B',
        '🚻 WC': 'W',
        '🚽 WCP': 'P',
        '⚠️ Other': 'O'
    }
    return mapping.get(display_name, 'O')


def migrate_excel_files():
    """Migrate all Excel files to SQLite database."""
    print("=" * 60)
    print("CSR Breaktime - Excel to SQLite Migration")
    print("=" * 60)

    # Initialize database
    print("\n1. Initializing database...")
    init_database()

    # Find all Excel files
    print("\n2. Scanning for Excel files...")
    excel_files = list(Path(DATABASE_DIR).rglob("break_logs_*.xlsx"))
    print(f"   Found {len(excel_files)} Excel files")

    if not excel_files:
        print("   No Excel files found to migrate.")
        return

    # Sort files by date
    excel_files.sort()

    # Track statistics
    stats = {
        'files_processed': 0,
        'records_imported': 0,
        'users_created': 0,
        'errors': 0
    }

    # Cache for break types
    break_type_cache = {}

    # Process each file
    print("\n3. Processing files...")
    for excel_file in excel_files:
        try:
            print(f"\n   Processing: {excel_file.name}")
            df = pd.read_excel(excel_file, engine='openpyxl')

            if df.empty:
                print(f"      - Empty file, skipping")
                continue

            # Extract date from filename
            date_str = excel_file.stem.replace('break_logs_', '')
            log_date = datetime.strptime(date_str, '%Y-%m-%d').date()

            records_in_file = 0
            users_in_file = set()

            with get_connection() as conn:
                for _, row in df.iterrows():
                    try:
                        # Get or create user
                        telegram_id = int(row['User ID'])
                        username = str(row['Username']) if pd.notna(row['Username']) else None
                        full_name = str(row['Full Name']) if pd.notna(row['Full Name']) else 'Unknown'

                        user_id = get_or_create_user(telegram_id, username, full_name)
                        users_in_file.add(telegram_id)

                        # Get break type
                        break_display = str(row['Break Type'])
                        break_code = get_break_type_from_display(break_display)

                        if break_code not in break_type_cache:
                            bt = get_break_type_by_code(break_code)
                            break_type_cache[break_code] = bt['id'] if bt else 1

                        break_type_id = break_type_cache[break_code]

                        # Parse timestamp
                        timestamp_str = str(row['Timestamp'])
                        try:
                            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            timestamp = datetime.strptime(timestamp_str.split('.')[0], '%Y-%m-%d %H:%M:%S')

                        # Get action and duration
                        action = str(row['Action']).upper()
                        duration = float(row['Duration (minutes)']) if pd.notna(row['Duration (minutes)']) and row['Duration (minutes)'] != '' else None
                        reason = str(row['Reason']) if pd.notna(row['Reason']) and row['Reason'] != '' else None

                        # Insert into database
                        conn.execute("""
                            INSERT INTO break_logs (user_id, break_type_id, action, timestamp, log_date, duration_minutes, reason)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (user_id, break_type_id, action, timestamp, log_date, duration, reason))

                        records_in_file += 1

                    except Exception as e:
                        print(f"      - Error processing row: {e}")
                        stats['errors'] += 1
                        continue

            print(f"      - Imported {records_in_file} records from {len(users_in_file)} users")
            stats['files_processed'] += 1
            stats['records_imported'] += records_in_file

        except Exception as e:
            print(f"      - Error processing file: {e}")
            stats['errors'] += 1
            continue

    # Calculate daily summaries
    print("\n4. Calculating daily summaries...")
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT DISTINCT user_id, log_date FROM break_logs ORDER BY log_date
        """)
        user_dates = cursor.fetchall()

        for row in user_dates:
            try:
                calculate_daily_summary(row['user_id'], row['log_date'])
            except Exception as e:
                print(f"   Error calculating summary for user {row['user_id']} on {row['log_date']}: {e}")

    print(f"   Calculated summaries for {len(user_dates)} user-days")

    # Print final statistics
    print("\n" + "=" * 60)
    print("Migration Complete!")
    print("=" * 60)
    print(f"\nStatistics:")
    print(f"  - Files processed: {stats['files_processed']}")
    print(f"  - Records imported: {stats['records_imported']}")
    print(f"  - Errors: {stats['errors']}")

    # Verify data
    print("\n5. Verifying data...")
    with get_connection() as conn:
        cursor = conn.execute("SELECT COUNT(*) as count FROM users")
        users_count = cursor.fetchone()['count']

        cursor = conn.execute("SELECT COUNT(*) as count FROM break_logs")
        logs_count = cursor.fetchone()['count']

        cursor = conn.execute("SELECT COUNT(*) as count FROM daily_summaries")
        summaries_count = cursor.fetchone()['count']

    print(f"  - Users in database: {users_count}")
    print(f"  - Break logs in database: {logs_count}")
    print(f"  - Daily summaries: {summaries_count}")

    print("\nMigration completed successfully!")


if __name__ == '__main__':
    migrate_excel_files()
