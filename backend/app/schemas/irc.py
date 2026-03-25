from pydantic import BaseModel, Field


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
    queued_search_jobs: int = 0
    queued_download_jobs: int = 0


class IrcSearchJobSummary(BaseModel):
    id: int
    book_id: int | None
    query_text: str
    status: str
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
    dcc_filename: str | None
    saved_path: str | None
    moved_to_library_path: str | None
    error_message: str | None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None


class IrcSearchRequest(BaseModel):
    book_id: int | None = None
    query_text: str = Field(min_length=1, max_length=300)


class IrcDownloadRequest(BaseModel):
    search_result_id: int
