import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { Book, BookInAuthor } from "../types";
import { getBookCoverPresentation, getImageUrl } from "../types";
import { useRefreshBook, useSetBookVisibility } from "../api/books";
import CoverPickerDialog from "./CoverPickerDialog";
import IrcSearchDialog from "./IrcSearchDialog";

type BookLike = Book | BookInAuthor;
type TableSortKey = "title" | "series" | "year" | "rating";

function isFullBook(book: BookLike): book is Book {
  return "author_name" in book;
}

function downloadBook(bookId: number) {
  window.open(`/api/books/${bookId}/download`, "_blank", "noopener,noreferrer");
}

function OwnedIndicator({ count }: { count: number }) {
  if (count > 1) {
    return (
      <div
        className="inline-flex min-w-5 items-center justify-center rounded-full bg-emerald-500 px-1.5 py-0.5 text-[10px] font-semibold text-white"
        title={`${count} owned copies`}
      >
        {count}
      </div>
    );
  }

  return (
    <div className="inline-flex bg-emerald-500 rounded-full p-0.5" title="Owned">
      <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
        <path
          fillRule="evenodd"
          d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
          clipRule="evenodd"
        />
      </svg>
    </div>
  );
}

function formatSeriesPosition(book: BookLike): string {
  if (!("series_info" in book) || !book.series_info || book.series_info.length === 0) return "";
  const si = book.series_info[0];
  const pos = si.position != null
    ? (Number.isInteger(si.position) ? `#${si.position}` : `#${si.position.toFixed(1)}`)
    : "";
  return pos ? `${si.series_name} ${pos}` : si.series_name;
}

function MetadataBadges({ book }: { book: BookLike }) {
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      <span
        className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${
          book.has_valid_isbn
            ? "bg-emerald-500/15 text-emerald-300"
            : "bg-slate-700 text-slate-400"
        }`}
        title={book.has_valid_isbn ? "Valid ISBN present" : "No valid ISBN"}
      >
        ISBN {book.has_valid_isbn ? "✓" : "—"}
      </span>
      {book.matched_google && (
        <span
          className="inline-flex items-center rounded-full bg-blue-500/15 px-2 py-0.5 text-[10px] font-medium text-blue-300"
          title="Matched with Google Books"
        >
          Google
        </span>
      )}
      {book.matched_openlibrary && (
        <span
          className="inline-flex items-center rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-300"
          title="Matched with Open Library"
        >
          OL
        </span>
      )}
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

export default function BookTable({
  books,
  showAuthor = true,
  authorName: contextAuthorName = null,
}: {
  books: BookLike[];
  showAuthor?: boolean;
  authorName?: string | null;
}) {
  const refreshBook = useRefreshBook();
  const setBookVisibility = useSetBookVisibility();
  const [coverPickerBook, setCoverPickerBook] = useState<{ id: number; title: string } | null>(null);
  const [ircSearchBook, setIrcSearchBook] = useState<{ id: number; title: string; authorName: string | null } | null>(null);
  const [sortKey, setSortKey] = useState<TableSortKey | null>(null);
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");

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
      }
      return sortDirection === "asc" ? comparison : -comparison;
    });

    return items;
  }, [books, sortDirection, sortKey]);

  const renderSortIndicator = (key: TableSortKey) => {
    if (sortKey !== key) return null;
    return <span className="ml-1 text-emerald-400">{sortDirection === "asc" ? "▲" : "▼"}</span>;
  };

  return (
    <>
      <div className="rounded-lg border border-slate-700 bg-slate-800 overflow-x-auto overflow-y-visible">
        <table className="w-full text-sm text-left">
          <thead className="border-b border-slate-700 bg-slate-800/80 text-[11px] uppercase tracking-wide text-slate-400">
            <tr>
              <th className="px-4 py-2 w-10"></th>
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

              return (
                <tr
                  key={book.id}
                  className="hover:bg-slate-700/50 transition-colors"
                >
                  <td className="px-4 py-2 text-center">
                    {book.is_owned ? (
                      <OwnedIndicator count={book.owned_copy_count} />
                    ) : (
                      <div className="w-4 h-4 rounded-full border border-dashed border-slate-500 mx-auto" />
                    )}
                  </td>
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
                    <MetadataBadges book={book} />
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
                      <ActionIconButton
                        label={book.is_owned ? "Download book" : "No local file available"}
                        onClick={() => downloadBook(book.id)}
                        disabled={!book.is_owned}
                        preferBelow={index === 0}
                      >
                        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v12m0 0l-4-4m4 4l4-4M5 21h14" />
                        </svg>
                      </ActionIconButton>
                      <ActionIconButton
                        label="Delete and re-import metadata"
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
                    </div>
                  </td>
                </tr>
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
