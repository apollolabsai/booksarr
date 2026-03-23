from sqlalchemy.engine import Connection


def run_schema_migrations(conn: Connection) -> None:
    rows = conn.exec_driver_sql("PRAGMA table_info(books)").fetchall()
    existing_columns = {row[1] for row in rows}

    column_defs = {
        "compilation": "BOOLEAN",
        "book_category_id": "INTEGER",
        "book_category_name": "VARCHAR",
        "literary_type_id": "INTEGER",
        "literary_type_name": "VARCHAR",
        "hardcover_state": "VARCHAR",
    }

    for column_name, column_type in column_defs.items():
        if column_name in existing_columns:
            continue
        conn.exec_driver_sql(f"ALTER TABLE books ADD COLUMN {column_name} {column_type}")
