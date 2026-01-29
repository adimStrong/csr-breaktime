"""
Excel Online Handler
Manages Excel file operations via Microsoft Graph API.
With circuit breaker pattern for resilience.
"""

import os
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from .graph_client import get_graph_client, GraphClient
from .auth import is_configured

# Excel configuration from environment
EXCEL_FILE_ID = os.getenv('EXCEL_FILE_ID', '')
EXCEL_TABLE_NAME = os.getenv('EXCEL_TABLE_NAME', 'BreakLog')
EXCEL_SYNC_ENABLED = os.getenv('EXCEL_SYNC_ENABLED', 'false').lower() == 'true'

# Sync timeout in seconds
SYNC_TIMEOUT_SECONDS = 5

# Circuit breaker state
_consecutive_failures = 0
_circuit_open_until: Optional[datetime] = None
CIRCUIT_BREAKER_THRESHOLD = 3  # failures before tripping
CIRCUIT_BREAKER_RESET_MINUTES = 5  # minutes before retry


def _is_circuit_open() -> bool:
    """Check if the circuit breaker is open (sync disabled temporarily)."""
    global _circuit_open_until
    if _circuit_open_until is None:
        return False
    if datetime.now() >= _circuit_open_until:
        print(f"[Excel] Circuit breaker reset - re-enabling sync")
        _circuit_open_until = None
        return False
    return True


def _record_success():
    """Record a successful sync, resetting failure count."""
    global _consecutive_failures
    _consecutive_failures = 0


def _record_failure():
    """Record a failed sync, potentially tripping the circuit breaker."""
    global _consecutive_failures, _circuit_open_until
    _consecutive_failures += 1
    if _consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
        _circuit_open_until = datetime.now() + timedelta(minutes=CIRCUIT_BREAKER_RESET_MINUTES)
        print(f"[Excel] Circuit breaker TRIPPED after {_consecutive_failures} failures - sync disabled for {CIRCUIT_BREAKER_RESET_MINUTES} minutes")


class ExcelHandler:
    """
    Handler for Excel Online operations.
    Syncs break events to an Excel table in OneDrive.
    """

    def __init__(self):
        self.client: GraphClient = get_graph_client()
        self.file_id = EXCEL_FILE_ID
        self.table_name = EXCEL_TABLE_NAME
        self._initialized = False
        self._enabled = EXCEL_SYNC_ENABLED and is_configured() and bool(EXCEL_FILE_ID)

    @property
    def enabled(self) -> bool:
        """Check if Excel sync is enabled and configured."""
        return self._enabled

    async def initialize(self) -> bool:
        """
        Initialize the Excel handler.
        Verifies the file exists and table is accessible.
        """
        if not self._enabled:
            print("[Excel] Sync disabled or not configured")
            return False

        try:
            # Verify file exists
            await self.client.get(f"/me/drive/items/{self.file_id}")

            # Verify table exists (or create it)
            await self._ensure_table_exists()

            self._initialized = True
            print(f"[Excel] Handler initialized - File ID: {self.file_id[:20]}...")
            return True

        except Exception as e:
            print(f"[Excel] Initialization failed: {e}")
            self._enabled = False
            return False

    async def _ensure_table_exists(self) -> bool:
        """Ensure the Excel table exists with correct headers."""
        try:
            # Try to get the table
            endpoint = f"/me/drive/items/{self.file_id}/workbook/tables/{self.table_name}"
            await self.client.get(endpoint)
            return True
        except Exception as e:
            # Table might not exist - that's OK, user should create it manually
            print(f"[Excel] Table '{self.table_name}' check: {e}")
            print("[Excel] Please ensure the table exists in your Excel file")
            return False

    async def add_break_event(
        self,
        user_id: int,
        username: str,
        full_name: str,
        break_type: str,
        action: str,
        timestamp: str,
        duration: Optional[float] = None,
        reason: Optional[str] = None
    ) -> bool:
        """
        Add a break event row to the Excel table.

        Args:
            user_id: Telegram user ID
            username: Telegram username
            full_name: User's full name
            break_type: Type of break (e.g., "Break", "WC")
            action: "OUT" or "BACK"
            timestamp: Timestamp string (YYYY-MM-DD HH:MM:SS)
            duration: Duration in minutes (for BACK action)
            reason: Optional reason for the break

        Returns:
            True if successful, False otherwise
        """
        if not self._enabled:
            return False

        # Check circuit breaker
        if _is_circuit_open():
            return False

        if not self._initialized:
            await self.initialize()
            if not self._initialized:
                _record_failure()
                return False

        try:
            # Prepare row data matching Excel table columns:
            # Timestamp | User ID | Username | Full Name | Break Type | Action | Duration | Reason
            row_values = [
                [
                    timestamp,
                    str(user_id),
                    username or 'N/A',
                    full_name,
                    break_type,
                    action,
                    str(duration) if duration else '',
                    reason or ''
                ]
            ]

            endpoint = f"/me/drive/items/{self.file_id}/workbook/tables/{self.table_name}/rows/add"

            # Add timeout to prevent hanging
            await asyncio.wait_for(
                self.client.post(endpoint, {"values": row_values}),
                timeout=SYNC_TIMEOUT_SECONDS
            )

            print(f"[Excel] Synced: {full_name} - {break_type} {action}")
            _record_success()
            return True

        except asyncio.TimeoutError:
            print(f"[Excel] Sync timeout after {SYNC_TIMEOUT_SECONDS}s")
            _record_failure()
            return False
        except Exception as e:
            print(f"[Excel] Failed to add row: {e}")
            _record_failure()
            return False

    async def get_table_rows(self, top: int = 100) -> List[Dict]:
        """Get recent rows from the Excel table."""
        if not self._enabled or not self._initialized:
            return []

        try:
            endpoint = f"/me/drive/items/{self.file_id}/workbook/tables/{self.table_name}/rows"
            result = await self.client.get(endpoint)
            return result.get('value', [])
        except Exception as e:
            print(f"[Excel] Failed to get rows: {e}")
            return []

    async def close(self):
        """Close the underlying client."""
        await self.client.close()


# Singleton instance
_handler: Optional[ExcelHandler] = None


def get_excel_handler() -> ExcelHandler:
    """Get the singleton ExcelHandler instance."""
    global _handler
    if _handler is None:
        _handler = ExcelHandler()
    return _handler


async def sync_break_to_excel(
    user_id: int,
    username: str,
    full_name: str,
    break_type: str,
    action: str,
    timestamp: str,
    duration: Optional[float] = None,
    reason: Optional[str] = None
) -> bool:
    """
    Convenience function to sync a break event to Excel.
    Non-blocking - failures are logged but don't raise exceptions.
    Uses circuit breaker to prevent repeated failures.
    """
    # Check circuit breaker early
    if _is_circuit_open():
        return False

    try:
        handler = get_excel_handler()
        return await handler.add_break_event(
            user_id, username, full_name, break_type,
            action, timestamp, duration, reason
        )
    except Exception as e:
        print(f"[Excel] Sync error (non-fatal): {e}")
        _record_failure()
        return False
