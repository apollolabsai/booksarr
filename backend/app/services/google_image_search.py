"""Image search via Bing for finding high-resolution book covers and portraits."""

import json
import logging
import re
from dataclasses import dataclass
from html import unescape

import httpx

logger = logging.getLogger("booksarr.image_search")

BING_URL = "https://www.bing.com/images/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Shared client — keeps a persistent connection to Bing alive across requests
# so each search reuses the existing TCP connection rather than opening a new one.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers=HEADERS,
            transport=httpx.AsyncHTTPTransport(local_address="0.0.0.0"),
        )
    return _client


@dataclass
class ImageResult:
    url: str
    thumbnail_url: str
    width: int | None
    height: int | None
    title: str
    source_url: str


async def _search_images(query: str, max_results: int = 10) -> list[ImageResult]:
    params = {
        "q": query,
        "qft": "+filterui:imagesize-large",
        "form": "IRFLTR",
        "first": "1",
    }

    logger.debug("Image search: query='%s' url=%s params=%s", query[:120], BING_URL, params)

    try:
        resp = await _get_client().get(BING_URL, params=params)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        logger.warning(
            "Image search HTTP error for query '%s': %r",
            query[:120], e, exc_info=True,
        )
        return []

    html_bytes = len(html.encode())
    content_type = resp.headers.get("content-type", "unknown")
    final_url = str(resp.url)
    logger.debug(
        "Image search response: status=%d content_type=%s size=%d final_url=%s",
        resp.status_code, content_type, html_bytes, final_url,
    )

    # Bing embeds image metadata in HTML-encoded JSON inside m="" attributes
    m_attrs = re.findall(r'm="([^"]+)"', html)
    logger.debug("Image search: found %d raw m= attributes in HTML", len(m_attrs))

    if not m_attrs:
        # Dump a snippet of the HTML to help diagnose captcha/redirect pages
        snippet = html[:500].replace("\n", " ").replace("\r", "")
        logger.warning(
            "Image search: 0 m= attributes found for query='%s' — "
            "status=%d size=%d content_type=%s html_start=%r",
            query[:120], resp.status_code, html_bytes, content_type, snippet,
        )

    results: list[ImageResult] = []
    seen_urls: set[str] = set()
    parse_errors = 0

    for m_raw in m_attrs:
        try:
            m_json = json.loads(unescape(m_raw))
        except (json.JSONDecodeError, TypeError):
            parse_errors += 1
            continue

        if not isinstance(m_json, dict):
            continue

        murl = m_json.get("murl", "")
        turl = m_json.get("turl", "")
        if not murl or not turl:
            continue

        if murl in seen_urls:
            continue
        seen_urls.add(murl)

        results.append(ImageResult(
            url=murl,
            thumbnail_url=turl,
            width=None,
            height=None,
            title=m_json.get("t", ""),
            source_url=m_json.get("purl", ""),
        ))

        if len(results) >= max_results:
            break

    logger.info(
        "Image search: query='%s' status=%d html=%dB m_attrs=%d parse_errors=%d final=%d",
        query[:80],
        resp.status_code,
        html_bytes,
        len(m_attrs),
        parse_errors,
        len(results),
    )
    return results


async def search_book_covers(
    title: str,
    author: str,
    max_results: int = 10,
) -> list[ImageResult]:
    """Search Bing Images for book cover art."""
    query = f"{title} {author} book cover".strip()
    return await _search_images(query, max_results=max_results)


async def search_author_portraits(
    author_name: str,
    max_results: int = 10,
) -> list[ImageResult]:
    """Search Bing Images for author portraits or headshots."""
    query = f"{author_name} author portrait".strip()
    return await _search_images(query, max_results=max_results)
