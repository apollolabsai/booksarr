from pydantic import BaseModel


class SettingsResponse(BaseModel):
    hardcover_api_key: str
    library_path: str
    last_scan_at: str | None
    scan_interval_hours: int


class SettingsUpdate(BaseModel):
    hardcover_api_key: str | None = None
    scan_interval_hours: int | None = None
