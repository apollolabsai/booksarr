import logging
from dataclasses import dataclass, field

import httpx
from backend.app.utils.api_usage import record_api_call

logger = logging.getLogger("booksarr.openlibrary")

SEARCH_URL = "https://openlibrary.org/search.json"
COVER_URL = "https://covers.openlibrary.org/b/id"


@dataclass
class OLBook:
    title: str
    first_publish_year: int | None = None
    cover_id: int | None = None
    cover_edition_key: str = ""
    edition_count: int = 0
    isbn_list: list[str] = field(default_factory=list)

    @property
    def cover_url_large(self) -> str:
        if self.cover_id:
            return f"{COVER_URL}/{self.cover_id}-L.jpg"
        return ""

    @property
    def cover_url_medium(self) -> str:
        if self.cover_id:
            return f"{COVER_URL}/{self.cover_id}-M.jpg"
        return ""


@dataclass
class OpenLibraryLookupResult:
    book: OLBook | None
    reason: str


class OpenLibraryClient:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=15.0,
                headers={"User-Agent": "Booksarr/0.1.0 (ebook library manager)"},
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def search_book(self, title: str, author: str) -> OLBook | None:
        return (await self.search_book_with_result(title, author)).book

    async def search_book_with_result(self, title: str, author: str) -> OpenLibraryLookupResult:
        """Search Open Library for a book by title and author."""
        client = await self._get_client()
        try:
            await record_api_call("openlibrary")
            resp = await client.get(
                SEARCH_URL,
                params={
                    "title": title,
                    "author": author,
                    "limit": 1,
                    "fields": "title,first_publish_year,cover_i,cover_edition_key,edition_count,isbn",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.debug("Open Library search failed for '%s': %s", title, e)
            return OpenLibraryLookupResult(book=None, reason="http_error")
        except httpx.RequestError as e:
            logger.debug("Open Library search failed for '%s': %s", title, e)
            return OpenLibraryLookupResult(book=None, reason="request_error")
        except ValueError as e:
            logger.debug("Open Library search failed for '%s': %s", title, e)
            return OpenLibraryLookupResult(book=None, reason="invalid_json")

        docs = data.get("docs", [])
        if not docs:
            return OpenLibraryLookupResult(book=None, reason="no_result")

        doc = docs[0]
        return OpenLibraryLookupResult(
            book=OLBook(
                title=doc.get("title", ""),
                first_publish_year=doc.get("first_publish_year"),
                cover_id=doc.get("cover_i"),
                cover_edition_key=doc.get("cover_edition_key", ""),
                edition_count=doc.get("edition_count", 0),
                isbn_list=doc.get("isbn", []),
            ),
            reason="matched",
        )

    async def search_book_by_isbn(self, isbn: str) -> OLBook | None:
        return (await self.search_book_by_isbn_with_result(isbn)).book

    async def search_book_by_isbn_with_result(self, isbn: str) -> OpenLibraryLookupResult:
        """Search Open Library by ISBN."""
        client = await self._get_client()
        try:
            await record_api_call("openlibrary")
            resp = await client.get(
                SEARCH_URL,
                params={
                    "isbn": isbn,
                    "limit": 1,
                    "fields": "title,first_publish_year,cover_i,cover_edition_key,edition_count,isbn",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.debug("Open Library ISBN search failed for '%s': %s", isbn, e)
            return OpenLibraryLookupResult(book=None, reason="http_error")
        except httpx.RequestError as e:
            logger.debug("Open Library ISBN search failed for '%s': %s", isbn, e)
            return OpenLibraryLookupResult(book=None, reason="request_error")
        except ValueError as e:
            logger.debug("Open Library ISBN search failed for '%s': %s", isbn, e)
            return OpenLibraryLookupResult(book=None, reason="invalid_json")

        docs = data.get("docs", [])
        if not docs:
            return OpenLibraryLookupResult(book=None, reason="no_result")

        doc = docs[0]
        return OpenLibraryLookupResult(
            book=OLBook(
                title=doc.get("title", ""),
                first_publish_year=doc.get("first_publish_year"),
                cover_id=doc.get("cover_i"),
                cover_edition_key=doc.get("cover_edition_key", ""),
                edition_count=doc.get("edition_count", 0),
                isbn_list=doc.get("isbn", []),
            ),
            reason="matched",
        )
