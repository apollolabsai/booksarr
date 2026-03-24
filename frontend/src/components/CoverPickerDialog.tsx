import { useEffect, useState } from "react";
import { getImageUrl } from "../types";
import { useBookCoverOptions, useSetBookCover } from "../api/books";

export default function CoverPickerDialog({
  bookId,
  title,
  open,
  onClose,
}: {
  bookId: number | null;
  title: string;
  open: boolean;
  onClose: () => void;
}) {
  const { data, isLoading, isError } = useBookCoverOptions(bookId, open);
  const setBookCover = useSetBookCover();
  const [selectedSource, setSelectedSource] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    const preferredSource =
      data.options.find((option) => option.is_manual)?.source
      ?? data.options.find((option) => option.is_current)?.source
      ?? data.options[0]?.source
      ?? null;
    setSelectedSource(preferredSource);
  }, [data]);

  if (!open || !bookId) return null;

  const handleSave = async () => {
    if (!selectedSource) return;
    await setBookCover.mutateAsync({ bookId, source: selectedSource });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 px-4 py-6">
      <div className="max-h-[90vh] w-full max-w-6xl overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-start justify-between border-b border-slate-700 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">Choose Poster</h2>
            <p className="mt-1 text-sm text-slate-400">{title}</p>
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
          {isLoading && <p className="text-sm text-slate-400">Loading poster options...</p>}
          {isError && <p className="text-sm text-rose-300">Failed to load poster options.</p>}
          {!isLoading && !isError && data?.options.length === 0 && (
            <p className="text-sm text-slate-400">No poster options are available for this book.</p>
          )}

          {data && data.options.length > 0 && (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {data.options.map((option) => {
                const imgUrl = getImageUrl(option.cached_path, option.image_url);
                const isSelected = selectedSource === option.source;
                return (
                  <button
                    key={option.key}
                    type="button"
                    onClick={() => setSelectedSource(option.source)}
                    className={`rounded-xl border p-3 text-left transition-colors ${
                      isSelected
                        ? "border-emerald-500 bg-emerald-500/10"
                        : "border-slate-700 bg-slate-800 hover:border-slate-500"
                    }`}
                  >
                    <div className="mb-3 flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-slate-100">{option.label}</span>
                      <div className="flex gap-1.5">
                        {option.is_current && (
                          <span className="rounded-full bg-blue-500/15 px-2 py-0.5 text-[10px] font-medium text-blue-300">
                            Current
                          </span>
                        )}
                        {option.is_manual && (
                          <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-300">
                            Saved
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex aspect-[2/3] items-center justify-center rounded-lg bg-black p-2">
                      {imgUrl ? (
                        <img src={imgUrl} alt={`${title} ${option.label} cover`} className="h-full w-full object-contain" />
                      ) : (
                        <div className="text-center text-xs text-slate-500">No preview</div>
                      )}
                    </div>
                    <div className="mt-3 space-y-1 text-xs text-slate-300">
                      <div>
                        Resolution: {option.width && option.height ? `${option.width} x ${option.height}` : "Unknown"}
                      </div>
                      <div>
                        2:3 delta: {option.ratio_delta_percent != null ? `${option.ratio_delta_percent}%` : "Unknown"}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-slate-700 px-6 py-4">
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
            disabled={!selectedSource || setBookCover.isPending}
            className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {setBookCover.isPending ? "Saving..." : "Save Poster"}
          </button>
        </div>
      </div>
    </div>
  );
}
