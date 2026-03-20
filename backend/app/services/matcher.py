import re
import unicodedata


def normalize_title(title: str) -> str:
    """Normalize a book title for fuzzy matching."""
    t = title.lower().strip()
    # Remove HTML entities
    t = re.sub(r"&\w+;", " ", t)
    # Take text before colon (subtitle separator)
    if ":" in t:
        t = t.split(":")[0].strip()
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


def titles_match(local_title: str, hc_title: str) -> bool:
    """Check if two titles match using normalization and similarity."""
    norm_local = normalize_title(local_title)
    norm_hc = normalize_title(hc_title)

    if not norm_local or not norm_hc:
        return False

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
        return False

    intersection = local_words & hc_words
    union = local_words | hc_words
    jaccard = len(intersection) / len(union)

    return jaccard >= 0.7
