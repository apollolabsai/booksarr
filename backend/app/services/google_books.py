"""Google Books API client for metadata lookups."""
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger("booksarr.google")

VOLUMES_URL = "https://www.googleapis.com/books/v1/volumes"


@dataclass
class GBook:
    title: str
    published_date: str | None = None
    cover_url: str | None = None
    google_id: str | None = None

    @property
    def publish_year(self) -> int | None:
        if self.published_date and len(self.published_date) >= 4:
            try:
                return int(self.published_date[:4])
            except ValueError:
                return None
        return None


class GoogleBooksClient:
    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None

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
        """Search by ISBN — most precise lookup."""
        clean = isbn.replace("-", "").replace(" ", "")
        return await self._search(f"isbn:{clean}")

    async def search_by_title_author(self, title: str, author: str) -> GBook | None:
        """Search by title and author name."""
        query = f"intitle:{title}"
        if author:
            query += f"+inauthor:{author}"
        return await self._search(query)

    async def _search(self, query: str) -> GBook | None:
        client = await self._get_client()
        try:
            resp = await client.get(
                VOLUMES_URL,
                params={"q": query, "maxResults": 1, "key": self._api_key},
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException:
            logger.warning("Google Books timeout: %s", query[:80])
            return None
        except httpx.HTTPStatusError as e:
            logger.warning("Google Books HTTP %d: %s", e.response.status_code, query[:80])
            return None
        except Exception as e:
            logger.warning("Google Books request failed '%s': %s", query[:80], e)
            return None

        items = data.get("items", [])
        if not items:
            return None

        item = items[0]
        info = item.get("volumeInfo", {})

        # Build high-res cover URL using zoom=0 for full size
        google_id = item.get("id")
        cover_url = None
        if google_id:
            cover_url = (
                f"https://books.google.com/books/content"
                f"?id={google_id}&printsec=frontcover&img=1&zoom=0"
            )

        return GBook(
            title=info.get("title", ""),
            published_date=info.get("publishedDate"),
            cover_url=cover_url,
            google_id=google_id,
        )
