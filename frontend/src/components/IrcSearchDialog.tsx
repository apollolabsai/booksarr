import { useEffect, useState } from "react";
import {
  useCreateIrcDownloadJob,
  useCreateIrcSearchJob,
  useIrcSearchJob,
  useIrcSearchResults,
} from "../api/irc";

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
  const [queryText, setQueryText] = useState("");
  const [jobId, setJobId] = useState<number | null>(null);
  const { data: job } = useIrcSearchJob(jobId, open);
  const { data: results, isLoading: resultsLoading } = useIrcSearchResults(jobId, open);

  useEffect(() => {
    if (!open) return;
    const defaultQuery = [authorName ?? "", title].filter(Boolean).join(" ").trim();
    setQueryText(defaultQuery);
    setJobId(null);
  }, [authorName, title, open]);

  if (!open || !bookId) return null;

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
            {createSearchJob.isError && (
              <div className="mt-3 text-sm text-rose-300">Failed to queue IRC search.</div>
            )}
          </div>

          {job && (
            <div className="mt-5 rounded-xl border border-slate-700 bg-slate-800 p-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-sm font-medium text-slate-100">Latest Job State</div>
                  <div className="mt-1 text-sm text-slate-300">{job.status}</div>
                </div>
                <div className="text-right text-xs text-slate-500">
                  <div>{job.created_at ? new Date(job.created_at).toLocaleString() : "Queued just now"}</div>
                  <div>{job.expected_result_filename || "Waiting for expected result filename"}</div>
                </div>
              </div>
              {job.error_message && <div className="mt-3 text-sm text-rose-300">{job.error_message}</div>}
            </div>
          )}

          {jobId != null && (
            <div className="mt-5 rounded-xl border border-slate-700 bg-slate-800 p-4">
              <div className="mb-3 flex items-center justify-between">
                <div className="text-sm font-medium text-slate-100">Parsed Results</div>
                <div className="text-xs text-slate-500">
                  {resultsLoading ? "Checking for results..." : `${results?.length ?? 0} result(s)`}
                </div>
              </div>

              {(results ?? []).length === 0 ? (
                <div className="text-sm text-slate-400">
                  No parsed results yet. Once a DCC result archive arrives and is parsed, the lines will appear here.
                </div>
              ) : (
                <div className="space-y-3">
                  {results?.map((result) => (
                    <div key={result.id} className="rounded-lg border border-slate-700 bg-slate-900/40 p-3">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <div className="text-sm font-medium text-slate-100">{result.display_name}</div>
                          <div className="mt-1 text-xs text-slate-500">{result.raw_line}</div>
                        </div>
                        <div className="text-right text-xs text-slate-400">
                          <div>{result.bot_name || "Unknown bot"}</div>
                          <div>{result.file_format || "Unknown format"}</div>
                          <div>{result.file_size_text || "Unknown size"}</div>
                        </div>
                      </div>
                      <div className="mt-2 rounded-md bg-slate-950/50 px-2.5 py-2 font-mono text-xs text-slate-300">
                        {result.download_command}
                      </div>
                      <div className="mt-3 flex items-center justify-between gap-3">
                        {result.selected ? (
                          <div className="text-xs text-emerald-300">Selected for download</div>
                        ) : (
                          <div className="text-xs text-slate-500">Ready to queue as a download job</div>
                        )}
                        <button
                          type="button"
                          onClick={() => createDownloadJob.mutate({ search_result_id: result.id })}
                          disabled={createDownloadJob.isPending}
                          className="rounded-md border border-slate-600 bg-slate-700 px-3 py-1.5 text-xs font-medium text-slate-100 transition-colors hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {createDownloadJob.isPending ? "Queueing..." : "Download"}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
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
