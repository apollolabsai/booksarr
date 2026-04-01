import { useState, useRef, useEffect } from "react";
import { useLogs } from "../api/logs";

const LEVEL_COLORS: Record<string, string> = {
  DEBUG: "text-slate-500",
  INFO: "text-sky-400",
  WARNING: "text-amber-400",
  ERROR: "text-red-400",
  CRITICAL: "text-red-500 font-bold",
};

const IPV4_TOKEN_RE = /\b\d{1,3}(?:\.\d{1,3}){3}\b/g;

export default function LogsPage() {
  const [category, setCategory] = useState("");
  const [level, setLevel] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);
  const { data } = useLogs(category || undefined, level || undefined);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [data?.entries.length, autoScroll]);

  const handleDownload = () => {
    const params = new URLSearchParams();
    if (category) params.set("category", category);
    const qs = params.toString();
    window.open(`/api/logs/download${qs ? `?${qs}` : ""}`, "_blank");
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold">Logs</h2>
        <div className="flex items-center gap-3">
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="bg-slate-700 border border-slate-600 text-slate-200 text-sm rounded-lg px-3 py-2"
          >
            <option value="">All Categories</option>
            {data?.categories.map((cat) => (
              <option key={cat} value={cat}>{cat}</option>
            ))}
          </select>
          <select
            value={level}
            onChange={(e) => setLevel(e.target.value)}
            className="bg-slate-700 border border-slate-600 text-slate-200 text-sm rounded-lg px-3 py-2"
          >
            <option value="">All Levels</option>
            <option value="DEBUG">DEBUG</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
          <label className="flex items-center gap-1.5 text-sm text-slate-400 cursor-pointer">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="rounded bg-slate-700 border-slate-600 text-emerald-500 focus:ring-emerald-500"
            />
            Auto-scroll
          </label>
          <button
            onClick={handleDownload}
            className="bg-slate-600 hover:bg-slate-500 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors flex items-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Download
          </button>
        </div>
      </div>

      <div className="flex-1 bg-slate-800 rounded-lg border border-slate-700 overflow-hidden flex flex-col min-h-0">
        <div className="overflow-y-auto flex-1 p-4 font-mono text-xs leading-relaxed">
          {!data || data.entries.length === 0 ? (
            <p className="text-slate-500">No log entries yet.</p>
          ) : (
            data.entries.map((entry, i) => (
              <div key={i} className="flex gap-3 hover:bg-slate-700/30 px-1 -mx-1 rounded">
                <span className="text-slate-500 flex-shrink-0">{entry.timestamp}</span>
                <span className={`w-16 flex-shrink-0 ${LEVEL_COLORS[entry.level] || "text-slate-400"}`}>
                  {entry.level}
                </span>
                <span className="text-emerald-600 flex-shrink-0 w-40 truncate">{entry.category}</span>
                <span className="text-slate-300">{renderLogMessage(entry.message)}</span>
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </div>
        <div className="px-4 py-2 border-t border-slate-700 text-xs text-slate-500 flex-shrink-0">
          {data?.entries.length ?? 0} entries
        </div>
      </div>
    </div>
  );
}

function renderLogMessage(message: string) {
  const parts = message.split(IPV4_TOKEN_RE);
  const matches = message.match(IPV4_TOKEN_RE) ?? [];

  return parts.flatMap((part, index) => {
    const segment = [<span key={`text-${index}`}>{part}</span>];
    const ip = matches[index];
    if (ip) {
      segment.push(
        <span key={`ip-${index}`} className="text-amber-300">
          {ip}
        </span>,
      );
    }
    return segment;
  });
}
