import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useAddAuthorFromHardcover, useAuthorAddStatus, useSearchHardcoverAuthors } from "../api/authors";
import { getImageUrl } from "../types";

export default function AddAuthorDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [activeHardcoverId, setActiveHardcoverId] = useState<number | null>(null);
  const navigatedAuthorId = useRef<number | null>(null);
  const searchAuthors = useSearchHardcoverAuthors();
  const addAuthor = useAddAuthorFromHardcover();
  const { data: addStatus } = useAuthorAddStatus(open);

  useEffect(() => {
    if (!open) {
      setQuery("");
    }
  }, [open]);

  useEffect(() => {
    if (!addStatus || addStatus.status !== "completed" || !addStatus.author_id) return;
    if (activeHardcoverId === null || addStatus.hardcover_id !== activeHardcoverId) return;
    if (navigatedAuthorId.current === addStatus.author_id) return;

    navigatedAuthorId.current = addStatus.author_id;
    queryClient.invalidateQueries({ queryKey: ["authors"] });
    queryClient.invalidateQueries({ queryKey: ["authors", addStatus.author_id] });
    onClose();
    navigate(`/authors/${addStatus.author_id}`);
  }, [activeHardcoverId, addStatus, navigate, onClose, queryClient]);

  const candidates = searchAuthors.data?.candidates ?? [];
  const activeAddStatus = addStatus && (
    addStatus?.status === "adding"
    || (activeHardcoverId !== null && addStatus?.hardcover_id === activeHardcoverId)
  ) ? addStatus : null;
  const addProgress = Math.max(0, Math.min(100, Math.round(activeAddStatus?.progress ?? 0)));
  const isAdding = activeAddStatus?.status === "adding" || addAuthor.isPending;
  const statusTitle = useMemo(() => {
    if (!activeAddStatus) return null;
    if (activeAddStatus.status === "failed") return "Author import failed";
    if (activeAddStatus.status === "completed") return "Author import complete";
    return activeAddStatus.author_name ? `Adding ${activeAddStatus.author_name}` : "Adding author";
  }, [activeAddStatus]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 px-4 py-6">
      <div className="max-h-[90vh] w-full max-w-3xl overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-start justify-between border-b border-slate-700 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">Add Author</h2>
            <p className="mt-1 text-sm text-slate-400">
              Enter the author name as first name last name, then choose the correct Hardcover match.
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
                placeholder="John Grisham"
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

            {candidates.length === 0 ? (
              <div className="text-sm text-slate-400">
                Search for an author to see Hardcover candidates ordered from best match to worst.
              </div>
            ) : (
              <div className="space-y-3">
                {candidates.map((candidate) => {
                  const imgUrl = getImageUrl(null, candidate.image_url);
                  return (
                    <div
                      key={candidate.hardcover_id}
                      className="flex items-center gap-4 rounded-lg border border-slate-700 bg-slate-900/40 p-3"
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
                        <div className="truncate text-sm font-medium text-slate-100">{candidate.name}</div>
                        <div className="mt-1 text-xs text-slate-400">
                          {candidate.books_count} book(s){candidate.slug ? ` • ${candidate.slug}` : ""}
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
                          setActiveHardcoverId(candidate.hardcover_id);
                          navigatedAuthorId.current = null;
                          const response = await addAuthor.mutateAsync(candidate.hardcover_id);
                          setActiveHardcoverId(response.add.hardcover_id);
                        }}
                        disabled={isAdding}
                        className="shrink-0 rounded-md border border-slate-600 bg-slate-700 px-3 py-1.5 text-xs font-medium text-slate-100 transition-colors hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {activeAddStatus?.status === "adding" && activeAddStatus.hardcover_id === candidate.hardcover_id
                          ? `${addProgress}%`
                          : addAuthor.isPending && activeHardcoverId === candidate.hardcover_id
                            ? "Starting..."
                            : "Select"}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}

            {activeAddStatus && activeAddStatus.status !== "idle" && (
              <div className={`mt-4 rounded-lg border p-3 ${
                activeAddStatus.status === "failed"
                  ? "border-rose-500/40 bg-rose-950/30"
                  : "border-emerald-500/30 bg-emerald-950/20"
              }`}>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <div className="min-w-0 text-sm font-medium text-slate-100">{statusTitle}</div>
                  <div className="shrink-0 text-xs tabular-nums text-slate-400">
                    {activeAddStatus.status === "adding" ? `${addProgress}%` : ""}
                  </div>
                </div>
                <div className={`mb-2 line-clamp-2 text-xs ${
                  activeAddStatus.status === "failed" ? "text-rose-200" : "text-slate-300"
                }`}>
                  {activeAddStatus.message || activeAddStatus.error || "Working..."}
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-slate-900">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${
                      activeAddStatus.status === "failed" ? "bg-rose-500" : "bg-emerald-500"
                    }`}
                    style={{ width: `${activeAddStatus.status === "failed" ? 100 : addProgress}%` }}
                  />
                </div>
              </div>
            )}

            {addAuthor.isError && !activeAddStatus && (
              <div className="mt-3 text-sm text-rose-300">Failed to start selected author import.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
