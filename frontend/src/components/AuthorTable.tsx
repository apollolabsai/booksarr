import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { Author } from "../types";
import { getImageUrl } from "../types";

type SortKey = "name" | "-name" | "owned" | "-owned" | "total" | "-total" | "completion" | "-completion";

function getCompletion(author: Author) {
  return author.book_count_total > 0
    ? author.book_count_local / author.book_count_total
    : 0;
}

export default function AuthorTable({
  authors,
  initialSort = "name",
}: {
  authors: Author[];
  initialSort?: SortKey | string;
}) {
  const [sort, setSort] = useState<SortKey>("name");

  useEffect(() => {
    if (initialSort === "-name" || initialSort === "owned" || initialSort === "-owned") {
      setSort(initialSort);
      return;
    }
    if (initialSort === "books") {
      setSort("total");
      return;
    }
    if (initialSort === "-books") {
      setSort("-total");
      return;
    }
    setSort("name");
  }, [initialSort]);

  const sortedAuthors = useMemo(() => {
    const list = [...authors];
    list.sort((a, b) => {
      switch (sort) {
        case "name":
          return a.name.localeCompare(b.name);
        case "-name":
          return b.name.localeCompare(a.name);
        case "owned":
          return a.book_count_local - b.book_count_local || a.name.localeCompare(b.name);
        case "-owned":
          return b.book_count_local - a.book_count_local || a.name.localeCompare(b.name);
        case "total":
          return a.book_count_total - b.book_count_total || a.name.localeCompare(b.name);
        case "-total":
          return b.book_count_total - a.book_count_total || a.name.localeCompare(b.name);
        case "completion":
          return getCompletion(a) - getCompletion(b) || a.name.localeCompare(b.name);
        case "-completion":
          return getCompletion(b) - getCompletion(a) || a.name.localeCompare(b.name);
        default:
          return 0;
      }
    });
    return list;
  }, [authors, sort]);

  const toggleSort = (asc: SortKey, desc: SortKey) => {
    setSort((current) => (current === asc ? desc : asc));
  };

  const headerClass =
    "px-4 py-3 transition-colors hover:text-slate-200";

  const renderSortIndicator = (asc: SortKey, desc: SortKey) => {
    if (sort === asc) return <span className="text-slate-300">▲</span>;
    if (sort === desc) return <span className="text-slate-300">▼</span>;
    return <span className="text-slate-600">▲</span>;
  };

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
      <table className="w-full text-sm text-left">
        <thead className="text-xs uppercase text-slate-400 bg-slate-800/80 border-b border-slate-700">
          <tr>
            <th className="px-4 py-3 w-12"></th>
            <th className={headerClass}>
              <button type="button" className="flex items-center gap-2" onClick={() => toggleSort("name", "-name")}>
                <span>Author</span>
                {renderSortIndicator("name", "-name")}
              </button>
            </th>
            <th className={`${headerClass} text-right`}>
              <button type="button" className="ml-auto flex items-center gap-2" onClick={() => toggleSort("owned", "-owned")}>
                <span>Owned</span>
                {renderSortIndicator("owned", "-owned")}
              </button>
            </th>
            <th className={`${headerClass} text-right`}>
              <button type="button" className="ml-auto flex items-center gap-2" onClick={() => toggleSort("total", "-total")}>
                <span>Total</span>
                {renderSortIndicator("total", "-total")}
              </button>
            </th>
            <th className={`${headerClass} text-right`}>
              <button type="button" className="ml-auto flex items-center gap-2" onClick={() => toggleSort("completion", "-completion")}>
                <span>Completion</span>
                {renderSortIndicator("completion", "-completion")}
              </button>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700">
          {sortedAuthors.map((author) => {
            const imgUrl = getImageUrl(author.image_cached_path, author.image_url);
            const pct = author.book_count_total > 0
              ? Math.round((author.book_count_local / author.book_count_total) * 100)
              : 0;
            return (
              <tr key={author.id} className="hover:bg-slate-700/50 transition-colors">
                <td className="px-4 py-2">
                  <div className="w-8 h-8 rounded-full overflow-hidden bg-slate-700 flex-shrink-0">
                    {imgUrl ? (
                      <img src={imgUrl} alt="" className="w-full h-full object-cover" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-xs font-bold text-slate-500">
                        {author.name.charAt(0)}
                      </div>
                    )}
                  </div>
                </td>
                <td className="px-4 py-2">
                  <Link
                    to={`/authors/${author.id}`}
                    className="font-medium text-slate-200 hover:text-emerald-400 transition-colors"
                  >
                    {author.name}
                  </Link>
                </td>
                <td className="px-4 py-2 text-right text-emerald-400 font-medium">
                  {author.book_count_local}
                </td>
                <td className="px-4 py-2 text-right text-slate-300">
                  {author.book_count_total}
                </td>
                <td className="px-4 py-2 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <div className="w-20 bg-slate-700 rounded-full h-1.5">
                      <div
                        className="bg-emerald-500 h-1.5 rounded-full"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-slate-400 text-xs w-8 text-right">{pct}%</span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
