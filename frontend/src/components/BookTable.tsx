import { Fragment, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { Book, BookInAuthor } from "../types";
import { getBookCoverPresentation, getImageUrl } from "../types";
import { useRefreshBook, useSetBookVisibility } from "../api/books";
import CoverPickerDialog from "./CoverPickerDialog";
import IrcSearchDialog from "./IrcSearchDialog";
import BookDownloadSelector from "./BookDownloadSelector";

type BookLike = Book | BookInAuthor;
type TableSortKey = "title" | "series" | "year" | "rating" | "size";

function isFullBook(book: BookLike): book is Book {
  return "author_name" in book;
}

function formatFileSize(size: number | null): string {
  if (size == null || Number.isNaN(size)) return "Unknown size";
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB"];
  let value = size / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 100 ? 0 : value >= 10 ? 1 : 2)} ${units[unitIndex]}`;
}


function formatSeriesPosition(book: BookLike): string {
  if (!("series_info" in book) || !book.series_info || book.series_info.length === 0) return "";
  const si = book.series_info[0];
  const pos = si.position != null
    ? (Number.isInteger(si.position) ? `#${si.position}` : `#${si.position.toFixed(1)}`)
    : "";
  return pos ? `${si.series_name} ${pos}` : si.series_name;
}

const FORMAT_BADGES: { key: string; label: string; activeClass: string }[] = [
  { key: "epub", label: "EPUB", activeClass: "bg-emerald-500/15 text-emerald-300" },
  { key: "mobi", label: "MOBI", activeClass: "bg-blue-500/15 text-blue-300" },
  { key: "pdf", label: "PDF", activeClass: "bg-amber-500/15 text-amber-300" },
  { key: "audiobook", label: "AUDIO", activeClass: "bg-purple-500/15 text-purple-300" },
];

const FORMAT_BADGE_MAP: Record<string, { label: string; activeClass: string }> = Object.fromEntries(
  FORMAT_BADGES.map(({ key, label, activeClass }) => [key, { label, activeClass }]),
);

function FileFormatTag({ format }: { format: string | null }) {
  const key = (format || "").toLowerCase();
  const entry = FORMAT_BADGE_MAP[key];
  const label = entry?.label ?? (key ? key.toUpperCase() : "FILE");
  const colorClass = entry?.activeClass ?? "bg-slate-700 text-slate-300";
  return (
    <span
      className={`inline-flex flex-shrink-0 items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${colorClass}`}
    >
      {label}
    </span>
  );
}

function FormatBadges({ book }: { book: BookLike }) {
  const ownedFormats = new Set(
    book.local_files
      .map((file) => (file.file_format || "").toLowerCase())
      .filter(Boolean),
  );

  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {FORMAT_BADGES.map(({ key, label, activeClass }) => {
        const owned = ownedFormats.has(key);
        return (
          <span
            key={key}
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${
              owned ? activeClass : "bg-slate-800 text-slate-500"
            }`}
            title={owned ? `${label} file available` : `No ${label} file`}
          >
            {label}
          </span>
        );
      })}
    </div>
  );
}

function ActionIconButton({
  label,
  onClick,
  disabled = false,
  preferBelow = false,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  preferBelow?: boolean;
  children: ReactNode;
}) {
  const [showTooltip, setShowTooltip] = useState(false);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) {
        window.clearTimeout(timerRef.current);
      }
    };
  }, []);

  const handleEnter = () => {
    if (timerRef.current) {
      window.clearTimeout(timerRef.current);
    }
    timerRef.current = window.setTimeout(() => setShowTooltip(true), 250);
  };

  const handleLeave = () => {
    if (timerRef.current) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setShowTooltip(false);
  };

  return (
    <div
      className="relative inline-flex"
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
      onFocus={handleEnter}
      onBlur={handleLeave}
    >
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-label={label}
        className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-600 bg-slate-700 text-slate-200 transition-colors hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {children}
      </button>
      {showTooltip && !disabled && (
        <div
          className={`pointer-events-none absolute right-0 z-20 whitespace-nowrap rounded-md border border-slate-600 bg-slate-900 px-2 py-1 text-[11px] font-medium text-slate-100 shadow-lg ${
            preferBelow ? "top-full mt-2" : "bottom-full mb-2"
          }`}
        >
          {label}
        </div>
      )}
    </div>
  );
}

function SelectionToggle({
  selected,
  label,
  onToggle,
}: {
  selected: boolean;
  label: string;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={selected}
      aria-label={label}
      className={`inline-flex h-3.5 w-3.5 items-center justify-center rounded-[4px] border transition-colors ${
        selected
          ? "border-emerald-500 bg-emerald-500/90 text-slate-950"
          : "border-slate-500 bg-slate-800/70 text-transparent hover:border-slate-300 hover:bg-slate-700"
      }`}
    >
      <svg className="h-2.5 w-2.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.25">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.25 8.25 6.5 11.5 12.75 4.75" />
      </svg>
    </button>
  );
}

export default function BookTable({
  books,
  showAuthor = true,
  authorName: contextAuthorName = null,
  selectedBookIds,
  onToggleSelected,
}: {
  books: BookLike[];
  showAuthor?: boolean;
  authorName?: string | null;
  selectedBookIds?: Set<number>;
  onToggleSelected?: (bookId: number) => void;
}) {
  const refreshBook = useRefreshBook();
  const setBookVisibility = useSetBookVisibility();
  const [coverPickerBook, setCoverPickerBook] = useState<{ id: number; title: string } | null>(null);
  const [ircSearchBook, setIrcSearchBook] = useState<{ id: number; title: string; authorName: string | null } | null>(null);
  const [sortKey, setSortKey] = useState<TableSortKey | null>(null);
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());
  const showSelectionColumn = Boolean(onToggleSelected);

  const handleSort = (nextKey: TableSortKey) => {
    setSortKey((currentKey) => {
      if (currentKey === nextKey) {
        setSortDirection((currentDirection) => currentDirection === "asc" ? "desc" : "asc");
        return currentKey;
      }
      setSortDirection("asc");
      return nextKey;
    });
  };

  const sortedBooks = useMemo(() => {
    const items = [...books];
    if (!sortKey) return items;

    items.sort((a, b) => {
      let comparison = 0;
      if (sortKey === "title") {
        comparison = a.title.localeCompare(b.title);
      } else if (sortKey === "series") {
        comparison = formatSeriesPosition(a).localeCompare(formatSeriesPosition(b)) || a.title.localeCompare(b.title);
      } else if (sortKey === "year") {
        comparison = (a.release_date || "").localeCompare(b.release_date || "") || a.title.localeCompare(b.title);
      } else if (sortKey === "rating") {
        comparison = (a.rating || 0) - (b.rating || 0) || a.title.localeCompare(b.title);
      } else if (sortKey === "size") {
        const sizeA = a.local_files.reduce((sum, f) => sum + (f.file_size ?? 0), 0);
        const sizeB = b.local_files.reduce((sum, f) => sum + (f.file_size ?? 0), 0);
        comparison = sizeA - sizeB || a.title.localeCompare(b.title);
      }
      return sortDirection === "asc" ? comparison : -comparison;
    });

    return items;
  }, [books, sortDirection, sortKey]);

  const renderSortIndicator = (key: TableSortKey) => {
    if (sortKey !== key) return null;
    return <span className="ml-1 text-emerald-400">{sortDirection === "asc" ? "▲" : "▼"}</span>;
  };

  const toggleExpanded = (bookId: number) => {
    setExpandedRows((current) => {
      const next = new Set(current);
      if (next.has(bookId)) {
        next.delete(bookId);
      } else {
        next.add(bookId);
      }
      return next;
    });
  };

  const detailColSpan = (showAuthor ? 8 : 7) + (showSelectionColumn ? 1 : 0);

  return (
    <>
      <div className="rounded-lg border border-slate-700 bg-slate-800 overflow-x-auto overflow-y-visible">
        <table className="w-full text-sm text-left">
          <thead className="border-b border-slate-700 bg-slate-800/80 text-[11px] uppercase tracking-wide text-slate-400">
            <tr>
              {showSelectionColumn && <th className="px-4 py-2 w-10"></th>}
              <th className="px-4 py-2 w-12"></th>
              <th className="px-4 py-2">
                <button type="button" onClick={() => handleSort("title")} className="hover:text-slate-200 transition-colors">
                  Book Title{renderSortIndicator("title")}
                </button>
              </th>
              {showAuthor && <th className="px-4 py-2"></th>}
              <th className="px-4 py-2">
                <button type="button" onClick={() => handleSort("series")} className="hover:text-slate-200 transition-colors">
                  Series{renderSortIndicator("series")}
                </button>
              </th>
              <th className="px-4 py-2 text-right">
                <button type="button" onClick={() => handleSort("year")} className="hover:text-slate-200 transition-colors">
                  Year{renderSortIndicator("year")}
                </button>
              </th>
              <th className="px-4 py-2 text-right">
                <button type="button" onClick={() => handleSort("rating")} className="hover:text-slate-200 transition-colors">
                  Rating{renderSortIndicator("rating")}
                </button>
              </th>
              <th className="px-4 py-2 text-right">
                <button type="button" onClick={() => handleSort("size")} className="hover:text-slate-200 transition-colors">
                  Size{renderSortIndicator("size")}
                </button>
              </th>
              <th className="px-4 py-2 text-right"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700">
            {sortedBooks.map((book, index) => {
              const imgUrl = getImageUrl(
                book.cover_image_cached_path,
                "cover_image_url" in book ? book.cover_image_url : null
              );
              const coverPresentation = getBookCoverPresentation(book.cover_aspect_ratio);
              const authorId = isFullBook(book) ? book.author_id : undefined;
              const authorName = isFullBook(book) ? book.author_name : undefined;
              const seriesStr = formatSeriesPosition(book);
              const isExpanded = expandedRows.has(book.id);
              const localFiles = [...book.local_files].sort((a, b) => a.file_path.localeCompare(b.file_path));
              const isSelected = selectedBookIds?.has(book.id) ?? false;

              return (
                <Fragment key={book.id}>
                  <tr
                    key={book.id}
                    className={`transition-colors ${isSelected ? "bg-emerald-500/10 hover:bg-emerald-500/15" : "hover:bg-slate-700/50"}`}
                  >
                    {showSelectionColumn && (
                      <td className="px-4 py-2 text-center">
                        <SelectionToggle
                          selected={isSelected}
                          onToggle={() => onToggleSelected?.(book.id)}
                          label={`Select ${book.title}`}
                        />
                      </td>
                    )}
                    <td className="px-4 py-2">
                      <div className={`w-8 h-12 rounded overflow-hidden flex-shrink-0 ${coverPresentation.frameClassName}`}>
                        {imgUrl ? (
                          coverPresentation.innerClassName ? (
                            <div className="flex h-full w-full items-center justify-center p-0.5">
                              <img src={imgUrl} alt="" className={coverPresentation.imageClassName} />
                            </div>
                          ) : (
                            <img src={imgUrl} alt="" className={coverPresentation.imageClassName} />
                          )
                        ) : (
                          <div className="w-full h-full flex items-center justify-center text-[8px] text-slate-500 p-0.5 text-center leading-tight">
                            {book.title.substring(0, 20)}
                          </div>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-2">
                      {book.hardcover_slug ? (
                        <a
                          href={`https://hardcover.app/books/${book.hardcover_slug}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-medium text-slate-200 hover:text-emerald-400 transition-colors"
                        >
                          {book.title}
                        </a>
                      ) : (
                        <span className="font-medium text-slate-200">{book.title}</span>
                      )}
                      <FormatBadges book={book} />
                    </td>
                    {showAuthor && (
                      <td className="px-4 py-2">
                        {authorId ? (
                          <Link
                            to={`/authors/${authorId}`}
                            className="text-slate-400 hover:text-emerald-400 transition-colors"
                          >
                            {authorName}
                          </Link>
                        ) : (
                          <span className="text-slate-400">-</span>
                        )}
                      </td>
                    )}
                    <td className="px-4 py-2 text-slate-400 text-xs">
                      {seriesStr || "-"}
                    </td>
                    <td className="px-4 py-2 text-right text-slate-400 whitespace-nowrap">
                      {book.release_date ? book.release_date.substring(0, 4) : "-"}
                    </td>
                    <td className="px-4 py-2 text-right text-slate-400">
                      {book.rating ? book.rating.toFixed(1) : "-"}
                    </td>
                    <td className="px-4 py-2 text-right text-slate-400 whitespace-nowrap">
                      {localFiles.length > 0
                        ? formatFileSize(localFiles.reduce((sum, f) => sum + (f.file_size ?? 0), 0))
                        : "-"}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <ActionIconButton
                          label="Choose poster"
                          onClick={() => setCoverPickerBook({ id: book.id, title: book.title })}
                          preferBelow={index === 0}
                        >
                          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2 1.586-1.586a2 2 0 012.828 0L20 14m-6-8h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                          </svg>
                        </ActionIconButton>
                        <ActionIconButton
                          label="Search IRC"
                          onClick={() => setIrcSearchBook({
                            id: book.id,
                            title: book.title,
                            authorName: authorName ?? contextAuthorName ?? null,
                          })}
                          preferBelow={index === 0}
                        >
                          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35" />
                            <circle cx="11" cy="11" r="6" strokeWidth={2} />
                          </svg>
                        </ActionIconButton>
                        <BookDownloadSelector
                          bookId={book.id}
                          localFiles={localFiles}
                          disabled={!book.is_owned}
                          direction={index === 0 ? "down" : "up"}
                          renderTrigger={({ toggle, disabled, hasMultiple }) => (
                            <ActionIconButton
                              label={
                                disabled
                                  ? "No local file available"
                                  : hasMultiple
                                    ? "Choose file to download"
                                    : "Download file"
                              }
                              onClick={toggle}
                              disabled={disabled}
                              preferBelow={index === 0}
                            >
                              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v12m0 0l-4-4m4 4l4-4M5 21h14" />
                              </svg>
                            </ActionIconButton>
                          )}
                        />
                        <ActionIconButton
                          label="Scan author folders and re-import metadata"
                          onClick={() => refreshBook.mutate(book.id)}
                          disabled={refreshBook.isPending}
                          preferBelow={index === 0}
                        >
                          <svg className={`h-4 w-4 ${refreshBook.isPending && refreshBook.variables === book.id ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m14.836 2A8.001 8.001 0 005.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.356-2m15.356 2H15" />
                          </svg>
                        </ActionIconButton>
                        <ActionIconButton
                          label="Hide book"
                          onClick={() => setBookVisibility.mutate({ bookId: book.id, action: "hide" })}
                          disabled={setBookVisibility.isPending}
                          preferBelow={index === 0}
                        >
                          <svg className={`h-4 w-4 ${setBookVisibility.isPending && setBookVisibility.variables?.bookId === book.id ? "animate-pulse" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3.98 8.223A10.477 10.477 0 0112 5c4.478 0 8.268 2.943 9.542 7-.435 1.384-1.18 2.625-2.153 3.646M6.228 6.228A9.956 9.956 0 002.458 12c1.274 4.057 5.064 7 9.542 7 1.671 0 3.254-.41 4.646-1.153M6.228 6.228L3 3m3.228 3.228l3.65 3.65m0 0a3 3 0 104.243 4.243m-4.243-4.243L14.12 14.12m0 0L21 21" />
                          </svg>
                        </ActionIconButton>
                        <ActionIconButton
                          label={isExpanded ? "Hide file paths" : "Show file paths"}
                          onClick={() => toggleExpanded(book.id)}
                          disabled={localFiles.length === 0}
                          preferBelow={index === 0}
                        >
                          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            {isExpanded ? (
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7-7-7 7" />
                            ) : (
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 10l7 7 7-7" />
                            )}
                          </svg>
                        </ActionIconButton>
                      </div>
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr className="bg-slate-800/20">
                      <td colSpan={detailColSpan} className="px-4 pb-4 pt-0">
                        <div className="ml-14 border-t border-slate-700/70 px-1 pt-3">
                          <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                            Local Files
                          </div>
                          <div className="space-y-1.5">
                            {localFiles.map((file) => (
                              <div
                                key={file.id}
                                className="flex items-start justify-between gap-4 px-0 py-1.5"
                              >
                                <div className="flex min-w-0 flex-1 items-start gap-2">
                                  <FileFormatTag format={file.file_format} />
                                  <div className="min-w-0 flex-1 break-all text-xs text-slate-300">
                                    {file.file_path}
                                  </div>
                                </div>
                                <div className="shrink-0 whitespace-nowrap pl-4 text-xs text-slate-500">
                                  {formatFileSize(file.file_size)}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <CoverPickerDialog
        bookId={coverPickerBook?.id ?? null}
        title={coverPickerBook?.title ?? ""}
        open={coverPickerBook !== null}
        onClose={() => setCoverPickerBook(null)}
      />
      <IrcSearchDialog
        bookId={ircSearchBook?.id ?? null}
        title={ircSearchBook?.title ?? ""}
        authorName={ircSearchBook?.authorName ?? null}
        open={ircSearchBook !== null}
        onClose={() => setIrcSearchBook(null)}
      />
    </>
  );
}
