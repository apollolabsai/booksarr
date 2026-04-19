import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useHiddenBooks, useSetBookVisibility } from "../api/books";
import SearchBar from "../components/SearchBar";
import { getBookCoverPresentation, getImageUrl } from "../types";

type SortKey = "title" | "author" | "hidden_by" | "year";

function getFilterLabel(selectedLabels: string[]) {
  if (selectedLabels.length === 0) return "All Hidden Reasons";
  if (selectedLabels.length === 1) return selectedLabels[0];
  return `${selectedLabels.length} Reasons`;
}

function MultiSelectReasonFilter({
  labels,
  selectedLabels,
  open,
  onToggleOpen,
  onToggleValue,
  onClear,
  menuRef,
}: {
  labels: string[];
  selectedLabels: string[];
  open: boolean;
  onToggleOpen: () => void;
  onToggleValue: (label: string) => void;
  onClear: () => void;
  menuRef: { current: HTMLDivElement | null };
}) {
  return (
    <div ref={(node) => { menuRef.current = node; }} className="relative">
      <button
        type="button"
        onClick={onToggleOpen}
        className="min-w-[200px] rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-slate-200 flex items-center justify-between gap-3"
      >
        <span className="truncate">{getFilterLabel(selectedLabels)}</span>
        <svg className="h-4 w-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-2 w-80 rounded-lg border border-slate-600 bg-slate-800 p-2 shadow-xl">
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="text-xs font-medium text-slate-400">
              {selectedLabels.length === 0 ? "All reasons shown" : `${selectedLabels.length} selected`}
            </span>
            <button
              type="button"
              onClick={onClear}
              className="text-xs text-emerald-400 hover:text-emerald-300"
            >
              Clear
            </button>
          </div>
          <div className="max-h-64 space-y-1 overflow-y-auto">
            {labels.map((label) => (
              <label
                key={label}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-slate-200 hover:bg-slate-700"
              >
                <input
                  type="checkbox"
                  checked={selectedLabels.includes(label)}
                  onChange={() => onToggleValue(label)}
                  className="rounded border-slate-600 bg-slate-700 text-emerald-500 focus:ring-emerald-500"
                />
                <span className="truncate">{label}</span>
              </label>
            ))}
            {labels.length === 0 && (
              <div className="px-2 py-1.5 text-sm text-slate-500">No hidden reasons available.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function HiddenBooksPage() {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("title");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [selectedReasonLabels, setSelectedReasonLabels] = useState<string[]>([]);
  const [reasonMenuOpen, setReasonMenuOpen] = useState(false);
  const { data: books, isLoading } = useHiddenBooks(search);
  const setBookVisibility = useSetBookVisibility();
  const reasonMenuRef = useRef<HTMLDivElement | null>(null);

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
  const hiddenReasonLabels = useMemo(() => (
    Array.from(new Set((books ?? []).flatMap((book) => book.hidden_categories.map((category) => category.label)))).sort()
  ), [books]);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (reasonMenuRef.current && !reasonMenuRef.current.contains(event.target as Node)) {
        setReasonMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, []);

  useEffect(() => {
    setSelectedReasonLabels((current) => current.filter((label) => hiddenReasonLabels.includes(label)));
  }, [hiddenReasonLabels]);

  const sortedBooks = useMemo(() => {
    const visibleBooks = selectedReasonLabels.length === 0
      ? (books ?? [])
      : (books ?? []).filter((book) => (
        book.hidden_categories.some((category) => selectedReasonLabels.includes(category.label))
      ));
    const items = [...visibleBooks];
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
  }, [books, selectedReasonLabels, sortDirection, sortKey]);

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
          to="/settings/profiles"
          className="bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          Back to Profiles
        </Link>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="max-w-sm flex-1 min-w-[280px]">
          <SearchBar value={search} onChange={handleSearch} placeholder="Search hidden books or authors..." />
        </div>
        <MultiSelectReasonFilter
          labels={hiddenReasonLabels}
          selectedLabels={selectedReasonLabels}
          open={reasonMenuOpen}
          onToggleOpen={() => setReasonMenuOpen((current) => !current)}
          onToggleValue={(label) => setSelectedReasonLabels((current) => (
            current.includes(label)
              ? current.filter((item) => item !== label)
              : [...current, label]
          ))}
          onClear={() => setSelectedReasonLabels([])}
          menuRef={reasonMenuRef}
        />
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
                <th className="px-4 py-3 text-right">Visibility</th>
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
                      <div className="flex flex-wrap gap-1.5">
                        {book.hidden_categories.map((category) => (
                          <span
                            key={category.key}
                            className="inline-flex rounded-full bg-amber-500/15 px-2.5 py-1 text-xs font-medium text-amber-300"
                          >
                            {category.label}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-2 text-right text-slate-400 whitespace-nowrap">
                      {book.release_date ? book.release_date.substring(0, 4) : "-"}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <button
                        type="button"
                        onClick={() => setBookVisibility.mutate({ bookId: book.id, action: "show" })}
                        disabled={setBookVisibility.isPending}
                        className="inline-flex items-center justify-center rounded-md border border-slate-600 bg-slate-700 px-2.5 py-1.5 text-slate-200 transition-colors hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
                        title="Unhide Book"
                      >
                        <svg className={`h-4 w-4 ${setBookVisibility.isPending && setBookVisibility.variables?.bookId === book.id ? "animate-pulse" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.522 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.478 0-8.268-2.943-9.542-7z" />
                        </svg>
                      </button>
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
