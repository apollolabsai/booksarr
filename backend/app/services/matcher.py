import re
import unicodedata


_SUBTITLE_DESCRIPTOR_RE = re.compile(r"^(a|an|the|book|volume|vol\.?)\b", re.IGNORECASE)


def normalize_title(title: str) -> str:
    """Normalize a book title for fuzzy matching."""
    t = title.lower().strip()
    # Remove HTML entities
    t = re.sub(r"&\w+;", " ", t)
    # Remove common subtitle patterns
    for suffix in ["a novel", "a thriller", "a legal thriller", "stories", "a memoir"]:
        t = re.sub(rf"\s*{re.escape(suffix)}\s*$", "", t)
    # Remove leading articles
    t = re.sub(r"^(the|a|an)\s+", "", t)
    # Normalize unicode
    t = unicodedata.normalize("NFKD", t)
    # Remove punctuation except spaces
    t = re.sub(r"[^\w\s]", "", t)
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _title_variants(title: str) -> set[str]:
    """Return normalized title variants for exact and series-prefixed matching."""
    raw = title.strip()
    variants = {normalize_title(raw)}

    if ":" in raw:
        left, right = raw.split(":", 1)
        variants.add(normalize_title(left))
        if not _SUBTITLE_DESCRIPTOR_RE.match(right.strip()):
            variants.add(normalize_title(right))

    if " - " in raw:
        parts = [part.strip() for part in raw.split(" - ") if part.strip()]
        if len(parts) >= 2:
            variants.add(normalize_title(parts[-1]))

    return {variant for variant in variants if variant}


def titles_match(local_title: str, hc_title: str) -> bool:
    """Check if two titles match using normalization and similarity."""
    local_variants = _title_variants(local_title)
    hc_variants = _title_variants(hc_title)

    if not local_variants or not hc_variants:
        return False

    for norm_local in local_variants:
        for norm_hc in hc_variants:
            # Exact match after normalization
            if norm_local == norm_hc:
                return True

            # Check if one contains the other (only if lengths are similar)
            shorter = min(len(norm_local), len(norm_hc))
            longer = max(len(norm_local), len(norm_hc))
            if shorter > 0 and shorter / longer >= 0.6:
                if norm_local in norm_hc or norm_hc in norm_local:
                    return True

            # Simple similarity: shared word ratio
            local_words = set(norm_local.split())
            hc_words = set(norm_hc.split())
            if not local_words or not hc_words:
                continue

            intersection = local_words & hc_words
            union = local_words | hc_words
            jaccard = len(intersection) / len(union)

            if jaccard >= 0.7:
                return True

    return False
