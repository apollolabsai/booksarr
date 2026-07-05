import { useEffect, useMemo, useState } from "react";
import type { BookMatchCandidate, LocalBookFile } from "../types";
import { getBookCoverPresentation, getImageUrl } from "../types";
import { useBookMatchCandidates, useFixBookMatch } from "../api/books";

function formatSeries(candidate: BookMatchCandidate): string {
  const series = candidate.series_info[0];
  if (!series) return "";
  if (series.position == null) return series.series_name;
  const position = Number.isInteger(series.position) ? series.position : series.position.toFixed(1);
  return `${series.series_name} #${position}`;
}

function formatFileLabel(file: LocalBookFile): string {
  const format = (file.file_format || "file").toUpperCase();
  return `${format} - ${file.file_path}`;
}

export default function FixBookMatchDialog({
  open,
  onClose,
  sourceBookId,
  sourceTitle,
  sourceAuthorName,
  localFiles,
}: {
  open: boolean;
  onClose: () => void;
  sourceBookId: number | null;
  sourceTitle: string;
  sourceAuthorName: string | null;
  localFiles: LocalBookFile[];
}) {
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [selectedFileIds, setSelectedFileIds] = useState<Set<number>>(new Set());
  const [selectedTarget, setSelectedTarget] = useState<BookMatchCandidate | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const fixMatch = useFixBookMatch();
  const { reset: resetFixMatch } = fixMatch;

  const candidatesQuery = useBookMatchCandidates({
    search: submittedQuery,
    excludeBookId: sourceBookId,
    enabled: open && sourceBookId != null,
  });

  useEffect(() => {
    if (!open) {
      setQuery("");
      setSubmittedQuery("");
      setSelectedFileIds(new Set());
      setSelectedTarget(null);
      setActionError(null);
      resetFixMatch();
      return;
    }

    const nextQuery = sourceTitle;
    setQuery(nextQuery);
    setSubmittedQuery(nextQuery);
    setSelectedFileIds(localFiles.length === 1 ? new Set([localFiles[0].id]) : new Set());
    setSelectedTarget(null);
    setActionError(null);
  }, [localFiles, open, resetFixMatch, sourceTitle]);

  const selectedFiles = useMemo(
    () => localFiles.filter((file) => selectedFileIds.has(file.id)),
    [localFiles, selectedFileIds],
  );

  if (!open || sourceBookId == null) return null;

  const candidates = candidatesQuery.data?.candidates ?? [];
  const canSave = selectedFiles.length > 0 && selectedTarget != null && !fixMatch.isPending;

  const toggleFile = (fileId: number) => {
    setSelectedFileIds((current) => {
      const next = new Set(current);
      if (next.has(fileId)) {
        next.delete(fileId);
      } else {
        next.add(fileId);
      }
      return next;
    });
  };

  const handleSave = async () => {
    if (!selectedTarget || selectedFiles.length === 0) return;
    setActionError(null);
    try {
      await fixMatch.mutateAsync({
        sourceBookId,
        targetBookId: selectedTarget.id,
        bookFileIds: selectedFiles.map((file) => file.id),
      });
      onClose();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Failed to fix match.");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 px-4 py-6">
      <div className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex shrink-0 items-start justify-between border-b border-slate-700 px-6 py-4">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-slate-100">Fix Match</h2>
            <div className="mt-1 truncate text-sm text-slate-400">
              <span className="text-slate-200">{sourceTitle}</span>
              {sourceAuthorName ? <span> by {sourceAuthorName}</span> : null}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-700"
          >
            Close
          </button>
        </div>

        <div className="grid min-h-0 flex-1 gap-0 overflow-hidden lg:grid-cols-[minmax(260px,0.85fr)_minmax(0,1.45fr)]">
          <div className="min-h-0 overflow-y-auto border-b border-slate-700 p-5 lg:border-b-0 lg:border-r">
            <div className="text-sm font-medium text-slate-100">Local Files</div>
            <div className="mt-3 space-y-2">
              {localFiles.map((file) => (
                <label
                  key={file.id}
                  className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                    selectedFileIds.has(file.id)
                      ? "border-emerald-500/60 bg-emerald-500/10"
                      : "border-slate-700 bg-slate-800 hover:border-slate-500"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedFileIds.has(file.id)}
                    onChange={() => toggleFile(file.id)}
                    className="mt-0.5 rounded border-slate-600 bg-slate-700 text-emerald-500 focus:ring-emerald-500"
                  />
                  <span className="min-w-0 break-all text-xs leading-5 text-slate-300">
                    {formatFileLabel(file)}
                  </span>
                </label>
              ))}
            </div>
          </div>

          <div className="min-h-0 overflow-y-auto p-5">
            <form
              onSubmit={(event) => {
                event.preventDefault();
                setSubmittedQuery(query.trim());
                setSelectedTarget(null);
              }}
              className="flex items-center gap-3"
            >
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="min-w-0 flex-1 rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-100"
                placeholder="Search target book"
              />
              <button
                type="submit"
                disabled={candidatesQuery.isFetching}
                className="shrink-0 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {candidatesQuery.isFetching ? "Searching..." : "Search"}
              </button>
            </form>

            {candidatesQuery.isError && (
              <div className="mt-4 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
                Failed to load target books.
              </div>
            )}

            <div className="mt-4 space-y-2">
              {candidates.map((candidate) => {
                const imgUrl = getImageUrl(candidate.cover_image_cached_path, candidate.cover_image_url);
                const coverPresentation = getBookCoverPresentation(candidate.cover_aspect_ratio);
                const isSelected = selectedTarget?.id === candidate.id;
                const series = formatSeries(candidate);
                return (
                  <button
                    key={candidate.id}
                    type="button"
                    onClick={() => setSelectedTarget(candidate)}
                    className={`flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors ${
                      isSelected
                        ? "border-emerald-500 bg-emerald-500/10"
                        : "border-slate-700 bg-slate-800 hover:border-slate-500"
                    }`}
                  >
                    <div className={`h-16 w-11 shrink-0 overflow-hidden rounded ${coverPresentation.frameClassName}`}>
                      {imgUrl ? (
                        <img src={imgUrl} alt="" className={coverPresentation.imageClassName} />
                      ) : (
                        <div className="flex h-full w-full items-center justify-center bg-slate-700 text-xs font-semibold text-slate-400">
                          {candidate.title.charAt(0)}
                        </div>
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <span className="truncate text-sm font-medium text-slate-100">{candidate.title}</span>
                        {candidate.is_hidden && (
                          <span className="shrink-0 rounded bg-amber-500/15 px-2 py-0.5 text-[11px] font-medium text-amber-300">
                            Hidden
                          </span>
                        )}
                        {candidate.is_owned && (
                          <span className="shrink-0 rounded bg-emerald-500/15 px-2 py-0.5 text-[11px] font-medium text-emerald-300">
                            Owned
                          </span>
                        )}
                      </div>
                      <div className="mt-1 truncate text-xs text-slate-400">
                        {candidate.author_name}
                        {candidate.release_date ? ` - ${candidate.release_date.substring(0, 4)}` : ""}
                        {series ? ` - ${series}` : ""}
                      </div>
                      {candidate.hidden_categories.length > 0 && (
                        <div className="mt-1 truncate text-xs text-slate-500">
                          {candidate.hidden_categories.map((category) => category.label).join(", ")}
                        </div>
                      )}
                    </div>
                  </button>
                );
              })}
              {!candidatesQuery.isFetching && candidates.length === 0 && (
                <div className="rounded-lg border border-slate-700 bg-slate-800 px-4 py-8 text-center text-sm text-slate-400">
                  No matching target books.
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="flex shrink-0 items-center justify-between gap-3 border-t border-slate-700 px-6 py-4">
          <div className="min-w-0 text-sm">
            {actionError ? (
              <span className="text-rose-300">{actionError}</span>
            ) : selectedTarget ? (
              <span className="text-slate-400">
                Target: <span className="text-slate-200">{selectedTarget.title}</span>
              </span>
            ) : (
              <span className="text-slate-500">Select a target book.</span>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-slate-600 bg-slate-800 px-4 py-2 text-sm text-slate-200 hover:bg-slate-700"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={!canSave}
              className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {fixMatch.isPending ? "Saving..." : "Fix Match"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
