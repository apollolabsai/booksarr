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
  isbn: string | null;
  release_date: string | null;
  cover_image_url: string | null;
  cover_image_cached_path: string | null;
  rating: number | null;
  pages: number | null;
  is_owned: boolean;
  series_info: SeriesPositionInfo[];
}

export interface ScanStatus {
  status: "idle" | "scanning";
  progress: number;
  message: string;
}

export interface Settings {
  hardcover_api_key: string;
  library_path: string;
  last_scan_at: string | null;
  scan_interval_hours: number;
}

export interface BuildInfo {
  branch: string;
  commit: string;
  date: string;
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
