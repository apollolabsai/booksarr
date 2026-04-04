import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useBooks } from "../api/books";
import MobileBookList from "../components/MobileBookList";
import SortControls from "../components/SortControls";
import SearchBar from "../components/SearchBar";
import ViewToggle from "../components/ViewToggle";
import BookTable from "../components/BookTable";
import BookCard from "../components/BookCard";
import { useIsMobile } from "../hooks/useIsMobile";

const SORT_OPTIONS = [
  { value: "title", label: "Title A-Z" },
  { value: "-title", label: "Title Z-A" },
  { value: "author", label: "Author A-Z" },
  { value: "-date", label: "Newest First" },
  { value: "date", label: "Oldest First" },
];

const FILTER_OPTIONS = [
  { value: "all", label: "All Books" },
  { value: "owned", label: "Owned" },
  { value: "missing", label: "Missing" },
];

export default function BooksPage() {
  const navigate = useNavigate();
  const [sort, setSort] = useState("title");
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"grid" | "table">("grid");
  const [selectedBookIds, setSelectedBookIds] = useState<Set<number>>(new Set());
  const owned = filter === "owned" ? true : filter === "missing" ? false : undefined;
  const { data: books, isLoading } = useBooks(sort, owned, search);
  const isMobile = useIsMobile();
  const showBulkIrcControls = !isMobile && view === "table";

  const handleSearch = useCallback((v: string) => setSearch(v), []);
  const selectedBooks = useMemo(
    () => (books ?? []).filter((book) => selectedBookIds.has(book.id)),
    [books, selectedBookIds],
  );

  useEffect(() => {
    if (showBulkIrcControls) return;
    setSelectedBookIds((current) => (current.size === 0 ? current : new Set()));
  }, [showBulkIrcControls]);

  useEffect(() => {
    if (!books) return;
    const visibleIds = new Set(books.map((book) => book.id));
    setSelectedBookIds((current) => {
      const next = new Set(Array.from(current).filter((bookId) => visibleIds.has(bookId)));
      return next.size === current.size ? current : next;
    });
  }, [books]);

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
    setSelectedBookIds(new Set((books ?? []).map((book) => book.id)));
  }, [books]);

  const selectMissingBooks = useCallback(() => {
    setSelectedBookIds(new Set((books ?? []).filter((book) => !book.is_owned).map((book) => book.id)));
  }, [books]);

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
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="bg-slate-700 border border-slate-600 text-slate-200 text-sm rounded-lg px-3 py-2"
          >
            {FILTER_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
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
                {(books ?? []).filter((book) => !book.is_owned).length} missing in view
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

      {!books || books.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-slate-400 text-lg">No books found</p>
        </div>
      ) : isMobile ? (
        <MobileBookList
          books={books}
          showAuthor={true}
          selectedBookIds={selectedBookIds}
          onToggleSelected={toggleBookSelection}
        />
      ) : view === "table" ? (
        <BookTable
          books={books}
          showAuthor={true}
          selectedBookIds={showBulkIrcControls ? selectedBookIds : undefined}
          onToggleSelected={showBulkIrcControls ? toggleBookSelection : undefined}
        />
      ) : (
        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-4">
          {books.map((book) => (
            <BookCard key={book.id} book={book} showAuthor={true} />
          ))}
        </div>
      )}
    </div>
  );
}
