"""Image search via Bing for finding high-resolution book covers."""

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


@dataclass
class ImageResult:
    url: str
    thumbnail_url: str
    width: int | None
    height: int | None
    title: str
    source_url: str


async def search_book_covers(
    title: str,
    author: str,
    max_results: int = 10,
) -> list[ImageResult]:
    """Search Bing Images for book cover art.

    Returns a list of image results with full-resolution URLs and Bing
    thumbnail URLs (which load reliably without hotlink issues).
    """
    query = f"{title} {author} book cover"
    logger.info("Image search: query='%s'", query[:120])

    params = {
        "q": query,
        "qft": "+filterui:imagesize-large",
        "form": "IRFLTR",
        "first": "1",
    }

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers=HEADERS,
        ) as client:
            resp = await client.get(BING_URL, params=params)
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        logger.warning("Image search failed: %s", e)
        return []

    # Bing embeds image metadata in HTML-encoded JSON inside m="" attributes
    m_attrs = re.findall(r'm="([^"]+)"', html)

    results: list[ImageResult] = []
    seen_urls: set[str] = set()

    for m_raw in m_attrs:
        try:
            m_json = json.loads(unescape(m_raw))
        except (json.JSONDecodeError, TypeError):
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
        "Image search: query='%s' raw=%d final=%d",
        query[:80],
        len(m_attrs),
        len(results),
    )
    return results
