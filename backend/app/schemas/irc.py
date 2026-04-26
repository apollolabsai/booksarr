from typing import Literal

from pydantic import BaseModel, Field


IrcBulkFileTypeKey = Literal["epub", "mobi", "pdf", "zip", "rar", "audiobook"]


class IrcBulkFileTypePreference(BaseModel):
    key: IrcBulkFileTypeKey
    enabled: bool = True


class IrcSettingsResponse(BaseModel):
    enabled: bool = False
    server: str = ""
    port: int = 6697
    use_tls: bool = True
    nickname: str = ""
    username: str = ""
    real_name: str = ""
    channel: str = ""
    channel_password_set: bool = False
    vpn_enabled: bool = False
    vpn_region: str = "Netherlands"
    vpn_username: str = ""
    vpn_password_set: bool = False
    auto_move_to_library: bool = True
    downloads_dir: str


class IrcSettingsUpdate(BaseModel):
    enabled: bool | None = None
    server: str | None = None
    port: int | None = None
    use_tls: bool | None = None
    nickname: str | None = None
    username: str | None = None
    real_name: str | None = None
    channel: str | None = None
    channel_password: str | None = None
    vpn_enabled: bool | None = None
    vpn_region: str | None = None
    vpn_username: str | None = None
    vpn_password: str | None = None
    auto_move_to_library: bool | None = None


class IrcWorkerStatusResponse(BaseModel):
    enabled: bool = False
    desired_connection: bool = False
    connected: bool = False
    joined_channel: bool = False
    state: str = "stopped"
    server: str | None = None
    channel: str | None = None
    nickname: str | None = None
    active_search_job_id: int | None = None
    active_download_job_id: int | None = None
    last_message: str | None = None
    last_error: str | None = None
    online_bots: list[str] = Field(default_factory=list)
    queued_search_jobs: int = 0
    queued_download_jobs: int = 0


class IrcSearchJobSummary(BaseModel):
    id: int
    book_id: int | None
    query_text: str
    status: str
    auto_download: bool = False
    bulk_request_id: str | None = None
    expected_result_filename: str | None
    result_count: int = 0
    error_message: str | None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None


class IrcSearchResultSummary(BaseModel):
    id: int
    search_job_id: int
    result_index: int
    raw_line: str
    bot_name: str | None
    bot_online: bool | None = None
    display_name: str
    file_format: str | None
    file_size_text: str | None
    download_command: str
    selected: bool


class IrcDownloadJobSummary(BaseModel):
    id: int
    book_id: int | None
    search_job_id: int | None
    search_result_id: int | None
    status: str
    bulk_request_id: str | None = None
    dcc_filename: str | None
    size_bytes: int | None = None
    bytes_downloaded: int | None = None
    saved_path: str | None
    moved_to_library_path: str | None
    error_message: str | None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None


class IrcBulkBatchCreateRequest(BaseModel):
    book_ids: list[int] = Field(min_length=1, max_length=50)
    file_type_preferences: list[IrcBulkFileTypePreference] = Field(default_factory=list)


class IrcBulkDownloadItemSummary(BaseModel):
    id: int
    book_id: int
    title: str
    author_id: int | None = None
    author_name: str | None
    position: int
    status: str
    query_text: str | None = None
    error_message: str | None = None
    selected_result_label: str | None = None
    attempt_count: int = 0
    search_job: IrcSearchJobSummary | None = None
    download_job: IrcDownloadJobSummary | None = None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None


class IrcBulkDownloadBatchSummary(BaseModel):
    id: int
    request_id: str
    status: str
    total_books: int
    completed_books: int
    failed_books: int
    cancelled_books: int = 0
    items: list[IrcBulkDownloadItemSummary]
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None


class IrcDownloadFeedEntry(BaseModel):
    entry_id: str
    source: str
    batch_id: int | None = None
    bulk_request_id: str | None = None
    book_id: int | None = None
    title: str
    author_id: int | None = None
    author_name: str | None = None
    status: str
    query_text: str | None = None
    selected_result_label: str | None = None
    attempt_count: int = 0
    active: bool = False
    final_result_kind: str | None = None
    final_result_text: str | None = None
    sort_timestamp: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    search_job: IrcSearchJobSummary | None = None
    download_job: IrcDownloadJobSummary | None = None


class IrcSearchRequest(BaseModel):
    book_id: int | None = None
    query_text: str = Field(min_length=1, max_length=300)
    auto_download: bool = False


class IrcBulkSearchRequest(BaseModel):
    book_ids: list[int] = Field(min_length=1, max_length=50)
    skip_owned: bool = True
    auto_download_single_result: bool = True


class IrcBulkSearchQueuedItem(BaseModel):
    book_id: int
    title: str
    author_name: str | None
    query_text: str
    job: IrcSearchJobSummary


class IrcBulkSearchSkippedItem(BaseModel):
    book_id: int
    title: str
    author_name: str | None
    reason: str


class IrcBulkSearchResponse(BaseModel):
    queued: list[IrcBulkSearchQueuedItem]
    skipped: list[IrcBulkSearchSkippedItem]


class IrcDownloadRequest(BaseModel):
    search_result_id: int
