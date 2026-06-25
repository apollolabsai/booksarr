import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useBooks } from "../api/books";
import MobileBookList from "../components/MobileBookList";
import SortControls from "../components/SortControls";
import SearchBar from "../components/SearchBar";
import ViewToggle from "../components/ViewToggle";
import BookTable from "../components/BookTable";
import BookCard from "../components/BookCard";
import { useIsMobile } from "../hooks/useIsMobile";
import { useElementWidth } from "../hooks/useElementWidth";
import { useWindowVirtualRange } from "../hooks/useWindowVirtualRange";
import type { Book } from "../types";
import { compareTitles, titleSortInitial } from "../utils/titleSort";

const SORT_OPTIONS = [
  { value: "title", label: "Title A-Z" },
  { value: "-title", label: "Title Z-A" },
  { value: "author", label: "Author A-Z" },
  { value: "-date", label: "Newest First" },
  { value: "date", label: "Oldest First" },
];

const FILTER_OPTIONS = [
  { value: "all", label: "All Books" },
  { value: "missing", label: "Missing" },
  { value: "epub", label: "EPUB" },
  { value: "mobi", label: "MOBI" },
  { value: "pdf", label: "PDF" },
  { value: "audiobook", label: "Audiobook" },
] as const;
const INDEX_KEYS = ["#", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("")];

type FilterKey = Exclude<(typeof FILTER_OPTIONS)[number]["value"], "all">;

type GenreOption = {
  value: string;
  label: string;
};

type BookScrollTarget = {
  id: number;
  index: number;
};

type BookScrollRequest = BookScrollTarget & {
  sequence: number;
};

function bookMatchesFilter(book: Book, filter: FilterKey): boolean {
  if (filter === "missing") return !book.is_owned;

  return book.local_files.some((file) => (file.file_format || "").toLowerCase() === filter);
}

function getFilterLabel(selected: FilterKey[]) {
  if (selected.length === 0) return "All Books";
  if (selected.length === 1) {
    return FILTER_OPTIONS.find((option) => option.value === selected[0])?.label ?? "All Books";
  }
  return `${selected.length} Filters`;
}

function normalizedGenre(genre: string) {
  return genre.trim().toLocaleLowerCase();
}

function getGenreFilterLabel(selected: string[], options: GenreOption[]) {
  if (selected.length === 0) return "All Genres";
  if (selected.length === 1) {
    return options.find((option) => option.value === selected[0])?.label ?? "1 Genre";
  }
  return `${selected.length} Genres`;
}

function getGridColumnCount(width: number) {
  if (width >= 1024) return 8;
  if (width >= 768) return 6;
  if (width >= 640) return 4;
  return 3;
}

function getGridColumnClass(columns: number) {
  switch (columns) {
    case 8:
      return "grid-cols-8";
    case 6:
      return "grid-cols-6";
    case 4:
      return "grid-cols-4";
    default:
      return "grid-cols-3";
  }
}

function MultiSelectBookFilter({
  selected,
  open,
  onToggleOpen,
  onToggleValue,
  onClear,
  menuRef,
}: {
  selected: FilterKey[];
  open: boolean;
  onToggleOpen: () => void;
  onToggleValue: (value: FilterKey | "all") => void;
  onClear: () => void;
  menuRef: { current: HTMLDivElement | null };
}) {
  return (
    <div ref={(node) => { menuRef.current = node; }} className="relative">
      <button
        type="button"
        onClick={onToggleOpen}
        className="min-w-[164px] rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-slate-200 flex items-center justify-between gap-3"
      >
        <span className="truncate">{getFilterLabel(selected)}</span>
        <svg className="h-4 w-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-2 w-72 rounded-lg border border-slate-600 bg-slate-800 p-2 shadow-xl">
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="text-xs font-medium text-slate-400">
              {selected.length === 0 ? "All books shown" : `${selected.length} selected`}
            </span>
            <button
              type="button"
              onClick={onClear}
              className="text-xs text-emerald-400 hover:text-emerald-300"
            >
              Clear
            </button>
          </div>
          <div className="space-y-1">
            {FILTER_OPTIONS.map((option) => (
              <label
                key={option.value}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-slate-200 hover:bg-slate-700"
              >
                <input
                  type="checkbox"
                  checked={option.value === "all" ? selected.length === 0 : selected.includes(option.value)}
                  onChange={() => onToggleValue(option.value)}
                  className="rounded border-slate-600 bg-slate-700 text-emerald-500 focus:ring-emerald-500"
                />
                <span className="truncate">{option.label}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function MultiSelectGenreFilter({
  options,
  selected,
  open,
  onToggleOpen,
  onToggleValue,
  onClear,
  menuRef,
}: {
  options: GenreOption[];
  selected: string[];
  open: boolean;
  onToggleOpen: () => void;
  onToggleValue: (value: string) => void;
  onClear: () => void;
  menuRef: { current: HTMLDivElement | null };
}) {
  return (
    <div ref={(node) => { menuRef.current = node; }} className="relative">
      <button
        type="button"
        onClick={onToggleOpen}
        disabled={options.length === 0}
        aria-expanded={open}
        className="min-w-[164px] rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-slate-200 flex items-center justify-between gap-3 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span className="truncate">{getGenreFilterLabel(selected, options)}</span>
        <svg className="h-4 w-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-2 w-72 rounded-lg border border-slate-600 bg-slate-800 p-2 shadow-xl">
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="text-xs font-medium text-slate-400">
              {selected.length === 0 ? "All genres shown" : `${selected.length} selected`}
            </span>
            <button
              type="button"
              onClick={onClear}
              className="text-xs text-emerald-400 hover:text-emerald-300"
            >
              Clear
            </button>
          </div>
          <div className="max-h-80 space-y-1 overflow-y-auto">
            <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-slate-200 hover:bg-slate-700">
              <input
                type="checkbox"
                checked={selected.length === 0}
                onChange={onClear}
                className="rounded border-slate-600 bg-slate-700 text-emerald-500 focus:ring-emerald-500"
              />
              <span>All Genres</span>
            </label>
            {options.map((option) => (
              <label
                key={option.value}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-slate-200 hover:bg-slate-700"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(option.value)}
                  onChange={() => onToggleValue(option.value)}
                  className="rounded border-slate-600 bg-slate-700 text-emerald-500 focus:ring-emerald-500"
                />
                <span className="truncate">{option.label}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function BooksPage() {
  const navigate = useNavigate();
  const [sort, setSort] = useState("title");
  const [filters, setFilters] = useState<FilterKey[]>([]);
  const [selectedGenres, setSelectedGenres] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"grid" | "table">("grid");
  const [selectedBookIds, setSelectedBookIds] = useState<Set<number>>(new Set());
  const [filterMenuOpen, setFilterMenuOpen] = useState(false);
  const [genreMenuOpen, setGenreMenuOpen] = useState(false);
  const [selectedIndexKey, setSelectedIndexKey] = useState<string | null>(null);
  const [scrollRequest, setScrollRequest] = useState<BookScrollRequest | null>(null);
  const filterMenuRef = useRef<HTMLDivElement | null>(null);
  const genreMenuRef = useRef<HTMLDivElement | null>(null);
  const { data: books, isLoading } = useBooks(sort, undefined, search);
  const isMobile = useIsMobile();
  const showBulkIrcControls = !isMobile && view === "table";
  const genreOptions = useMemo<GenreOption[]>(() => {
    const labelsByGenre = new Map<string, Map<string, number>>();
    for (const book of books ?? []) {
      for (const genre of book.genres) {
        const value = normalizedGenre(genre);
        if (!value) continue;
        const labels = labelsByGenre.get(value) ?? new Map<string, number>();
        labels.set(genre, (labels.get(genre) ?? 0) + 1);
        labelsByGenre.set(value, labels);
      }
    }

    return Array.from(labelsByGenre, ([value, labels]) => {
      const label = Array.from(labels.entries()).sort((a, b) => (
        b[1] - a[1] || a[0].localeCompare(b[0])
      ))[0][0];
      return { value, label };
    }).sort((a, b) => a.label.localeCompare(b.label));
  }, [books]);
  const filteredBooks = useMemo(() => {
    if (!books) return [];
    return books.filter((book) => {
      const matchesBookFilter = filters.length === 0
        || filters.some((filter) => bookMatchesFilter(book, filter));
      const bookGenres = new Set(book.genres.map(normalizedGenre));
      const matchesGenre = selectedGenres.length === 0
        || selectedGenres.some((genre) => bookGenres.has(genre));
      return matchesBookFilter && matchesGenre;
    });
  }, [books, filters, selectedGenres]);
  const showTitleIndex = sort === "title" || sort === "-title";
  const indexTargets = useMemo(() => {
    const targets = new Map<string, BookScrollTarget>();
    const booksById = new Map(filteredBooks.map((book, index) => [book.id, index]));
    const sortedBooks = [...filteredBooks].sort((a, b) => (
      sort === "-title" ? compareTitles(b.title, a.title) : compareTitles(a.title, b.title)
    ));
    sortedBooks.forEach((book) => {
      const initial = titleSortInitial(book.title);
      const index = booksById.get(book.id);
      if (initial && index != null && !targets.has(initial)) {
        targets.set(initial, { id: book.id, index });
      }
    });
    return targets;
  }, [filteredBooks, sort]);

  const handleSearch = useCallback((v: string) => setSearch(v), []);
  const handleIndexSelect = useCallback((key: string) => {
    const target = indexTargets.get(key);
    if (target == null) return;
    setSelectedIndexKey(key);
    setScrollRequest((current) => ({
      ...target,
      sequence: (current?.sequence ?? 0) + 1,
    }));
  }, [indexTargets]);
  const selectedBooks = useMemo(
    () => filteredBooks.filter((book) => selectedBookIds.has(book.id)),
    [filteredBooks, selectedBookIds],
  );

  useEffect(() => {
    if (showBulkIrcControls) return;
    setSelectedBookIds((current) => (current.size === 0 ? current : new Set()));
  }, [showBulkIrcControls]);

  useEffect(() => {
    const visibleIds = new Set(filteredBooks.map((book) => book.id));
    setSelectedBookIds((current) => {
      const next = new Set(Array.from(current).filter((bookId) => visibleIds.has(bookId)));
      return next.size === current.size ? current : next;
    });
  }, [filteredBooks]);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (filterMenuRef.current && !filterMenuRef.current.contains(event.target as Node)) {
        setFilterMenuOpen(false);
      }
      if (genreMenuRef.current && !genreMenuRef.current.contains(event.target as Node)) {
        setGenreMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, []);

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
    setSelectedBookIds(new Set(filteredBooks.map((book) => book.id)));
  }, [filteredBooks]);

  const selectMissingBooks = useCallback(() => {
    setSelectedBookIds(new Set(filteredBooks.filter((book) => !book.is_owned).map((book) => book.id)));
  }, [filteredBooks]);

  const clearSelectedBooks = useCallback(() => {
    setSelectedBookIds(new Set());
  }, []);

  const toggleFilterValue = useCallback((value: FilterKey | "all") => {
    if (value === "all") {
      setFilters([]);
      return;
    }

    setFilters((current) => (
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value]
    ));
  }, []);

  const toggleGenreValue = useCallback((value: string) => {
    setSelectedGenres((current) => (
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value]
    ));
  }, []);

  const openIrcDownloads = useCallback(() => {
    if (selectedBooks.length === 0) return;
    navigate("/irc-downloads", {
      state: {
        selectedBooks: selectedBooks.map((book) => ({
          id: book.id,
          title: book.title,
          author_name: book.author_name,
          is_owned: book.is_owned,
        })),
      },
    });
  }, [navigate, selectedBooks]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-slate-400">Loading books...</div>
      </div>
    );
  }

  return (
    <div>
      <div className={`mb-6 ${isMobile ? "space-y-3" : "flex items-center justify-between"}`}>
        <h2 className={`${isMobile ? "text-xl" : "text-2xl"} font-bold`}>Books</h2>
        <div className={`flex ${isMobile ? "flex-col gap-2" : "items-center gap-3"}`}>
          <SearchBar value={search} onChange={handleSearch} placeholder="Search books..." />
          <MultiSelectBookFilter
            selected={filters}
            open={filterMenuOpen}
            onToggleOpen={() => {
              setGenreMenuOpen(false);
              setFilterMenuOpen((current) => !current);
            }}
            onToggleValue={toggleFilterValue}
            onClear={() => setFilters([])}
            menuRef={filterMenuRef}
          />
          <MultiSelectGenreFilter
            options={genreOptions}
            selected={selectedGenres}
            open={genreMenuOpen}
            onToggleOpen={() => {
              setFilterMenuOpen(false);
              setGenreMenuOpen((current) => !current);
            }}
            onToggleValue={toggleGenreValue}
            onClear={() => setSelectedGenres([])}
            menuRef={genreMenuRef}
          />
          {isMobile ? (
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value)}
              className="bg-slate-700 border border-slate-600 text-slate-200 text-sm rounded-lg px-3 py-2"
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

      {!!books?.length && showBulkIrcControls && (
        <div className="mb-6 rounded-xl border border-slate-700 bg-slate-800/80 p-4">
          <div className={`${isMobile ? "space-y-3" : "flex items-center justify-between gap-4"}`}>
            <div className="flex flex-wrap items-center gap-2 text-sm text-slate-300">
              <span className="rounded-full bg-slate-700 px-3 py-1">
                {selectedBooks.length} selected
              </span>
              <span className="rounded-full bg-slate-700 px-3 py-1">
                {filteredBooks.filter((book) => !book.is_owned).length} missing in view
              </span>
            </div>
            <div className={`flex ${isMobile ? "flex-col gap-2" : "flex-wrap items-center gap-2"}`}>
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

      {filteredBooks.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-slate-400 text-lg">No books found</p>
        </div>
      ) : isMobile ? (
        <>
          <div className={showTitleIndex ? "pr-7" : ""}>
            <MobileBookList
              books={filteredBooks}
              showAuthor={true}
              selectedBookIds={selectedBookIds}
              onToggleSelected={toggleBookSelection}
              scrollRequest={scrollRequest}
            />
          </div>
          {showTitleIndex && (
            <BookTitleIndex
              targets={indexTargets}
              selectedKey={selectedIndexKey}
              onSelect={handleIndexSelect}
              compact
            />
          )}
        </>
      ) : view === "table" ? (
        <>
          <div className={showTitleIndex ? "pr-8" : ""}>
            <BookTable
              books={filteredBooks}
              showAuthor={true}
              selectedBookIds={showBulkIrcControls ? selectedBookIds : undefined}
              onToggleSelected={showBulkIrcControls ? toggleBookSelection : undefined}
              scrollRequest={scrollRequest}
            />
          </div>
          {showTitleIndex && (
            <BookTitleIndex
              targets={indexTargets}
              selectedKey={selectedIndexKey}
              onSelect={handleIndexSelect}
            />
          )}
        </>
      ) : (
        <>
          <VirtualBookGrid
            books={filteredBooks}
            selectedBookIds={selectedBookIds}
            onToggleSelected={showBulkIrcControls ? toggleBookSelection : undefined}
            scrollRequest={scrollRequest}
            reserveIndexSpace={showTitleIndex}
          />
          {showTitleIndex && (
            <BookTitleIndex
              targets={indexTargets}
              selectedKey={selectedIndexKey}
              onSelect={handleIndexSelect}
            />
          )}
        </>
      )}
    </div>
  );
}

function BookTitleIndex({
  targets,
  selectedKey,
  onSelect,
  compact = false,
}: {
  targets: Map<string, BookScrollTarget>;
  selectedKey: string | null;
  onSelect: (key: string) => void;
  compact?: boolean;
}) {
  return (
    <nav
      aria-label="Book title index"
      className={`fixed right-2 top-1/2 z-30 flex -translate-y-1/2 flex-col rounded-full border border-slate-700 bg-slate-950/90 py-1 shadow-xl shadow-black/30 backdrop-blur ${
        compact ? "max-h-[70vh]" : "max-h-[80vh]"
      }`}
    >
      {INDEX_KEYS.map((key) => {
        const enabled = targets.has(key);
        const selected = selectedKey === key;
        return (
          <button
            key={key}
            type="button"
            disabled={!enabled}
            aria-label={key === "#" ? "Jump to numeric titles" : `Jump to books starting with ${key}`}
            onClick={() => onSelect(key)}
            className={`h-5 w-7 text-[11px] font-semibold leading-5 transition ${
              selected
                ? "text-emerald-300"
                : enabled
                  ? "text-slate-300 hover:text-emerald-300"
                  : "cursor-default text-slate-700"
            }`}
          >
            {key}
          </button>
        );
      })}
    </nav>
  );
}

function VirtualBookGrid({
  books,
  selectedBookIds,
  onToggleSelected,
  scrollRequest,
  reserveIndexSpace = false,
}: {
  books: Book[];
  selectedBookIds: Set<number>;
  onToggleSelected?: (bookId: number) => void;
  scrollRequest: BookScrollRequest | null;
  reserveIndexSpace?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const width = useElementWidth(containerRef);
  const fallbackWidth = typeof window === "undefined" ? 1280 : window.innerWidth;
  const columns = getGridColumnCount(width || fallbackWidth);
  const gap = 16;
  const cardWidth = width > 0 ? (width - gap * (columns - 1)) / columns : 140;
  const rowHeight = Math.ceil(cardWidth * 4 / 3 + 78 + gap);
  const rowCount = Math.ceil(books.length / columns);
  const virtualRows = useWindowVirtualRange(containerRef, rowCount, rowHeight, 4);

  useEffect(() => {
    if (!scrollRequest) return;
    virtualRows.scrollToIndex(Math.floor(scrollRequest.index / columns));
  }, [columns, scrollRequest, virtualRows.scrollToIndex]);

  return (
    <div className={reserveIndexSpace ? "pr-8" : ""}>
      <div ref={containerRef} className="relative" style={{ height: virtualRows.totalSize }}>
        <div
          className="absolute left-0 right-0 space-y-4"
          style={{ transform: `translateY(${virtualRows.offsetTop}px)` }}
        >
          {virtualRows.virtualIndexes.map((rowIndex) => {
            const start = rowIndex * columns;
            const rowBooks = books.slice(start, start + columns);
            return (
              <div key={rowIndex} className={`grid ${getGridColumnClass(columns)} gap-4`}>
                {rowBooks.map((book) => (
                  <BookCard
                    key={book.id}
                    book={book}
                    showAuthor={true}
                    selected={selectedBookIds.has(book.id)}
                    onToggleSelected={onToggleSelected ? () => onToggleSelected(book.id) : undefined}
                  />
                ))}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
