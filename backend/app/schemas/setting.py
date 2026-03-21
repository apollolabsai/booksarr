from pydantic import BaseModel


class SettingsResponse(BaseModel):
    hardcover_api_key: str
    hardcover_api_key_from_env: bool = False
    google_books_api_key: str
    google_books_api_key_from_env: bool = False
    library_path: str
    last_scan_at: str | None
    scan_interval_hours: int


class SettingsUpdate(BaseModel):
    hardcover_api_key: str | None = None
    google_books_api_key: str | None = None
    scan_interval_hours: int | None = None
