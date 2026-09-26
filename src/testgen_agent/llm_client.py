"""DeepSeek HTTP client setup; response parsing and retry policy belong to B2."""

from __future__ import annotations

import httpx

from .config import AppConfig


def create_http_client(
    config: AppConfig, *, transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    """Create without sending requests; caller closes it via a context manager.

    Later callers use the relative path 'chat/completions' to preserve a /v1
    base path. HTTPX performs no automatic retries; B2 owns any retry budget.
    """
    return httpx.Client(
        base_url=config.base_url + "/",
        headers={
            "Authorization": f"Bearer {config.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        },
        timeout=httpx.Timeout(config.request_timeout_seconds),
        follow_redirects=False,
        transport=transport,
    )
