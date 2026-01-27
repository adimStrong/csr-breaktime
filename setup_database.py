"""
CSR Breaktime - Database Setup Script
Initializes the database and migrates existing Excel data.
"""

import os
import sys

# Set base directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ['BASE_DIR'] = BASE_DIR

# Add to path
sys.path.insert(0, BASE_DIR)

def main():
    print("=" * 60)
    print("CSR Breaktime - Database Setup")
    print("=" * 60)

    # Step 1: Initialize database
    print("\n[Step 1] Initializing database schema...")
    from database.db import init_database
    init_database()
    print("Database initialized successfully!")

    # Step 2: Run migration
    print("\n[Step 2] Migrating Excel data...")
    from database.migrate_excel import migrate_excel_files
    migrate_excel_files()

    # Step 3: Test aggregations
    print("\n[Step 3] Testing aggregation layer...")
    try:
        from dashboard.aggregations import get_realtime_dashboard_metrics, get_compliance_trend

        metrics = get_realtime_dashboard_metrics()
        print(f"   - Real-time metrics: OK")
        print(f"     Active breaks: {metrics.active_breaks}")
        print(f"     Agents active today: {metrics.agents_active_today}")
        print(f"     Compliance rate: {metrics.compliance_rate}%")

        trend = get_compliance_trend(7)
        print(f"   - Compliance trend: {len(trend)} days of data")

    except Exception as e:
        print(f"   - Warning: Aggregation test failed: {e}")

    print("\n" + "=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Run 'python -m dashboard.aggregations' to test aggregations")
    print("  2. Start building the dashboard API (Task #3)")
    print("  3. Update the bot to use the new database (optional)")


if __name__ == '__main__':
    main()
