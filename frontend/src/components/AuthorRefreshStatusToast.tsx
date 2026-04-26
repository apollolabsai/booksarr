import { useEffect, useMemo, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthorRefreshStatus } from "../api/authors";
import type { AuthorRefreshStatus } from "../types";

const TERMINAL_VISIBLE_MS = 15000;

export default function AuthorRefreshStatusToast() {
  const queryClient = useQueryClient();
  const { data: status } = useAuthorRefreshStatus();
  const previousStatus = useRef<AuthorRefreshStatus["status"] | null>(null);

  useEffect(() => {
    const previous = previousStatus.current;
    previousStatus.current = status?.status ?? null;

    if (!status || previous !== "refreshing") return;
    if (status.status !== "completed" && status.status !== "failed") return;

    queryClient.invalidateQueries({ queryKey: ["authors"] });
    if (status.author_id) {
      queryClient.invalidateQueries({ queryKey: ["authors", status.author_id] });
    }
    queryClient.invalidateQueries({ queryKey: ["books"] });
    queryClient.invalidateQueries({ queryKey: ["hiddenBooks"] });
  }, [queryClient, status]);

  const isVisible = useMemo(() => {
    if (!status) return false;
    if (status.status === "refreshing") return true;
    if ((status.status === "completed" || status.status === "failed") && status.completed_at) {
      return Date.now() - parseTimestamp(status.completed_at) < TERMINAL_VISIBLE_MS;
    }
    return false;
  }, [status]);

  if (!status || !isVisible) return null;

  const isFailed = status.status === "failed";
  const title = status.author_name ? `Refreshing ${status.author_name}` : "Refreshing Author";
  const progress = Math.max(0, Math.min(100, Math.round(status.progress)));

  return (
    <div className="fixed bottom-24 left-4 z-50 w-[min(calc(100vw-2rem),22rem)] rounded-lg border border-slate-700 bg-slate-950/95 p-3 shadow-2xl shadow-black/40 backdrop-blur sm:bottom-4">
      <div className="mb-2 flex items-start gap-3">
        <div
          className={`mt-1 h-2.5 w-2.5 flex-shrink-0 rounded-full ${
            isFailed ? "bg-rose-400" : status.status === "completed" ? "bg-emerald-400" : "animate-pulse bg-emerald-400"
          }`}
        />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-slate-100">
            {status.status === "completed" ? "Author refresh complete" : title}
          </div>
          <div className={`mt-0.5 line-clamp-2 text-xs ${isFailed ? "text-rose-300" : "text-slate-400"}`}>
            {status.message || (isFailed ? status.error : "Working...")}
          </div>
        </div>
        <div className="text-xs tabular-nums text-slate-500">{status.status === "refreshing" ? `${progress}%` : ""}</div>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-800">
        <div
          className={`h-full rounded-full transition-all duration-500 ${isFailed ? "bg-rose-500" : "bg-emerald-500"}`}
          style={{ width: `${status.status === "failed" ? 100 : progress}%` }}
        />
      </div>
    </div>
  );
}

function parseTimestamp(value: string): number {
  const normalized = value.endsWith("Z") ? value : `${value}Z`;
  const parsed = Date.parse(normalized);
  return Number.isNaN(parsed) ? 0 : parsed;
}
