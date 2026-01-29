"""
Microsoft OAuth2 Token Management
Handles token refresh and caching for Microsoft Graph API access.
"""

import os
import time
import threading
from typing import Optional, Dict
import msal

# Microsoft Azure App Configuration
CLIENT_ID = os.getenv('MICROSOFT_CLIENT_ID', '')
CLIENT_SECRET = os.getenv('MICROSOFT_CLIENT_SECRET', '')
TENANT_ID = os.getenv('MICROSOFT_TENANT_ID', 'consumers')  # 'consumers' for personal accounts
REFRESH_TOKEN = os.getenv('MICROSOFT_REFRESH_TOKEN', '')

# OAuth2 Scopes needed for Excel Online
SCOPES = ['Files.ReadWrite', 'User.Read']

# Token cache with thread safety
_token_cache: Dict[str, any] = {
    'access_token': None,
    'expires_at': 0,
}
_token_lock = threading.Lock()


def get_msal_app() -> msal.ConfidentialClientApplication:
    """Create MSAL confidential client application."""
    authority = f"https://login.microsoftonline.com/{TENANT_ID}"
    return msal.ConfidentialClientApplication(
        client_id=CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=authority,
    )


def refresh_access_token() -> Optional[str]:
    """
    Refresh the access token using the stored refresh token.
    Returns the new access token or None if refresh fails.
    """
    if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
        print("[MS Auth] Missing credentials - CLIENT_ID, CLIENT_SECRET, or REFRESH_TOKEN not set")
        return None

    try:
        app = get_msal_app()

        # Use refresh token to get new access token
        result = app.acquire_token_by_refresh_token(
            refresh_token=REFRESH_TOKEN,
            scopes=SCOPES
        )

        if 'access_token' in result:
            with _token_lock:
                _token_cache['access_token'] = result['access_token']
                # Token typically expires in 1 hour, refresh 5 minutes early
                _token_cache['expires_at'] = time.time() + result.get('expires_in', 3600) - 300

            print("[MS Auth] Token refreshed successfully")
            return result['access_token']
        else:
            error = result.get('error_description', result.get('error', 'Unknown error'))
            print(f"[MS Auth] Token refresh failed: {error}")
            return None

    except Exception as e:
        print(f"[MS Auth] Token refresh error: {e}")
        return None


def get_access_token() -> Optional[str]:
    """
    Get a valid access token, refreshing if necessary.
    Thread-safe with automatic token refresh.
    """
    with _token_lock:
        # Check if we have a valid cached token
        if _token_cache['access_token'] and time.time() < _token_cache['expires_at']:
            return _token_cache['access_token']

    # Need to refresh token
    return refresh_access_token()


def is_configured() -> bool:
    """Check if Microsoft integration is properly configured."""
    return all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN])


def get_auth_url() -> str:
    """Get the authorization URL for initial setup."""
    app = get_msal_app()
    auth_url = app.get_authorization_request_url(
        scopes=SCOPES,
        redirect_uri='http://localhost:8080/callback'
    )
    return auth_url
