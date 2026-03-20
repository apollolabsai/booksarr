import type { SeriesInAuthor, BookInAuthor } from "../types";
import BookCard from "./BookCard";

export default function SeriesGroup({
  series,
  allBooks,
}: {
  series: SeriesInAuthor;
  allBooks: BookInAuthor[];
}) {
  const ownedCount = series.books.filter((b) => b.is_owned).length;

  return (
    <div className="mb-8">
      <div className="flex items-center gap-3 mb-4">
        <h3 className="text-lg font-semibold text-slate-200">{series.name}</h3>
        <span className="text-sm text-slate-400">
          <span className="text-emerald-400">{ownedCount}</span> / {series.books.length} books
        </span>
      </div>
      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-4">
        {series.books.map((sb) => {
          const fullBook = allBooks.find((b) => b.id === sb.book_id);
          if (!fullBook) return null;
          return (
            <div key={sb.book_id} className="relative">
              {sb.position != null && (
                <div className="absolute -top-2 -left-2 z-10 bg-slate-700 border border-slate-600 rounded-full w-6 h-6 flex items-center justify-center text-xs font-bold text-slate-300">
                  {Number.isInteger(sb.position) ? sb.position : sb.position.toFixed(1)}
                </div>
              )}
              <BookCard book={fullBook} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
