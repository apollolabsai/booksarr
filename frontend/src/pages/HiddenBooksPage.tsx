import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useHiddenBooks } from "../api/books";
import SearchBar from "../components/SearchBar";
import { getBookCoverPresentation, getImageUrl } from "../types";

type SortKey = "title" | "author" | "hidden_by" | "year";

export default function HiddenBooksPage() {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("title");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const { data: books, isLoading } = useHiddenBooks(search);

  const handleSearch = useCallback((value: string) => setSearch(value), []);
  const handleSort = useCallback((nextKey: SortKey) => {
    setSortKey((currentKey) => {
      if (currentKey === nextKey) {
        setSortDirection((currentDirection) => currentDirection === "asc" ? "desc" : "asc");
        return currentKey;
      }
      setSortDirection("asc");
      return nextKey;
    });
  }, []);

  const sortedBooks = useMemo(() => {
    const items = [...(books ?? [])];
    items.sort((a, b) => {
      let comparison = 0;
      if (sortKey === "title") {
        comparison = a.title.localeCompare(b.title);
      } else if (sortKey === "author") {
        comparison = a.author_name.localeCompare(b.author_name) || a.title.localeCompare(b.title);
      } else if (sortKey === "hidden_by") {
        comparison = a.hidden_category_label.localeCompare(b.hidden_category_label) || a.title.localeCompare(b.title);
      } else if (sortKey === "year") {
        comparison = (a.release_date || "").localeCompare(b.release_date || "") || a.title.localeCompare(b.title);
      }
      return sortDirection === "asc" ? comparison : -comparison;
    });
    return items;
  }, [books, sortDirection, sortKey]);

  const renderSortIndicator = (key: SortKey) => {
    if (sortKey !== key) return null;
    return <span className="ml-1 text-emerald-400">{sortDirection === "asc" ? "▲" : "▼"}</span>;
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-slate-400">Loading hidden books...</div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold">Hidden Books</h2>
          <p className="text-sm text-slate-400 mt-1">
            Books currently excluded by your visibility profile and the category that hid them.
          </p>
          <p className="text-sm text-slate-500 mt-2">
            {sortedBooks.length} hidden book{sortedBooks.length === 1 ? "" : "s"} in this list
          </p>
        </div>
        <Link
          to="/settings#profiles"
          className="bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          Back to Profiles
        </Link>
      </div>

      <div className="mb-4 max-w-sm">
        <SearchBar value={search} onChange={handleSearch} placeholder="Search hidden books..." />
      </div>

      {!sortedBooks || sortedBooks.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-slate-400 text-lg">No hidden books found</p>
        </div>
      ) : (
        <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
          <table className="w-full text-sm text-left">
            <thead className="text-xs uppercase text-slate-400 bg-slate-800/80 border-b border-slate-700">
              <tr>
                <th className="px-4 py-3 w-12"></th>
                <th className="px-4 py-3">
                  <button onClick={() => handleSort("title")} className="hover:text-slate-200 transition-colors">
                    Title{renderSortIndicator("title")}
                  </button>
                </th>
                <th className="px-4 py-3">
                  <button onClick={() => handleSort("author")} className="hover:text-slate-200 transition-colors">
                    Author{renderSortIndicator("author")}
                  </button>
                </th>
                <th className="px-4 py-3">
                  <button onClick={() => handleSort("hidden_by")} className="hover:text-slate-200 transition-colors">
                    Hidden By{renderSortIndicator("hidden_by")}
                  </button>
                </th>
                <th className="px-4 py-3 text-right">
                  <button onClick={() => handleSort("year")} className="hover:text-slate-200 transition-colors">
                    Year{renderSortIndicator("year")}
                  </button>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700">
              {sortedBooks.map((book) => {
                const imgUrl = getImageUrl(book.cover_image_cached_path, book.cover_image_url);
                const coverPresentation = getBookCoverPresentation(book.cover_aspect_ratio);
                return (
                  <tr key={book.id} className="hover:bg-slate-700/40 transition-colors">
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
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${
                            book.has_valid_isbn
                              ? "bg-emerald-500/15 text-emerald-300"
                              : "bg-slate-700 text-slate-400"
                          }`}
                        >
                          ISBN {book.has_valid_isbn ? "✓" : "—"}
                        </span>
                        {book.matched_google && (
                          <span className="inline-flex items-center rounded-full bg-blue-500/15 px-2 py-0.5 text-[10px] font-medium text-blue-300">
                            Google
                          </span>
                        )}
                        {book.matched_openlibrary && (
                          <span className="inline-flex items-center rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-300">
                            OL
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-2 text-slate-400">
                      <Link
                        to={`/authors/${book.author_id}`}
                        className="text-slate-400 hover:text-emerald-400 transition-colors"
                      >
                        {book.author_name}
                      </Link>
                    </td>
                    <td className="px-4 py-2">
                      <span className="inline-flex rounded-full bg-amber-500/15 px-2.5 py-1 text-xs font-medium text-amber-300">
                        {book.hidden_category_label}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right text-slate-400 whitespace-nowrap">
                      {book.release_date ? book.release_date.substring(0, 4) : "-"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
