import logging
import shutil
from pathlib import Path

import httpx

from backend.app.config import CONFIG_DIR

logger = logging.getLogger("booksarr.images")

CACHE_DIR = CONFIG_DIR / "cache"


async def download_image(url: str, category: str, filename: str) -> str | None:
    """Download an image and cache it. Returns relative cache path."""
    if not url:
        return None

    cache_path = CACHE_DIR / category / filename
    if cache_path.exists():
        logger.debug("Image already cached: %s/%s", category, filename)
        return f"cache/{category}/{filename}"

    try:
        logger.info("Downloading image: %s -> %s/%s", url[:80], category, filename)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(resp.content)
            logger.debug("Cached image: %s/%s (%d bytes)", category, filename, len(resp.content))
            return f"cache/{category}/{filename}"
    except httpx.HTTPStatusError as e:
        logger.warning("HTTP %d downloading image %s", e.response.status_code, url[:80])
        return None
    except Exception as e:
        logger.warning("Failed to download image %s: %s", url[:80], e)
        return None


async def cache_author_image(hardcover_id: int, url: str) -> str | None:
    ext = _get_ext(url)
    return await download_image(url, "authors", f"hc_{hardcover_id}{ext}")


async def cache_book_image(hardcover_id: int, url: str) -> str | None:
    ext = _get_ext(url)
    return await download_image(url, "books", f"hc_{hardcover_id}{ext}")


def cache_local_cover(local_cover_path: str, book_db_id: int) -> str | None:
    """Copy a local cover.jpg to the cache."""
    src = Path(local_cover_path)
    if not src.exists():
        return None

    dest = CACHE_DIR / "books" / f"local_{book_db_id}.jpg"
    if dest.exists():
        return f"cache/books/local_{book_db_id}.jpg"

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dest))
        return f"cache/books/local_{book_db_id}.jpg"
    except Exception as e:
        logger.warning("Failed to cache local cover %s: %s", local_cover_path, e)
        return None


def _get_ext(url: str) -> str:
    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
        if ext in url.lower():
            return ext
    return ".jpg"
