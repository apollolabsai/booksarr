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

    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS author_directories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author_id INTEGER NOT NULL,
            dir_path VARCHAR NOT NULL UNIQUE,
            is_primary BOOLEAN NOT NULL DEFAULT 0,
            last_seen_at DATETIME NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(author_id) REFERENCES authors (id)
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_author_directories_author_id ON author_directories (author_id)"
    )

    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS irc_search_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NULL,
            query_text VARCHAR NOT NULL,
            normalized_query VARCHAR NOT NULL,
            status VARCHAR NOT NULL DEFAULT 'queued',
            request_message TEXT NULL,
            expected_result_filename VARCHAR NULL,
            result_archive_path VARCHAR NULL,
            result_text_path VARCHAR NULL,
            error_message TEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME NULL,
            FOREIGN KEY(book_id) REFERENCES books (id)
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_irc_search_jobs_status ON irc_search_jobs (status)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_irc_search_jobs_book_id ON irc_search_jobs (book_id)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_irc_search_jobs_normalized_query ON irc_search_jobs (normalized_query)"
    )

    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS irc_search_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_job_id INTEGER NOT NULL,
            result_index INTEGER NOT NULL,
            raw_line TEXT NOT NULL,
            bot_name VARCHAR NULL,
            display_name TEXT NOT NULL,
            normalized_title VARCHAR NULL,
            normalized_author VARCHAR NULL,
            file_format VARCHAR NULL,
            file_size_text VARCHAR NULL,
            download_command TEXT NOT NULL,
            selected BOOLEAN NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(search_job_id) REFERENCES irc_search_jobs (id)
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_irc_search_results_search_job_id ON irc_search_results (search_job_id)"
    )

    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS irc_download_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NULL,
            search_job_id INTEGER NULL,
            search_result_id INTEGER NULL,
            status VARCHAR NOT NULL DEFAULT 'queued',
            request_message TEXT NULL,
            dcc_filename VARCHAR NULL,
            saved_path VARCHAR NULL,
            moved_to_library_path VARCHAR NULL,
            error_message TEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME NULL,
            FOREIGN KEY(book_id) REFERENCES books (id),
            FOREIGN KEY(search_job_id) REFERENCES irc_search_jobs (id),
            FOREIGN KEY(search_result_id) REFERENCES irc_search_results (id)
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_irc_download_jobs_status ON irc_download_jobs (status)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_irc_download_jobs_book_id ON irc_download_jobs (book_id)"
    )
