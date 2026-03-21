import logging
import shutil
from pathlib import Path

import httpx

from backend.app.config import CONFIG_DIR
from backend.app.utils.epub_cover import extract_cover, get_image_dimensions

logger = logging.getLogger("booksarr.images")

CACHE_DIR = CONFIG_DIR / "cache"

# Local covers smaller than this are considered thumbnails and skipped
MIN_COVER_BYTES = 20_000  # 20KB


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
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
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
    """Copy a local cover.jpg to the cache if it's high-res enough.

    Returns the cache path, or None if the file is missing or too small (thumbnail).
    """
    src = Path(local_cover_path)
    if not src.exists():
        return None

    # Skip thumbnails
    file_size = src.stat().st_size
    if file_size < MIN_COVER_BYTES:
        logger.debug("Skipping local cover %s — too small (%d bytes)", src.name, file_size)
        return None

    dest = CACHE_DIR / "books" / f"local_{book_db_id}.jpg"
    if dest.exists():
        return f"cache/books/local_{book_db_id}.jpg"

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dest))
        logger.debug("Cached local cover: %s (%d bytes)", dest.name, file_size)
        return f"cache/books/local_{book_db_id}.jpg"
    except Exception as e:
        logger.warning("Failed to cache local cover %s: %s", local_cover_path, e)
        return None


def cache_best_local_cover(
    local_cover_path: str | None,
    epub_path: Path | None,
    book_db_id: int,
    existing_cached_path: str | None = None,
) -> str | None:
    """Pick the best cover from local sources (cover.jpg + EPUB embedded).

    Compares by pixel count (width * height). If an existing cached cover is
    provided, only replaces it if a local source has higher resolution.
    Returns cache path or None if no improvement found.
    """
    candidates: list[tuple[bytes, str]] = []

    # Candidate 1: Local cover.jpg
    if local_cover_path:
        src = Path(local_cover_path)
        if src.exists() and src.stat().st_size >= MIN_COVER_BYTES:
            try:
                candidates.append((src.read_bytes(), "cover.jpg"))
            except Exception:
                pass

    # Candidate 2: EPUB embedded cover
    if epub_path and epub_path.exists():
        epub_data = extract_cover(epub_path)
        if epub_data and len(epub_data) >= MIN_COVER_BYTES:
            candidates.append((epub_data, "epub"))

    if not candidates:
        return None

    # Pick highest resolution among local sources
    best_data = None
    best_pixels = 0
    best_source = ""

    for data, source in candidates:
        dims = get_image_dimensions(data)
        pixels = (dims[0] * dims[1]) if dims else len(data)  # fallback to file size
        if pixels > best_pixels:
            best_data = data
            best_pixels = pixels
            best_source = source

    if not best_data:
        return None

    # If there's already a cached cover, only replace if local is better
    if existing_cached_path:
        existing_file = CACHE_DIR / existing_cached_path.removeprefix("cache/")
        if existing_file.exists():
            existing_data = existing_file.read_bytes()
            existing_dims = get_image_dimensions(existing_data)
            existing_pixels = (existing_dims[0] * existing_dims[1]) if existing_dims else len(existing_data)
            if existing_pixels >= best_pixels:
                return None  # existing is already as good or better

            existing_dims_str = f"{existing_dims[0]}x{existing_dims[1]}" if existing_dims else "?"
            best_dims = get_image_dimensions(best_data)
            best_dims_str = f"{best_dims[0]}x{best_dims[1]}" if best_dims else "?"
            logger.info(
                "Upgrading cover for book %d: %s (%s) -> %s (%s)",
                book_db_id, existing_cached_path, existing_dims_str,
                best_source, best_dims_str,
            )

    # Determine extension from image header
    ext = ".png" if best_data[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
    dest = CACHE_DIR / "books" / f"local_{book_db_id}{ext}"

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(best_data)
        dims = get_image_dimensions(best_data)
        dim_str = f"{dims[0]}x{dims[1]}" if dims else "?"
        logger.debug(
            "Cached best local cover for book %d: %s (%s, %d bytes)",
            book_db_id, best_source, dim_str, len(best_data),
        )
        return f"cache/books/local_{book_db_id}{ext}"
    except Exception as e:
        logger.warning("Failed to cache local cover for book %d: %s", book_db_id, e)
        return None


async def download_image_bytes(url: str) -> bytes | None:
    """Download an image and return raw bytes without caching."""
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            if len(resp.content) < 1000:
                return None
            return resp.content
    except httpx.HTTPStatusError as e:
        logger.warning("HTTP %d downloading %s", e.response.status_code, url[:80])
        return None
    except Exception as e:
        logger.warning("Failed to download %s: %s", url[:80], e)
        return None


def cache_cover_data(data: bytes, book_id: int, source: str = "remote") -> str | None:
    """Save raw image bytes to cache as cover_{book_id}.ext. Overwrites if exists."""
    if not data or len(data) < MIN_COVER_BYTES:
        return None
    ext = ".png" if data[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
    dest = CACHE_DIR / "books" / f"cover_{book_id}{ext}"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        dims = get_image_dimensions(data)
        dim_str = f"{dims[0]}x{dims[1]}" if dims else "?"
        logger.debug(
            "Cached %s cover for book %d: %s (%d bytes)",
            source, book_id, dim_str, len(data),
        )
        return f"cache/books/cover_{book_id}{ext}"
    except Exception as e:
        logger.warning("Failed to cache %s cover for book %d: %s", source, book_id, e)
        return None


def get_cached_cover_height(cached_path: str | None) -> int:
    """Read a cached cover and return its height in pixels. Returns 0 on error."""
    if not cached_path:
        return 0
    file_path = CACHE_DIR / cached_path.removeprefix("cache/")
    if not file_path.exists():
        return 0
    try:
        data = file_path.read_bytes()
        dims = get_image_dimensions(data)
        return dims[1] if dims else 0
    except Exception:
        return 0


def _get_ext(url: str) -> str:
    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
        if ext in url.lower():
            return ext
    return ".jpg"
