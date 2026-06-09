import { type MutableRefObject, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import type { Author } from "../types";
import { getImageUrl } from "../types";
import { useWindowVirtualRange } from "../hooks/useWindowVirtualRange";

export default function MobileAuthorList({
  authors,
  getItemId,
  scrollToAuthorRef,
}: {
  authors: Author[];
  getItemId?: (author: Author) => string;
  scrollToAuthorRef?: MutableRefObject<((target: { id: number; index: number }) => void) | null>;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rowHeight = 92;
  const virtualRows = useWindowVirtualRange(containerRef, authors.length, rowHeight, 12);

  useEffect(() => {
    if (!scrollToAuthorRef) return;
    scrollToAuthorRef.current = (target: { id: number; index: number }) => {
      virtualRows.scrollToIndex(target.index);
    };
    return () => {
      scrollToAuthorRef.current = null;
    };
  }, [scrollToAuthorRef, virtualRows.scrollToIndex]);

  return (
    <div ref={containerRef} className="relative" style={{ height: virtualRows.totalSize }}>
      <div className="absolute left-0 right-0 space-y-3" style={{ transform: `translateY(${virtualRows.offsetTop}px)` }}>
        {virtualRows.virtualIndexes.map((index) => {
          const author = authors[index];
          if (!author) return null;
          const imageUrl = getImageUrl(author.image_cached_path, author.image_url);
          return (
            <Link
              key={author.id}
              id={getItemId?.(author)}
              to={`/authors/${author.id}`}
              className="flex scroll-mt-6 items-center gap-3 rounded-2xl border border-slate-800 bg-slate-900/70 px-3 py-3 transition-colors hover:border-emerald-500/40"
            >
              <div className="h-14 w-14 flex-shrink-0 overflow-hidden rounded-2xl bg-slate-800">
                {imageUrl ? (
                  <img src={imageUrl} alt={author.name} className="h-full w-full object-cover" decoding="async" loading="lazy" />
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
    </div>
  );
}
