import { useState, useRef, useEffect } from "react";
import type { Dispatch, SetStateAction } from "react";
import { useLogs } from "../api/logs";
import { useSettings, useUpdateSettings } from "../api/settings";

const LEVEL_COLORS: Record<string, string> = {
  DEBUG: "text-slate-500",
  INFO: "text-sky-400",
  WARNING: "text-amber-400",
  ERROR: "text-red-400",
  CRITICAL: "text-red-500 font-bold",
};

const IPV4_TOKEN_RE = /\b\d{1,3}(?:\.\d{1,3}){3}\b/g;
const LEVEL_OPTIONS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];

export default function LogsPage() {
  const [categories, setCategories] = useState<string[]>([]);
  const [levels, setLevels] = useState<string[]>([]);
  const [autoScroll, setAutoScroll] = useState(true);
  const [categoryMenuOpen, setCategoryMenuOpen] = useState(false);
  const [levelMenuOpen, setLevelMenuOpen] = useState(false);
  const [logLevel, setLogLevel] = useState("INFO");
  const { data } = useLogs(categories, levels);
  const { data: settings } = useSettings();
  const updateSettings = useUpdateSettings();
  const bottomRef = useRef<HTMLDivElement>(null);
  const categoryMenuRef = useRef<HTMLDivElement>(null);
  const levelMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [data?.entries.length, autoScroll]);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (categoryMenuRef.current && !categoryMenuRef.current.contains(event.target as Node)) {
        setCategoryMenuOpen(false);
      }
      if (levelMenuRef.current && !levelMenuRef.current.contains(event.target as Node)) {
        setLevelMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, []);

  useEffect(() => {
    if (settings?.log_level) {
      setLogLevel(settings.log_level);
    }
  }, [settings?.log_level]);

  const handleDownload = () => {
    const params = new URLSearchParams();
    for (const category of categories) params.append("category", category);
    for (const level of levels) params.append("level", level);
    const qs = params.toString();
    window.open(`/api/logs/download${qs ? `?${qs}` : ""}`, "_blank");
  };

  const toggleValue = (
    value: string,
    selected: string[],
    setSelected: Dispatch<SetStateAction<string[]>>,
  ) => {
    setSelected((current) => (
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value]
    ));
  };

  const handleLogLevelChange = (nextLogLevel: string) => {
    setLogLevel(nextLogLevel);
    updateSettings.mutate({ log_level: nextLogLevel });
  };

  return (
    <div className="flex flex-col h-full">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold">Logs</h2>
          <p className="mt-1 text-sm text-slate-400">
            Runtime log level controls which new events are captured below.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2">
            <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
              Log Level
            </span>
            <select
              value={logLevel}
              onChange={(event) => handleLogLevelChange(event.target.value)}
              disabled={updateSettings.isPending}
              className="rounded-md border border-slate-600 bg-slate-700 px-2 py-1 text-sm text-slate-100 focus:border-emerald-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
            >
              {LEVEL_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
            <span className="min-w-[72px] text-right text-xs text-slate-400">
              {updateSettings.isPending ? "Saving..." : "Live"}
            </span>
          </div>
          <MultiSelectFilter
            label={getFilterLabel("All Categories", categories, "Categories")}
            options={data?.categories ?? []}
            selected={categories}
            open={categoryMenuOpen}
            onToggleOpen={() => setCategoryMenuOpen((current) => !current)}
            onToggleValue={(value) => toggleValue(value, categories, setCategories)}
            onClear={() => setCategories([])}
            menuRef={categoryMenuRef}
          />
          <MultiSelectFilter
            label={getFilterLabel("All Levels", levels, "Levels")}
            options={LEVEL_OPTIONS}
            selected={levels}
            open={levelMenuOpen}
            onToggleOpen={() => setLevelMenuOpen((current) => !current)}
            onToggleValue={(value) => toggleValue(value, levels, setLevels)}
            onClear={() => setLevels([])}
            menuRef={levelMenuRef}
          />
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

function getFilterLabel(defaultLabel: string, selected: string[], pluralLabel: string) {
  if (selected.length === 0) return defaultLabel;
  if (selected.length === 1) return selected[0];
  return `${selected.length} ${pluralLabel}`;
}

function MultiSelectFilter({
  label,
  options,
  selected,
  open,
  onToggleOpen,
  onToggleValue,
  onClear,
  menuRef,
}: {
  label: string;
  options: string[];
  selected: string[];
  open: boolean;
  onToggleOpen: () => void;
  onToggleValue: (value: string) => void;
  onClear: () => void;
  menuRef: { current: HTMLDivElement | null };
}) {
  return (
    <div ref={(node) => { menuRef.current = node; }} className="relative">
      <button
        type="button"
        onClick={onToggleOpen}
        className="min-w-[164px] bg-slate-700 border border-slate-600 text-slate-200 text-sm rounded-lg px-3 py-2 flex items-center justify-between gap-3"
      >
        <span className="truncate">{label}</span>
        <svg className="h-4 w-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-2 w-72 rounded-lg border border-slate-600 bg-slate-800 p-2 shadow-xl">
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="text-xs font-medium text-slate-400">
              {selected.length === 0 ? "All selected" : `${selected.length} selected`}
            </span>
            <button
              type="button"
              onClick={onClear}
              className="text-xs text-emerald-400 hover:text-emerald-300"
            >
              Clear
            </button>
          </div>
          <div className="max-h-64 space-y-1 overflow-y-auto">
            {options.map((option) => (
              <label
                key={option}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-slate-200 hover:bg-slate-700"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(option)}
                  onChange={() => onToggleValue(option)}
                  className="rounded bg-slate-700 border-slate-600 text-emerald-500 focus:ring-emerald-500"
                />
                <span className="truncate">{option}</span>
              </label>
            ))}
            {options.length === 0 && (
              <div className="px-2 py-1.5 text-sm text-slate-500">No options yet.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
