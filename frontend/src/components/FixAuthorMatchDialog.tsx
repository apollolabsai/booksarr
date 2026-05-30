import { useEffect, useState } from "react";
import { useRelinkAuthorHardcover, useSearchHardcoverAuthors } from "../api/authors";
import { getImageUrl } from "../types";

export default function FixAuthorMatchDialog({
  open,
  onClose,
  authorId,
  authorName,
  currentHardcoverId,
}: {
  open: boolean;
  onClose: () => void;
  authorId: number;
  authorName: string;
  currentHardcoverId: number | null;
}) {
  const [query, setQuery] = useState("");
  const searchAuthors = useSearchHardcoverAuthors();
  const relinkAuthor = useRelinkAuthorHardcover();
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const { mutate: runSearch, reset: resetSearch } = searchAuthors;
  const { reset: resetRelink } = relinkAuthor;

  // Seed the search box with the current author name and auto-search on open.
  useEffect(() => {
    if (!open) {
      setQuery("");
      setPendingId(null);
      setActionError(null);
      resetRelink();
      resetSearch();
      return;
    }
    setQuery(authorName);
    if (authorName.trim().length >= 3) {
      runSearch(authorName.trim());
    }
  }, [open, authorName, runSearch, resetSearch, resetRelink]);

  if (!open) return null;

  const candidates = searchAuthors.data?.candidates ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 px-4 py-6">
      <div className="max-h-[90vh] w-full max-w-3xl overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-start justify-between border-b border-slate-700 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">Fix Hardcover Match</h2>
            <p className="mt-1 text-sm text-slate-400">
              Search Hardcover and pick the correct author profile for <span className="text-slate-200">{authorName}</span>. The book with the highest count is usually the canonical profile. Selecting a match relinks this author and refreshes their books.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-700"
          >
            Close
          </button>
        </div>

        <div className="max-h-[calc(90vh-140px)] overflow-y-auto px-6 py-5">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!query.trim()) return;
              searchAuthors.mutate(query.trim());
            }}
            className="rounded-xl border border-slate-700 bg-slate-800 p-4"
          >
            <div className="mb-2 text-sm font-medium text-slate-200">Author name</div>
            <div className="flex items-center gap-3">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-full rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-slate-100"
                placeholder="J.A. Jance"
              />
              <button
                type="submit"
                disabled={searchAuthors.isPending || !query.trim()}
                className="shrink-0 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {searchAuthors.isPending ? "Searching..." : "Search"}
              </button>
            </div>
            {searchAuthors.isError && (
              <div className="mt-3 text-sm text-rose-300">Failed to search Hardcover. Check your API key and query.</div>
            )}
          </form>

          <div className="mt-5 rounded-xl border border-slate-700 bg-slate-800 p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="text-sm font-medium text-slate-100">Hardcover matches</div>
              <div className="text-xs text-slate-500">{candidates.length} result(s)</div>
            </div>
            {actionError && (
              <div className="mb-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                {actionError}
              </div>
            )}

            {candidates.length === 0 ? (
              <div className="text-sm text-slate-400">
                {searchAuthors.isPending
                  ? "Searching Hardcover..."
                  : "Search for an author to see Hardcover candidates ordered from best match to worst."}
              </div>
            ) : (
              <div className="space-y-3">
                {candidates.map((candidate) => {
                  const imgUrl = getImageUrl(null, candidate.image_url);
                  const isCurrent = currentHardcoverId != null && candidate.hardcover_id === currentHardcoverId;
                  return (
                    <div
                      key={candidate.hardcover_id}
                      className={`flex items-center gap-4 rounded-lg border p-3 ${
                        isCurrent ? "border-emerald-500/50 bg-emerald-500/5" : "border-slate-700 bg-slate-900/40"
                      }`}
                    >
                      <div className="h-16 w-12 shrink-0 overflow-hidden rounded bg-slate-700">
                        {imgUrl ? (
                          <img src={imgUrl} alt={candidate.name} className="h-full w-full object-cover" />
                        ) : (
                          <div className="flex h-full w-full items-center justify-center text-lg font-semibold text-slate-500">
                            {candidate.name.charAt(0)}
                          </div>
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-medium text-slate-100">{candidate.name}</span>
                          {isCurrent && (
                            <span className="shrink-0 rounded bg-emerald-500/15 px-2 py-0.5 text-[11px] font-medium text-emerald-300">
                              Currently linked
                            </span>
                          )}
                        </div>
                        <div className="mt-1 text-xs text-slate-400">
                          <span className="font-semibold text-slate-300">{candidate.books_count}</span> book(s){candidate.slug ? ` • ${candidate.slug}` : ""}
                        </div>
                        {candidate.bio && (
                          <div className="mt-1 line-clamp-2 text-xs text-slate-500">
                            {candidate.bio}
                          </div>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={async () => {
                          setPendingId(candidate.hardcover_id);
                          setActionError(null);
                          try {
                            await relinkAuthor.mutateAsync({ authorId, hardcoverId: candidate.hardcover_id });
                            onClose();
                          } catch (error) {
                            setActionError(
                              error instanceof Error
                                ? error.message
                                : "Failed to relink author to the selected match.",
                            );
                          } finally {
                            setPendingId(null);
                          }
                        }}
                        disabled={isCurrent || relinkAuthor.isPending}
                        className="shrink-0 rounded-md border border-slate-600 bg-slate-700 px-3 py-1.5 text-xs font-medium text-slate-100 transition-colors hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {pendingId === candidate.hardcover_id ? "Linking..." : isCurrent ? "Linked" : "Select"}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}

            {relinkAuthor.isError && !actionError && (
              <div className="mt-3 text-sm text-rose-300">Failed to relink author to the selected match.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
