import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  useClearIrcDownloadsFeed,
  useCreateIrcBulkBatch,
  useIrcBulkBatch,
  useIrcDownloadsFeed,
  useIrcStatus,
} from "../api/irc";
import type { Book, IrcBulkDownloadItem, IrcDownloadFeedEntry } from "../types";

type SelectedBook = Pick<Book, "id" | "title" | "author_name" | "is_owned">;

type IrcDownloadsLocationState = {
  selectedBooks?: SelectedBook[];
};

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

export default function IrcDownloadsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const createBatch = useCreateIrcBulkBatch();
  const clearHistory = useClearIrcDownloadsFeed();
  const { data: ircStatus, isLoading: ircStatusLoading } = useIrcStatus(true);
  const { data: feedEntries, isLoading: feedLoading } = useIrcDownloadsFeed(true);
  const batchId = Number(searchParams.get("batchId") || "") || null;
  const { data: batch, isLoading: batchLoading } = useIrcBulkBatch(batchId, batchId != null);
  const locationState = (location.state as IrcDownloadsLocationState | null) ?? null;
  const [pendingBooks, setPendingBooks] = useState<SelectedBook[]>(locationState?.selectedBooks ?? []);
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
      const createdBatch = await createBatch.mutateAsync({
        book_ids: pendingBooks.map((book) => book.id),
      });
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set("batchId", String(createdBatch.id));
      setSearchParams(nextParams, { replace: true });
      setPendingBooks([]);
      navigate({ pathname: "/irc-downloads", search: nextParams.toString() }, { replace: true });
    } catch {
      // Mutation state is rendered below.
    }
  };

  const handleClearHistory = async () => {
    if (!window.confirm("Clear completed and failed IRC download history? Active jobs will be kept.")) {
      return;
    }
    await clearHistory.mutateAsync();
    if (batch?.status === "completed" && batchId != null) {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.delete("batchId");
      setSearchParams(nextParams, { replace: true });
    }
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

      {batchId != null && (
        <section className="rounded-2xl border border-slate-700 bg-slate-800/80">
          <div className="border-b border-slate-700 px-5 py-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-base font-semibold text-slate-100">Focused Batch</div>
                <div className="mt-1 text-sm text-slate-400">
                  Batch #{batchId}{batch?.created_at ? ` • ${formatLocalTimestamp(batch.created_at)}` : ""}
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
            {batchLoading && !batch && (
              <div className="text-sm text-slate-400">Loading batch status...</div>
            )}
            {batch && (
              <>
                <div className="flex flex-wrap items-center gap-2 text-sm text-slate-300">
                  <span className="rounded-full bg-slate-700 px-3 py-1">{batch.completed_books} completed</span>
                  <span className="rounded-full bg-slate-700 px-3 py-1">{batch.failed_books} failed</span>
                  <span className="rounded-full bg-slate-700 px-3 py-1">
                    {Math.max(0, batch.total_books - batch.completed_books - batch.failed_books)} remaining
                  </span>
                </div>
                <div className="space-y-2">
                  {batch.items.map((item) => (
                    <FocusedBatchRow key={item.id} item={item} />
                  ))}
                </div>
              </>
            )}
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
        ) : activeEntries.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/40 px-5 py-6 text-sm text-slate-500">
            No active IRC jobs.
          </div>
        ) : (
          <div className="space-y-3">
            {activeEntries.map((entry) => (
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
          <div className="space-y-3">
            {historyEntries.map((entry) => (
              <DownloadFeedCard key={entry.entry_id} entry={entry} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function FocusedBatchRow({ item }: { item: IrcBulkDownloadItem }) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/40 px-4 py-3">
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
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
          {item.selected_result_label && (
            <div className="mt-2 rounded-md border border-cyan-500/20 bg-cyan-500/10 px-3 py-2 text-[11px] text-cyan-200">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-300/80">
                Selected Result
              </div>
              <div className="break-words font-mono">{item.selected_result_label}</div>
            </div>
          )}
        </div>
        <div className="lg:min-w-[320px]">
          <CompactStageRail status={item.status} error={item.error_message} />
        </div>
      </div>
    </div>
  );
}

function DownloadFeedCard({ entry, compact = false }: { entry: IrcDownloadFeedEntry; compact?: boolean }) {
  const timestamp = entry.completed_at ?? entry.updated_at ?? entry.created_at ?? entry.sort_timestamp;
  const showInlineFinalResult = Boolean(entry.final_result_kind && entry.final_result_text);
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
          <div className="mt-1 text-sm text-slate-400">{entry.author_name || "Unknown author"}</div>
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
            <CompactStageRail status={entry.status} error={entry.final_result_kind === "error" ? entry.final_result_text : null} />
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
                  entry.final_result_kind === "imported" ? "text-emerald-200" : "text-rose-200"
                }`}
              >
                {entry.final_result_kind === "imported" ? "Imported to" : "Error"}
              </div>
              <div
                className={`mt-1 break-all text-xs ${
                  entry.final_result_kind === "imported" ? "text-emerald-100/90" : "text-rose-100/90"
                }`}
              >
                {entry.final_result_text}
              </div>
            </div>
          )}
          {!showInlineFinalResult && entry.active && (
            <div className="mt-3 rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-3 text-sm text-slate-400">
              Job still running.
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

function CompactStageRail({
  status,
  error,
}: {
  status: string;
  error?: string | null;
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
