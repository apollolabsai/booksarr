import { useState, useEffect, useRef } from "react";
import { Link, useLocation } from "react-router-dom";
import { useSettings, useUpdateSettings, useScanStatus, useTriggerScan, useResetData, useApiUsage } from "../api/settings";
import { useQueryClient } from "@tanstack/react-query";
import type { ScanSummary, VisibilityCategories } from "../types";

const VISIBILITY_OPTIONS: Array<{
  key: keyof VisibilityCategories;
  label: string;
  description: string;
}> = [
  {
    key: "standard_books",
    label: "Standard Books",
    description: "Regular Hardcover books that are not classified into a more specific bucket.",
  },
  {
    key: "short_fiction",
    label: "Short Fiction",
    description: "Novellas and short stories.",
  },
  {
    key: "collections_and_compilations",
    label: "Collections & Compilations",
    description: "Hardcover-classified collections and books flagged with compilation=true.",
  },
  {
    key: "likely_collections_by_title",
    label: "Likely Collections by Title Heuristic",
    description: "Collection-like bundles inferred from the title, such as Value Collection, boxed sets, omnibuses, and similar bundle naming.",
  },
  {
    key: "graphic_and_alternate_formats",
    label: "Graphic & Alternate Formats",
    description: "Graphic novels, poetry, web novels, and light novels.",
  },
  {
    key: "research_non_book_material",
    label: "Research / Non-Book Material",
    description: "Research papers and other non-standard book material.",
  },
  {
    key: "fan_fiction",
    label: "Fan Fiction",
    description: "Hardcover items categorized as fan fiction.",
  },
  {
    key: "valid_isbn",
    label: "Valid ISBN",
    description: "Only show books that have at least one valid ISBN from local metadata, Hardcover, Google, or Open Library.",
  },
  {
    key: "non_english_books",
    label: "Non-English Books",
    description: "Books with a detected language outside English.",
  },
  {
    key: "upcoming_unreleased",
    label: "Upcoming / Unreleased",
    description: "Books with a future release date.",
  },
  {
    key: "pending_hardcover_records",
    label: "Pending Hardcover Records",
    description: "Books where Hardcover state is pending rather than normalized.",
  },
  {
    key: "likely_excerpts",
    label: "Likely Excerpts / Samples",
    description: "Low-page pending Book records that look like excerpts or sampler entries.",
  },
];

export default function SettingsPage() {
  const location = useLocation();
  const { data: settings } = useSettings();
  const updateSettings = useUpdateSettings();
  const triggerScan = useTriggerScan();
  const resetData = useResetData();
  const [apiKey, setApiKey] = useState("");
  const [googleKey, setGoogleKey] = useState("");
  const [confirmReset, setConfirmReset] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [showGoogleKey, setShowGoogleKey] = useState(false);
  const [saved, setSaved] = useState(false);
  const [googleSaved, setGoogleSaved] = useState(false);
  const [scanInterval, setScanInterval] = useState("24");
  const [intervalSaved, setIntervalSaved] = useState(false);
  const [persistedScanSummary, setPersistedScanSummary] = useState<ScanSummary | null>(() => {
    if (typeof window === "undefined") return null;
    const raw = window.localStorage.getItem("booksarr:lastScanSummary");
    if (!raw) return null;
    try {
      return JSON.parse(raw) as ScanSummary;
    } catch {
      return null;
    }
  });
  const [visibilityCategories, setVisibilityCategories] = useState<VisibilityCategories | null>(null);
  const [visibilitySaved, setVisibilitySaved] = useState(false);
  const queryClient = useQueryClient();

  const { data: scanStatus } = useScanStatus(true);
  const isScanning = scanStatus?.status === "scanning";
  const { data: apiUsage } = useApiUsage(7, true);
  const wasScanningRef = useRef(false);

  useEffect(() => {
    if (settings?.scan_interval_hours !== undefined) {
      setScanInterval(String(settings.scan_interval_hours));
    }
  }, [settings?.scan_interval_hours]);

  useEffect(() => {
    if (settings?.visibility_categories) {
      setVisibilityCategories(settings.visibility_categories);
    }
  }, [settings?.visibility_categories]);

  useEffect(() => {
    if (!settings?.last_scan_summary || typeof window === "undefined") return;
    setPersistedScanSummary(settings.last_scan_summary);
    window.localStorage.setItem(
      "booksarr:lastScanSummary",
      JSON.stringify(settings.last_scan_summary),
    );
  }, [settings?.last_scan_summary]);

  useEffect(() => {
    if (!settings || typeof window === "undefined") return;
    if (settings.last_scan_summary || settings.last_scan_at) return;
    setPersistedScanSummary(null);
    window.localStorage.removeItem("booksarr:lastScanSummary");
  }, [settings]);

  useEffect(() => {
    if (!location.hash) return;
    const id = location.hash.slice(1);
    const el = document.getElementById(id);
    if (!el) return;
    requestAnimationFrame(() => {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, [location.hash]);

  useEffect(() => {
    if (isScanning) {
      wasScanningRef.current = true;
      return;
    }

    if (wasScanningRef.current && scanStatus?.status === "idle") {
      wasScanningRef.current = false;
      queryClient.invalidateQueries({ queryKey: ["authors"] });
      queryClient.invalidateQueries({ queryKey: ["books"] });
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    }
  }, [isScanning, queryClient, scanStatus]);

  const handleSaveKey = async () => {
    if (!apiKey.trim()) return;
    await updateSettings.mutateAsync({ hardcover_api_key: apiKey });
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const handleSaveGoogleKey = async () => {
    if (!googleKey.trim()) return;
    await updateSettings.mutateAsync({ google_books_api_key: googleKey });
    setGoogleSaved(true);
    setTimeout(() => setGoogleSaved(false), 3000);
  };

  const handleSaveInterval = async () => {
    const hours = parseInt(scanInterval, 10);
    if (isNaN(hours) || hours < 0) return;
    await updateSettings.mutateAsync({ scan_interval_hours: hours });
    setIntervalSaved(true);
    setTimeout(() => setIntervalSaved(false), 3000);
  };

  const handleSaveVisibility = async () => {
    if (!visibilityCategories) return;
    await updateSettings.mutateAsync({ visibility_categories: visibilityCategories });
    setVisibilitySaved(true);
    setTimeout(() => setVisibilitySaved(false), 3000);
  };

  const handleScan = async (force?: boolean) => {
    await triggerScan.mutateAsync(force);
    queryClient.invalidateQueries({ queryKey: ["scanStatus"] });
  };

  const parsedInterval = parseInt(scanInterval, 10);
  const intervalChanged = !isNaN(parsedInterval) && parsedInterval >= 0 && parsedInterval !== (settings?.scan_interval_hours ?? 24);
  const visibilityChanged = JSON.stringify(visibilityCategories) !== JSON.stringify(settings?.visibility_categories ?? null);
  const lastScanSummary = settings?.last_scan_summary ?? persistedScanSummary;
  const formatUsageDay = (day: string) => {
    const [year, month, date] = day.split("-");
    return `${parseInt(month, 10)}/${parseInt(date, 10)}/${year.slice(2)}`;
  };
  const parseApiDate = (value: string | null | undefined) => {
    if (!value) return null;
    const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
  };
  const formatApiDateTime = (value: string | null | undefined, fallback: string) =>
    parseApiDate(value)?.toLocaleString() ?? fallback;
  const formatSummaryReason = (value: string) =>
    value
      .split("_")
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");

  return (
    <div className="max-w-2xl">
      <h2 className="text-2xl font-bold mb-6">Settings</h2>

      <section id="api-keys" className="scroll-mt-6 mb-8">
        <div className="mb-3">
          <h3 className="text-lg font-semibold">API Keys</h3>
          <p className="text-sm text-slate-400">Configure the external services used for metadata enrichment.</p>
        </div>

      {/* Hardcover API Key */}
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-6">
        <h3 className="text-lg font-semibold mb-4">Hardcover API Key</h3>
        <p className="text-sm text-slate-400 mb-4">
          Get your API key from your{" "}
          <a href="https://hardcover.app/account/api" target="_blank" rel="noopener noreferrer" className="text-emerald-400 hover:underline">
            Hardcover account settings
          </a>.
        </p>
        {settings?.hardcover_api_key && (
          <p className="text-sm text-slate-400 mb-3">
            Current key: <code className="text-slate-300">{settings.hardcover_api_key}</code>
            {settings.hardcover_api_key_from_env && (
              <span className="ml-2 text-xs bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded">ENV</span>
            )}
          </p>
        )}
        {settings?.hardcover_api_key_from_env ? (
          <p className="text-xs text-slate-500">
            Set via <code>HARDCOVER_API_KEY</code> environment variable in docker-compose.yml
          </p>
        ) : (
          <>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <input
                  type={showKey ? "text" : "password"}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="Enter new API key..."
                  className="w-full bg-slate-700 border border-slate-600 text-slate-200 text-sm rounded-lg px-4 py-2 pr-10"
                />
                <button
                  onClick={() => setShowKey(!showKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    {showKey ? (
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L3 3m6.878 6.878L21 21" />
                    ) : (
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    )}
                  </svg>
                </button>
              </div>
              <button
                onClick={handleSaveKey}
                disabled={!apiKey.trim()}
                className="bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-600 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
              >
                Save
              </button>
            </div>
            {saved && <p className="text-emerald-400 text-sm mt-2">API key saved!</p>}
          </>
        )}
      </div>

      {/* Google Books API Key */}
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-6">
        <div className="flex items-center gap-2 mb-4">
          <h3 className="text-lg font-semibold">Google Books API Key</h3>
          <span className="text-xs bg-slate-600 text-slate-300 px-2 py-0.5 rounded">Optional</span>
        </div>
        <p className="text-sm text-slate-400 mb-2">
          Recommended for more accurate publish dates. Without it, Open Library is used as a fallback (less reliable). Free — allows 1,000 requests/day.
        </p>
        <ol className="text-sm text-slate-400 mb-4 list-decimal list-inside space-y-1">
          <li>Go to the{" "}
            <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener noreferrer" className="text-emerald-400 hover:underline">
              Google Cloud Console
            </a>
          </li>
          <li>Create a project (or select an existing one)</li>
          <li>Enable the{" "}
            <a href="https://console.cloud.google.com/apis/library/books.googleapis.com" target="_blank" rel="noopener noreferrer" className="text-emerald-400 hover:underline">
              Books API
            </a>
          </li>
          <li>Go to Credentials and create an API key</li>
        </ol>
        {settings?.google_books_api_key && (
          <p className="text-sm text-slate-400 mb-3">
            Current key: <code className="text-slate-300">{settings.google_books_api_key}</code>
            {settings.google_books_api_key_from_env && (
              <span className="ml-2 text-xs bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded">ENV</span>
            )}
          </p>
        )}
        {settings?.google_books_api_key_from_env ? (
          <p className="text-xs text-slate-500">
            Set via <code>GOOGLE_BOOKS_API_KEY</code> environment variable in docker-compose.yml
          </p>
        ) : (
          <>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <input
                  type={showGoogleKey ? "text" : "password"}
                  value={googleKey}
                  onChange={(e) => setGoogleKey(e.target.value)}
                  placeholder="Enter Google Books API key..."
                  className="w-full bg-slate-700 border border-slate-600 text-slate-200 text-sm rounded-lg px-4 py-2 pr-10"
                />
                <button
                  onClick={() => setShowGoogleKey(!showGoogleKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    {showGoogleKey ? (
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L3 3m6.878 6.878L21 21" />
                    ) : (
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    )}
                  </svg>
                </button>
              </div>
              <button
                onClick={handleSaveGoogleKey}
                disabled={!googleKey.trim()}
                className="bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-600 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
              >
                Save
              </button>
            </div>
            {googleSaved && <p className="text-emerald-400 text-sm mt-2">API key saved!</p>}
          </>
        )}
      </div>

      {/* API Usage */}
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-6">
        <h3 className="text-lg font-semibold mb-4">API Calls</h3>
        <p className="text-sm text-slate-400 mb-4">
          Daily outbound API call totals by source for the last 7 days.
        </p>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm border-collapse">
            <thead>
              <tr className="bg-slate-700/60 text-slate-200">
                <th className="border border-slate-600 px-3 py-2 text-left">API Calls</th>
                <th className="border border-slate-600 px-3 py-2 text-right">Total</th>
                <th className="border border-slate-600 px-3 py-2 text-right">Hard Cover</th>
                <th className="border border-slate-600 px-3 py-2 text-right">Google</th>
                <th className="border border-slate-600 px-3 py-2 text-right">Open Library</th>
              </tr>
            </thead>
            <tbody>
              {(apiUsage ?? []).map((row) => (
                <tr key={row.day} className="text-slate-300 odd:bg-slate-800 even:bg-slate-800/50">
                  <td className="border border-slate-700 px-3 py-2">{formatUsageDay(row.day)}</td>
                  <td className="border border-slate-700 px-3 py-2 text-right">{row.total}</td>
                  <td className="border border-slate-700 px-3 py-2 text-right">{row.hardcover}</td>
                  <td className="border border-slate-700 px-3 py-2 text-right">{row.google}</td>
                  <td className="border border-slate-700 px-3 py-2 text-right">{row.openlibrary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      </section>

      <section id="profiles" className="scroll-mt-6 mb-8">
        <div className="mb-3">
          <h3 className="text-lg font-semibold">Profiles</h3>
          <p className="text-sm text-slate-400">Control what kinds of books appear in the library and review the current library profile.</p>
        </div>

        {/* Visibility */}
        <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-6">
          <h3 className="text-lg font-semibold mb-4">Book Visibility</h3>
          <p className="text-sm text-slate-400 mb-2">
            Choose which types of books should be included in the library by default.
          </p>
          <p className="text-xs text-slate-500 mb-4">
            Owned books are always shown. Books hidden by these rules are skipped for Google Books and Open Library lookups to conserve external API usage.
          </p>
          <div className="space-y-3">
            {VISIBILITY_OPTIONS.map((option) => (
              <label
                key={option.key}
                className="flex items-start gap-3 rounded-lg border border-slate-700 bg-slate-900/30 px-4 py-3"
              >
                <input
                  type="checkbox"
                  checked={visibilityCategories?.[option.key] ?? false}
                  onChange={(e) =>
                    setVisibilityCategories((current) =>
                      current
                        ? { ...current, [option.key]: e.target.checked }
                        : current
                    )
                  }
                  className="mt-1 h-4 w-4 rounded border-slate-500 bg-slate-700 text-emerald-500 focus:ring-emerald-500"
                />
                <div>
                  <div className="text-sm font-medium text-slate-200">{option.label}</div>
                  <div className="text-xs text-slate-400 mt-1">{option.description}</div>
                </div>
              </label>
            ))}
          </div>
          <div className="flex items-center gap-3 mt-4">
            <button
              onClick={handleSaveVisibility}
              disabled={!visibilityChanged || !visibilityCategories}
              className="bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-600 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
            >
              Save
            </button>
            {visibilitySaved && <span className="text-emerald-400 text-sm">Visibility rules updated!</span>}
          </div>
          <div className="mt-4 pt-4 border-t border-slate-700">
            <Link
              to="/books/hidden"
              className="inline-flex items-center gap-2 bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm font-medium px-4 py-2 rounded-lg transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12H9m12 0A9 9 0 113 12a9 9 0 0118 0z" />
              </svg>
              View Hidden Books
            </Link>
          </div>
        </div>

      {/* Library Info */}
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-6">
        <h3 className="text-lg font-semibold mb-4">Library</h3>
        <div className="space-y-3 text-sm">
          <div className="flex justify-between">
            <span className="text-slate-400">Library Path</span>
            <code className="text-slate-300">{settings?.library_path || "-"}</code>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Last Scan</span>
            <span className="text-slate-300">
              {settings?.last_scan_at
                ? formatApiDateTime(settings.last_scan_at, "Never")
                : "Never"}
            </span>
          </div>
        </div>
      </div>
      </section>

      <section id="metadata-refreshes" className="scroll-mt-6 mb-8">
        <div className="mb-3">
          <h3 className="text-lg font-semibold">Metadata Refreshes</h3>
          <p className="text-sm text-slate-400">Run scans, manage refresh cadence, and reset metadata state when needed.</p>
        </div>

        {/* Scan Controls */}
        <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-6">
        <h3 className="text-lg font-semibold mb-4">Library Scan</h3>
        <p className="text-sm text-slate-400 mb-4">
          Scan your library folder for new books, match to Hardcover, and download metadata and covers.
          Only new and removed files are processed — existing books are untouched.
        </p>

        <p className="text-xs text-slate-500 mb-4">
          Live scan status refreshes automatically every second while this page is open.
        </p>

        {isScanning && scanStatus && (
          <div className="mb-4">
            <div className="flex justify-between text-sm mb-1">
              <span className="text-slate-300">{scanStatus.message}</span>
              <span className="text-emerald-400">{Math.round(scanStatus.progress)}%</span>
            </div>
            <div className="w-full bg-slate-700 rounded-full h-2">
              <div
                className="bg-emerald-500 h-2 rounded-full transition-all duration-500"
                style={{ width: `${scanStatus.progress}%` }}
              />
            </div>
          </div>
        )}

        <div className="flex gap-3 mb-4">
          <button
            onClick={() => handleScan()}
            disabled={isScanning}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-600 disabled:cursor-not-allowed text-white font-medium px-6 py-2 rounded-lg transition-colors"
          >
            {isScanning ? "Scanning..." : "Scan Library"}
          </button>
          <button
            onClick={() => handleScan(true)}
            disabled={isScanning}
            className="bg-slate-600 hover:bg-slate-500 disabled:bg-slate-700 disabled:cursor-not-allowed text-white font-medium px-6 py-2 rounded-lg transition-colors"
          >
            Full Refresh
          </button>
        </div>
        <p className="text-xs text-slate-500">
          Scan Library detects new/removed files and only fetches metadata for changes. Full Refresh re-fetches all data from Hardcover.
        </p>

        {lastScanSummary && (
          <div className="mt-6 border-t border-slate-700 pt-6">
            <div className="flex flex-col gap-1 mb-4">
              <h4 className="text-base font-semibold text-slate-100">Last Run Summary</h4>
              <p className="text-sm text-slate-400">
                {lastScanSummary.completed_at
                  ? `Completed ${formatApiDateTime(lastScanSummary.completed_at, "recently")}`
                  : "Most recent completed scan"}
                {" · "}
                {lastScanSummary.mode === "full_refresh" ? "Full Refresh" : "Scan Library"}
                {" · "}
                <span className={lastScanSummary.status === "error" ? "text-red-400" : "text-emerald-400"}>
                  {lastScanSummary.status === "error" ? "Failed" : "Completed"}
                </span>
              </p>
              {lastScanSummary.message && (
                <p className="text-xs text-slate-500">{lastScanSummary.message}</p>
              )}
            </div>

            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 mb-4">
              <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-4">
                <div className="text-xs uppercase tracking-wide text-slate-500">Owned Books Found Locally</div>
                <div className="mt-1 text-2xl font-semibold text-slate-100">{lastScanSummary.owned_books_found}</div>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-4">
                <div className="text-xs uppercase tracking-wide text-slate-500">Authors Added</div>
                <div className="mt-1 text-2xl font-semibold text-slate-100">{lastScanSummary.authors_added}</div>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-4">
                <div className="text-xs uppercase tracking-wide text-slate-500">Books Added</div>
                <div className="mt-1 text-2xl font-semibold text-slate-100">{lastScanSummary.books_added}</div>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-4">
                <div className="text-xs uppercase tracking-wide text-slate-500">Books Hidden</div>
                <div className="mt-1 text-2xl font-semibold text-slate-100">{lastScanSummary.books_hidden}</div>
              </div>
            </div>

            <div className="rounded-lg border border-slate-700 bg-slate-900/30 px-4 py-3 mb-4 text-sm text-slate-300">
              Files processed: {lastScanSummary.files_total} total, {lastScanSummary.files_new} new, {lastScanSummary.files_deleted} deleted, {lastScanSummary.files_unchanged} unchanged.
            </div>

            {lastScanSummary.hidden_by_category.length > 0 && (
              <div className="mb-4">
                <div className="text-sm font-medium text-slate-200 mb-2">Hidden By Category</div>
                <div className="flex flex-wrap gap-2">
                  {lastScanSummary.hidden_by_category.map((item) => (
                    <span
                      key={item.key}
                      className="rounded-full border border-slate-700 bg-slate-900/40 px-3 py-1 text-xs text-slate-300"
                    >
                      {item.label}: {item.count}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="grid gap-4 lg:grid-cols-3">
              {[
                { key: "hardcover", label: "Hardcover", summary: lastScanSummary.hardcover },
                { key: "google", label: "Google Books", summary: lastScanSummary.google },
                { key: "openlibrary", label: "Open Library", summary: lastScanSummary.openlibrary },
              ].map((source) => (
                <div key={source.key} className="rounded-lg border border-slate-700 bg-slate-900/30 p-4">
                  <div className="text-sm font-semibold text-slate-100 mb-3">{source.label}</div>
                  <div className="grid grid-cols-2 gap-3 text-sm mb-3">
                    <div>
                      <div className="text-slate-500">Lookups</div>
                      <div className="text-slate-200">{source.summary.lookups_attempted}</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Matched</div>
                      <div className="text-slate-200">{source.summary.matched}</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Failed</div>
                      <div className="text-slate-200">{source.summary.failed}</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Cached</div>
                      <div className="text-slate-200">{source.summary.cached}</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Deferred</div>
                      <div className="text-slate-200">{source.summary.deferred}</div>
                    </div>
                  </div>
                  {Object.keys(source.summary.failure_reasons).length > 0 ? (
                    <div className="border-t border-slate-700 pt-3">
                      <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Failure Reasons</div>
                      <div className="space-y-1 text-sm">
                        {Object.entries(source.summary.failure_reasons).map(([reason, count]) => (
                          <div key={reason} className="flex justify-between gap-3 text-slate-300">
                            <span>{formatSummaryReason(reason)}</span>
                            <span>{count}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="border-t border-slate-700 pt-3 text-sm text-slate-500">No failures recorded in this run.</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Scheduled Scan */}
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-6">
        <h3 className="text-lg font-semibold mb-4">Scheduled Scan</h3>
        <p className="text-sm text-slate-400 mb-4">
          Automatically scan your library for changes on a schedule. Set to 0 to disable.
        </p>
        <div className="flex gap-2 items-center">
          <input
            type="number"
            min="0"
            value={scanInterval}
            onChange={(e) => setScanInterval(e.target.value)}
            className="w-24 bg-slate-700 border border-slate-600 text-slate-200 text-sm rounded-lg px-4 py-2"
          />
          <span className="text-sm text-slate-400">hours</span>
          <button
            onClick={handleSaveInterval}
            disabled={!intervalChanged}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-600 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            Save
          </button>
          {intervalSaved && <span className="text-emerald-400 text-sm">Schedule updated!</span>}
        </div>
        {(settings?.scan_interval_hours ?? 24) > 0 && (
          <p className="text-xs text-emerald-400 mt-2">
            Active: scanning every {settings?.scan_interval_hours ?? 24} hour(s)
          </p>
        )}
      </div>

      {/* Reset */}
      <div className="bg-slate-800 rounded-lg border border-red-900/50 p-6">
        <h3 className="text-lg font-semibold text-red-400 mb-2">Danger Zone</h3>
        <p className="text-sm text-slate-400 mb-4">
          Delete all database data and cached images. This resets the application to a fresh install. Your ebook files are not affected.
        </p>
        {!confirmReset ? (
          <button
            onClick={() => setConfirmReset(true)}
            className="bg-red-600 hover:bg-red-500 text-white font-medium px-6 py-2 rounded-lg transition-colors"
          >
            Reset All Data
          </button>
        ) : (
          <div className="flex items-center gap-3">
            <button
              onClick={async () => {
                await resetData.mutateAsync();
                setConfirmReset(false);
              }}
              disabled={resetData.isPending}
              className="bg-red-600 hover:bg-red-500 disabled:bg-red-800 text-white font-medium px-6 py-2 rounded-lg transition-colors"
            >
              {resetData.isPending ? "Resetting..." : "Yes, delete everything"}
            </button>
            <button
              onClick={() => setConfirmReset(false)}
              className="bg-slate-600 hover:bg-slate-500 text-white font-medium px-6 py-2 rounded-lg transition-colors"
            >
              Cancel
            </button>
          </div>
        )}
      </div>
      </section>

      <section id="logs" className="scroll-mt-6 mb-8">
        <div className="mb-3">
          <h3 className="text-lg font-semibold">Logs</h3>
          <p className="text-sm text-slate-400">Open the live application log viewer for filtering, scrolling, and download.</p>
        </div>

        <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-6">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-lg font-semibold">Logs</h3>
              <p className="text-sm text-slate-400 mt-1">View application logs, filter by category, and download.</p>
            </div>
            <Link
              to="/logs"
              className="bg-slate-600 hover:bg-slate-500 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors flex items-center gap-2"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              View Logs
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
