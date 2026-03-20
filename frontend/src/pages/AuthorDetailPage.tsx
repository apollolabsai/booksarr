import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useAuthor } from "../api/authors";
import { getImageUrl } from "../types";
import type { BookInAuthor } from "../types";
import BookCard from "../components/BookCard";
import SeriesGroup from "../components/SeriesGroup";
import SortControls from "../components/SortControls";

const SORT_OPTIONS = [
  { value: "series", label: "By Series" },
  { value: "title", label: "Title A-Z" },
  { value: "-date", label: "Newest First" },
  { value: "date", label: "Oldest First" },
  { value: "owned", label: "Owned First" },
];

export default function AuthorDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: author, isLoading } = useAuthor(Number(id));
  const [sort, setSort] = useState("series");
  const [bioExpanded, setBioExpanded] = useState(false);

  if (isLoading || !author) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-slate-400">Loading...</div>
      </div>
    );
  }

  const imgUrl = getImageUrl(author.image_cached_path, author.image_url);

  // Sort books
  const sortedBooks = [...author.books].sort((a, b) => {
    switch (sort) {
      case "title":
        return a.title.localeCompare(b.title);
      case "-date":
        return (b.release_date || "").localeCompare(a.release_date || "");
      case "date":
        return (a.release_date || "").localeCompare(b.release_date || "");
      case "owned":
        return (b.is_owned ? 1 : 0) - (a.is_owned ? 1 : 0);
      default:
        return 0;
    }
  });

  // Determine standalone books (not in any series)
  const booksInSeries = new Set<number>();
  author.series.forEach((s) => s.books.forEach((b) => booksInSeries.add(b.book_id)));
  const standaloneBooks = sortedBooks.filter((b) => !booksInSeries.has(b.id));

  const bioTruncated = author.bio && author.bio.length > 400;
  const displayBio = bioExpanded ? author.bio : author.bio?.substring(0, 400);

  return (
    <div>
      <Link to="/" className="text-slate-400 hover:text-emerald-400 text-sm mb-4 inline-flex items-center gap-1">
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
        Back to Authors
      </Link>

      {/* Hero Section */}
      <div className="flex gap-6 mb-8 mt-4">
        <div className="w-40 h-52 flex-shrink-0 rounded-lg overflow-hidden bg-slate-700">
          {imgUrl ? (
            <img src={imgUrl} alt={author.name} className="w-full h-full object-cover" />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-5xl font-bold text-slate-500">
              {author.name.charAt(0)}
            </div>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="text-3xl font-bold mb-2">{author.name}</h1>
          <div className="flex gap-4 text-sm text-slate-400 mb-4">
            <span><span className="text-emerald-400 font-semibold">{author.book_count_local}</span> owned</span>
            <span><span className="text-slate-200 font-semibold">{author.book_count_total}</span> total books</span>
            <span><span className="text-slate-200 font-semibold">{author.series.length}</span> series</span>
          </div>
          {author.bio && (
            <div className="text-sm text-slate-300 leading-relaxed">
              <p className="whitespace-pre-line">{displayBio}{bioTruncated && !bioExpanded ? "..." : ""}</p>
              {bioTruncated && (
                <button
                  onClick={() => setBioExpanded(!bioExpanded)}
                  className="text-emerald-400 hover:underline mt-1"
                >
                  {bioExpanded ? "Show less" : "Read more"}
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Sort + Stats Bar */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold">Books</h2>
        <SortControls options={SORT_OPTIONS} value={sort} onChange={setSort} />
      </div>

      {sort === "series" ? (
        <>
          {/* Series groups */}
          {author.series.map((s) => (
            <SeriesGroup key={s.id} series={s} allBooks={author.books} />
          ))}

          {/* Standalone books */}
          {standaloneBooks.length > 0 && (
            <div className="mb-8">
              <h3 className="text-lg font-semibold text-slate-200 mb-4">Standalone</h3>
              <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-4">
                {standaloneBooks.map((book) => (
                  <BookCard key={book.id} book={book} />
                ))}
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-4">
          {sortedBooks.map((book) => (
            <BookCard key={book.id} book={book} />
          ))}
        </div>
      )}
    </div>
  );
}
