import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { BookInAuthor, Book } from "../types";
import { getBookCoverPresentation, getImageUrl } from "../types";
import CoverPickerDialog from "./CoverPickerDialog";
import { useRefreshBook, useSetBookVisibility } from "../api/books";

type BookLike = BookInAuthor | Book;

function isFullBook(book: BookLike): book is Book {
  return "author_name" in book;
}

export default function BookCard({
  book,
  onClick,
  showAuthor = false,
}: {
  book: BookLike;
  onClick?: () => void;
  showAuthor?: boolean;
}) {
  const refreshBook = useRefreshBook();
  const setBookVisibility = useSetBookVisibility();
  const [coverPickerOpen, setCoverPickerOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const imgUrl = getImageUrl(
    book.cover_image_cached_path,
    "cover_image_url" in book ? book.cover_image_url : null
  );
  const coverPresentation = getBookCoverPresentation(book.cover_aspect_ratio);

  const hardcoverUrl = book.hardcover_slug
    ? `https://hardcover.app/books/${book.hardcover_slug}`
    : null;

  const handleClick = () => {
    if (hardcoverUrl) {
      window.open(hardcoverUrl, "_blank", "noopener,noreferrer");
    } else if (onClick) {
      onClick();
    }
  };

  useEffect(() => {
    if (!menuOpen) return;

    const handlePointerDown = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [menuOpen]);

  return (
    <>
      <div
        className={`group cursor-pointer ${!book.is_owned ? "opacity-60" : ""}`}
        onClick={handleClick}
      >
        <div
          className={`relative rounded-lg overflow-hidden border border-slate-600 group-hover:border-emerald-500/50 transition-all ${coverPresentation.frameClassName}`}
          style={coverPresentation.frameStyle}
        >
          {imgUrl ? (
            coverPresentation.innerClassName ? (
              <div className={coverPresentation.innerClassName}>
                <img
                  src={imgUrl}
                  alt={book.title}
                  className={coverPresentation.imageClassName}
                  loading="lazy"
                />
              </div>
            ) : (
              <img
                src={imgUrl}
                alt={book.title}
                className={coverPresentation.imageClassName}
                loading="lazy"
              />
            )
          ) : (
            <div className="w-full h-full flex items-center justify-center p-2 text-center text-sm text-slate-400">
              {book.title}
            </div>
          )}
          <div ref={menuRef} className="absolute bottom-2 left-2 right-2">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setMenuOpen((current) => !current);
              }}
              className="rounded-md border border-slate-500/60 bg-slate-900/70 px-1.5 py-1 text-slate-100 opacity-0 transition-opacity hover:bg-slate-800/90 group-hover:opacity-100"
              title="Book actions"
            >
              <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
                <circle cx="5" cy="12" r="1.75" />
                <circle cx="12" cy="12" r="1.75" />
                <circle cx="19" cy="12" r="1.75" />
              </svg>
            </button>
            {menuOpen && (
              <div
                className="absolute bottom-9 left-0 right-0 z-20 rounded-lg border border-slate-600 bg-slate-900/95 p-1 shadow-xl"
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    setCoverPickerOpen(true);
                  }}
                  className="flex w-full items-center rounded-md px-2.5 py-1.5 text-xs text-slate-200 transition-colors hover:bg-slate-800"
                >
                  Choose Poster
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    refreshBook.mutate(book.id);
                  }}
                  disabled={refreshBook.isPending}
                  className="flex w-full items-center rounded-md px-2.5 py-1.5 text-xs text-slate-200 transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Refresh
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    setBookVisibility.mutate({ bookId: book.id, action: "hide" });
                  }}
                  disabled={setBookVisibility.isPending}
                  className="flex w-full items-center rounded-md px-2.5 py-1.5 text-xs text-rose-300 transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Hide Book
                </button>
              </div>
            )}
          </div>
          {book.is_owned && (
            <div className="absolute top-2 right-2 bg-emerald-500 rounded-full p-1">
              <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                <path
                  fillRule="evenodd"
                  d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                  clipRule="evenodd"
                />
              </svg>
            </div>
          )}
        </div>
        <div className="mt-2">
          <p className="text-sm font-medium text-slate-200 truncate group-hover:text-emerald-400 transition-colors">
            {book.title}
          </p>
          {showAuthor && isFullBook(book) && (
            <Link
              to={`/authors/${book.author_id}`}
              className="block text-xs text-slate-500 hover:text-emerald-400 truncate"
              onClick={(e) => e.stopPropagation()}
            >
              {book.author_name}
            </Link>
          )}
          {book.release_date && (
            <p className="text-xs text-slate-500 mt-0.5">
              {book.release_date.substring(0, 4)}
            </p>
          )}
        </div>
      </div>
      <CoverPickerDialog
        bookId={book.id}
        title={book.title}
        open={coverPickerOpen}
        onClose={() => setCoverPickerOpen(false)}
      />
    </>
  );
}
