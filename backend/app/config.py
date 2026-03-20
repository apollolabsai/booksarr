import os
from pathlib import Path


CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "./config"))
BOOKS_DIR = Path(os.environ.get("BOOKS_DIR", "/books"))
DATABASE_URL = f"sqlite+aiosqlite:///{CONFIG_DIR}/booksarr.db"
PORT = int(os.environ.get("PORT", "8889"))
HARDCOVER_API_KEY = os.environ.get("HARDCOVER_API_KEY", "")

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
(CONFIG_DIR / "cache" / "authors").mkdir(parents=True, exist_ok=True)
(CONFIG_DIR / "cache" / "books").mkdir(parents=True, exist_ok=True)
