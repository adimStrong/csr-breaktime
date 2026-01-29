"""
Get Excel File ID from OneDrive
Lists files in your OneDrive to help find the Excel file ID.

Usage:
    python scripts/get_excel_file_id.py

Prerequisites:
    - Run setup_microsoft_auth.py first
    - Set MICROSOFT_REFRESH_TOKEN environment variable
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import requests
except ImportError:
    print("Error: requests package not installed. Run: pip install requests")
    sys.exit(1)

from microsoft.auth import get_access_token, is_configured


def list_excel_files():
    """List Excel files in OneDrive root and recent files."""

    if not is_configured():
        print("ERROR: Microsoft credentials not configured")
        print("Run setup_microsoft_auth.py first")
        return

    token = get_access_token()
    if not token:
        print("ERROR: Failed to get access token")
        return

    headers = {'Authorization': f'Bearer {token}'}

    print("=" * 60)
    print("Excel Files in OneDrive")
    print("=" * 60)
    print()

    # Search for Excel files
    search_url = "https://graph.microsoft.com/v1.0/me/drive/root/search(q='.xlsx')"

    try:
        response = requests.get(search_url, headers=headers)
        response.raise_for_status()
        data = response.json()

        files = data.get('value', [])

        if not files:
            print("No Excel files found in OneDrive")
            print()
            print("Create an Excel file:")
            print("1. Go to OneDrive (onedrive.live.com)")
            print("2. Click 'New' -> 'Excel workbook'")
            print("3. Name it 'CSR_Breaktime_Log.xlsx'")
            print("4. Add headers in Row 1:")
            print("   A: Timestamp")
            print("   B: User ID")
            print("   C: Username")
            print("   D: Full Name")
            print("   E: Break Type")
            print("   F: Action")
            print("   G: Duration")
            print("   H: Reason")
            print("5. Select A1:H1, then Insert -> Table")
            print("6. Name the table 'BreakLog'")
            return

        print(f"Found {len(files)} Excel file(s):\n")

        for f in files:
            name = f.get('name', 'Unknown')
            file_id = f.get('id', 'Unknown')
            modified = f.get('lastModifiedDateTime', 'Unknown')[:10]
            web_url = f.get('webUrl', '')

            print(f"Name: {name}")
            print(f"  File ID: {file_id}")
            print(f"  Modified: {modified}")
            print(f"  URL: {web_url}")
            print()

        print("=" * 60)
        print("Copy the File ID for your target file and set in Railway:")
        print("  EXCEL_FILE_ID=<file-id-here>")
        print("=" * 60)

    except requests.exceptions.RequestException as e:
        print(f"ERROR: API request failed: {e}")


if __name__ == '__main__':
    list_excel_files()
