import re

_AUTHOR_SUFFIXES = {
    "jr",
    "sr",
    "ii",
    "iii",
    "iv",
    "v",
    "esq",
    "md",
    "m.d",
    "phd",
    "ph.d",
}
_SORT_HONORIFICS = {
    "sir",
    "dame",
    "lord",
    "lady",
    "dr",
    "mr",
    "mrs",
    "ms",
    "rev",
    "prof",
}


def clean_author_name(author: str) -> str:
    cleaned = author.strip()
    if "," in cleaned:
        parts = [part.strip() for part in cleaned.split(",") if part.strip()]
        if len(parts) == 2 and not _is_author_suffix_chunk(parts[1]):
            cleaned = f"{parts[1]} {parts[0]}"
    cleaned = cleaned.rstrip(" ;,")
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_author_key(author: str | None) -> str:
    return clean_author_name(author or "").lower()


def author_sort_key(name: str | None) -> str:
    """Return a display-name sort key that favors surname ordering."""
    if not name:
        return ""

    text = re.sub(r"\s+", " ", name.strip())
    if not text:
        return ""

    if " & " in text:
        return author_sort_key(text.split(" & ", 1)[0])

    if "," in text:
        chunks = [chunk.strip() for chunk in text.split(",") if chunk.strip()]
        stripped_suffix = False
        while len(chunks) > 1 and _is_author_suffix_chunk(chunks[-1]):
            chunks = chunks[:-1]
            stripped_suffix = True
        if stripped_suffix and len(chunks) == 1:
            return author_sort_key(chunks[0])
        return ", ".join(chunks).lower()

    parts = text.split()
    while len(parts) > 1 and _is_author_suffix_chunk(parts[-1]):
        parts = parts[:-1]
    while len(parts) > 1 and _normalized_name_token(parts[0]) in _SORT_HONORIFICS:
        parts = parts[1:]

    if not parts:
        return text.lower()

    surname = parts[-1].lower()
    rest = " ".join(parts[:-1]).lower()
    return f"{surname}, {rest}" if rest else surname


def _normalized_name_token(value: str) -> str:
    return value.lower().rstrip(".")


def _is_author_suffix_chunk(value: str) -> bool:
    tokens = [_normalized_name_token(token) for token in value.split() if token.strip()]
    return bool(tokens) and all(token in _AUTHOR_SUFFIXES for token in tokens)
