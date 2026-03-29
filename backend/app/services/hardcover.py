import asyncio
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime

import httpx

from backend.app.utils.api_usage import record_api_call

logger = logging.getLogger("booksarr.hardcover")

API_URL = "https://api.hardcover.app/v1/graphql"
MIN_REQUEST_INTERVAL_SECONDS = 1.35
REQUEST_JITTER_MIN_SECONDS = 0.05
REQUEST_JITTER_MAX_SECONDS = 0.15
THROTTLE_RETRY_MIN_SECONDS = 30.0
THROTTLE_RETRY_FALLBACK_SECONDS = 60.0


class HardcoverLookupError(RuntimeError):
    def __init__(self, reason: str, message: str):
        self.reason = reason
        super().__init__(message)


@dataclass
class HCAuthor:
    id: int
    name: str
    slug: str = ""
    bio: str = ""
    image_url: str = ""
    books_count: int = 0


@dataclass
class HCSeriesRef:
    id: int
    name: str
    position: float | None = None


@dataclass
class HCBook:
    id: int
    title: str
    slug: str = ""
    description: str = ""
    release_date: str = ""
    image_url: str = ""
    rating: float = 0.0
    pages: int = 0
    language: str = ""
    is_canonical: bool = True
    users_count: int = 0
    compilation: bool | None = None
    book_category_id: int | None = None
    literary_type_id: int | None = None
    state: str = ""
    isbn_10: str | None = None
    isbn_13: str | None = None
    tags: list[str] = field(default_factory=list)
    series_refs: list[HCSeriesRef] = field(default_factory=list)


class HardcoverClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None
        self._pacing_lock = asyncio.Lock()
        self._next_request_at = 0.0
        self._throttled_until = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _wait_for_request_slot(self):
        async with self._pacing_lock:
            now = time.monotonic()
            wait_until = max(self._next_request_at, self._throttled_until)
            if wait_until > now:
                delay = wait_until - now
                logger.info("Hardcover pacing: sleeping %.2fs before next request", delay)
                await asyncio.sleep(delay)
                now = time.monotonic()

            self._next_request_at = (
                now
                + MIN_REQUEST_INTERVAL_SECONDS
                + random.uniform(REQUEST_JITTER_MIN_SECONDS, REQUEST_JITTER_MAX_SECONDS)
            )

    def _apply_throttle_cooldown(self, seconds: float):
        self._throttled_until = max(self._throttled_until, time.monotonic() + seconds)

    def _retry_after_seconds(self, response: httpx.Response) -> float:
        raw_value = response.headers.get("Retry-After")
        if not raw_value:
            return THROTTLE_RETRY_FALLBACK_SECONDS

        try:
            return max(float(raw_value), THROTTLE_RETRY_MIN_SECONDS)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(raw_value)
                seconds = retry_at.timestamp() - time.time()
                return max(seconds, THROTTLE_RETRY_MIN_SECONDS)
            except (TypeError, ValueError, OverflowError):
                return THROTTLE_RETRY_FALLBACK_SECONDS

    async def _query(self, query: str, variables: dict | None = None) -> dict:
        client = await self._get_client()
        payload: dict = {"query": query}
        if variables:
            payload["variables"] = variables

        # Extract operation name for logging
        op_name = "unknown"
        if variables:
            op_name = str(list(variables.values())[:1])

        logger.debug("GraphQL request: vars=%s", op_name)
        for attempt in (1, 2):
            try:
                await self._wait_for_request_slot()
                await record_api_call("hardcover")
                resp = await client.post(API_URL, json=payload)
                resp.raise_for_status()
                break
            except httpx.HTTPStatusError as e:
                logger.error("Hardcover API HTTP error %d for %s", e.response.status_code, op_name)
                if e.response.status_code == 429 and attempt == 1:
                    cooldown_seconds = self._retry_after_seconds(e.response)
                    self._apply_throttle_cooldown(cooldown_seconds)
                    logger.warning(
                        "Hardcover throttled for %s; sleeping %.0fs before one retry",
                        op_name,
                        cooldown_seconds,
                    )
                    continue
                if e.response.status_code == 429:
                    raise HardcoverLookupError("throttled", "HTTP 429") from e
                if e.response.status_code == 401:
                    raise HardcoverLookupError("unauthorized", "HTTP 401") from e
                raise HardcoverLookupError("http_error", f"HTTP {e.response.status_code}") from e
            except httpx.RequestError as e:
                logger.error("Hardcover API request failed for %s: %s", op_name, e)
                raise HardcoverLookupError("request_error", str(e)) from e

        try:
            data = resp.json()
        except ValueError as e:
            logger.error("Hardcover API invalid JSON for %s", op_name)
            raise HardcoverLookupError("invalid_json", "invalid JSON") from e

        if "errors" in data:
            logger.error("GraphQL errors for %s: %s", op_name, data["errors"])
            raise HardcoverLookupError(
                "graphql_error",
                data["errors"][0].get("message", "Unknown"),
            )

        logger.debug("GraphQL response OK for %s", op_name)
        return data.get("data", {})

    async def search_author(self, name: str) -> HCAuthor | None:
        query = """
        query($name: String!) {
          authors(where: {name: {_eq: $name}}, order_by: {users_count: desc}, limit: 1) {
            id name slug bio cached_image books_count users_count
          }
        }
        """
        logger.info("Searching for author: %s", name)
        data = await self._query(query, {"name": name})
        authors = data.get("authors", [])
        if not authors:
            logger.warning("No Hardcover match found for author: %s", name)
            return None

        a = authors[0]
        image_url = ""
        cached_image = a.get("cached_image")
        if cached_image and isinstance(cached_image, dict):
            image_url = cached_image.get("url", "")

        result = HCAuthor(
            id=a["id"],
            name=a["name"],
            slug=a.get("slug", ""),
            bio=a.get("bio", "") or "",
            image_url=image_url,
            books_count=a.get("books_count", 0),
        )
        logger.info("Found author: %s (HC ID: %d, %d books)", result.name, result.id, result.books_count)
        return result

    async def get_author(self, author_id: int) -> HCAuthor | None:
        query = """
        query($id: Int!) {
          authors(where: {id: {_eq: $id}}, limit: 1) {
            id name slug bio cached_image books_count users_count
          }
        }
        """
        logger.info("Fetching Hardcover author HC ID: %d", author_id)
        data = await self._query(query, {"id": author_id})
        authors = data.get("authors", [])
        if not authors:
            return None

        row = authors[0]
        image_url = ""
        cached_image = row.get("cached_image")
        if cached_image and isinstance(cached_image, dict):
            image_url = cached_image.get("url", "")

        return HCAuthor(
            id=row["id"],
            name=row["name"],
            slug=row.get("slug", ""),
            bio=row.get("bio", "") or "",
            image_url=image_url,
            books_count=row.get("books_count", 0),
        )

    async def search_author_candidates(self, name: str, limit: int = 10) -> list[HCAuthor]:
        normalized_query = _normalize_author_query(name)
        if not normalized_query:
            return []

        query = """
        query($query: String!, $per_page: Int!) {
          search(query: $query, query_type: "author", per_page: $per_page, page: 1) {
            results
          }
        }
        """
        logger.info("Searching Hardcover author candidates for: %s", name)
        data = await self._query(query, {"query": name.strip(), "per_page": limit * 3})
        results = data.get("search", {}).get("results", {}) or {}
        hits = results.get("hits", []) or []
        if not hits:
            logger.warning("No Hardcover author candidates found for: %s", name)
            return []

        candidates: list[HCAuthor] = []
        for hit in hits:
            document = hit.get("document", {}) if isinstance(hit, dict) else {}
            try:
                candidate_id = int(document.get("id"))
            except (TypeError, ValueError):
                continue
            name_value = str(document.get("name") or "").strip()
            if not name_value:
                continue
            image = document.get("image") if isinstance(document.get("image"), dict) else {}
            candidates.append(HCAuthor(
                id=candidate_id,
                name=name_value,
                slug=str(document.get("slug") or "").strip(),
                bio="",
                image_url=str(image.get("url") or "").strip(),
                books_count=int(document.get("books_count") or 0),
            ))

        if not candidates:
            logger.warning("Hardcover author search returned hits but no usable author documents for: %s", name)
            return []

        scored: list[tuple[tuple[float, int], HCAuthor]] = []
        query_tokens = set(normalized_query.split())
        for candidate in candidates:
            normalized_name = _normalize_author_query(candidate.name)
            exact = 1.0 if normalized_name == normalized_query else 0.0
            token_overlap = (
                len(query_tokens & set(normalized_name.split())) / max(len(query_tokens), 1)
                if normalized_name else 0.0
            )
            similarity = SequenceMatcher(None, normalized_query, normalized_name).ratio()
            prefix_bonus = 0.5 if normalized_name.startswith(normalized_query) else 0.0
            score = exact * 10.0 + token_overlap * 2.0 + similarity + prefix_bonus
            scored.append(((score, candidate.books_count), candidate))

        scored.sort(key=lambda item: item[0], reverse=True)
        results = [candidate for _, candidate in scored[:limit]]
        logger.info(
            "Found %d Hardcover author candidate(s) for %s: %s",
            len(results),
            name,
            [candidate.name for candidate in results],
        )
        return results

    async def get_author_books(self, author_id: int) -> list[HCBook]:
        query = """
        query($author_id: Int!) {
          books(
            where: {contributions: {author_id: {_eq: $author_id}}}
            order_by: {users_count: desc}
          ) {
            id title slug description release_date canonical_id
            compilation book_category_id literary_type_id state
            image { url }
            default_cover_edition {
              language { code2 }
              isbn_10
              isbn_13
            }
            cached_contributors
            cached_tags rating pages users_count
            book_series {
              position
              series { id name }
            }
          }
        }
        """
        logger.info("Fetching books for author HC ID: %d", author_id)
        data = await self._query(query, {"author_id": author_id})
        books_data = data.get("books", [])
        logger.info("Retrieved %d books for author HC ID: %d", len(books_data), author_id)

        return [self._parse_hc_book(b) for b in books_data]

    async def get_book(self, book_id: int) -> HCBook | None:
        query = """
        query($book_id: Int!) {
          books(where: {id: {_eq: $book_id}}, limit: 1) {
            id title slug description release_date canonical_id
            compilation book_category_id literary_type_id state
            image { url }
            default_cover_edition {
              language { code2 }
              isbn_10
              isbn_13
            }
            cached_contributors
            cached_tags rating pages users_count
            book_series {
              position
              series { id name }
            }
          }
        }
        """
        logger.info("Fetching Hardcover metadata for book HC ID: %d", book_id)
        data = await self._query(query, {"book_id": book_id})
        books_data = data.get("books", [])
        if not books_data:
            return None
        return self._parse_hc_book(books_data[0])

    def _parse_hc_book(self, b: dict) -> HCBook:
        image_url = ""
        img = b.get("image")
        if img and isinstance(img, dict):
            image_url = img.get("url", "")

        tags = []
        cached_tags = b.get("cached_tags")
        if cached_tags and isinstance(cached_tags, dict):
            for category_tags in cached_tags.values():
                if isinstance(category_tags, list):
                    for t in category_tags[:3]:
                        if isinstance(t, dict) and "tag" in t:
                            tags.append(t["tag"])

        series_refs = []
        for bs in b.get("book_series", []):
            s = bs.get("series", {})
            if s and s.get("id"):
                series_refs.append(HCSeriesRef(
                    id=s["id"],
                    name=s.get("name", ""),
                    position=bs.get("position"),
                ))

        language = ""
        dce = b.get("default_cover_edition")
        isbn_10 = None
        isbn_13 = None
        if dce and isinstance(dce, dict):
            lang_obj = dce.get("language")
            if lang_obj and isinstance(lang_obj, dict):
                language = lang_obj.get("code2", "")
            raw_isbn_10 = dce.get("isbn_10")
            raw_isbn_13 = dce.get("isbn_13")
            isbn_10 = str(raw_isbn_10).strip() if raw_isbn_10 else None
            isbn_13 = str(raw_isbn_13).strip() if raw_isbn_13 else None

        if not language:
            contributors = b.get("cached_contributors") or []
            for contrib in contributors:
                if isinstance(contrib, dict):
                    role = (contrib.get("contribution") or "").lower()
                    if "translat" in role:
                        language = "translated"
                        break

        return HCBook(
            id=b["id"],
            title=b["title"],
            slug=b.get("slug", ""),
            description=b.get("description", "") or "",
            release_date=b.get("release_date", "") or "",
            image_url=image_url,
            rating=b.get("rating", 0) or 0,
            pages=b.get("pages", 0) or 0,
            language=language,
            is_canonical=b.get("canonical_id") is None,
            users_count=b.get("users_count", 0) or 0,
            compilation=b.get("compilation"),
            book_category_id=b.get("book_category_id"),
            literary_type_id=b.get("literary_type_id"),
            state=b.get("state", "") or "",
            isbn_10=isbn_10,
            isbn_13=isbn_13,
            tags=tags,
            series_refs=series_refs,
        )

    async def search_book_by_isbn(self, isbn: str) -> int | None:
        """Search for a book by ISBN, return Hardcover book ID if found."""
        query = """
        query($isbn: String!) {
          search(query: $isbn, query_type: "books", per_page: 1, page: 1) {
            results
          }
        }
        """
        data = await self._query(query, {"isbn": isbn})
        results = data.get("search", {}).get("results", {})
        hits = results.get("hits", [])
        if hits:
            doc = hits[0].get("document", {})
            book_id = doc.get("id")
            if book_id:
                return int(book_id)
        return None


def _normalize_author_query(value: str) -> str:
    lowered = value.lower().strip()
    lowered = re.sub(r"[^\w\s]", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered
