import type { BookInAuthor, Book } from "../types";
import { getBookCoverPresentation, getImageUrl } from "../types";

type BookLike = BookInAuthor | Book;

export default function BookCard({
  book,
  onClick,
}: {
  book: BookLike;
  onClick?: () => void;
}) {
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

  return (
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
        {book.release_date && (
          <p className="text-xs text-slate-500 mt-0.5">
            {book.release_date.substring(0, 4)}
          </p>
        )}
      </div>
    </div>
  );
}
