import re


_NON_ALNUM_RE = re.compile(r"[^0-9Xx]")


def normalize_isbn(value: str | None) -> str:
    if not value:
        return ""
    return _NON_ALNUM_RE.sub("", value).upper()


def normalized_valid_isbn(value: str | None) -> str | None:
    isbn = normalize_isbn(value)
    if not isbn or not is_valid_isbn(isbn):
        return None
    return isbn


def is_valid_isbn(value: str | None) -> bool:
    isbn = normalize_isbn(value)
    if len(isbn) == 10:
        return _is_valid_isbn10(isbn)
    if len(isbn) == 13:
        return _is_valid_isbn13(isbn)
    return False


def has_any_valid_isbn(*values: str | None) -> bool:
    return any(is_valid_isbn(value) for value in values)


def extract_isbn_variants(values: list[str] | None) -> tuple[str | None, str | None]:
    isbn10 = None
    isbn13 = None
    for value in values or []:
        normalized = normalized_valid_isbn(value)
        if not normalized:
            continue
        if len(normalized) == 10 and isbn10 is None:
            isbn10 = normalized
        elif len(normalized) == 13 and isbn13 is None:
            isbn13 = normalized
        if isbn10 and isbn13:
            break
    return isbn10, isbn13


def _is_valid_isbn10(isbn: str) -> bool:
    if not re.fullmatch(r"\d{9}[\dX]", isbn):
        return False
    total = 0
    for index, char in enumerate(isbn):
        digit = 10 if char == "X" else int(char)
        total += (10 - index) * digit
    return total % 11 == 0


def _is_valid_isbn13(isbn: str) -> bool:
    if not isbn.isdigit():
        return False
    total = 0
    for index, char in enumerate(isbn[:12]):
        digit = int(char)
        total += digit if index % 2 == 0 else digit * 3
    check_digit = (10 - (total % 10)) % 10
    return check_digit == int(isbn[12])
