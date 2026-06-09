import re
import unicodedata


_LEADING_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)
_DIGIT_RE = re.compile(r"\d+")


def title_sort_key(title: str | None) -> str:
    """Return a stable catalog-style key for title ordering."""
    text = _strip_edge_non_alnum((title or "").strip())
    text = _LEADING_ARTICLE_RE.sub("", text)
    text = unicodedata.normalize("NFKD", text).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"\s+", " ", text).strip()
    return _DIGIT_RE.sub(lambda match: match.group(0).zfill(12), text)


def effective_title_sort_key(title: str | None, manual_title: str | None = None) -> str:
    override = _clean_manual_value(manual_title)
    return title_sort_key(override or title)


def _clean_manual_value(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _strip_edge_non_alnum(value: str) -> str:
    start = 0
    end = len(value)
    for index, char in enumerate(value):
        if char.isalnum():
            start = index
            break
    else:
        return ""
    for index in range(len(value) - 1, start - 1, -1):
        if value[index].isalnum():
            end = index + 1
            break
    return value[start:end]
