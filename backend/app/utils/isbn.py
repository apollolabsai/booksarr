import re


_NON_ALNUM_RE = re.compile(r"[^0-9Xx]")


def normalize_isbn(value: str | None) -> str:
    if not value:
        return ""
    return _NON_ALNUM_RE.sub("", value).upper()


def is_valid_isbn(value: str | None) -> bool:
    isbn = normalize_isbn(value)
    if len(isbn) == 10:
        return _is_valid_isbn10(isbn)
    if len(isbn) == 13:
        return _is_valid_isbn13(isbn)
    return False


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
