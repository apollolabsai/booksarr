HARDCOVER_BOOK_CATEGORY_NAMES = {
    1: "Book",
    2: "Novella",
    3: "Short Story",
    4: "Graphic Novel",
    5: "Fan Fiction",
    6: "Research Paper",
    7: "Poetry",
    8: "Collection",
    9: "Web Novel",
    10: "Light Novel",
}

# Hardcover does not currently expose a public lookup table for these IDs in the
# schema we query. Keep this mapping deliberately small and explicit until we
# observe additional stable IDs.
HARDCOVER_LITERARY_TYPE_NAMES = {
    1: "Fiction",
    2: "Nonfiction",
}


def get_book_category_name(book_category_id: int | None) -> str | None:
    if book_category_id is None:
        return None
    return HARDCOVER_BOOK_CATEGORY_NAMES.get(book_category_id)


def get_literary_type_name(literary_type_id: int | None) -> str | None:
    if literary_type_id is None:
        return None
    return HARDCOVER_LITERARY_TYPE_NAMES.get(literary_type_id)
