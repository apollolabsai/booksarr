from dataclasses import dataclass

from backend.app.models import Author
from backend.app.services.image_cache import cache_author_image, get_cached_cover_dimensions
from backend.app.services.wikimedia import WikimediaClient, WikimediaAuthor


@dataclass
class AuthorPortraitCandidate:
    key: str
    source: str
    label: str
    image_url: str | None
    cached_path: str | None
    page_url: str | None = None
    creator: str | None = None
    license: str | None = None
    width: int | None = None
    height: int | None = None
    is_current: bool = False
    is_manual: bool = False

    @property
    def aspect_ratio(self) -> float | None:
        if not self.width or not self.height or self.height <= 0:
            return None
        return self.width / self.height


def _infer_author_image_source(author: Author) -> str:
    if author.manual_image_source:
        return author.manual_image_source

    normalized = (author.image_url or "").lower()
    if "openlibrary.org" in normalized:
        return "openlibrary"
    if "wikimedia.org" in normalized or "wikipedia.org" in normalized:
        return "wikimedia"
    if normalized:
        return "hardcover"
    return "unknown"


def _current_author_option(author: Author) -> AuthorPortraitCandidate | None:
    if not author.image_url and not author.image_cached_path:
        return None

    width = height = None
    if author.image_cached_path:
        dims = get_cached_cover_dimensions(author.image_cached_path)
        if dims:
            width, height = dims

    source = _infer_author_image_source(author)
    label_map = {
        "hardcover": "Current Hardcover Portrait",
        "openlibrary": "Current Open Library Portrait",
        "wikimedia": "Current Wikimedia Portrait",
    }

    return AuthorPortraitCandidate(
        key="current",
        source=source,
        label=label_map.get(source, "Current Portrait"),
        image_url=author.image_url,
        cached_path=author.image_cached_path,
        page_url=author.manual_image_page_url,
        width=width,
        height=height,
        is_current=True,
        is_manual=bool(author.manual_image_source and author.manual_image_url),
    )


def _wikimedia_candidate(index: int, candidate: WikimediaAuthor) -> AuthorPortraitCandidate:
    return AuthorPortraitCandidate(
        key=f"wikimedia:{index}",
        source="wikimedia",
        label="Wikimedia",
        image_url=candidate.image_url,
        cached_path=None,
        page_url=candidate.page_url,
        width=candidate.width,
        height=candidate.height,
    )


async def get_author_portrait_options(author: Author) -> list[dict]:
    options: list[AuthorPortraitCandidate] = []
    seen_urls: set[str] = set()

    current_option = _current_author_option(author)
    if current_option:
        options.append(current_option)
        if current_option.image_url:
            seen_urls.add(current_option.image_url)

    wikimedia_client = WikimediaClient()
    try:
        wikimedia_candidates = await wikimedia_client.search_author_candidates(author.name, limit=3)
        for index, candidate in enumerate(wikimedia_candidates, start=1):
            if candidate.image_url in seen_urls:
                continue
            options.append(_wikimedia_candidate(index, candidate))
            seen_urls.add(candidate.image_url)
    finally:
        await wikimedia_client.close()

    return [
        {
            "key": option.key,
            "source": option.source,
            "label": option.label,
            "image_url": option.image_url,
            "cached_path": option.cached_path,
            "page_url": option.page_url,
            "creator": option.creator,
            "license": option.license,
            "width": option.width,
            "height": option.height,
            "aspect_ratio": option.aspect_ratio,
            "is_current": option.is_current,
            "is_manual": option.is_manual,
        }
        for option in options
    ]


async def set_author_portrait_selection(
    author: Author,
    *,
    source: str,
    image_url: str,
    page_url: str | None = None,
) -> bool:
    if not image_url.startswith(("http://", "https://")):
        return False

    cached = await cache_author_image(author.id, image_url, source=source)
    if not cached:
        return False

    author.manual_image_source = source
    author.manual_image_url = image_url
    author.manual_image_page_url = page_url
    author.image_url = image_url
    author.image_cached_path = cached
    return True
