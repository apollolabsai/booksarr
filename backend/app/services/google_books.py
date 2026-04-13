"""Google Books API client for metadata lookups."""
import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from time import monotonic

import httpx

from backend.app.services.matcher import titles_match
from backend.app.utils.rate_limiter import RateLimiter
from backend.app.utils.api_usage import record_api_call

logger = logging.getLogger("booksarr.google")

VOLUMES_URL = "https://www.googleapis.com/books/v1/volumes"
RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
QUOTA_REASONS = {
    "dailylimitexceeded",
    "quotaexceeded",
    "ratelimitexceeded",
    "userratelimitexceeded",
}
TITLE_MATCH_THRESHOLD = 0.75


@dataclass
class GBook:
    title: str
    published_date: str | None = None
    cover_url: str | None = None
    google_id: str | None = None
    isbn_10: str | None = None
    isbn_13: str | None = None
    language: str | None = None

    @property
    def publish_year(self) -> int | None:
        if self.published_date and len(self.published_date) >= 4:
            try:
                return int(self.published_date[:4])
            except ValueError:
                return None
        return None


@dataclass
class GoogleLookupResult:
    book: GBook | None
    reason: str


class GoogleBooksLookupError(RuntimeError):
    """Raised when a Google Books lookup fails and should be retried later."""

    def __init__(self, reason: str, message: str | None = None):
        self.reason = reason
        super().__init__(message or reason)


class GoogleBooksThrottledError(GoogleBooksLookupError):
    """Raised when Google Books signals a quota or rate-limit response."""


class GoogleBooksClient:
    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None
        # Keep Google requests deliberately slow; a full refresh can issue
        # hundreds of lookups and the free tier is easy to throttle.
        self._rate_limiter = RateLimiter(max_tokens=1, refill_rate=1.0)
        self._throttled = False

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=True,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def search_by_isbn(self, isbn: str) -> GBook | None:
        return (await self.search_by_isbn_result(isbn)).book

    async def search_by_isbn_result(self, isbn: str) -> GoogleLookupResult:
        """Search by ISBN — most precise lookup."""
        clean = isbn.replace("-", "").replace(" ", "")
        return await self._search(
            f"isbn:{clean}",
            max_results=1,
            lookup_type="isbn",
            book_context=clean,
        )

    async def search_by_title_author(self, title: str, author: str) -> GBook | None:
        return (await self.search_by_title_author_result(title, author)).book

    async def search_by_title_author_result(self, title: str, author: str) -> GoogleLookupResult:
        """Search by title and author name."""
        query = f"intitle:{title}"
        if author:
            query += f"+inauthor:{author}"
        return await self._search(
            query,
            expected_title=title,
            expected_author=author,
            max_results=5,
            lookup_type="title_author",
            book_context=title,
        )

    def _normalize_search_title(self, title: str) -> str:
        normalized = unicodedata.normalize("NFKD", title.lower().strip())
        normalized = normalized.replace("volume", "vol")
        normalized = re.sub(r"&\w+;", " ", normalized)
        normalized = re.sub(r"[^\w\s]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _title_score(self, expected_title: str, candidate_title: str) -> float:
        expected_norm = self._normalize_search_title(expected_title)
        candidate_norm = self._normalize_search_title(candidate_title)
        if not expected_norm or not candidate_norm:
            return 0.0

        if expected_norm == candidate_norm:
            return 1.0
        if titles_match(expected_title, candidate_title):
            return 0.95

        if candidate_norm.startswith(expected_norm) or candidate_norm.endswith(expected_norm):
            return 0.92
        if expected_norm.startswith(candidate_norm) or expected_norm.endswith(candidate_norm):
            return 0.88
        if f" {expected_norm} " in f" {candidate_norm} ":
            return 0.9

        shorter = min(len(expected_norm), len(candidate_norm))
        longer = max(len(expected_norm), len(candidate_norm))
        if shorter > 0 and shorter / longer >= 0.85:
            if expected_norm in candidate_norm or candidate_norm in expected_norm:
                return 0.85

        return SequenceMatcher(None, expected_norm, candidate_norm).ratio()

    def _extract_isbns(self, info: dict) -> tuple[str | None, str | None]:
        isbn_10 = None
        isbn_13 = None
        for identifier in info.get("industryIdentifiers") or []:
            if not isinstance(identifier, dict):
                continue
            id_type = str(identifier.get("type") or "").upper()
            value = str(identifier.get("identifier") or "").strip()
            if not value:
                continue
            if id_type == "ISBN_10" and not isbn_10:
                isbn_10 = value
            elif id_type == "ISBN_13" and not isbn_13:
                isbn_13 = value
        return isbn_10, isbn_13

    def _pick_cover_url(self, info: dict) -> str | None:
        image_links = info.get("imageLinks") or {}
        for key in ["extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail"]:
            value = image_links.get(key)
            if isinstance(value, str) and value:
                return value.replace("http://", "https://")
        return None

    def _authors_match(self, authors: list[str], expected_author: str) -> bool:
        if not expected_author:
            return True

        expected_author_lower = expected_author.lower()
        expected_parts = [part for part in expected_author_lower.split() if part]
        if not expected_parts:
            return True

        expected_last = expected_parts[-1]
        for author in authors:
            author_lower = author.lower()
            author_parts = [part for part in author_lower.split() if part]
            if author_lower == expected_author_lower:
                return True
            if expected_last and expected_last in author_parts:
                return True
        return False

    def _is_throttled_response(self, response: httpx.Response) -> bool:
        if response.status_code == 429:
            return True
        if response.status_code != 403:
            return False
        try:
            data = response.json()
        except ValueError:
            return False

        error = data.get("error", {})
        message = str(error.get("message", "")).lower()
        reasons = {
            str(item.get("reason", "")).lower()
            for item in error.get("errors", [])
            if isinstance(item, dict)
        }
        return bool(reasons & QUOTA_REASONS) or "quota" in message or "rate limit" in message

    async def _sleep_before_retry(self, attempt: int):
        await asyncio.sleep(min(8.0, float(2 ** attempt)))

    async def _search(
        self,
        query: str,
        expected_title: str | None = None,
        expected_author: str | None = None,
        max_results: int = 1,
        lookup_type: str = "unknown",
        book_context: str | None = None,
    ) -> GoogleLookupResult:
        if self._throttled:
            raise GoogleBooksThrottledError(
                "throttled",
                "Google Books lookups paused after a throttle response",
            )

        client = await self._get_client()
        for attempt in range(3):
            await self._rate_limiter.acquire()
            started_at = monotonic()
            logger.info(
                "Google Books request: book='%s' author='%s' lookup=%s query='%s' maxResults=%d attempt=%d",
                (book_context or expected_title or query)[:80],
                (expected_author or "")[:80],
                lookup_type,
                query[:160],
                max_results,
                attempt + 1,
            )
            try:
                await record_api_call("google")
                resp = await client.get(
                    VOLUMES_URL,
                    params={"q": query, "maxResults": max_results, "key": self._api_key},
                )
                if self._is_throttled_response(resp):
                    self._throttled = True
                    logger.warning(
                        "Google Books response: book='%s' lookup=%s status=%d elapsed_ms=%d result='throttled'",
                        (book_context or expected_title or query)[:80],
                        lookup_type,
                        resp.status_code,
                        int((monotonic() - started_at) * 1000),
                    )
                    raise GoogleBooksThrottledError(
                        "throttled",
                        f"Google Books throttled with HTTP {resp.status_code}"
                    )
                resp.raise_for_status()
                data = resp.json()
                break
            except GoogleBooksThrottledError:
                raise
            except httpx.TimeoutException as e:
                if attempt < 2:
                    await self._sleep_before_retry(attempt)
                    continue
                logger.warning(
                    "Google Books response: book='%s' lookup=%s result='timeout'",
                    (book_context or expected_title or query)[:80],
                    lookup_type,
                )
                raise GoogleBooksLookupError("timeout") from e
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                if status_code in RETRYABLE_STATUS_CODES and attempt < 2:
                    await self._sleep_before_retry(attempt)
                    continue
                logger.warning(
                    "Google Books response: book='%s' lookup=%s status=%d result='http_error'",
                    (book_context or expected_title or query)[:80],
                    lookup_type,
                    status_code,
                )
                raise GoogleBooksLookupError("http_error", f"HTTP {status_code}") from e
            except httpx.RequestError as e:
                if attempt < 2:
                    await self._sleep_before_retry(attempt)
                    continue
                logger.warning(
                    "Google Books response: book='%s' lookup=%s result='request_error' detail='%s'",
                    (book_context or expected_title or query)[:80],
                    lookup_type,
                    str(e)[:160],
                )
                raise GoogleBooksLookupError("request_error", str(e)) from e
            except ValueError as e:
                logger.warning(
                    "Google Books response: book='%s' lookup=%s result='invalid_json'",
                    (book_context or expected_title or query)[:80],
                    lookup_type,
                )
                raise GoogleBooksLookupError("invalid_json", "invalid JSON") from e

        items = data.get("items", [])
        if not items:
            logger.warning(
                "Google Books response: book='%s' author='%s' lookup=%s status=200 candidates=0 result='no_result'",
                (book_context or expected_title or query)[:80],
                (expected_author or "")[:80],
                lookup_type,
            )
            return GoogleLookupResult(book=None, reason="no_result")

        best_match: tuple[dict, dict, str, list[str], float] | None = None
        best_author_mismatch: tuple[str, list[str], float] | None = None

        for item in items:
            info = item.get("volumeInfo", {})
            info_title = info.get("title", "") or ""
            info_authors = [
                str(author) for author in (info.get("authors") or [])
                if isinstance(author, str) and author.strip()
            ]

            title_score = (
                self._title_score(expected_title, info_title)
                if expected_title else 1.0
            )
            author_match = (
                self._authors_match(info_authors, expected_author)
                if expected_author else True
            )

            if not author_match:
                if best_author_mismatch is None or title_score > best_author_mismatch[2]:
                    best_author_mismatch = (info_title, info_authors, title_score)
                continue

            if best_match is None or title_score > best_match[4]:
                best_match = (item, info, info_title, info_authors, title_score)

        if best_match is None:
            if best_author_mismatch and expected_author:
                logger.warning(
                    "Google Books response: book='%s' author='%s' lookup=%s status=200 candidates=%d selected_title='%s' selected_author='%s' result='author_mismatch'",
                    (book_context or expected_title or query)[:80],
                    expected_author[:80],
                    lookup_type,
                    len(items),
                    best_author_mismatch[0][:80],
                    ", ".join(best_author_mismatch[1])[:80],
                )
            else:
                logger.warning(
                    "Google Books response: book='%s' author='%s' lookup=%s status=200 candidates=%d result='no_result'",
                    (book_context or expected_title or query)[:80],
                    (expected_author or "")[:80],
                    lookup_type,
                    len(items),
                )
            return GoogleLookupResult(
                book=None,
                reason="author_mismatch" if best_author_mismatch and expected_author else "no_result",
            )

        item, info, info_title, _info_authors, title_score = best_match
        if expected_title and title_score < TITLE_MATCH_THRESHOLD:
            logger.warning(
                "Google Books response: book='%s' author='%s' lookup=%s status=200 candidates=%d selected_title='%s' result='title_mismatch' score=%.3f",
                expected_title[:80],
                (expected_author or "")[:80],
                lookup_type,
                len(items),
                info_title[:80],
                title_score,
            )
            return GoogleLookupResult(book=None, reason="title_mismatch")

        google_id = item.get("id")
        cover_url = self._pick_cover_url(info)
        isbn_10, isbn_13 = self._extract_isbns(info)
        logger.info(
            "Google Books response: book='%s' author='%s' lookup=%s status=200 candidates=%d selected_id='%s' selected_title='%s' published='%s' result='matched'",
            (book_context or expected_title or query)[:80],
            (expected_author or "")[:80],
            lookup_type,
            len(items),
            str(google_id or "")[:80],
            info_title[:80],
            str(info.get("publishedDate") or "")[:40],
        )

        return GoogleLookupResult(
            book=GBook(
                title=info_title,
                published_date=info.get("publishedDate"),
                cover_url=cover_url,
                google_id=google_id,
                isbn_10=isbn_10,
                isbn_13=isbn_13,
                language=info.get("language"),
            ),
            reason="matched",
        )
