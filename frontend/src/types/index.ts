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

export interface SeriesPositionInfo {
  series_id: number;
  series_name: string;
  position: number | null;
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
  books: BookInAuthor[];
  series: SeriesInAuthor[];
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
  hardcover: ScanSourceSummary;
  google: ScanSourceSummary;
  openlibrary: ScanSourceSummary;
  wikimedia: ScanSourceSummary;
}

export interface Settings {
  hardcover_api_key: string;
  hardcover_api_key_from_env: boolean;
  google_books_api_key: string;
  google_books_api_key_from_env: boolean;
  library_path: string;
  last_scan_at: string | null;
  last_scan_summary: ScanSummary | null;
  scan_interval_hours: number;
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
  queued_search_jobs: number;
  queued_download_jobs: number;
}

export interface IrcSearchJob {
  id: number;
  book_id: number | null;
  query_text: string;
  status: string;
  expected_result_filename: string | null;
  result_count: number;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
}

export interface IrcSearchResult {
  id: number;
  search_job_id: number;
  result_index: number;
  raw_line: string;
  bot_name: string | null;
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
  dcc_filename: string | null;
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
