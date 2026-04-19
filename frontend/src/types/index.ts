export interface Author {
  id: number;
  name: string;
  hardcover_id: number | null;
  hardcover_slug: string | null;
  bio: string | null;
  image_url: string | null;
  image_cached_path: string | null;
  book_count_local: number;
  book_count_total: number;
  book_count_hidden: number;
}

export interface AuthorDirectoryEntry {
  id: number;
  dir_path: string;
  is_primary: boolean;
}

export interface AuthorSearchCandidate {
  hardcover_id: number;
  name: string;
  slug: string | null;
  bio: string | null;
  image_url: string | null;
  books_count: number;
}

export interface AuthorSearchResponse {
  query: string;
  candidates: AuthorSearchCandidate[];
}

export interface AuthorPortraitOption {
  key: string;
  source: string;
  label: string;
  image_url: string | null;
  cached_path: string | null;
  page_url: string | null;
  creator: string | null;
  license: string | null;
  width: number | null;
  height: number | null;
  aspect_ratio: number | null;
  is_current: boolean;
  is_manual: boolean;
}

export interface AuthorPortraitOptionsResponse {
  author_id: number;
  current_source: string | null;
  manual_source: string | null;
  options: AuthorPortraitOption[];
}

export interface AuthorPortraitSearchResult {
  url: string;
  thumbnail_url: string;
  width: number | null;
  height: number | null;
  title: string;
  source_url: string;
}

export interface AuthorPortraitSearchResponse {
  author_id: number;
  query: string;
  results: AuthorPortraitSearchResult[];
}

export interface SeriesPositionInfo {
  series_id: number;
  series_name: string;
  position: number | null;
}

export interface LocalBookFile {
  id: number;
  file_path: string;
  file_name: string;
  file_size: number | null;
  file_format: string | null;
}

export interface UnmatchedLocalFile {
  file_path: string;
  file_name: string;
  file_size: number | null;
  file_format: string | null;
  linked_book_id: number | null;
  linked_book_title: string | null;
  author_id: number | null;
  author_name: string | null;
}

export interface BookInAuthor {
  id: number;
  title: string;
  hardcover_id: number | null;
  hardcover_slug: string | null;
  compilation: boolean | null;
  book_category_id: number | null;
  book_category_name: string | null;
  literary_type_id: number | null;
  literary_type_name: string | null;
  hardcover_state: string | null;
  hardcover_isbn_10: string | null;
  hardcover_isbn_13: string | null;
  isbn: string | null;
  google_isbn_10: string | null;
  google_isbn_13: string | null;
  ol_isbn_10: string | null;
  ol_isbn_13: string | null;
  has_valid_isbn: boolean;
  matched_google: boolean;
  matched_openlibrary: boolean;
  description: string | null;
  release_date: string | null;
  cover_image_url: string | null;
  cover_image_cached_path: string | null;
  cover_aspect_ratio: number | null;
  rating: number | null;
  pages: number | null;
  is_owned: boolean;
  owned_copy_count: number;
  local_files: LocalBookFile[];
  series_info: SeriesPositionInfo[];
}

export interface SeriesBookEntry {
  book_id: number;
  title: string;
  position: number | null;
  is_owned: boolean;
  cover_image_cached_path: string | null;
}

export interface SeriesInAuthor {
  id: number;
  name: string;
  hardcover_id: number | null;
  books: SeriesBookEntry[];
}

export interface AuthorDetail extends Author {
  author_directories: AuthorDirectoryEntry[];
  books: BookInAuthor[];
  series: SeriesInAuthor[];
  unmatched_local_files: UnmatchedLocalFile[];
}

export interface AuthorDirectoryMergeResponse {
  status: string;
  message: string;
  kept_directory: string;
  removed_directories: string[];
  moved_items: number;
}

export interface Book {
  id: number;
  title: string;
  author_id: number;
  author_name: string;
  hardcover_id: number | null;
  hardcover_slug: string | null;
  compilation: boolean | null;
  book_category_id: number | null;
  book_category_name: string | null;
  literary_type_id: number | null;
  literary_type_name: string | null;
  hardcover_state: string | null;
  hardcover_isbn_10: string | null;
  hardcover_isbn_13: string | null;
  isbn: string | null;
  google_isbn_10: string | null;
  google_isbn_13: string | null;
  ol_isbn_10: string | null;
  ol_isbn_13: string | null;
  has_valid_isbn: boolean;
  matched_google: boolean;
  matched_openlibrary: boolean;
  release_date: string | null;
  cover_image_url: string | null;
  cover_image_cached_path: string | null;
  cover_aspect_ratio: number | null;
  rating: number | null;
  pages: number | null;
  is_owned: boolean;
  owned_copy_count: number;
  local_files: LocalBookFile[];
  series_info: SeriesPositionInfo[];
}

export interface HiddenBook extends Book {
  hidden_category_key: string;
  hidden_category_label: string;
  hidden_categories: Array<{
    key: string;
    label: string;
  }>;
}

export interface CoverOption {
  key: string;
  source: string;
  label: string;
  image_url: string | null;
  cached_path: string | null;
  width: number | null;
  height: number | null;
  aspect_ratio: number | null;
  ratio_delta_percent: number | null;
  is_current: boolean;
  is_manual: boolean;
}

export interface BookCoverOptionsResponse {
  book_id: number;
  current_source: string | null;
  manual_source: string | null;
  options: CoverOption[];
}

export interface CoverSearchResult {
  url: string;
  thumbnail_url: string;
  width: number | null;
  height: number | null;
  title: string;
  source_url: string;
}

export interface BookCoverSearchResponse {
  book_id: number;
  query: string;
  results: CoverSearchResult[];
}

export interface ScanStatus {
  status: "idle" | "scanning";
  progress: number;
  message: string;
}

export interface HiddenCategorySummary {
  key: string;
  label: string;
  count: number;
}

export interface ScanSourceSummary {
  lookups_attempted: number;
  matched: number;
  failed: number;
  cached: number;
  deferred: number;
  failure_reasons: Record<string, number>;
}

export interface ScanSummary {
  status: string;
  mode: string;
  message: string;
  started_at: string | null;
  completed_at: string | null;
  files_total: number;
  files_new: number;
  files_deleted: number;
  files_unchanged: number;
  owned_books_found: number;
  authors_added: number;
  books_added: number;
  books_hidden: number;
  hidden_by_category: HiddenCategorySummary[];
  new_books_list: { title: string; author: string }[];
  isbn_gains: number;
  hardcover: ScanSourceSummary;
  google: ScanSourceSummary;
  openlibrary: ScanSourceSummary;
  wikimedia: ScanSourceSummary;
}

export interface Settings {
  hardcover_api_key: string;
  hardcover_api_key_from_env: boolean;
  hardcover_api_key_source: "database" | "environment" | "none";
  google_books_api_key: string;
  google_books_api_key_from_env: boolean;
  google_books_api_key_source: "database" | "environment" | "none";
  library_path: string;
  last_scan_at: string | null;
  last_scan_summary: ScanSummary | null;
  scan_interval_hours: number;
  log_level: string;
  visibility_categories: VisibilityCategories;
}

export interface VisibilityCategories {
  standard_books: boolean;
  short_fiction: boolean;
  collections_and_compilations: boolean;
  likely_collections_by_title: boolean;
  graphic_and_alternate_formats: boolean;
  research_non_book_material: boolean;
  fan_fiction: boolean;
  valid_isbn: boolean;
  non_english_books: boolean;
  upcoming_unreleased: boolean;
  pending_hardcover_records: boolean;
  likely_excerpts: boolean;
}

export interface BuildInfo {
  branch: string;
  commit: string;
  date: string;
}

export interface ApiUsageDay {
  day: string;
  total: number;
  hardcover: number;
  google: number;
  openlibrary: number;
  wikimedia: number;
}

export interface IrcSettings {
  enabled: boolean;
  server: string;
  port: number;
  use_tls: boolean;
  nickname: string;
  username: string;
  real_name: string;
  channel: string;
  channel_password_set: boolean;
  vpn_enabled: boolean;
  vpn_region: string;
  vpn_username: string;
  vpn_password_set: boolean;
  auto_move_to_library: boolean;
  downloads_dir: string;
}

export interface IrcWorkerStatus {
  enabled: boolean;
  desired_connection: boolean;
  connected: boolean;
  joined_channel: boolean;
  state: string;
  server: string | null;
  channel: string | null;
  nickname: string | null;
  active_search_job_id: number | null;
  active_download_job_id: number | null;
  last_message: string | null;
  last_error: string | null;
  online_bots: string[];
  queued_search_jobs: number;
  queued_download_jobs: number;
}

export interface IrcSearchJob {
  id: number;
  book_id: number | null;
  query_text: string;
  status: string;
  auto_download: boolean;
  bulk_request_id: string | null;
  expected_result_filename: string | null;
  result_count: number;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
}

export interface IrcBulkSearchQueuedItem {
  book_id: number;
  title: string;
  author_name: string | null;
  query_text: string;
  job: IrcSearchJob;
}

export interface IrcBulkSearchSkippedItem {
  book_id: number;
  title: string;
  author_name: string | null;
  reason: string;
}

export interface IrcBulkSearchResponse {
  queued: IrcBulkSearchQueuedItem[];
  skipped: IrcBulkSearchSkippedItem[];
}

export type IrcBulkFileTypeKey = "epub" | "mobi" | "zip" | "rar" | "audiobook";

export interface IrcBulkFileTypePreference {
  key: IrcBulkFileTypeKey;
  enabled: boolean;
}

export interface IrcBulkDownloadItem {
  id: number;
  book_id: number;
  title: string;
  author_id: number | null;
  author_name: string | null;
  position: number;
  status: string;
  query_text: string | null;
  error_message: string | null;
  selected_result_label: string | null;
  attempt_count: number;
  search_job: IrcSearchJob | null;
  download_job: IrcDownloadJob | null;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
}

export interface IrcBulkDownloadBatch {
  id: number;
  request_id: string;
  status: string;
  total_books: number;
  completed_books: number;
  failed_books: number;
  cancelled_books: number;
  items: IrcBulkDownloadItem[];
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
}

export interface IrcDownloadFeedEntry {
  entry_id: string;
  source: string;
  batch_id: number | null;
  bulk_request_id: string | null;
  book_id: number | null;
  title: string;
  author_id: number | null;
  author_name: string | null;
  status: string;
  query_text: string | null;
  selected_result_label: string | null;
  attempt_count: number;
  active: boolean;
  final_result_kind: string | null;
  final_result_text: string | null;
  sort_timestamp: string | null;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
  search_job: IrcSearchJob | null;
  download_job: IrcDownloadJob | null;
}

export interface IrcSearchResult {
  id: number;
  search_job_id: number;
  result_index: number;
  raw_line: string;
  bot_name: string | null;
  bot_online: boolean | null;
  display_name: string;
  file_format: string | null;
  file_size_text: string | null;
  download_command: string;
  selected: boolean;
}

export interface IrcDownloadJob {
  id: number;
  book_id: number | null;
  search_job_id: number | null;
  search_result_id: number | null;
  status: string;
  bulk_request_id: string | null;
  dcc_filename: string | null;
  size_bytes: number | null;
  bytes_downloaded: number | null;
  saved_path: string | null;
  moved_to_library_path: string | null;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
}

export interface LogEntry {
  timestamp: string;
  level: string;
  category: string;
  message: string;
}

export interface LogsResponse {
  entries: LogEntry[];
  categories: string[];
}

export function getImageUrl(cachedPath: string | null, fallbackUrl: string | null): string {
  if (cachedPath) return `/api/images/${cachedPath.replace("cache/", "")}`;
  if (fallbackUrl) return fallbackUrl;
  return "";
}

export function getBookCoverPresentation(coverAspectRatio: number | null) {
  const targetRatio = 2 / 3;
  const normalLowerBound = 0.62;
  const normalUpperBound = 0.72;
  const stretchLowerBound = targetRatio * 0.8;
  const stretchUpperBound = targetRatio * 1.2;

  if (
    coverAspectRatio != null &&
    (coverAspectRatio < normalLowerBound || coverAspectRatio > normalUpperBound) &&
    coverAspectRatio >= stretchLowerBound &&
    coverAspectRatio <= stretchUpperBound
  ) {
    return {
      frameStyle: { aspectRatio: "2 / 3" as const },
      frameClassName: "bg-slate-700",
      imageClassName: "w-full h-full object-fill",
      innerClassName: "",
    };
  }

  if (coverAspectRatio != null && (coverAspectRatio < normalLowerBound || coverAspectRatio > normalUpperBound)) {
    return {
      frameStyle: { aspectRatio: "2 / 3" as const },
      frameClassName: "bg-black",
      imageClassName: "w-full h-full object-contain",
      innerClassName: "flex h-full w-full items-center justify-center p-2",
    };
  }

  return {
    frameStyle: { aspectRatio: "2 / 3" as const },
    frameClassName: "bg-slate-700",
    imageClassName: "w-full h-full object-cover",
    innerClassName: "",
  };
}
