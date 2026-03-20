import { useState, useCallback } from "react";
import { useBooks } from "../api/books";
import { getImageUrl } from "../types";
import SortControls from "../components/SortControls";
import SearchBar from "../components/SearchBar";
import ViewToggle from "../components/ViewToggle";
import BookTable from "../components/BookTable";
import { Link } from "react-router-dom";

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
          {books.map((book) => {
            const imgUrl = getImageUrl(book.cover_image_cached_path, book.cover_image_url);
            return (
              <div key={book.id} className={`group cursor-pointer ${!book.is_owned ? "opacity-60" : ""}`}
                onClick={() => book.hardcover_slug && window.open(`https://hardcover.app/books/${book.hardcover_slug}`, "_blank", "noopener,noreferrer")}
              >
                <div className="relative aspect-[2/3] bg-slate-700 rounded-lg overflow-hidden border border-slate-600 group-hover:border-emerald-500/50 transition-all">
                  {imgUrl ? (
                    <img src={imgUrl} alt={book.title} className="w-full h-full object-cover" loading="lazy" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center p-2 text-center text-xs text-slate-400">
                      {book.title}
                    </div>
                  )}
                  {book.is_owned && (
                    <div className="absolute top-1.5 right-1.5 bg-emerald-500 rounded-full p-0.5">
                      <svg className="w-2.5 h-2.5 text-white" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                    </div>
                  )}
                </div>
                <p className="mt-1.5 text-xs font-medium text-slate-200 truncate group-hover:text-emerald-400 transition-colors">{book.title}</p>
                <Link to={`/authors/${book.author_id}`} className="text-xs text-slate-500 hover:text-emerald-400 truncate block"
                  onClick={(e) => e.stopPropagation()}
                >
                  {book.author_name}
                </Link>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
