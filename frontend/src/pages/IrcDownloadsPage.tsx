import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  useCancelIrcBulkBatch,
  useClearIrcDownloadsFeed,
  useCreateIrcBulkBatch,
  useIrcBulkBatch,
  useIrcDownloadsFeed,
  useIrcStatus,
  usePauseIrcBulkBatch,
  useResumeIrcBulkBatch,
} from "../api/irc";
import type { Book, IrcBulkDownloadItem, IrcDownloadFeedEntry } from "../types";

type SelectedBook = Pick<Book, "id" | "title" | "author_name" | "is_owned">;

type IrcDownloadsLocationState = {
  selectedBooks?: SelectedBook[];
};

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

export default function IrcDownloadsPage() {
  const location = useLocation();
  const queryClient = useQueryClient();
  const createBatch = useCreateIrcBulkBatch();
  const clearHistory = useClearIrcDownloadsFeed();
  const { data: ircStatus, isLoading: ircStatusLoading } = useIrcStatus(true);
  const { data: feedEntries, isLoading: feedLoading } = useIrcDownloadsFeed(true);
  const locationState = (location.state as IrcDownloadsLocationState | null) ?? null;
  const [pendingBooks, setPendingBooks] = useState<SelectedBook[]>(locationState?.selectedBooks ?? []);
  const [dismissedBatchIds, setDismissedBatchIds] = useState<number[]>([]);
  const completedEntryIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (locationState?.selectedBooks && locationState.selectedBooks.length > 0) {
      setPendingBooks(locationState.selectedBooks);
    }
  }, [locationState]);

  useEffect(() => {
    if (!feedEntries) return;
    const newCompletedEntryIds = feedEntries
      .filter((entry) => entry.status === "completed")
      .map((entry) => entry.entry_id)
      .filter((entryId) => !completedEntryIdsRef.current.has(entryId));

    if (newCompletedEntryIds.length === 0) return;

    newCompletedEntryIds.forEach((entryId) => completedEntryIdsRef.current.add(entryId));
    queryClient.invalidateQueries({ queryKey: ["books"] });
    queryClient.invalidateQueries({ queryKey: ["authors"] });
    queryClient.invalidateQueries({ queryKey: ["hiddenBooks"] });
  }, [feedEntries, queryClient]);

  const isIrcReady = Boolean(ircStatus?.connected && ircStatus?.joined_channel);
  const activeEntries = useMemo(
    () => (feedEntries ?? []).filter((entry) => entry.active),
    [feedEntries],
  );
  const activeSingleEntries = useMemo(
    () => activeEntries.filter((entry) => entry.source !== "bulk"),
    [activeEntries],
  );
  const activeBulkBatchIds = useMemo(() => {
    const ids: number[] = [];
    const seen = new Set<number>();
    for (const entry of activeEntries) {
      if (entry.source !== "bulk" || entry.batch_id == null || dismissedBatchIds.includes(entry.batch_id)) {
        continue;
      }
      if (seen.has(entry.batch_id)) {
        continue;
      }
      seen.add(entry.batch_id);
      ids.push(entry.batch_id);
    }
    return ids;
  }, [activeEntries, dismissedBatchIds]);
  const historyEntries = useMemo(
    () => (feedEntries ?? []).filter((entry) => !entry.active),
    [feedEntries],
  );
  const selectedMissingCount = useMemo(
    () => pendingBooks.filter((book) => !book.is_owned).length,
    [pendingBooks],
  );

  const handleStartBatch = async () => {
    if (pendingBooks.length === 0) return;
    try {
      await createBatch.mutateAsync({
        book_ids: pendingBooks.map((book) => book.id),
      });
      setPendingBooks([]);
    } catch {
      // Mutation state is rendered below.
    }
  };

  const handleClearHistory = async () => {
    if (!window.confirm("Clear completed and failed IRC download history? Active jobs will be kept.")) {
      return;
    }
    await clearHistory.mutateAsync();
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">IRC Downloads</h1>
          <p className="mt-1 text-sm text-slate-400">
            Persistent per-book IRC activity for bulk and individual downloads.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleClearHistory}
            disabled={clearHistory.isPending}
            className="rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-200 transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {clearHistory.isPending ? "Clearing..." : "Clear History"}
          </button>
          <Link
            to="/settings/irc"
            className="rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-200 transition-colors hover:bg-slate-700"
          >
            IRC Settings
          </Link>
        </div>
      </div>

      {!ircStatusLoading && !isIrcReady && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4">
          <div className="text-sm font-semibold text-amber-200">IRC is not ready</div>
          <div className="mt-1 text-sm text-amber-100/90">
            Connect to the IRC server and join the configured channel before starting a bulk download run.
          </div>
        </div>
      )}

      {pendingBooks.length > 0 && (
        <section className="rounded-2xl border border-slate-700 bg-slate-800/80">
          <div className="border-b border-slate-700 px-5 py-4">
            <div className="text-base font-semibold text-slate-100">Start Bulk IRC Download</div>
            <div className="mt-1 text-sm text-slate-400">
              Confirm the selected books, then Booksarr will search and import them one at a time.
            </div>
          </div>
          <div className="space-y-4 px-5 py-4">
            <div className="flex flex-wrap items-center gap-2 text-sm text-slate-300">
              <span className="rounded-full bg-slate-700 px-3 py-1">{pendingBooks.length} selected</span>
              <span className="rounded-full bg-slate-700 px-3 py-1">{selectedMissingCount} missing</span>
              {selectedMissingCount !== pendingBooks.length && (
                <span className="rounded-full bg-slate-700 px-3 py-1">{pendingBooks.length - selectedMissingCount} owned</span>
              )}
            </div>
            <div className="rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-3 text-sm text-slate-300">
              Booksarr will search each selected book, download the search results, choose the best ebook match, import it into the library, then continue to the next book.
            </div>
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {pendingBooks.map((book, index) => (
                <div key={book.id} className="rounded-lg border border-slate-700 bg-slate-900/40 px-3 py-2.5">
                  <div className="flex items-start gap-3">
                    <div className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-700 text-[11px] font-semibold text-slate-200">
                      {index + 1}
                    </div>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-slate-100">{book.title}</div>
                      <div className="truncate text-xs text-slate-400">{book.author_name}</div>
                    </div>
                    <div className="ml-auto shrink-0 text-[11px] text-slate-500">
                      {book.is_owned ? "Owned" : "Missing"}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            {createBatch.isError && (
              <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
                Failed to start the bulk IRC batch.
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-end gap-3 border-t border-slate-700 px-5 py-4">
            <button
              type="button"
              onClick={() => setPendingBooks([])}
              className="rounded-md border border-slate-600 bg-slate-800 px-4 py-2 text-sm text-slate-200 transition-colors hover:bg-slate-700"
            >
              Clear Selection
            </button>
            <button
              type="button"
              onClick={handleStartBatch}
              disabled={!isIrcReady || createBatch.isPending}
              className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {createBatch.isPending ? "Starting..." : "Search All Selected Books"}
            </button>
          </div>
        </section>
      )}

      {activeBulkBatchIds.length > 0 && (
        <section className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">Active IRC Batches</h2>
            <p className="mt-1 text-sm text-slate-400">
              Bulk runs are grouped here with pause, resume, and cancel controls per batch.
            </p>
          </div>
          <div className="space-y-4">
            {activeBulkBatchIds.map((activeBatchId) => (
              <ActiveBulkBatchCard
                key={activeBatchId}
                batchId={activeBatchId}
                onDismiss={(dismissedId) => {
                  setDismissedBatchIds((current) => (
                    current.includes(dismissedId) ? current : [...current, dismissedId]
                  ));
                }}
              />
            ))}
          </div>
        </section>
      )}

      <section className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">Active IRC Jobs</h2>
            <p className="mt-1 text-sm text-slate-400">Running jobs stay pinned here until they complete or fail.</p>
          </div>
        </div>
        {feedLoading && !feedEntries ? (
          <div className="rounded-xl border border-slate-700 bg-slate-800/70 px-5 py-6 text-sm text-slate-400">
            Loading IRC download activity...
          </div>
        ) : activeSingleEntries.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/40 px-5 py-6 text-sm text-slate-500">
            No active IRC jobs.
          </div>
        ) : (
          <div className="space-y-3">
            {activeSingleEntries.map((entry) => (
              <DownloadFeedCard key={entry.entry_id} entry={entry} compact />
            ))}
          </div>
        )}
      </section>

      <section className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">Recent IRC History</h2>
          <p className="mt-1 text-sm text-slate-400">Most recent completed and failed book jobs.</p>
        </div>
        {historyEntries.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/40 px-5 py-6 text-sm text-slate-500">
            No completed IRC history yet.
          </div>
        ) : (
          <RecentHistoryTable entries={historyEntries} />
        )}
      </section>
    </div>
  );
}

function ActiveBulkBatchCard({
  batchId,
  onDismiss,
}: {
  batchId: number;
  onDismiss: (batchId: number) => void;
}) {
  const { data: batch, isLoading: batchLoading } = useIrcBulkBatch(batchId, true);
  const pauseBatch = usePauseIrcBulkBatch();
  const resumeBatch = useResumeIrcBulkBatch();
  const cancelBatch = useCancelIrcBulkBatch();

  const remainingBatchBooks = batch
    ? Math.max(0, batch.total_books - batch.completed_books - batch.failed_books - batch.cancelled_books)
    : 0;
  const batchActionPending = pauseBatch.isPending || resumeBatch.isPending || cancelBatch.isPending;

  useEffect(() => {
    if (batch && (batch.status === "cancelling" || batch.status === "cancelled")) {
      onDismiss(batch.id);
    }
  }, [batch, onDismiss]);

  const handlePauseBatch = async () => {
    await pauseBatch.mutateAsync(batchId);
  };

  const handleResumeBatch = async () => {
    await resumeBatch.mutateAsync(batchId);
  };

  const handleCancelBatch = async () => {
    const message =
      batch?.status === "paused"
        ? "Cancel this paused batch and remove the remaining queued books from the list?"
        : "Cancel this batch after the current book finishes? Remaining queued books will be removed from the list.";
    if (!window.confirm(message)) {
      return;
    }
    await cancelBatch.mutateAsync(batchId);
    onDismiss(batchId);
  };

  return (
    <section className="rounded-2xl border border-slate-700 bg-slate-800/80">
      <div className="border-b border-slate-700 px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-base font-semibold text-slate-100">Batch #{batchId}</div>
            <div className="mt-1 text-sm text-slate-400">
              {batch?.created_at ? formatLocalTimestamp(batch.created_at) : "Loading batch status..."}
            </div>
          </div>
          {batch?.status && (
            <div className={`rounded-full px-3 py-1 text-xs font-medium ${batchStatusTone(batch.status)}`}>
              {formatBatchStatus(batch.status)}
            </div>
          )}
        </div>
      </div>
      <div className="space-y-4 px-5 py-4">
        {batchLoading && !batch ? (
          <div className="text-sm text-slate-400">Loading batch status...</div>
        ) : batch ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2 text-sm text-slate-300">
                <span className="rounded-full bg-slate-700 px-3 py-1">{batch.completed_books} completed</span>
                <span className="rounded-full bg-slate-700 px-3 py-1">{batch.failed_books} failed</span>
                {batch.cancelled_books > 0 && (
                  <span className="rounded-full bg-slate-700 px-3 py-1">{batch.cancelled_books} cancelled</span>
                )}
                <span className="rounded-full bg-slate-700 px-3 py-1">{remainingBatchBooks} remaining</span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {(batch.status === "queued" || batch.status === "running") && (
                  <>
                    <button
                      type="button"
                      onClick={handlePauseBatch}
                      disabled={batchActionPending}
                      className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm font-medium text-amber-200 transition-colors hover:bg-amber-500/15 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {pauseBatch.isPending ? "Pausing..." : "Pause After Current"}
                    </button>
                    <button
                      type="button"
                      onClick={handleCancelBatch}
                      disabled={batchActionPending}
                      className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm font-medium text-rose-200 transition-colors hover:bg-rose-500/15 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {cancelBatch.isPending ? "Cancelling..." : "Cancel After Current"}
                    </button>
                  </>
                )}
                {batch.status === "pausing" && (
                  <>
                    <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm font-medium text-amber-200">
                      Pausing after current book
                    </div>
                    <button
                      type="button"
                      onClick={handleCancelBatch}
                      disabled={batchActionPending}
                      className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm font-medium text-rose-200 transition-colors hover:bg-rose-500/15 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {cancelBatch.isPending ? "Cancelling..." : "Cancel After Current"}
                    </button>
                  </>
                )}
                {batch.status === "paused" && (
                  <>
                    <button
                      type="button"
                      onClick={handleResumeBatch}
                      disabled={batchActionPending}
                      className="rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {resumeBatch.isPending ? "Resuming..." : "Resume"}
                    </button>
                    <button
                      type="button"
                      onClick={handleCancelBatch}
                      disabled={batchActionPending}
                      className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm font-medium text-rose-200 transition-colors hover:bg-rose-500/15 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {cancelBatch.isPending ? "Cancelling..." : "Cancel"}
                    </button>
                  </>
                )}
                {batch.status === "cancelling" && (
                  <div className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm font-medium text-rose-200">
                    Cancelling after current book
                  </div>
                )}
              </div>
            </div>
            {(pauseBatch.isError || resumeBatch.isError || cancelBatch.isError) && (
              <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
                Failed to update the batch state.
              </div>
            )}
            <div className="space-y-2">
              {batch.items.map((item) => (
                <FocusedBatchRow key={item.id} item={item} />
              ))}
            </div>
          </>
        ) : (
          <div className="text-sm text-slate-400">Batch not found.</div>
        )}
      </div>
    </section>
  );
}

function FocusedBatchRow({ item }: { item: IrcBulkDownloadItem }) {
  const activeRetryError = item.status !== "failed" ? item.error_message : null;
  const importedPath = item.download_job?.moved_to_library_path ?? null;
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/40 px-4 py-3">
      <div className="space-y-3">
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
              <AuthorNameLink authorId={item.author_id} authorName={item.author_name} />
              {item.attempt_count > 0 ? ` • Attempt ${item.attempt_count}` : ""}
            </div>
          </div>
          <CompactStageRail status={item.status} error={item.error_message} retryError={activeRetryError} />
        </div>
        {item.selected_result_label && (
          <div className="rounded-md border border-cyan-500/20 bg-cyan-500/10 px-3 py-2 text-[11px] text-cyan-200">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-300/80">
              Selected Result
            </div>
            <div className="break-words font-mono">{item.selected_result_label}</div>
            {importedPath && (
              <div className="mt-2 border-t border-cyan-400/15 pt-2">
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-emerald-300/80">
                  Imported To
                </div>
                <div className="break-all text-[11px] text-emerald-200">{importedPath}</div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function DownloadFeedCard({ entry, compact = false }: { entry: IrcDownloadFeedEntry; compact?: boolean }) {
  const timestamp = entry.completed_at ?? entry.updated_at ?? entry.created_at ?? entry.sort_timestamp;
  const activeRetryError =
    entry.active && entry.source === "bulk" && entry.final_result_kind === "error"
      ? entry.final_result_text
      : null;
  const showInlineFinalResult = Boolean(!entry.active && entry.final_result_kind && entry.final_result_text);
  return (
    <article className="rounded-2xl border border-slate-700 bg-slate-800/70 px-4 py-3">
      <div className={`grid gap-3 ${compact ? "xl:grid-cols-[170px_minmax(0,1fr)]" : "xl:grid-cols-[170px_minmax(0,1fr)]"}`}>
        <div className="space-y-2">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
            {entry.active ? "Active" : "Completed"}
          </div>
          <div className="text-sm font-medium text-slate-200">
            {timestamp ? formatLocalTimestamp(timestamp) : "No timestamp"}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${itemStatusTone(entry.status)}`}>
              {formatItemStatus(entry.status)}
            </span>
            <span className="rounded-full bg-slate-700 px-2.5 py-1 text-[11px] font-medium text-slate-300">
              {entry.source === "bulk" ? "Bulk" : "Single"}
            </span>
            {entry.attempt_count > 0 && (
              <span className="rounded-full bg-slate-700 px-2.5 py-1 text-[11px] font-medium text-slate-300">
                Attempt {entry.attempt_count}
              </span>
            )}
          </div>
        </div>

        <div className="min-w-0">
          <div className="text-base font-semibold text-slate-100">{entry.title}</div>
          <div className="mt-1 text-sm text-slate-400">
            <AuthorNameLink authorId={entry.author_id} authorName={entry.author_name} />
          </div>
          {entry.query_text && (
            <div className="mt-2 text-xs text-slate-500">
              Query: <span className="text-slate-400">{entry.query_text}</span>
            </div>
          )}
          {entry.selected_result_label && (
            <div className="mt-2 rounded-md border border-cyan-500/20 bg-cyan-500/10 px-3 py-2 text-[11px] text-cyan-200">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-300/80">
                Selected Result
              </div>
              <div className="break-words font-mono">{entry.selected_result_label}</div>
            </div>
          )}
          <div className="mt-3 rounded-md bg-slate-950/60 px-3 py-2">
            <CompactStageRail
              status={entry.status}
              error={!entry.active && entry.final_result_kind === "error" ? entry.final_result_text : null}
              retryError={activeRetryError}
            />
          </div>
          {showInlineFinalResult && entry.final_result_text && (
            <div
              className={`mt-3 rounded-xl px-4 py-3 ${
                entry.final_result_kind === "imported"
                  ? "border border-emerald-500/20 bg-emerald-500/10"
                  : "border border-rose-500/25 bg-rose-500/10"
              }`}
            >
              <div
                className={`text-[11px] font-semibold uppercase tracking-[0.14em] ${
                  entry.final_result_kind === "imported" ? "text-emerald-300/80" : "text-rose-300/80"
                }`}
              >
                Final Result
              </div>
              <div
                className={`mt-1 text-sm font-medium ${
                  entry.final_result_kind === "error" ? "text-rose-200" : "text-emerald-200"
                }`}
              >
                {entry.final_result_kind === "imported"
                  ? "Imported to"
                  : entry.final_result_kind === "downloaded"
                    ? "Downloaded to"
                    : "Error"}
              </div>
              <div
                className={`mt-1 break-all text-xs ${
                  entry.final_result_kind === "error" ? "text-rose-100/90" : "text-emerald-100/90"
                }`}
              >
                {entry.final_result_text}
              </div>
            </div>
          )}
          {!showInlineFinalResult && entry.active && (
            <div className="mt-3 rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-3 text-sm text-slate-400">
              {activeRetryError ? "Retrying after the last failure." : "Job still running."}
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

function RecentHistoryTable({ entries }: { entries: IrcDownloadFeedEntry[] }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-700 bg-slate-800/70">
      <div className="hidden grid-cols-[52px_172px_180px_minmax(240px,1.45fr)_132px_84px_78px_82px] gap-x-5 border-b border-slate-700 bg-slate-900/80 px-5 py-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400 lg:grid">
        <div className="text-center"><span className="sr-only">Status</span></div>
        <div>Date Time</div>
        <div>Author</div>
        <div>Book Title</div>
        <div>Final Result</div>
        <div>Size</div>
        <div>Attempts</div>
        <div>Bulk #</div>
      </div>
      <div className="divide-y divide-slate-700">
        {entries.map((entry) => (
          <RecentHistoryRow key={entry.entry_id} entry={entry} />
        ))}
      </div>
    </div>
  );
}

function RecentHistoryRow({ entry }: { entry: IrcDownloadFeedEntry }) {
  const timestamp = entry.completed_at ?? entry.updated_at ?? entry.created_at ?? entry.sort_timestamp;
  const detailRows = getHistoryDetailRows(entry);
  const sizeText = getHistorySize(entry);

  return (
    <article className="px-5 py-3.5">
      <div className="grid gap-3 lg:grid-cols-[52px_172px_180px_minmax(240px,1.45fr)_132px_84px_78px_82px] lg:items-center lg:gap-x-5">
        <div className="flex items-start justify-between gap-3 lg:block">
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 lg:hidden">
            Status
          </div>
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-900/80 ring-1 ring-slate-700 lg:mx-auto">
            <HistoryStatusIcon kind={entry.final_result_kind} />
          </div>
        </div>
        <HistoryCell
          label="Date Time"
          value={timestamp ? formatLocalTimestamp(timestamp) : "No timestamp"}
          noTruncate
          className="text-slate-300"
        />
        <HistoryCell
          label="Author"
          value={entry.author_name || "Unknown author"}
          href={entry.author_id != null ? `/authors/${entry.author_id}` : undefined}
        />
        <HistoryCell label="Book Title" value={entry.title} emphasized />
        <HistoryCell
          label="Final Result"
          value={formatHistoryFinalResult(entry)}
          tone={entry.final_result_kind === "error" ? "text-rose-200" : "text-emerald-200"}
        />
        <HistoryCell label="Size" value={sizeText} mono className="lg:text-center" />
        <HistoryCell
          label="Attempts"
          value={entry.attempt_count > 0 ? String(entry.attempt_count) : "1"}
          className="lg:text-center"
        />
        <HistoryCell
          label="Bulk #"
          value={entry.batch_id != null ? `#${entry.batch_id}` : "Single"}
          className="lg:text-center"
        />
      </div>
      <div className="mt-2 space-y-1.5 border-t border-slate-700/70 pt-2">
        {detailRows.map((row) => (
          <div key={row.label} className="text-xs leading-5">
            <span className={`mr-2 font-semibold uppercase tracking-[0.12em] ${row.labelTone}`}>
              {row.label}:
            </span>
            <span className={`break-all ${row.valueTone}`}>{row.value}</span>
          </div>
        ))}
      </div>
    </article>
  );
}

function HistoryStatusIcon({ kind }: { kind: string | null }) {
  const isError = kind === "error";
  if (isError) {
    return (
      <svg
        className="h-5 w-5 text-rose-400"
        viewBox="0 0 20 20"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M6.25 6.25L13.75 13.75M13.75 6.25L6.25 13.75"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      </svg>
    );
  }
  return (
    <svg
      className="h-4 w-4 text-emerald-400"
      viewBox="0 0 20 20"
      fill="currentColor"
      aria-hidden="true"
    >
      <path
        fillRule="evenodd"
        d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.03-9.22a.75.75 0 10-1.06-1.06L9.25 10.44 8.03 9.22a.75.75 0 00-1.06 1.06l1.75 1.75a.75.75 0 001.06 0l3.25-3.25z"
        clipRule="evenodd"
      />
    </svg>
  );
}

function HistoryCell({
  label,
  value,
  emphasized = false,
  tone = "text-slate-200",
  mono = false,
  noTruncate = false,
  className = "",
  href,
}: {
  label: string;
  value: string;
  emphasized?: boolean;
  tone?: string;
  mono?: boolean;
  noTruncate?: boolean;
  className?: string;
  href?: string;
}) {
  const contentClassName = `${noTruncate ? "" : "truncate"} text-sm leading-5 ${tone} ${emphasized ? "font-semibold text-slate-100" : ""} ${mono ? "font-mono text-[13px]" : ""} ${className}`;
  return (
    <div className="min-w-0">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500 lg:hidden">
        {label}
      </div>
      {href ? (
        <Link to={href} className={`${contentClassName} transition-colors hover:text-emerald-300`}>
          {value}
        </Link>
      ) : (
        <div className={contentClassName}>{value}</div>
      )}
    </div>
  );
}

function AuthorNameLink({
  authorId,
  authorName,
}: {
  authorId: number | null | undefined;
  authorName: string | null | undefined;
}) {
  const label = authorName || "Unknown author";
  if (authorId == null) {
    return <>{label}</>;
  }
  return (
    <Link to={`/authors/${authorId}`} className="transition-colors hover:text-emerald-300">
      {label}
    </Link>
  );
}

function CompactStageRail({
  status,
  error,
  retryError,
}: {
  status: string;
  error?: string | null;
  retryError?: string | null;
}) {
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
  const activeRank = ITEM_PROGRESS_ORDER.indexOf((status === "failed" ? "queued" : status) as typeof ITEM_PROGRESS_ORDER[number]);
  const failureRank = getFailureProgressRank(status);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {stages.map((stage, index) => {
          const isErrorStage = stage.key === "failed";
          const isActive = status === stage.key;
          const isDone = isErrorStage
            ? false
            : status === "failed"
              ? failureRank >= index
              : activeRank > index;
          const tone = isErrorStage && isActive
            ? "border-rose-500/30 bg-rose-500/15 text-rose-200"
            : isDone || isActive
              ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-200"
              : status === "failed"
                ? "border-rose-500/15 bg-slate-900 text-rose-200/70"
                : "border-slate-700 bg-slate-900 text-slate-500";
          const marker = isActive ? "->" : isDone ? "✓" : " ";

          return (
            <div key={stage.key} className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-[11px] font-medium ${tone}`}>
              <span className="font-semibold">{marker}</span>
              <span>{stage.label}</span>
            </div>
          );
        })}
      </div>
      {status === "failed" && error && (
        <div className="break-all text-[11px] text-rose-200/90">{error}</div>
      )}
      {status !== "failed" && retryError && (
        <div className="rounded-md border border-rose-500/20 bg-rose-500/10 px-3 py-2">
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-rose-300/80">
            Latest Retry Error
          </div>
          <div className="mt-1 break-all text-[11px] text-rose-200/90">{retryError}</div>
        </div>
      )}
    </div>
  );
}

function getFailureProgressRank(status: string, path?: string | null): number {
  if (status === "completed" && path) return 6;
  if (status === "importing") return 6;
  if (status === "extracting") return 5;
  if (status === "downloading_book") return 4;
  if (status === "choosing_best_option") return 3;
  if (status === "downloading_search_results") return 2;
  if (status === "searching") return 1;
  return 0;
}

function formatBatchStatus(status: string): string {
  if (status === "queued") return "Queued";
  if (status === "running") return "Running";
  if (status === "pausing") return "Pausing After Current Book";
  if (status === "paused") return "Paused";
  if (status === "cancelling") return "Cancelling After Current Book";
  if (status === "cancelled") return "Cancelled";
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
  if (status === "cancelled") return "Cancelled";
  if (status === "failed") return "Failed";
  return status;
}

function batchStatusTone(status: string): string {
  if (status === "completed") return "bg-emerald-500/15 text-emerald-300";
  if (status === "running") return "bg-blue-500/15 text-blue-300";
  if (status === "pausing" || status === "paused") return "bg-amber-500/15 text-amber-300";
  if (status === "cancelling" || status === "cancelled") return "bg-rose-500/15 text-rose-300";
  return "bg-slate-700 text-slate-300";
}

function itemStatusTone(status: string): string {
  if (status === "completed") return "bg-emerald-500/15 text-emerald-300";
  if (status === "cancelled") return "bg-slate-700 text-slate-300";
  if (status === "failed") return "bg-rose-500/15 text-rose-300";
  if (status === "queued") return "bg-slate-700 text-slate-300";
  return "bg-blue-500/15 text-blue-300";
}

function formatLocalTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  let hours = date.getHours();
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const meridiem = hours >= 12 ? "pm" : "am";
  hours %= 12;
  if (hours === 0) hours = 12;
  return `${year}-${month}-${day} ${hours}:${minutes}${meridiem}`;
}

function formatHistoryFinalResult(entry: IrcDownloadFeedEntry): string {
  if (entry.final_result_kind === "imported") return "Imported";
  if (entry.final_result_kind === "downloaded") return "Downloaded";
  if (entry.final_result_kind === "error") return "Error";
  if (entry.status === "cancelled") return "Cancelled";
  return formatItemStatus(entry.status);
}

function getHistoryDetailRows(entry: IrcDownloadFeedEntry): Array<{
  label: string;
  value: string;
  labelTone: string;
  valueTone: string;
}> {
  if (entry.final_result_kind === "error" && entry.final_result_text) {
    return [
      {
        label: "Error",
        value: entry.final_result_text,
        labelTone: "text-rose-300/80",
        valueTone: "text-rose-200",
      },
    ];
  }

  const rows: Array<{
    label: string;
    value: string;
    labelTone: string;
    valueTone: string;
  }> = [];

  if (entry.selected_result_label) {
    rows.push({
      label: "Selected Result",
      value: entry.selected_result_label,
      labelTone: "text-cyan-300/80",
      valueTone: "font-mono text-cyan-200",
    });
  }

  if (entry.final_result_kind === "imported" && entry.final_result_text) {
    rows.push({
      label: "Import Path",
      value: entry.final_result_text,
      labelTone: "text-emerald-300/80",
      valueTone: "text-emerald-200",
    });
  } else if (entry.final_result_kind === "downloaded" && entry.final_result_text) {
    rows.push({
      label: "Download Path",
      value: entry.final_result_text,
      labelTone: "text-emerald-300/80",
      valueTone: "text-emerald-200",
    });
  }

  if (rows.length > 0) {
    return rows;
  }

  return [
    {
      label: "Status",
      value: formatHistoryFinalResult(entry),
      labelTone: "text-slate-400",
      valueTone: "text-slate-300",
    },
  ];
}

function getHistorySize(entry: IrcDownloadFeedEntry): string {
  const fromSelectedResult = extractResultSize(entry.selected_result_label);
  if (fromSelectedResult) return fromSelectedResult;
  const dccFilename = entry.download_job?.dcc_filename;
  const fromFilename = extractResultSize(dccFilename);
  return fromFilename ?? "—";
}

function extractResultSize(value: string | null | undefined): string | null {
  if (!value) return null;
  const match = value.match(/::INFO::\s*([0-9]+(?:\.[0-9]+)?\s*(?:KB|MB|GB|TB))/i);
  return match ? match[1].replace(/\s+/g, "") : null;
}
