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
  isbn: string | null;
  description: string | null;
  release_date: string | null;
  cover_image_url: string | null;
  cover_image_cached_path: string | null;
  rating: number | null;
  pages: number | null;
  is_owned: boolean;
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
  isbn: string | null;
  release_date: string | null;
  cover_image_url: string | null;
  cover_image_cached_path: string | null;
  rating: number | null;
  pages: number | null;
  is_owned: boolean;
  series_info: SeriesPositionInfo[];
}

export interface HiddenBook extends Book {
  hidden_category_key: string;
  hidden_category_label: string;
}

export interface ScanStatus {
  status: "idle" | "scanning";
  progress: number;
  message: string;
}

export interface Settings {
  hardcover_api_key: string;
  hardcover_api_key_from_env: boolean;
  google_books_api_key: string;
  google_books_api_key_from_env: boolean;
  library_path: string;
  last_scan_at: string | null;
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
