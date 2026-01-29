"""
Microsoft OAuth2 Setup Script
Run this locally to get the refresh token for Railway configuration.

Usage:
    python scripts/setup_microsoft_auth.py

Prerequisites:
    1. Create Azure App Registration at https://portal.azure.com
    2. Set environment variables:
       - MICROSOFT_CLIENT_ID
       - MICROSOFT_CLIENT_SECRET
       - MICROSOFT_TENANT_ID (optional, defaults to 'common')
"""

import os
import sys
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import msal
except ImportError:
    print("Error: msal package not installed. Run: pip install msal")
    sys.exit(1)

# Configuration
CLIENT_ID = os.getenv('MICROSOFT_CLIENT_ID', '')
CLIENT_SECRET = os.getenv('MICROSOFT_CLIENT_SECRET', '')
TENANT_ID = os.getenv('MICROSOFT_TENANT_ID', 'consumers')
REDIRECT_URI = 'http://localhost:8080/callback'
SCOPES = ['Files.ReadWrite', 'User.Read']

# Store auth code from callback
auth_code = None


class CallbackHandler(BaseHTTPRequestHandler):
    """Handle OAuth callback."""

    def do_GET(self):
        global auth_code
        parsed = urlparse(self.path)

        if parsed.path == '/callback':
            query = parse_qs(parsed.query)

            if 'code' in query:
                auth_code = query['code'][0]
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b'''
                    <html><body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1>Authorization Successful!</h1>
                    <p>You can close this window and return to the terminal.</p>
                    </body></html>
                ''')
            elif 'error' in query:
                error = query.get('error_description', query.get('error', ['Unknown error']))[0]
                self.send_response(400)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(f'''
                    <html><body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1>Authorization Failed</h1>
                    <p>Error: {error}</p>
                    </body></html>
                '''.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress HTTP logs


def main():
    global auth_code

    print("=" * 60)
    print("Microsoft OAuth2 Setup for CSR Breaktime Excel Sync")
    print("=" * 60)
    print()

    # Check configuration
    if not CLIENT_ID:
        print("ERROR: MICROSOFT_CLIENT_ID environment variable not set")
        print()
        print("Steps to get Client ID:")
        print("1. Go to https://portal.azure.com")
        print("2. Search for 'App registrations'")
        print("3. Click 'New registration'")
        print("4. Name: 'CSR-Breaktime-Excel-Sync'")
        print("5. Supported account types: 'Personal Microsoft accounts only'")
        print("   (or 'Accounts in any organizational directory and personal')")
        print("6. Redirect URI: Web -> http://localhost:8080/callback")
        print("7. Copy the 'Application (client) ID'")
        print()
        print("Then set: export MICROSOFT_CLIENT_ID='your-client-id'")
        return

    if not CLIENT_SECRET:
        print("ERROR: MICROSOFT_CLIENT_SECRET environment variable not set")
        print()
        print("Steps to get Client Secret:")
        print("1. In your App Registration, go to 'Certificates & secrets'")
        print("2. Click 'New client secret'")
        print("3. Add a description and choose expiry")
        print("4. Copy the secret VALUE (not the ID)")
        print()
        print("Then set: export MICROSOFT_CLIENT_SECRET='your-secret'")
        return

    print(f"Client ID: {CLIENT_ID[:20]}...")
    print(f"Tenant ID: {TENANT_ID}")
    print(f"Redirect URI: {REDIRECT_URI}")
    print()

    # Create MSAL app
    authority = f"https://login.microsoftonline.com/{TENANT_ID}"
    app = msal.ConfidentialClientApplication(
        client_id=CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=authority,
    )

    # Get authorization URL
    auth_url = app.get_authorization_request_url(
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )

    print("Opening browser for Microsoft login...")
    print(f"If browser doesn't open, visit: {auth_url}")
    print()

    # Start local server for callback
    server = HTTPServer(('localhost', 8080), CallbackHandler)
    server.timeout = 120  # 2 minute timeout

    # Open browser
    webbrowser.open(auth_url)

    print("Waiting for authorization (2 minute timeout)...")

    # Wait for callback
    while auth_code is None:
        server.handle_request()

    server.server_close()

    if not auth_code:
        print("ERROR: No authorization code received")
        return

    print()
    print("Exchanging code for tokens...")

    # Exchange code for tokens
    result = app.acquire_token_by_authorization_code(
        code=auth_code,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )

    if 'access_token' in result:
        print()
        print("=" * 60)
        print("SUCCESS! Copy these values to Railway environment variables:")
        print("=" * 60)
        print()
        print(f"MICROSOFT_CLIENT_ID={CLIENT_ID}")
        print(f"MICROSOFT_CLIENT_SECRET={CLIENT_SECRET}")
        print(f"MICROSOFT_TENANT_ID={TENANT_ID}")
        print()
        print("MICROSOFT_REFRESH_TOKEN=" + result.get('refresh_token', 'NO_REFRESH_TOKEN'))
        print()
        print("=" * 60)
        print()
        print("Also set these in Railway:")
        print("  EXCEL_SYNC_ENABLED=true")
        print("  EXCEL_FILE_ID=<your-file-id>")
        print("  EXCEL_TABLE_NAME=BreakLog")
        print()
        print("To get EXCEL_FILE_ID:")
        print("1. Open your Excel file in OneDrive web")
        print("2. The URL looks like: ...onedrive.live.com/edit.aspx?resid=ABC123...")
        print("3. The file ID is the 'resid' parameter value")
        print("   OR use: python scripts/get_excel_file_id.py")
    else:
        error = result.get('error_description', result.get('error', 'Unknown error'))
        print(f"ERROR: Failed to get tokens: {error}")


if __name__ == '__main__':
    main()
