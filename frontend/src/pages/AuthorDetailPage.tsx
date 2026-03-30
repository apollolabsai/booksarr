import { useState, useCallback, useEffect, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import { useAuthor, useMergeAuthorDirectories, useRefreshAuthor } from "../api/authors";
import { getImageUrl } from "../types";
import type { BookInAuthor, SeriesInAuthor } from "../types";
import BookCard from "../components/BookCard";
import BookTable from "../components/BookTable";
import SeriesGroup from "../components/SeriesGroup";
import SortControls from "../components/SortControls";
import ViewToggle from "../components/ViewToggle";
import SearchBar from "../components/SearchBar";
import AuthorPortraitPickerDialog from "../components/AuthorPortraitPickerDialog";

const SORT_OPTIONS = [
  { value: "series", label: "By Series" },
  { value: "title", label: "Title A-Z" },
  { value: "-date", label: "Newest First" },
  { value: "date", label: "Oldest First" },
  { value: "owned", label: "Owned First" },
];

export default function AuthorDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: author, isLoading } = useAuthor(Number(id));
  const refreshAuthor = useRefreshAuthor();
  const mergeAuthorDirectories = useMergeAuthorDirectories();
  const [sort, setSort] = useState("series");
  const [view, setView] = useState<"grid" | "table">("grid");
  const [search, setSearch] = useState("");
  const [bioExpanded, setBioExpanded] = useState(false);
  const [portraitPickerOpen, setPortraitPickerOpen] = useState(false);
  const [portraitMenuOpen, setPortraitMenuOpen] = useState(false);
  const [mergeFoldersOpen, setMergeFoldersOpen] = useState(false);
  const [mergeTargetDirectoryId, setMergeTargetDirectoryId] = useState<number | null>(null);
  const portraitMenuRef = useRef<HTMLDivElement | null>(null);
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

  if (isLoading || !author) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-slate-400">Loading...</div>
      </div>
    );
  }

  const imgUrl = getImageUrl(author.image_cached_path, author.image_url);

  const searchNormalized = search.trim().toLowerCase();
  const filteredBooks = searchNormalized
    ? author.books.filter((book) => book.title.toLowerCase().includes(searchNormalized))
    : author.books;

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
  const filteredSeries: SeriesInAuthor[] = author.series
    .map((series) => ({
      ...series,
      books: series.books.filter((book) => filteredBookIds.has(book.book_id)),
    }))
    .filter((series) => series.books.length > 0);

  // Determine standalone books (not in any visible series)
  const booksInSeries = new Set<number>();
  filteredSeries.forEach((s) => s.books.forEach((b) => booksInSeries.add(b.book_id)));
  const standaloneBooks = sortedBooks.filter((b) => !booksInSeries.has(b.id));

  const bioTruncated = author.bio && author.bio.length > 400;
  const displayBio = bioExpanded ? author.bio : author.bio?.substring(0, 400);

  const renderBooks = () => {
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
                  <BookTable books={seriesFullBooks} showAuthor={false} authorName={author.name} />
                </div>
              );
            })}
            {standaloneBooks.length > 0 && (
              <div className="mb-6">
                <h3 className="text-lg font-semibold text-slate-200 mb-3">Standalone</h3>
                <BookTable books={standaloneBooks} showAuthor={false} authorName={author.name} />
              </div>
            )}
          </>
        );
      }
      return <BookTable books={sortedBooks} showAuthor={false} authorName={author.name} />;
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
      <div className="flex gap-6 mb-8 mt-4">
        <div
          ref={portraitMenuRef}
          className="group relative w-40 h-52 flex-shrink-0 rounded-lg overflow-hidden bg-slate-700"
        >
          {imgUrl ? (
            <img src={imgUrl} alt={author.name} className="w-full h-full object-cover" />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-5xl font-bold text-slate-500">
              {author.name.charAt(0)}
            </div>
          )}
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
        </div>
        <div className="flex-1 min-w-0">
          <div className="mb-2">
            <div className="flex items-center gap-3">
              <h1 className="text-3xl font-bold">{author.name}</h1>
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
            </div>
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
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold">Books</h2>
        <div className="flex items-center gap-3">
          <SearchBar value={search} onChange={handleSearch} placeholder="Search this author..." />
          <SortControls options={SORT_OPTIONS} value={sort} onChange={setSort} />
          <ViewToggle view={view} onChange={setView} />
        </div>
      </div>

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
