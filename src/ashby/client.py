"""HTTP client for the Ashby API.

Wraps `httpx.AsyncClient` with HTTP Basic auth (API key as username) and
applies a tenacity retry policy for transient 429/5xx responses. HTTP
errors are surfaced as `AshbyAPIError`, which carries the response body
so callers can see Ashby's structured error envelope.
"""

import json
import logging
import os
from typing import Any, Optional

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger("ashby.client")


class AshbyAPIError(Exception):
    """HTTP error response from Ashby, with the response body preserved.

    `str(err)` renders as `<status> <endpoint>: <body>` so the raw
    Ashby error envelope is visible in logs and in the text response
    surfaced to the caller.
    """

    def __init__(self, status_code: int, body: Any, endpoint: str) -> None:
        self.status_code = status_code
        self.body = body
        self.endpoint = endpoint
        body_repr = json.dumps(body) if not isinstance(body, str) else body
        super().__init__(f"{status_code} {endpoint}: {body_repr}")


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, AshbyAPIError) and exc.status_code in (429, 500, 502, 503, 504)


def _extract_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text


class AshbyClient:
    """Handles Ashby API operations.

    Construction has no side effects — the API key is read and the HTTP
    client is created lazily on the first request. A single
    `httpx.AsyncClient` is reused across requests for connection reuse.
    """

    def __init__(self) -> None:
        self.api_key: Optional[str] = None
        self.base_url = "https://api.ashbyhq.com"
        self.headers: dict = {}
        self._http_client: Optional[httpx.AsyncClient] = None

    def connect(self) -> bool:
        """Read ASHBY_API_KEY from the environment and configure headers.

        Called lazily on first use, but exposed so callers can eagerly
        verify configuration at startup if they want to fail fast.
        """
        self.api_key = os.getenv("ASHBY_API_KEY")
        if not self.api_key:
            return False
        self.headers = {"Content-Type": "application/json"}
        return True

    def _ensure_connected(self) -> None:
        if self.api_key:
            return
        if not self.connect():
            raise ValueError("Ashby connection not established (ASHBY_API_KEY is not set)")

    def _client(self) -> httpx.AsyncClient:
        """Lazily create and reuse a single AsyncClient for connection pooling."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient()
        return self._http_client

    async def aclose(self) -> None:
        """Close the underlying HTTP client. Safe to call multiple times."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _make_request(
        self, endpoint: str, method: str = "GET", data: Optional[dict] = None
    ) -> dict:
        self._ensure_connected()

        url = f"{self.base_url}{endpoint}"
        logger.debug("Ashby %s %s", method, endpoint)
        response = await self._client().request(
            method=method,
            url=url,
            headers=self.headers,
            json=data,
            auth=(self.api_key, ""),
        )
        if response.is_error:
            body = _extract_body(response)
            logger.warning("Ashby %s failed: %d %s", endpoint, response.status_code, body)
            raise AshbyAPIError(response.status_code, body, endpoint)
        return response.json()

    async def _make_multipart_request(
        self,
        endpoint: str,
        data: Optional[dict] = None,
        files: Optional[dict] = None,
    ) -> dict:
        """Multipart POST for file uploads.

        Does NOT send the JSON Content-Type header — httpx sets the
        multipart boundary automatically when `files` is provided.
        Not retried — file handles may not be rewindable.
        """
        self._ensure_connected()

        url = f"{self.base_url}{endpoint}"
        logger.debug("Ashby POST %s (multipart)", endpoint)
        response = await self._client().post(
            url,
            data=data,
            files=files,
            auth=(self.api_key, ""),
        )
        if response.is_error:
            body = _extract_body(response)
            logger.warning("Ashby %s failed: %d %s", endpoint, response.status_code, body)
            raise AshbyAPIError(response.status_code, body, endpoint)
        return response.json()


# Module-level singleton — no side effects at import. First request
# triggers connect() and AsyncClient creation.
ashby_client = AshbyClient()
