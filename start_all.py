"""
CSR Breaktime - Start both Bot and Dashboard
For Railway deployment to share the same data volume.
"""

import os
import sys
import subprocess
import threading
import time

os.environ['BASE_DIR'] = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ['BASE_DIR'])


def run_bot():
    """Run the Telegram bot."""
    print("[Bot] Starting Telegram bot...")
    subprocess.run([sys.executable, "-u", "breaktime_tracker_bot.py"])


def run_dashboard():
    """Run the dashboard server."""
    print("[Dashboard] Starting dashboard server...")
    import uvicorn
    uvicorn.run(
        "dashboard.api:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=False
    )


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


if __name__ == "__main__":
    mode = os.getenv("RUN_MODE", "both").lower()

    if mode == "bot":
        run_bot()
    elif mode == "dashboard":
        run_dashboard()
    elif mode == "sync":
        run_auto_sync()
    else:
        # Run all services together
        print("=" * 50)
        print("CSR Breaktime - Starting Bot + Dashboard + Sync")
        print("=" * 50)
        print()

        # Start sync in background thread
        sync_thread = threading.Thread(target=run_auto_sync, daemon=True)
        sync_thread.start()

        # Start bot in background thread
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()

        # Run dashboard in main thread (handles signals properly)
        run_dashboard()
