import logging
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from backend.app.utils.api_usage import record_api_call

logger = logging.getLogger("booksarr.wikimedia")

SEARCH_URL = "https://en.wikipedia.org/w/api.php"
SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary"


def _normalize_name(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _title_score(name: str, title: str) -> int:
    normalized_name = _normalize_name(name)
    normalized_title = _normalize_name(title)
    if not normalized_name or not normalized_title:
        return 0
    if normalized_title == normalized_name:
        return 100
    if normalized_title.startswith(f"{normalized_name} ("):
        return 95
    if normalized_name in normalized_title:
        return 80
    return 0


@dataclass
class WikimediaAuthor:
    title: str
    image_url: str
    page_url: str = ""


@dataclass
class WikimediaAuthorLookupResult:
    author: WikimediaAuthor | None
    reason: str


class WikimediaClient:
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

    async def search_author(self, name: str) -> WikimediaAuthor | None:
        return (await self.search_author_with_result(name)).author

    async def search_author_with_result(self, name: str) -> WikimediaAuthorLookupResult:
        exact_result = await self._fetch_summary_for_title(name, expected_name=name)
        if exact_result.author:
            return exact_result

        search_titles = await self._search_author_candidates(name)
        if not search_titles:
            return WikimediaAuthorLookupResult(author=None, reason=exact_result.reason)

        best_reason = exact_result.reason
        for title in search_titles:
            summary_result = await self._fetch_summary_for_title(title, expected_name=name)
            if summary_result.author:
                return summary_result
            if summary_result.reason != "no_result":
                best_reason = summary_result.reason

        return WikimediaAuthorLookupResult(author=None, reason=best_reason)

    async def _search_author_candidates(self, name: str) -> list[str] | None:
        client = await self._get_client()
        try:
            await record_api_call("wikimedia")
            resp = await client.get(
                SEARCH_URL,
                params={
                    "action": "query",
                    "format": "json",
                    "list": "search",
                    "srsearch": f"\"{name}\"",
                    "srlimit": 5,
                    "srnamespace": 0,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPStatusError, httpx.RequestError, ValueError) as e:
            logger.debug("Wikimedia author search failed for '%s': %s", name, e)
            return None

        matches: list[tuple[int, str]] = []
        for item in data.get("query", {}).get("search", []):
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            score = _title_score(name, title)
            if score <= 0:
                continue
            matches.append((score, title))

        if not matches:
            return None

        matches.sort(key=lambda item: (-item[0], item[1]))
        return [title for _, title in matches]

    async def _fetch_summary_for_title(
        self,
        title: str,
        *,
        expected_name: str,
    ) -> WikimediaAuthorLookupResult:
        if _title_score(expected_name, title) <= 0:
            return WikimediaAuthorLookupResult(author=None, reason="title_mismatch")

        client = await self._get_client()
        try:
            await record_api_call("wikimedia")
            resp = await client.get(f"{SUMMARY_URL}/{quote(title, safe='')}")
            if resp.status_code == 404:
                return WikimediaAuthorLookupResult(author=None, reason="no_result")
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.debug("Wikimedia summary failed for '%s': %s", title, e)
            return WikimediaAuthorLookupResult(author=None, reason="http_error")
        except httpx.RequestError as e:
            logger.debug("Wikimedia summary failed for '%s': %s", title, e)
            return WikimediaAuthorLookupResult(author=None, reason="request_error")
        except ValueError as e:
            logger.debug("Wikimedia summary failed for '%s': %s", title, e)
            return WikimediaAuthorLookupResult(author=None, reason="invalid_json")

        page_type = str(data.get("type") or "").strip().lower()
        if page_type == "disambiguation":
            return WikimediaAuthorLookupResult(author=None, reason="disambiguation")

        summary_title = str(data.get("title") or title).strip()
        if _title_score(expected_name, summary_title) <= 0:
            return WikimediaAuthorLookupResult(author=None, reason="title_mismatch")

        original_image = data.get("originalimage") or {}
        thumbnail = data.get("thumbnail") or {}
        image_url = str(original_image.get("source") or thumbnail.get("source") or "").strip()
        if not image_url:
            return WikimediaAuthorLookupResult(author=None, reason="no_image")

        page_url = (
            data.get("content_urls", {})
            .get("desktop", {})
            .get("page", "")
        )
        return WikimediaAuthorLookupResult(
            author=WikimediaAuthor(
                title=summary_title,
                image_url=image_url,
                page_url=str(page_url or ""),
            ),
            reason="matched",
        )
