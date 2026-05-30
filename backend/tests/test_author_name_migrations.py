from sqlalchemy import create_engine

from backend.app.database import Base
from backend.app.models import *  # noqa: F401, F403
from backend.app.utils.db_migrations import run_schema_migrations


def test_schema_migration_cleans_existing_calibre_windows_author_names(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        conn.exec_driver_sql(
            """
            INSERT INTO authors (
                id,
                name,
                author_key,
                book_count_local,
                book_count_total,
                created_at,
                updated_at
            )
            VALUES
                (1, 'Murphy, C. E_', 'c. e_ murphy', 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (2, 'C. E. Murphy', 'c. e. murphy', 2, 2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )

        run_schema_migrations(conn)

        rows = conn.exec_driver_sql(
            "SELECT id, name, author_key FROM authors ORDER BY id"
        ).fetchall()

    engine.dispose()

    assert rows == [(2, "C. E. Murphy", "c. e. murphy")]
