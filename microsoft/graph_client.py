"""
Microsoft Graph API Client
Low-level client for making authenticated requests to Microsoft Graph API.
"""

import asyncio
import aiohttp
from typing import Optional, Dict, Any, List
from .auth import get_access_token

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


class GraphClient:
    """Async client for Microsoft Graph API with retry logic."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        token = get_access_token()
        if not token:
            raise RuntimeError("Failed to get access token")

        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }

    async def _request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict] = None,
        retry_count: int = 3,
        retry_delay: float = 1.0
    ) -> Dict[str, Any]:
        """
        Make an authenticated request to Graph API with retry logic.

        Handles:
        - 401: Token expired - refresh and retry
        - 429: Rate limited - exponential backoff
        - 5xx: Server error - retry with backoff
        """
        url = f"{GRAPH_BASE_URL}{endpoint}"
        session = await self._get_session()

        for attempt in range(retry_count):
            try:
                headers = self._get_headers()

                async with session.request(method, url, headers=headers, json=json_data) as response:
                    # Success
                    if response.status in (200, 201, 204):
                        if response.status == 204:
                            return {}
                        return await response.json()

                    # Token expired - refresh and retry
                    if response.status == 401:
                        print(f"[Graph] 401 Unauthorized - refreshing token (attempt {attempt + 1})")
                        from .auth import refresh_access_token
                        refresh_access_token()
                        continue

                    # Rate limited - exponential backoff
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', retry_delay * (2 ** attempt)))
                        print(f"[Graph] 429 Rate limited - waiting {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue

                    # Server error - retry with backoff
                    if response.status >= 500:
                        print(f"[Graph] {response.status} Server error - retrying in {retry_delay * (2 ** attempt)}s")
                        await asyncio.sleep(retry_delay * (2 ** attempt))
                        continue

                    # Client error - don't retry
                    error_text = await response.text()
                    raise RuntimeError(f"Graph API error {response.status}: {error_text}")

            except aiohttp.ClientError as e:
                if attempt < retry_count - 1:
                    print(f"[Graph] Network error - retrying: {e}")
                    await asyncio.sleep(retry_delay * (2 ** attempt))
                    continue
                raise

        raise RuntimeError(f"Failed after {retry_count} attempts")

    async def get(self, endpoint: str) -> Dict[str, Any]:
        """Make a GET request."""
        return await self._request('GET', endpoint)

    async def post(self, endpoint: str, data: Dict = None) -> Dict[str, Any]:
        """Make a POST request."""
        return await self._request('POST', endpoint, json_data=data)

    async def patch(self, endpoint: str, data: Dict = None) -> Dict[str, Any]:
        """Make a PATCH request."""
        return await self._request('PATCH', endpoint, json_data=data)


# Singleton instance
_client: Optional[GraphClient] = None


def get_graph_client() -> GraphClient:
    """Get the singleton GraphClient instance."""
    global _client
    if _client is None:
        _client = GraphClient()
    return _client
