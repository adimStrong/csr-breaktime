"""
Test Excel Online sync functionality.
"""

import os
import sys
import asyncio
from pathlib import Path
from datetime import datetime

# Load .env file
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from microsoft.excel_handler import sync_break_to_excel, get_excel_handler

async def test_sync():
    print("=" * 50)
    print("Testing Excel Online Sync")
    print("=" * 50)

    # Initialize handler
    print("\n1. Initializing Excel handler...")
    handler = get_excel_handler()

    if not handler.enabled:
        print("   ERROR: Excel sync is not enabled")
        print("   Check EXCEL_SYNC_ENABLED=true in .env")
        return False

    print(f"   Enabled: {handler.enabled}")

    # Initialize
    result = await handler.initialize()
    print(f"   Initialized: {result}")

    if not result:
        print("   ERROR: Could not initialize Excel handler")
        return False

    # Test sync
    print("\n2. Testing sync with sample data...")
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    success = await sync_break_to_excel(
        user_id=0,
        username="test_user",
        full_name="System Test",
        break_type="Test",
        action="TEST",
        timestamp=timestamp,
        duration=None,
        reason="Testing Excel Online sync"
    )

    if success:
        print(f"   SUCCESS! Test row added at {timestamp}")
        print("\n" + "=" * 50)
        print("Excel Online sync is working!")
        print("=" * 50)
    else:
        print("   FAILED to sync test data")
        return False

    await handler.close()
    return True


if __name__ == '__main__':
    result = asyncio.run(test_sync())
    sys.exit(0 if result else 1)
