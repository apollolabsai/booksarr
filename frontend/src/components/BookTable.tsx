import { useState } from "react";
import { Link } from "react-router-dom";
import type { Book, BookInAuthor } from "../types";
import { getBookCoverPresentation, getImageUrl } from "../types";
import { useRefreshBook, useSetBookVisibility } from "../api/books";
import CoverPickerDialog from "./CoverPickerDialog";

type BookLike = Book | BookInAuthor;

function isFullBook(book: BookLike): book is Book {
  return "author_name" in book;
}

function OwnedIndicator({ count }: { count: number }) {
  if (count > 1) {
    return (
      <div
        className="inline-flex min-w-5 items-center justify-center rounded-full bg-emerald-500 px-1.5 py-0.5 text-[10px] font-semibold text-white"
        title={`${count} owned copies`}
      >
        {count}
      </div>
    );
  }

  return (
    <div className="inline-flex bg-emerald-500 rounded-full p-0.5" title="Owned">
      <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
        <path
          fillRule="evenodd"
          d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
          clipRule="evenodd"
        />
      </svg>
    </div>
  );
}

function formatSeriesPosition(book: BookLike): string {
  if (!("series_info" in book) || !book.series_info || book.series_info.length === 0) return "";
  const si = book.series_info[0];
  const pos = si.position != null
    ? (Number.isInteger(si.position) ? `#${si.position}` : `#${si.position.toFixed(1)}`)
    : "";
  return pos ? `${si.series_name} ${pos}` : si.series_name;
}

function MetadataBadges({ book }: { book: BookLike }) {
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      <span
        className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${
          book.has_valid_isbn
            ? "bg-emerald-500/15 text-emerald-300"
            : "bg-slate-700 text-slate-400"
        }`}
        title={book.has_valid_isbn ? "Valid ISBN present" : "No valid ISBN"}
      >
        ISBN {book.has_valid_isbn ? "✓" : "—"}
      </span>
      {book.matched_google && (
        <span
          className="inline-flex items-center rounded-full bg-blue-500/15 px-2 py-0.5 text-[10px] font-medium text-blue-300"
          title="Matched with Google Books"
        >
          Google
        </span>
      )}
      {book.matched_openlibrary && (
        <span
          className="inline-flex items-center rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-300"
          title="Matched with Open Library"
        >
          OL
        </span>
      )}
    </div>
  );
}

export default function BookTable({
  books,
  showAuthor = true,
}: {
  books: BookLike[];
  showAuthor?: boolean;
}) {
  const refreshBook = useRefreshBook();
  const setBookVisibility = useSetBookVisibility();
  const [coverPickerBook, setCoverPickerBook] = useState<{ id: number; title: string } | null>(null);

  return (
    <>
      <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
        <table className="w-full text-sm text-left">
          <thead className="text-xs uppercase text-slate-400 bg-slate-800/80 border-b border-slate-700">
            <tr>
              <th className="px-4 py-3 w-10"></th>
              <th className="px-4 py-3 w-12"></th>
              <th className="px-4 py-3">Title</th>
              {showAuthor && <th className="px-4 py-3">Author</th>}
              <th className="px-4 py-3">Series</th>
              <th className="px-4 py-3 text-right">Year</th>
              <th className="px-4 py-3 text-right">Rating</th>
              <th className="px-4 py-3 text-right">Poster</th>
              <th className="px-4 py-3 text-right">Refresh</th>
              <th className="px-4 py-3 text-right">Visibility</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700">
            {books.map((book) => {
              const imgUrl = getImageUrl(
                book.cover_image_cached_path,
                "cover_image_url" in book ? book.cover_image_url : null
              );
              const coverPresentation = getBookCoverPresentation(book.cover_aspect_ratio);
              const authorId = isFullBook(book) ? book.author_id : undefined;
              const authorName = isFullBook(book) ? book.author_name : undefined;
              const seriesStr = formatSeriesPosition(book);

              return (
                <tr
                  key={book.id}
                  className="hover:bg-slate-700/50 transition-colors"
                >
                  <td className="px-4 py-2 text-center">
                    {book.is_owned ? (
                      <OwnedIndicator count={book.owned_copy_count} />
                    ) : (
                      <div className="w-4 h-4 rounded-full border border-dashed border-slate-500 mx-auto" />
                    )}
                  </td>
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
                    <MetadataBadges book={book} />
                  </td>
                  {showAuthor && (
                    <td className="px-4 py-2">
                      {authorId ? (
                        <Link
                          to={`/authors/${authorId}`}
                          className="text-slate-400 hover:text-emerald-400 transition-colors"
                        >
                          {authorName}
                        </Link>
                      ) : (
                        <span className="text-slate-400">-</span>
                      )}
                    </td>
                  )}
                  <td className="px-4 py-2 text-slate-400 text-xs">
                    {seriesStr || "-"}
                  </td>
                  <td className="px-4 py-2 text-right text-slate-400 whitespace-nowrap">
                    {book.release_date ? book.release_date.substring(0, 4) : "-"}
                  </td>
                  <td className="px-4 py-2 text-right text-slate-400">
                    {book.rating ? book.rating.toFixed(1) : "-"}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => setCoverPickerBook({ id: book.id, title: book.title })}
                      className="inline-flex items-center justify-center rounded-md border border-slate-600 bg-slate-700 px-2.5 py-1.5 text-slate-200 transition-colors hover:bg-slate-600"
                      title="Choose a poster for this book"
                    >
                      Poster
                    </button>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => refreshBook.mutate(book.id)}
                      disabled={refreshBook.isPending}
                      className="inline-flex items-center justify-center rounded-md border border-slate-600 bg-slate-700 px-2.5 py-1.5 text-slate-200 transition-colors hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
                      title="Delete and re-import metadata for this book"
                    >
                      <svg className={`h-4 w-4 ${refreshBook.isPending && refreshBook.variables === book.id ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m14.836 2A8.001 8.001 0 005.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.356-2m15.356 2H15" />
                      </svg>
                    </button>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => setBookVisibility.mutate({ bookId: book.id, action: "hide" })}
                      disabled={setBookVisibility.isPending}
                      className="inline-flex items-center justify-center rounded-md border border-slate-600 bg-slate-700 px-2.5 py-1.5 text-slate-200 transition-colors hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
                      title="Hide Book"
                    >
                      <svg className={`h-4 w-4 ${setBookVisibility.isPending && setBookVisibility.variables?.bookId === book.id ? "animate-pulse" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3.98 8.223A10.477 10.477 0 0112 5c4.478 0 8.268 2.943 9.542 7-.435 1.384-1.18 2.625-2.153 3.646M6.228 6.228A9.956 9.956 0 002.458 12c1.274 4.057 5.064 7 9.542 7 1.671 0 3.254-.41 4.646-1.153M6.228 6.228L3 3m3.228 3.228l3.65 3.65m0 0a3 3 0 104.243 4.243m-4.243-4.243L14.12 14.12m0 0L21 21" />
                      </svg>
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <CoverPickerDialog
        bookId={coverPickerBook?.id ?? null}
        title={coverPickerBook?.title ?? ""}
        open={coverPickerBook !== null}
        onClose={() => setCoverPickerBook(null)}
      />
    </>
  );
}
