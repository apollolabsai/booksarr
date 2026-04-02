import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  useCreateIrcDownloadJob,
  useCreateIrcSearchJob,
  useIrcDownloadJob,
  useIrcDownloadJobs,
  useIrcSearchJob,
  useIrcSearchResults,
  useIrcStatus,
} from "../api/irc";
import type { IrcDownloadJob } from "../types";

export default function IrcSearchDialog({
  bookId,
  title,
  authorName,
  open,
  onClose,
}: {
  bookId: number | null;
  title: string;
  authorName: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const createSearchJob = useCreateIrcSearchJob();
  const createDownloadJob = useCreateIrcDownloadJob();
  const queryClient = useQueryClient();
  const [queryText, setQueryText] = useState("");
  const [jobId, setJobId] = useState<number | null>(null);
  const [downloadJobId, setDownloadJobId] = useState<number | null>(null);
  const [activeResultId, setActiveResultId] = useState<number | null>(null);
  const [queuedDownloadJob, setQueuedDownloadJob] = useState<IrcDownloadJob | null>(null);
  const lastOwnershipRefreshJobId = useRef<number | null>(null);
  const { data: ircStatus, isLoading: ircStatusLoading } = useIrcStatus(open);
  const { data: job } = useIrcSearchJob(jobId, open);
  const { data: results, isLoading: resultsLoading } = useIrcSearchResults(jobId, open);
  const { data: downloadJobs } = useIrcDownloadJobs(open || downloadJobId != null || queuedDownloadJob != null);
  const { data: downloadJob } = useIrcDownloadJob(downloadJobId, downloadJobId != null);
  const selectedResultId = activeResultId ?? results?.find((result) => result.selected)?.id ?? null;
  const fallbackDownloadJob =
    (downloadJobId != null ? downloadJobs?.find((candidate) => candidate.id === downloadJobId) : null)
    ?? (selectedResultId != null ? downloadJobs?.find((candidate) => candidate.search_result_id === selectedResultId) : null)
    ?? (jobId != null ? downloadJobs?.find((candidate) => candidate.search_job_id === jobId && !isTerminalDownloadStatus(candidate.status)) : null)
    ?? queuedDownloadJob;
  const currentDownloadJob = downloadJob ?? fallbackDownloadJob ?? null;

  useEffect(() => {
    if (!open) return;
    const defaultQuery = [authorName ?? "", title].filter(Boolean).join(" ").trim();
    setQueryText(defaultQuery);
    setJobId(null);
    setDownloadJobId(null);
    setActiveResultId(null);
    setQueuedDownloadJob(null);
    lastOwnershipRefreshJobId.current = null;
  }, [authorName, title, open]);

  useEffect(() => {
    if (!currentDownloadJob || downloadJobId === currentDownloadJob.id) return;
    setDownloadJobId(currentDownloadJob.id);
  }, [currentDownloadJob, downloadJobId]);

  useEffect(() => {
    if (!currentDownloadJob || currentDownloadJob.status !== "moved") return;
    if (lastOwnershipRefreshJobId.current === currentDownloadJob.id) return;

    lastOwnershipRefreshJobId.current = currentDownloadJob.id;
    queryClient.invalidateQueries({ queryKey: ["books"] });
    queryClient.invalidateQueries({ queryKey: ["authors"] });
    queryClient.invalidateQueries({ queryKey: ["hiddenBooks"] });
  }, [currentDownloadJob, queryClient]);

  useEffect(() => {
    if (!currentDownloadJob || !isTerminalDownloadStatus(currentDownloadJob.status)) return;
    setQueuedDownloadJob((current) => (current?.id === currentDownloadJob.id ? null : current));
  }, [currentDownloadJob]);

  if (!open || !bookId) return null;

  const isIrcReady = Boolean(ircStatus?.connected && ircStatus?.joined_channel);

  const handleSearch = async () => {
    const job = await createSearchJob.mutateAsync({
      book_id: bookId,
      query_text: queryText,
    });
    setJobId(job.id);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 px-4 py-6">
      <div className="max-h-[90vh] w-full max-w-4xl overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-start justify-between border-b border-slate-700 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">Search IRC</h2>
            <p className="mt-1 text-sm text-slate-400">
              Queue an IRC search for this book and watch the job status update in real time.
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
          {!ircStatusLoading && !isIrcReady && (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-5">
              <div className="text-base font-semibold text-amber-200">Connect to IRC first</div>
              <p className="mt-2 text-sm text-amber-100/90">
                Search can only run when the app is connected to the IRC server and joined to the configured channel.
              </p>
              <div className="mt-3 space-y-1 text-sm text-amber-50/80">
                <div>
                  Connection state: <span className="font-medium text-amber-100">{ircStatus?.state || "disconnected"}</span>
                </div>
                {ircStatus?.server && (
                  <div>
                    Server: <span className="text-amber-100">{ircStatus.server}</span>
                  </div>
                )}
                {ircStatus?.channel && (
                  <div>
                    Channel: <span className="text-amber-100">{ircStatus.channel}</span>
                  </div>
                )}
                {ircStatus?.last_error && (
                  <div className="text-rose-200">
                    Last error: <span className="text-rose-100">{ircStatus.last_error}</span>
                  </div>
                )}
              </div>
              <div className="mt-4 flex items-center gap-3">
                <Link
                  to="/settings/irc"
                  onClick={onClose}
                  className="inline-flex items-center rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500"
                >
                  Open IRC Settings
                </Link>
                <span className="text-xs text-amber-100/70">
                  Connect there, then come back and run the search again.
                </span>
              </div>
            </div>
          )}

          {ircStatusLoading && (
            <div className="rounded-xl border border-slate-700 bg-slate-800 p-5 text-sm text-slate-300">
              Checking IRC connection status...
            </div>
          )}

          {isIrcReady && (
            <>
          <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
            <div className="mb-2 text-sm font-medium text-slate-200">Query</div>
            <input
              value={queryText}
              onChange={(e) => setQueryText(e.target.value)}
              className="w-full rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-slate-100"
              placeholder="John Grisham The Activist"
            />
            <div className="mt-3 flex items-center gap-3">
              <button
                type="button"
                onClick={handleSearch}
                disabled={createSearchJob.isPending || !queryText.trim()}
                className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {createSearchJob.isPending ? "Queueing..." : "Queue IRC Search"}
              </button>
              {job && (
                <div className="text-sm text-slate-400">
                  Job #{job.id}: <span className="text-slate-200">{job.status}</span>
                </div>
              )}
            </div>
            {job && (
              <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
                <div>
                  {job.created_at ? new Date(job.created_at).toLocaleString() : "Queued just now"}
                </div>
                <div>
                  {job.expected_result_filename || "Waiting for expected result filename"}
                </div>
              </div>
            )}
            {job?.error_message && (
              <div className="mt-3 text-sm text-rose-300">{job.error_message}</div>
            )}
            {createSearchJob.isError && (
              <div className="mt-3 text-sm text-rose-300">Failed to queue IRC search.</div>
            )}
          </div>

          {jobId != null && (
            <div className="mt-5 rounded-xl border border-slate-700 bg-slate-800 p-4">
              {(currentDownloadJob || queuedDownloadJob) && (
                <div className="mb-4 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-medium text-emerald-100">Active Download</div>
                    <div className="text-xs text-emerald-200">
                      {formatDownloadStatus((currentDownloadJob ?? queuedDownloadJob)?.status ?? "queued")}
                    </div>
                  </div>
                  <div className="mt-2">
                    <DownloadStageList status={(currentDownloadJob ?? queuedDownloadJob)?.status ?? "queued"} />
                  </div>
                  {(currentDownloadJob ?? queuedDownloadJob)?.dcc_filename && (
                    <div className="mt-2 text-xs text-slate-300">
                      File: <span className="text-slate-100">{(currentDownloadJob ?? queuedDownloadJob)?.dcc_filename}</span>
                    </div>
                  )}
                  {(currentDownloadJob ?? queuedDownloadJob)?.saved_path && (
                    <div className="mt-1 text-xs text-slate-400">
                      Downloaded to: <span className="text-slate-200">{(currentDownloadJob ?? queuedDownloadJob)?.saved_path}</span>
                    </div>
                  )}
                  {(currentDownloadJob ?? queuedDownloadJob)?.moved_to_library_path && (
                    <div className="mt-1 text-xs text-emerald-200">
                      Imported to: <span className="text-emerald-100">{(currentDownloadJob ?? queuedDownloadJob)?.moved_to_library_path}</span>
                    </div>
                  )}
                  {(currentDownloadJob ?? queuedDownloadJob)?.error_message && (
                    <div className="mt-1 text-xs text-rose-300">{(currentDownloadJob ?? queuedDownloadJob)?.error_message}</div>
                  )}
                </div>
              )}

              <div className="mb-3 flex items-center justify-between">
                <div className="text-sm font-medium text-slate-100">Parsed Results</div>
                <div className="text-xs text-slate-500">
                  {resultsLoading ? "Checking for results..." : `${results?.length ?? 0} result(s)`}
                </div>
              </div>

              {(results ?? []).length === 0 ? (
                job?.status === "failed" ? (
                  <div className="text-sm text-rose-300">
                    {job.error_message || "The IRC search did not return any results."}
                  </div>
                ) : (
                  <div className="text-sm text-slate-400">
                    No parsed results yet. Once a DCC result archive arrives and is parsed, the lines will appear here.
                  </div>
                )
              ) : (
                <div className="divide-y divide-slate-700 overflow-hidden rounded-lg border border-slate-700 bg-slate-900/40">
                  {results?.map((result) => (
                    <div key={result.id} className="px-3 py-2.5">
                      <div className="flex items-center gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm text-slate-100">
                            {result.download_command}
                          </div>
                        </div>
                        <div className="shrink-0 rounded border border-slate-600 bg-slate-800 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-300">
                          {result.file_format || "unknown"}
                        </div>
                        <div className="shrink-0 text-xs text-slate-400">
                          {result.file_size_text || "Unknown size"}
                        </div>
                        <button
                          type="button"
                          onClick={async () => {
                            setActiveResultId(result.id);
                            const job = await createDownloadJob.mutateAsync({ search_result_id: result.id });
                            setQueuedDownloadJob(job);
                            setDownloadJobId(job.id);
                          }}
                          disabled={createDownloadJob.isPending}
                          className="shrink-0 rounded-md border border-slate-600 bg-slate-700 px-3 py-1.5 text-xs font-medium text-slate-100 transition-colors hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {createDownloadJob.isPending && activeResultId === result.id ? "Queueing..." : "Download"}
                        </button>
                      </div>
                      {(activeResultId === result.id || result.selected || currentDownloadJob?.search_result_id === result.id) && (
                        <div className="mt-2 rounded-md bg-slate-950/60 px-3 py-2 text-xs">
                          <div className="text-emerald-300">
                            {currentDownloadJob?.search_result_id === result.id
                              ? `Selected for download. Status: ${formatDownloadStatus(currentDownloadJob.status)}`
                              : currentDownloadJob
                                ? "Selected for download. Tracking active download status above..."
                                : queuedDownloadJob
                                  ? "Selected for download. Waiting for live status to attach..."
                                  : "Selected for download. Waiting for download job confirmation..."}
                          </div>
                          {currentDownloadJob?.search_result_id === result.id && (
                            <>
                              <div className="mt-2">
                                <DownloadStageList status={currentDownloadJob.status} />
                              </div>
                              {currentDownloadJob.dcc_filename && (
                                <div className="mt-1 text-slate-400">
                                  File: <span className="text-slate-300">{currentDownloadJob.dcc_filename}</span>
                                </div>
                              )}
                              {currentDownloadJob.saved_path && (
                                <div className="mt-1 text-slate-400">
                                  Downloaded to: <span className="text-slate-300">{currentDownloadJob.saved_path}</span>
                                </div>
                              )}
                              {currentDownloadJob.moved_to_library_path && (
                                <div className="mt-1 text-emerald-300">
                                  Imported to: <span className="text-emerald-200">{currentDownloadJob.moved_to_library_path}</span>
                                </div>
                              )}
                              {currentDownloadJob.error_message && (
                                <div className="mt-1 text-rose-300">{currentDownloadJob.error_message}</div>
                              )}
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
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
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

function formatDownloadStatus(status: string): string {
  switch (status) {
    case "queued":
      return "queued";
    case "sent":
      return "request sent";
    case "waiting_dcc":
      return "waiting on download";
    case "downloading":
      return "downloading";
    case "extracting":
      return "extracting archive";
    case "extracted":
      return "archive extracted";
    case "importing":
      return "importing to library";
    case "refreshing_library":
      return "refreshing library";
    case "downloaded":
      return "downloaded";
    case "moved":
      return "imported";
    case "failed":
      return "failed";
    case "cancelled":
      return "cancelled";
    default:
      return status;
  }
}

function isTerminalDownloadStatus(status: string | null): boolean {
  return status === "moved" || status === "failed" || status === "cancelled";
}

function DownloadStageList({ status }: { status: string }) {
  const stages = [
    { label: "Queued", statuses: ["queued"] },
    { label: "Request Sent", statuses: ["sent", "waiting_dcc"] },
    { label: "Downloading", statuses: ["downloading", "downloaded"] },
    { label: "Extracting", statuses: ["extracting", "extracted"] },
    { label: "Importing", statuses: ["importing", "refreshing_library"] },
    { label: "Done", statuses: ["moved"] },
    { label: "Error", statuses: ["failed", "cancelled"] },
  ];

  const activeIndex = stages.findIndex((stage) => stage.statuses.includes(status));

  return (
    <div className="grid gap-1.5 sm:grid-cols-3">
      {stages.map((stage, index) => {
        const isDone = activeIndex > index;
        const isActive = stage.statuses.includes(status);
        const tone = isActive
          ? stage.label === "Error"
            ? "border-rose-500/60 bg-rose-500/10 text-rose-200"
            : "border-emerald-500/60 bg-emerald-500/10 text-emerald-200"
          : isDone
            ? "border-slate-600 bg-slate-900/80 text-slate-300"
            : "border-slate-700 bg-slate-900/40 text-slate-500";
        const marker = isActive ? "-" : isDone ? "✓" : " ";

        return (
          <div key={stage.label} className={`rounded-md border px-2 py-1.5 ${tone}`}>
            <div className="flex items-center gap-2 font-medium">
              <span className="inline-block w-3 text-center">{marker}</span>
              <span>{stage.label}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
