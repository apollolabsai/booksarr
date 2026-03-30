import { Link } from "react-router-dom";
import type { Author } from "../types";
import { getImageUrl } from "../types";

export default function MobileAuthorList({ authors }: { authors: Author[] }) {
  return (
    <div className="space-y-3">
      {authors.map((author) => {
        const imageUrl = getImageUrl(author.image_cached_path, author.image_url);
        return (
          <Link
            key={author.id}
            to={`/authors/${author.id}`}
            className="flex items-center gap-3 rounded-2xl border border-slate-800 bg-slate-900/70 px-3 py-3 transition-colors hover:border-emerald-500/40"
          >
            <div className="h-14 w-14 flex-shrink-0 overflow-hidden rounded-2xl bg-slate-800">
              {imageUrl ? (
                <img src={imageUrl} alt={author.name} className="h-full w-full object-cover" />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-lg font-bold text-slate-500">
                  {author.name.charAt(0)}
                </div>
              )}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold text-slate-100">{author.name}</div>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                <span className="rounded-full bg-emerald-500/12 px-2 py-0.5 text-emerald-300">
                  {author.book_count_local} owned
                </span>
                <span>{author.book_count_total} visible</span>
              </div>
            </div>
            <svg className="h-4 w-4 flex-shrink-0 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </Link>
        );
      })}
    </div>
  );
}
