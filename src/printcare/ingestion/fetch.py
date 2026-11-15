"""HTTP fetching for official wiki pages.

The fetcher keeps the request footprint small: one GET per page, a descriptive
User-Agent, a timeout, a size cap and a polite delay between requests.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request

from printcare.ingestion.models import DocumentRef

DEFAULT_USER_AGENT = (
    "PrintCareAI-Ingestion/0.1 (+https://github.com/demonpepper45-a11y/printcare-ai)"
)
MAX_PAGE_BYTES = 4 * 1024 * 1024


class FetchError(RuntimeError):
    """Raised when a page cannot be fetched; the message never contains page text."""


class HttpFetcher:
    """Fetch page HTML from the wiki with retries and light rate limiting."""

    def __init__(
        self,
        timeout: int = 30,
        retries: int = 1,
        delay: float = 0.3,
        max_bytes: int = MAX_PAGE_BYTES,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.delay = delay
        self.max_bytes = max_bytes
        self._last_request_at = 0.0

    def __call__(self, ref: DocumentRef) -> str:
        return self.fetch_url(ref.source_url)

    def fetch_url(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait_before_request()
            try:
                return self._get(url)
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code < 500 or attempt == self.retries:
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt == self.retries:
                    break
            self._last_request_at = time.monotonic()
        raise self._describe_failure(url, last_error)

    def _wait_before_request(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if self._last_request_at and elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    def _get(self, url: str) -> str:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            if "html" not in content_type.lower():
                raise FetchError(f"unexpected content type: {content_type or 'unknown'}")
            body = response.read(self.max_bytes + 1)
        self._last_request_at = time.monotonic()
        if len(body) > self.max_bytes:
            raise FetchError(f"page exceeds {self.max_bytes} bytes")
        return body.decode("utf-8", errors="replace")

    @staticmethod
    def _describe_failure(url: str, error: Exception | None) -> FetchError:
        if isinstance(error, urllib.error.HTTPError):
            return FetchError(f"HTTP {error.code} for {url}")
        if error is not None:
            return FetchError(f"network error ({type(error).__name__}) for {url}")
        return FetchError(f"fetch failed for {url}")
