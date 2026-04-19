import re


def clean_author_name(author: str) -> str:
    cleaned = author.strip()
    if "," in cleaned:
        parts = [part.strip() for part in cleaned.split(",") if part.strip()]
        if len(parts) == 2:
            cleaned = f"{parts[1]} {parts[0]}"
    cleaned = cleaned.rstrip(" ;,")
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_author_key(author: str | None) -> str:
    return clean_author_name(author or "").lower()
