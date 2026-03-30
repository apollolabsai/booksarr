import { Link } from "react-router-dom";
import type { Book, BookInAuthor } from "../types";
import { getBookCoverPresentation, getImageUrl } from "../types";

type BookLike = Book | BookInAuthor;

function isFullBook(book: BookLike): book is Book {
  return "author_name" in book;
}

function downloadBook(bookId: number) {
  window.location.assign(`/api/books/${bookId}/download`);
}

function getSeriesLabel(book: BookLike): string | null {
  if (!book.series_info?.length) return null;
  const series = book.series_info[0];
  if (series.position == null) return series.series_name;
  return `${series.series_name} #${Number.isInteger(series.position) ? series.position : series.position.toFixed(1)}`;
}

export default function MobileBookList({
  books,
  showAuthor = true,
}: {
  books: BookLike[];
  showAuthor?: boolean;
}) {
  return (
    <div className="space-y-3">
      {books.map((book) => {
        const imageUrl = getImageUrl(book.cover_image_cached_path, "cover_image_url" in book ? book.cover_image_url : null);
        const seriesLabel = getSeriesLabel(book);
        const coverPresentation = getBookCoverPresentation(book.cover_aspect_ratio);

        return (
          <div
            key={book.id}
            className="rounded-2xl border border-slate-800 bg-slate-900/70 p-3"
          >
            <div className="flex gap-3">
              <div className={`h-24 w-16 flex-shrink-0 overflow-hidden rounded-xl ${coverPresentation.frameClassName}`}>
                {imageUrl ? (
                  coverPresentation.innerClassName ? (
                    <div className="flex h-full w-full items-center justify-center bg-slate-800">
                      <img src={imageUrl} alt={book.title} className={coverPresentation.imageClassName} />
                    </div>
                  ) : (
                    <img src={imageUrl} alt={book.title} className={coverPresentation.imageClassName} />
                  )
                ) : (
                  <div className="flex h-full w-full items-center justify-center bg-slate-800 p-2 text-center text-[10px] text-slate-500">
                    {book.title}
                  </div>
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="line-clamp-2 text-sm font-semibold text-slate-100">{book.title}</div>
                {showAuthor && isFullBook(book) && (
                  <Link to={`/authors/${book.author_id}`} className="mt-1 block truncate text-xs text-slate-400">
                    {book.author_name}
                  </Link>
                )}
                <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-400">
                  {seriesLabel && <span className="rounded-full bg-slate-800 px-2 py-0.5">{seriesLabel}</span>}
                  {book.release_date && <span>{book.release_date.substring(0, 4)}</span>}
                  {book.is_owned && (
                    <span className="rounded-full bg-emerald-500/12 px-2 py-0.5 text-emerald-300">
                      {book.owned_copy_count > 1 ? `${book.owned_copy_count} owned` : "Owned"}
                    </span>
                  )}
                </div>
                <div className="mt-3 flex gap-2">
                  {book.hardcover_slug && (
                    <a
                      href={`https://hardcover.app/books/${book.hardcover_slug}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rounded-xl border border-slate-700 px-3 py-2 text-xs font-medium text-slate-200"
                    >
                      Details
                    </a>
                  )}
                  <button
                    type="button"
                    onClick={() => downloadBook(book.id)}
                    disabled={!book.is_owned}
                    className="rounded-xl bg-emerald-600 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                  >
                    Download
                  </button>
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
