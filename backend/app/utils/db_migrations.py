from sqlalchemy.engine import Connection


def run_schema_migrations(conn: Connection) -> None:
    book_rows = conn.exec_driver_sql("PRAGMA table_info(books)").fetchall()
    existing_book_columns = {row[1] for row in book_rows}
    author_rows = conn.exec_driver_sql("PRAGMA table_info(authors)").fetchall()
    existing_author_columns = {row[1] for row in author_rows}

    book_column_defs = {
        "compilation": "BOOLEAN",
        "book_category_id": "INTEGER",
        "book_category_name": "VARCHAR",
        "literary_type_id": "INTEGER",
        "literary_type_name": "VARCHAR",
        "hardcover_state": "VARCHAR",
        "hardcover_isbn_10": "VARCHAR",
        "hardcover_isbn_13": "VARCHAR",
        "google_isbn_10": "VARCHAR",
        "google_isbn_13": "VARCHAR",
        "ol_isbn_10": "VARCHAR",
        "ol_isbn_13": "VARCHAR",
        "manual_cover_source": "VARCHAR",
        "manual_cover_url": "VARCHAR",
        "manual_visibility": "VARCHAR",
    }

    for column_name, column_type in book_column_defs.items():
        if column_name in existing_book_columns:
            continue
        conn.exec_driver_sql(f"ALTER TABLE books ADD COLUMN {column_name} {column_type}")

    author_column_defs = {
        "manual_image_source": "VARCHAR",
        "manual_image_url": "VARCHAR",
        "manual_image_page_url": "VARCHAR",
    }

    for column_name, column_type in author_column_defs.items():
        if column_name in existing_author_columns:
            continue
        conn.exec_driver_sql(f"ALTER TABLE authors ADD COLUMN {column_name} {column_type}")
