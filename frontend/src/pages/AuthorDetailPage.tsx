import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useAuthor, useMergeAuthorDirectories, useRefreshAuthor, useRemoveAuthor } from "../api/authors";
import { getImageUrl } from "../types";
import type { BookInAuthor, SeriesInAuthor, UnmatchedLocalFile } from "../types";
import BookCard from "../components/BookCard";
import BookTable from "../components/BookTable";
import MobileBookList from "../components/MobileBookList";
import SeriesGroup from "../components/SeriesGroup";
import SortControls from "../components/SortControls";
import ViewToggle from "../components/ViewToggle";
import SearchBar from "../components/SearchBar";
import AuthorPortraitPickerDialog from "../components/AuthorPortraitPickerDialog";
import { useIsMobile } from "../hooks/useIsMobile";

const SORT_OPTIONS = [
  { value: "series", label: "By Series" },
  { value: "title", label: "Title A-Z" },
  { value: "-date", label: "Newest First" },
  { value: "date", label: "Oldest First" },
  { value: "owned", label: "Owned First" },
];

const UNMATCHED_FORMAT_STYLES: Record<string, string> = {
  epub: "bg-emerald-500/15 text-emerald-300",
  mobi: "bg-blue-500/15 text-blue-300",
  audiobook: "bg-purple-500/15 text-purple-300",
};

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

function UnmatchedFileTag({ format }: { format: string | null }) {
  const key = (format || "").toLowerCase();
  const label = key === "audiobook" ? "AUDIO" : (key || "FILE").toUpperCase();
  const colorClass = UNMATCHED_FORMAT_STYLES[key] ?? "bg-slate-700 text-slate-300";
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${colorClass}`}>
      {label}
    </span>
  );
}

export default function AuthorDetailPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const { data: author, isLoading } = useAuthor(Number(id));
  const refreshAuthor = useRefreshAuthor();
  const removeAuthor = useRemoveAuthor();
  const mergeAuthorDirectories = useMergeAuthorDirectories();
  const isMobile = useIsMobile();
  const [sort, setSort] = useState("series");
  const [view, setView] = useState<"grid" | "table">("grid");
  const [search, setSearch] = useState("");
  const [bioExpanded, setBioExpanded] = useState(false);
  const [portraitPickerOpen, setPortraitPickerOpen] = useState(false);
  const [portraitMenuOpen, setPortraitMenuOpen] = useState(false);
  const [mergeFoldersOpen, setMergeFoldersOpen] = useState(false);
  const [mergeTargetDirectoryId, setMergeTargetDirectoryId] = useState<number | null>(null);
  const [selectedBookIds, setSelectedBookIds] = useState<Set<number>>(new Set());
  const portraitMenuRef = useRef<HTMLDivElement | null>(null);
  const authorName = author?.name ?? "Unknown author";
  const handleSearch = useCallback((value: string) => setSearch(value), []);

  useEffect(() => {
    if (!author) {
      setMergeTargetDirectoryId(null);
      return;
    }
    const preferredDirectory = author.author_directories.find((directory) => directory.is_primary) ?? author.author_directories[0];
    setMergeTargetDirectoryId(preferredDirectory?.id ?? null);
  }, [author]);

  useEffect(() => {
    if (!portraitMenuOpen) return;

    const handlePointerDown = (event: MouseEvent) => {
      if (portraitMenuRef.current && !portraitMenuRef.current.contains(event.target as Node)) {
        setPortraitMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [portraitMenuOpen]);
  const imgUrl = author ? getImageUrl(author.image_cached_path, author.image_url) : "";

  const searchNormalized = search.trim().toLowerCase();
  const filteredBooks = searchNormalized
    ? (author?.books ?? []).filter((book) => book.title.toLowerCase().includes(searchNormalized))
    : (author?.books ?? []);
  const filteredUnmatchedLocalFiles: UnmatchedLocalFile[] = searchNormalized
    ? (author?.unmatched_local_files ?? []).filter((file) =>
      file.file_path.toLowerCase().includes(searchNormalized)
      || (file.linked_book_title ?? "").toLowerCase().includes(searchNormalized))
    : (author?.unmatched_local_files ?? []);

  // Sort books
  const sortedBooks = [...filteredBooks].sort((a, b) => {
    switch (sort) {
      case "title":
        return a.title.localeCompare(b.title);
      case "-date":
        return (b.release_date || "").localeCompare(a.release_date || "");
      case "date":
        return (a.release_date || "").localeCompare(b.release_date || "");
      case "owned":
        return (b.is_owned ? 1 : 0) - (a.is_owned ? 1 : 0);
      default:
        return 0;
    }
  });

  const filteredBookIds = new Set(sortedBooks.map((book) => book.id));
  const filteredSeries: SeriesInAuthor[] = (author?.series ?? [])
    .map((series) => ({
      ...series,
      books: series.books.filter((book) => filteredBookIds.has(book.book_id)),
    }))
    .filter((series) => series.books.length > 0);

  // Determine standalone books (not in any visible series)
  const booksInSeries = new Set<number>();
  filteredSeries.forEach((s) => s.books.forEach((b) => booksInSeries.add(b.book_id)));
  const standaloneBooks = sortedBooks.filter((b) => !booksInSeries.has(b.id));
  const showBulkIrcControls = !isMobile && view === "table";
  const selectedBooks = useMemo(
    () => sortedBooks.filter((book) => selectedBookIds.has(book.id)),
    [selectedBookIds, sortedBooks],
  );

  const bioTruncated = Boolean(author?.bio && author.bio.length > 400);
  const displayBio = bioExpanded ? author?.bio : author?.bio?.substring(0, 400);

  useEffect(() => {
    if (showBulkIrcControls) return;
    setSelectedBookIds((current) => (current.size === 0 ? current : new Set()));
  }, [showBulkIrcControls]);

  useEffect(() => {
    const visibleIds = new Set(sortedBooks.map((book) => book.id));
    setSelectedBookIds((current) => {
      const next = new Set(Array.from(current).filter((bookId) => visibleIds.has(bookId)));
      return next.size === current.size ? current : next;
    });
  }, [sortedBooks]);

  const toggleBookSelection = useCallback((bookId: number) => {
    setSelectedBookIds((current) => {
      const next = new Set(current);
      if (next.has(bookId)) {
        next.delete(bookId);
      } else {
        next.add(bookId);
      }
      return next;
    });
  }, []);

  const selectVisibleBooks = useCallback(() => {
    setSelectedBookIds(new Set(sortedBooks.map((book) => book.id)));
  }, [sortedBooks]);

  const selectMissingBooks = useCallback(() => {
    setSelectedBookIds(new Set(sortedBooks.filter((book) => !book.is_owned).map((book) => book.id)));
  }, [sortedBooks]);

  const clearSelectedBooks = useCallback(() => {
    setSelectedBookIds(new Set());
  }, []);

  const openIrcDownloads = useCallback(() => {
    if (selectedBooks.length === 0) return;
    navigate("/irc-downloads", {
      state: {
        selectedBooks: selectedBooks.map((book) => ({
          id: book.id,
          title: book.title,
          author_name: authorName,
          is_owned: book.is_owned,
        })),
      },
    });
  }, [authorName, navigate, selectedBooks]);

  const handleRemoveAuthor = useCallback(async () => {
    if (!author) return;
    const confirmed = window.confirm(
      `Remove ${author.name} and all of this author's books from the database?\n\nThis will not delete any files or folders.`,
    );
    if (!confirmed) return;

    await removeAuthor.mutateAsync(author.id);
    navigate("/", { replace: true });
  }, [author, navigate, removeAuthor]);

  if (isLoading || !author) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-slate-400">Loading...</div>
      </div>
    );
  }

  const renderBooks = () => {
    if (isMobile) {
      return <MobileBookList books={sortedBooks} showAuthor={false} />;
    }

    if (view === "table") {
      if (sort === "series") {
        return (
          <>
            {filteredSeries.map((s) => {
              const seriesBookIds = new Set(s.books.map((b) => b.book_id));
              const seriesFullBooks = sortedBooks.filter((b) => seriesBookIds.has(b.id));
              // Sort by series position
              seriesFullBooks.sort((a, b) => {
                const posA = s.books.find((sb) => sb.book_id === a.id)?.position ?? 9999;
                const posB = s.books.find((sb) => sb.book_id === b.id)?.position ?? 9999;
                return posA - posB;
              });
              const ownedCount = s.books.filter((b) => b.is_owned).length;
              return (
                <div key={s.id} className="mb-6">
                  <div className="flex items-center gap-3 mb-3">
                    <h3 className="text-lg font-semibold text-slate-200">{s.name}</h3>
                    <span className="text-sm text-slate-400">
                      <span className="text-emerald-400">{ownedCount}</span> / {s.books.length} books
                    </span>
                  </div>
                  <BookTable
                    books={seriesFullBooks}
                    showAuthor={false}
                    authorName={author.name}
                    selectedBookIds={showBulkIrcControls ? selectedBookIds : undefined}
                    onToggleSelected={showBulkIrcControls ? toggleBookSelection : undefined}
                  />
                </div>
              );
            })}
            {standaloneBooks.length > 0 && (
              <div className="mb-6">
                <h3 className="text-lg font-semibold text-slate-200 mb-3">Standalone</h3>
                <BookTable
                  books={standaloneBooks}
                  showAuthor={false}
                  authorName={author.name}
                  selectedBookIds={showBulkIrcControls ? selectedBookIds : undefined}
                  onToggleSelected={showBulkIrcControls ? toggleBookSelection : undefined}
                />
              </div>
            )}
          </>
        );
      }
      return (
        <BookTable
          books={sortedBooks}
          showAuthor={false}
          authorName={author.name}
          selectedBookIds={showBulkIrcControls ? selectedBookIds : undefined}
          onToggleSelected={showBulkIrcControls ? toggleBookSelection : undefined}
        />
      );
    }

    // Grid view
    if (sort === "series") {
      return (
        <>
          {filteredSeries.map((s) => (
            <SeriesGroup key={s.id} series={s} allBooks={sortedBooks} />
          ))}
          {standaloneBooks.length > 0 && (
            <div className="mb-8">
              <h3 className="text-lg font-semibold text-slate-200 mb-4">Standalone</h3>
              <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-4">
                {standaloneBooks.map((book) => (
                  <BookCard key={book.id} book={book} authorName={author.name} />
                ))}
              </div>
            </div>
          )}
        </>
      );
    }

    return (
      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-4">
        {sortedBooks.map((book) => (
          <BookCard key={book.id} book={book} authorName={author.name} />
        ))}
      </div>
    );
  };

  return (
    <div>
      <Link to="/" className="text-slate-400 hover:text-emerald-400 text-sm mb-4 inline-flex items-center gap-1">
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
        Back to Authors
      </Link>

      {/* Hero Section */}
      <div className={`${isMobile ? "mt-2 mb-6 block" : "mt-4 mb-8 flex gap-6"}`}>
        <div
          ref={portraitMenuRef}
          className={`group relative overflow-hidden rounded-lg bg-slate-700 ${isMobile ? "mx-auto mb-4 h-40 w-32" : "h-52 w-40 flex-shrink-0"}`}
        >
          {imgUrl ? (
            <img src={imgUrl} alt={author.name} className="w-full h-full object-cover" />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-5xl font-bold text-slate-500">
              {author.name.charAt(0)}
            </div>
          )}
          {!isMobile && (
            <div className="absolute bottom-2 left-2 right-2">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setPortraitMenuOpen((current) => !current);
                }}
                className="rounded-md border border-slate-500/60 bg-slate-900/70 px-1.5 py-1 text-slate-100 opacity-0 transition-opacity hover:bg-slate-800/90 group-hover:opacity-100"
                title="Author actions"
              >
                <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
                  <circle cx="5" cy="12" r="1.75" />
                  <circle cx="12" cy="12" r="1.75" />
                  <circle cx="19" cy="12" r="1.75" />
                </svg>
              </button>
              {portraitMenuOpen && (
                <div
                  className="absolute bottom-9 left-0 right-0 z-20 rounded-lg border border-slate-600 bg-slate-900/95 p-1 shadow-xl"
                  onClick={(e) => e.stopPropagation()}
                >
                  <button
                    type="button"
                    onClick={() => {
                      setPortraitMenuOpen(false);
                      setPortraitPickerOpen(true);
                    }}
                    className="flex w-full items-center rounded-md px-2.5 py-1.5 text-xs text-slate-200 transition-colors hover:bg-slate-800"
                  >
                    Choose Portrait
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="mb-2">
            <div className={`flex ${isMobile ? "flex-col items-start gap-2" : "items-center gap-3"}`}>
              <h1 className={`${isMobile ? "text-2xl" : "text-3xl"} font-bold`}>{author.name}</h1>
              <button
                type="button"
                onClick={() => refreshAuthor.mutate(author.id)}
                disabled={refreshAuthor.isPending}
                className="inline-flex items-center gap-2 rounded-md border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-200 transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                title="Refresh this author and rescan local files for newly added books"
              >
                <svg className={`h-4 w-4 ${refreshAuthor.isPending ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m14.836 2A8.001 8.001 0 005.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.356-2m15.356 2H15" />
                </svg>
                {refreshAuthor.isPending ? "Refreshing..." : "Refresh Author"}
              </button>
              <button
                type="button"
                onClick={handleRemoveAuthor}
                disabled={removeAuthor.isPending}
                className="inline-flex items-center gap-2 rounded-md border border-rose-700 bg-rose-950/40 px-3 py-1.5 text-sm text-rose-200 transition-colors hover:bg-rose-900/50 disabled:cursor-not-allowed disabled:opacity-50"
                title="Remove this author and all linked books from the database without deleting files"
              >
                <svg className={`h-4 w-4 ${removeAuthor.isPending ? "animate-pulse" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 7h12M9 7V5h6v2m-7 4v6m4-6v6m4-6v6M5 7l1 12h12l1-12" />
                </svg>
                {removeAuthor.isPending ? "Removing..." : "Remove Author"}
              </button>
            </div>
            {removeAuthor.error && (
              <div className="mt-2 text-sm text-rose-300">
                {removeAuthor.error instanceof Error
                  ? removeAuthor.error.message
                  : "Unable to remove author"}
              </div>
            )}
          </div>
          <div className="flex gap-4 text-sm text-slate-400 mb-4">
            <span><span className="text-emerald-400 font-semibold">{author.book_count_local}</span> owned</span>
            <span><span className="text-slate-200 font-semibold">{author.book_count_total}</span> total books</span>
            <span><span className="text-slate-200 font-semibold">{author.series.length}</span> series</span>
          </div>
          {author.author_directories.length > 0 && (
            <div className="mb-4">
              <div className="mb-1 flex items-center gap-3">
                <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                  Linked Folder Paths
                </div>
                {author.author_directories.length > 1 && (
                  <button
                    type="button"
                    onClick={() => setMergeFoldersOpen((current) => !current)}
                    className="rounded-md border border-slate-600 bg-slate-800 px-2 py-1 text-[11px] font-medium text-slate-200 transition-colors hover:bg-slate-700"
                  >
                    {mergeFoldersOpen ? "Cancel Merge" : "Merge Folders"}
                  </button>
                )}
              </div>
              <div className="space-y-1">
                {author.author_directories.map((directory) => (
                  <div key={directory.id} className="flex items-start gap-2 text-sm text-slate-300">
                    <code className="break-all rounded bg-slate-800 px-2 py-1 text-xs text-slate-200">
                      {directory.dir_path}
                    </code>
                    {directory.is_primary && (
                      <span className="rounded bg-emerald-500/15 px-2 py-1 text-[11px] font-medium text-emerald-300">
                        Primary
                      </span>
                    )}
                  </div>
                ))}
              </div>
              {mergeFoldersOpen && author.author_directories.length > 1 && (
                <div className="mt-3 rounded-lg border border-slate-700 bg-slate-900/70 p-3">
                  <div className="mb-2 text-sm font-medium text-slate-200">Choose the folder to keep</div>
                  <div className="mb-3 text-xs text-slate-400">
                    Booksarr will move all books from the other linked author folders into the selected folder, update linked file paths, and remove the empty folder mappings. If conflicting file names already exist, the merge will stop instead of overwriting anything.
                  </div>
                  <div className="space-y-2">
                    {author.author_directories.map((directory) => (
                      <label
                        key={directory.id}
                        className="flex cursor-pointer items-start gap-2 rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800/70"
                      >
                        <input
                          type="radio"
                          name="merge-target-directory"
                          checked={mergeTargetDirectoryId === directory.id}
                          onChange={() => setMergeTargetDirectoryId(directory.id)}
                          className="mt-0.5"
                        />
                        <div className="flex min-w-0 items-center gap-2">
                          <code className="break-all text-xs text-slate-200">{directory.dir_path}</code>
                          {directory.is_primary && (
                            <span className="rounded bg-emerald-500/15 px-2 py-0.5 text-[11px] font-medium text-emerald-300">
                              Current primary
                            </span>
                          )}
                        </div>
                      </label>
                    ))}
                  </div>
                  {mergeAuthorDirectories.error && (
                    <div className="mt-3 text-xs text-rose-300">
                      {mergeAuthorDirectories.error instanceof Error
                        ? mergeAuthorDirectories.error.message
                        : "Unable to merge author folders"}
                    </div>
                  )}
                  <div className="mt-3 flex gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        if (!mergeTargetDirectoryId) return;
                        mergeAuthorDirectories.mutate(
                          {
                            authorId: author.id,
                            targetDirectoryId: mergeTargetDirectoryId,
                          },
                          {
                            onSuccess: () => {
                              setMergeFoldersOpen(false);
                            },
                          },
                        );
                      }}
                      disabled={!mergeTargetDirectoryId || mergeAuthorDirectories.isPending}
                      className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {mergeAuthorDirectories.isPending ? "Merging..." : "Merge Into Selected Folder"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setMergeFoldersOpen(false)}
                      className="rounded-md border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-200 transition-colors hover:bg-slate-700"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
          {filteredUnmatchedLocalFiles.length > 0 && (
            <div className="mb-4 rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
              <div className="mb-1 flex items-center gap-3">
                <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-amber-200">
                  Unmatched Local Files
                </h2>
                <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-medium text-amber-300">
                  {filteredUnmatchedLocalFiles.length}
                </span>
              </div>
              <p className="mb-3 text-sm text-slate-300">
                Files currently present in this author&apos;s linked folder paths that are not attached to any shown book.
              </p>
              <div className="space-y-2">
                {filteredUnmatchedLocalFiles.map((file) => (
                  <div key={file.file_path} className="rounded-lg border border-slate-700 bg-slate-900/60 p-3">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <UnmatchedFileTag format={file.file_format} />
                      <span className="text-xs text-slate-400">{formatFileSize(file.file_size)}</span>
                    </div>
                    <code className="block break-all text-xs text-slate-200">{file.file_path}</code>
                    {file.linked_book_title && (
                      <div className="mt-2 text-xs text-amber-300">
                        Linked to hidden book: {file.linked_book_title}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          {author.bio && (
            <div className="text-sm text-slate-300 leading-relaxed">
              <p className="whitespace-pre-line">{displayBio}{bioTruncated && !bioExpanded ? "..." : ""}</p>
              {bioTruncated && (
                <button
                  onClick={() => setBioExpanded(!bioExpanded)}
                  className="text-emerald-400 hover:underline mt-1"
                >
                  {bioExpanded ? "Show less" : "Read more"}
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Sort + View Controls */}
      <div className={`mb-6 ${isMobile ? "space-y-3" : "flex items-center justify-between"}`}>
        <h2 className="text-xl font-semibold">Books</h2>
        <div className={`flex ${isMobile ? "flex-col gap-2" : "items-center gap-3"}`}>
          <SearchBar value={search} onChange={handleSearch} placeholder="Search this author..." />
          {isMobile ? (
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
            >
              {SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          ) : (
            <>
              <SortControls options={SORT_OPTIONS} value={sort} onChange={setSort} />
              <ViewToggle view={view} onChange={setView} />
            </>
          )}
        </div>
      </div>

      {showBulkIrcControls && sortedBooks.length > 0 && (
        <div className="mb-6 rounded-xl border border-slate-700 bg-slate-800/80 p-4">
          <div className="flex items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-2 text-sm text-slate-300">
              <span className="rounded-full bg-slate-700 px-3 py-1">
                {selectedBooks.length} selected
              </span>
              <span className="rounded-full bg-slate-700 px-3 py-1">
                {sortedBooks.filter((book) => !book.is_owned).length} missing in view
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={selectVisibleBooks}
                className="rounded-md border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-slate-100 hover:bg-slate-600"
              >
                Select Visible
              </button>
              <button
                type="button"
                onClick={selectMissingBooks}
                className="rounded-md border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-slate-100 hover:bg-slate-600"
              >
                Select Missing
              </button>
              <button
                type="button"
                onClick={clearSelectedBooks}
                disabled={selectedBooks.length === 0}
                className="rounded-md border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-slate-100 hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Clear
              </button>
              <button
                type="button"
                onClick={openIrcDownloads}
                disabled={selectedBooks.length === 0}
                className="rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Download Selected From IRC
              </button>
            </div>
          </div>
        </div>
      )}

      {sortedBooks.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-slate-400 text-lg">No matching books found</p>
        </div>
      ) : (
        renderBooks()
      )}
      <AuthorPortraitPickerDialog
        authorId={author.id}
        authorName={author.name}
        open={portraitPickerOpen}
        onClose={() => setPortraitPickerOpen(false)}
      />
    </div>
  );
}
