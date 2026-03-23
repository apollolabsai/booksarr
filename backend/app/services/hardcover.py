import json
import logging
from dataclasses import dataclass, field

import httpx

from backend.app.utils.rate_limiter import RateLimiter
from backend.app.utils.api_usage import record_api_call

logger = logging.getLogger("booksarr.hardcover")

API_URL = "https://api.hardcover.app/v1/graphql"


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
        self.rate_limiter = RateLimiter(max_tokens=55, refill_rate=1.0)
        self._client: httpx.AsyncClient | None = None

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

    async def _query(self, query: str, variables: dict | None = None) -> dict:
        await self.rate_limiter.acquire()
        client = await self._get_client()
        payload: dict = {"query": query}
        if variables:
            payload["variables"] = variables

        # Extract operation name for logging
        op_name = "unknown"
        if variables:
            op_name = str(list(variables.values())[:1])

        logger.debug("GraphQL request: vars=%s", op_name)
        try:
            await record_api_call("hardcover")
            resp = await client.post(API_URL, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error("Hardcover API HTTP error %d for %s", e.response.status_code, op_name)
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
