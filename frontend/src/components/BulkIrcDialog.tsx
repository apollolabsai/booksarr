import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useCreateIrcBulkBatch, useIrcBulkBatch, useIrcStatus } from "../api/irc";
import type { Book, IrcBulkDownloadItem, IrcBulkFileTypePreference } from "../types";

const ACTIVE_ITEM_STATUSES = new Set([
  "searching",
  "downloading_search_results",
  "choosing_best_option",
  "downloading_book",
  "extracting",
  "importing",
]);

const ITEM_PROGRESS_ORDER = [
  "queued",
  "searching",
  "downloading_search_results",
  "choosing_best_option",
  "downloading_book",
  "extracting",
  "importing",
  "completed",
] as const;

const DEFAULT_IRC_BULK_FILE_TYPE_PREFERENCES: IrcBulkFileTypePreference[] = [
  { key: "epub", enabled: true },
  { key: "mobi", enabled: true },
  { key: "pdf", enabled: true },
  { key: "zip", enabled: true },
  { key: "rar", enabled: true },
  { key: "audiobook", enabled: true },
];

export default function BulkIrcDialog({
  open,
  books,
  onClose,
  onQueued,
}: {
  open: boolean;
  books: Book[];
  onClose: () => void;
  onQueued: () => void;
}) {
  const queryClient = useQueryClient();
  const createBatch = useCreateIrcBulkBatch();
  const { data: ircStatus, isLoading: ircStatusLoading } = useIrcStatus(open);
  const [batchId, setBatchId] = useState<number | null>(null);
  const completedBookIdsRef = useRef<Set<number>>(new Set());
  const { data: batch, isLoading: batchLoading } = useIrcBulkBatch(batchId, open && batchId != null);

  useEffect(() => {
    if (!open) return;
    setBatchId(null);
    completedBookIdsRef.current = new Set();
    createBatch.reset();
  }, [open]);

  useEffect(() => {
    if (!batch) return;
    const newCompletedBookIds = batch.items
      .filter((item) => item.status === "completed")
      .map((item) => item.book_id)
      .filter((bookId) => !completedBookIdsRef.current.has(bookId));

    if (newCompletedBookIds.length === 0) return;

    newCompletedBookIds.forEach((bookId) => completedBookIdsRef.current.add(bookId));
    queryClient.invalidateQueries({ queryKey: ["books"] });
    queryClient.invalidateQueries({ queryKey: ["authors"] });
    queryClient.invalidateQueries({ queryKey: ["hiddenBooks"] });
  }, [batch, queryClient]);

  const selectedMissingCount = useMemo(
    () => books.filter((book) => !book.is_owned).length,
    [books],
  );
  const isIrcReady = Boolean(ircStatus?.connected && ircStatus?.joined_channel);
  const activeItem = batch?.items.find((item) => ACTIVE_ITEM_STATUSES.has(item.status))
    ?? batch?.items.find((item) => item.status === "queued")
    ?? null;

  const handleStartBatch = async () => {
    try {
      const createdBatch = await createBatch.mutateAsync({
        book_ids: books.map((book) => book.id),
        file_type_preferences: DEFAULT_IRC_BULK_FILE_TYPE_PREFERENCES,
      });
      setBatchId(createdBatch.id);
      onQueued();
    } catch {
      // Error state is rendered below.
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 px-4 py-6">
      <div className="max-h-[90vh] w-full max-w-4xl overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-start justify-between border-b border-slate-700 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">Bulk IRC Download</h2>
            <p className="mt-1 text-sm text-slate-400">
              Confirm the selected books, then Booksarr will search and import them one at a time.
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

        <div className="max-h-[calc(90vh-140px)] space-y-5 overflow-y-auto px-6 py-5">
          {!ircStatusLoading && !isIrcReady && (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-5">
              <div className="text-base font-semibold text-amber-200">Connect to IRC first</div>
              <p className="mt-2 text-sm text-amber-100/90">
                Bulk downloads only run while the app is connected to the IRC server and joined to the configured channel.
              </p>
              <div className="mt-4">
                <Link
                  to="/settings/irc"
                  onClick={onClose}
                  className="inline-flex items-center rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500"
                >
                  Open IRC Settings
                </Link>
              </div>
            </div>
          )}

          {ircStatusLoading && (
            <div className="rounded-xl border border-slate-700 bg-slate-800 p-5 text-sm text-slate-300">
              Checking IRC connection status...
            </div>
          )}

          {isIrcReady && batchId == null && (
            <>
              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <div className="flex flex-wrap items-center gap-3 text-sm text-slate-300">
                  <div className="rounded-full bg-slate-700 px-3 py-1">{books.length} selected</div>
                  <div className="rounded-full bg-slate-700 px-3 py-1">{selectedMissingCount} missing</div>
                  {selectedMissingCount !== books.length && (
                    <div className="rounded-full bg-slate-700 px-3 py-1">{books.length - selectedMissingCount} owned</div>
                  )}
                </div>
                <div className="mt-4 rounded-lg border border-slate-700 bg-slate-900/40 px-4 py-3 text-sm text-slate-300">
                  Booksarr will search the first selected book, download the search results, choose the best ebook match, import it into the library, then continue to the next book.
                </div>
              </div>

              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <div className="mb-3 text-sm font-medium text-slate-100">Selected Books</div>
                <div className="max-h-80 space-y-2 overflow-y-auto pr-1">
                  {books.map((book, index) => (
                    <div
                      key={book.id}
                      className="flex items-center justify-between gap-4 rounded-lg border border-slate-700 bg-slate-900/40 px-3 py-2"
                    >
                      <div className="flex min-w-0 items-center gap-3">
                        <div className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-slate-700 text-[11px] font-semibold text-slate-200">
                          {index + 1}
                        </div>
                        <div className="min-w-0">
                          <div className="truncate text-sm text-slate-100">{book.title}</div>
                          <div className="truncate text-xs text-slate-400">{book.author_name}</div>
                        </div>
                      </div>
                      <div className="shrink-0 text-xs text-slate-500">
                        {book.is_owned ? "Owned" : "Missing"}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {createBatch.isError && (
                <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200">
                  Failed to start the bulk IRC batch.
                </div>
              )}
            </>
          )}

          {isIrcReady && batchId != null && (
            <>
              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <div className="flex flex-wrap items-center gap-3 text-sm text-slate-300">
                  <div className="rounded-full bg-slate-700 px-3 py-1">{batch?.completed_books ?? 0} completed</div>
                  <div className="rounded-full bg-slate-700 px-3 py-1">{batch?.failed_books ?? 0} failed</div>
                  <div className="rounded-full bg-slate-700 px-3 py-1">
                    {Math.max(0, (batch?.total_books ?? books.length) - (batch?.completed_books ?? 0) - (batch?.failed_books ?? 0))} remaining
                  </div>
                  {batch?.status && (
                    <div className={`rounded-full px-3 py-1 ${batchStatusTone(batch.status)}`}>
                      {formatBatchStatus(batch.status)}
                    </div>
                  )}
                </div>
                {activeItem && (
                  <div className="mt-4 rounded-lg border border-slate-700 bg-slate-900/40 px-4 py-3">
                    <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Current Book</div>
                    <div className="mt-1 text-sm font-medium text-slate-100">
                      {activeItem.position}. {activeItem.title}
                    </div>
                    <div className="mt-1 text-xs text-slate-400">
                      {activeItem.author_name || "Unknown author"} • {formatItemStatus(activeItem.status)}
                    </div>
                    {activeItem.selected_result_label && (
                      <div className="mt-2 rounded-md border border-cyan-500/20 bg-cyan-500/10 px-3 py-2 text-[11px] text-cyan-200">
                        <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-300/80">
                          Selected Result
                        </div>
                        <div className="break-words font-mono">
                          {activeItem.selected_result_label}
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {batch?.status === "completed" && (
                  <div className="mt-4 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
                    Batch finished. Completed books should now be reflected in the library views.
                  </div>
                )}
              </div>

              {batchLoading && !batch && (
                <div className="rounded-xl border border-slate-700 bg-slate-800 p-5 text-sm text-slate-300">
                  Loading batch status...
                </div>
              )}

              {batch && (
                <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                  <div className="mb-3 text-sm font-medium text-slate-100">Book Status</div>
                  <div className="space-y-3">
                    {batch.items.map((item) => (
                      <BulkBatchItemCard key={item.id} item={item} />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-slate-700 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-600 bg-slate-800 px-4 py-2 text-sm text-slate-200 hover:bg-slate-700"
          >
            {batchId != null ? "Done" : "Cancel"}
          </button>
          {batchId == null && (
            <button
              type="button"
              onClick={handleStartBatch}
              disabled={!isIrcReady || createBatch.isPending || books.length === 0}
              className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {createBatch.isPending ? "Starting..." : "Search All Selected Books"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function BulkBatchItemCard({ item }: { item: IrcBulkDownloadItem }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/40 px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-slate-700 text-[11px] font-semibold text-slate-200">
              {item.position}
            </div>
            <div className="text-sm font-medium text-slate-100">{item.title}</div>
            <div className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${itemStatusTone(item.status)}`}>
              {formatItemStatus(item.status)}
            </div>
          </div>
          <div className="mt-1 text-xs text-slate-400">
            {item.author_name || "Unknown author"}
            {item.attempt_count > 0 ? ` • Attempt ${item.attempt_count}` : ""}
          </div>
          {item.query_text && (
            <div className="mt-2 text-xs text-slate-500">Query: {item.query_text}</div>
          )}
          {item.selected_result_label && (
            <div className="mt-2 rounded-md border border-cyan-500/20 bg-cyan-500/10 px-3 py-2 text-[11px] text-cyan-200">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-300/80">
                Selected Result
              </div>
              <div className="break-words font-mono">
                {item.selected_result_label}
              </div>
            </div>
          )}
          {item.error_message && (
            <div className="mt-2 text-xs text-rose-300">{item.error_message}</div>
          )}
        </div>
      </div>
      <div className="mt-3 rounded-md bg-slate-950/60 px-3 py-2 text-xs">
        <BulkStageList item={item} />
      </div>
    </div>
  );
}

function BulkStageList({ item }: { item: IrcBulkDownloadItem }) {
  const stages = [
    { label: "Queued", key: "queued" },
    { label: "Search", key: "searching" },
    { label: "Download Search Results", key: "downloading_search_results" },
    { label: "Choosing Best Option", key: "choosing_best_option" },
    { label: "Downloading Book", key: "downloading_book" },
    { label: "Extracting", key: "extracting" },
    { label: "Importing", key: "importing" },
    { label: "Done", key: "completed" },
    { label: "Error", key: "failed" },
  ] as const;

  const failureRank = getFailureProgressRank(item);
  const activeRank = ITEM_PROGRESS_ORDER.indexOf((item.status === "failed" ? "queued" : item.status) as typeof ITEM_PROGRESS_ORDER[number]);

  return (
    <div className="space-y-1">
      {stages.map((stage, index) => {
        const isErrorStage = stage.key === "failed";
        const isActive = item.status === stage.key;
        const isDone = isErrorStage
          ? false
          : item.status === "failed"
            ? failureRank >= index
            : activeRank > index;
        const tone = isErrorStage && isActive
          ? "text-rose-300"
          : isDone || isActive
            ? "text-emerald-300"
            : item.status === "failed"
              ? "text-rose-300/70"
              : "text-slate-500";
        const marker = isActive ? "->" : isDone ? "✓" : " ";

        return (
          <div key={stage.key} className={tone}>
            <div className="flex items-start gap-2">
              <span className="inline-block w-4 shrink-0 text-left font-medium">{marker}</span>
              <span>{stage.label}</span>
            </div>
            {stage.key === "importing" && item.download_job?.moved_to_library_path && (
              <div className="ml-6 break-all text-[11px] text-emerald-200/90">
                {item.download_job.moved_to_library_path}
              </div>
            )}
            {stage.key === "failed" && isActive && item.error_message && (
              <div className="ml-6 break-all text-[11px] text-rose-200/90">{item.error_message}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function getFailureProgressRank(item: IrcBulkDownloadItem): number {
  if (item.download_job?.moved_to_library_path) return 6;

  if (item.download_job?.saved_path) {
    const originalWasArchive = (item.download_job.dcc_filename ?? "").toLowerCase().endsWith(".rar");
    const extractedArtifactReady = Boolean(
      originalWasArchive
        && item.download_job.saved_path
        && !item.download_job.saved_path.toLowerCase().endsWith(".rar"),
    );
    if (extractedArtifactReady) return 5;
    return 4;
  }

  if (item.selected_result_label) return 3;
  if ((item.search_job?.result_count ?? 0) > 0) return 2;
  if (item.search_job != null) return 1;
  return 0;
}

function formatBatchStatus(status: string): string {
  if (status === "queued") return "Queued";
  if (status === "running") return "Running";
  if (status === "completed") return "Completed";
  return status;
}

function formatItemStatus(status: string): string {
  if (status === "queued") return "Queued";
  if (status === "searching") return "Search";
  if (status === "downloading_search_results") return "Download Search Results";
  if (status === "choosing_best_option") return "Choosing Best Option";
  if (status === "downloading_book") return "Downloading Book";
  if (status === "extracting") return "Extracting";
  if (status === "importing") return "Importing";
  if (status === "completed") return "Done";
  if (status === "failed") return "Failed";
  return status;
}

function batchStatusTone(status: string): string {
  if (status === "completed") return "bg-emerald-500/15 text-emerald-300";
  if (status === "running") return "bg-blue-500/15 text-blue-300";
  return "bg-slate-700 text-slate-300";
}

function itemStatusTone(status: string): string {
  if (status === "completed") return "bg-emerald-500/15 text-emerald-300";
  if (status === "failed") return "bg-rose-500/15 text-rose-300";
  if (status === "queued") return "bg-slate-700 text-slate-300";
  return "bg-blue-500/15 text-blue-300";
}
