import { useState, useCallback } from "react";
import { useBooks } from "../api/books";
import SortControls from "../components/SortControls";
import SearchBar from "../components/SearchBar";
import ViewToggle from "../components/ViewToggle";
import BookTable from "../components/BookTable";
import BookCard from "../components/BookCard";

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
  const [sort, setSort] = useState("title");
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"grid" | "table">("grid");
  const owned = filter === "owned" ? true : filter === "missing" ? false : undefined;
  const { data: books, isLoading } = useBooks(sort, owned, search);

  const handleSearch = useCallback((v: string) => setSearch(v), []);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-slate-400">Loading books...</div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Books</h2>
        <div className="flex items-center gap-3">
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
          <SortControls options={SORT_OPTIONS} value={sort} onChange={setSort} />
          <ViewToggle view={view} onChange={setView} />
        </div>
      </div>

      {!books || books.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-slate-400 text-lg">No books found</p>
        </div>
      ) : view === "table" ? (
        <BookTable books={books} showAuthor={true} />
      ) : (
        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 xl:grid-cols-10 gap-4">
          {books.map((book) => (
            <BookCard key={book.id} book={book} showAuthor={true} />
          ))}
        </div>
      )}
    </div>
  );
}
