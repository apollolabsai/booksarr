import { useState, useEffect } from "react";
import { useSettings, useUpdateSettings, useScanStatus, useTriggerScan } from "../api/settings";
import { useQueryClient } from "@tanstack/react-query";

export default function SettingsPage() {
  const { data: settings } = useSettings();
  const updateSettings = useUpdateSettings();
  const triggerScan = useTriggerScan();
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [saved, setSaved] = useState(false);
  const queryClient = useQueryClient();

  const { data: scanStatus } = useScanStatus(true);
  const isScanning = scanStatus?.status === "scanning";

  const handleSaveKey = async () => {
    if (!apiKey.trim()) return;
    await updateSettings.mutateAsync({ hardcover_api_key: apiKey });
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const handleScan = async () => {
    await triggerScan.mutateAsync();
    // After scan completes, refresh all data
    const pollUntilDone = setInterval(async () => {
      const status = await fetch("/api/library/status").then((r) => r.json());
      if (status.status === "idle" && status.progress >= 100) {
        clearInterval(pollUntilDone);
        queryClient.invalidateQueries({ queryKey: ["authors"] });
        queryClient.invalidateQueries({ queryKey: ["books"] });
      }
    }, 3000);
  };

  return (
    <div className="max-w-2xl">
      <h2 className="text-2xl font-bold mb-6">Settings</h2>

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
          </p>
        )}
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
                ? new Date(settings.last_scan_at).toLocaleString()
                : "Never"}
            </span>
          </div>
        </div>
      </div>

      {/* Scan Controls */}
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6">
        <h3 className="text-lg font-semibold mb-4">Library Scan</h3>
        <p className="text-sm text-slate-400 mb-4">
          Scan your library folder, match books to Hardcover, and download metadata and covers.
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

        <button
          onClick={handleScan}
          disabled={isScanning}
          className="bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-600 disabled:cursor-not-allowed text-white font-medium px-6 py-2 rounded-lg transition-colors"
        >
          {isScanning ? "Scanning..." : "Scan Library"}
        </button>
      </div>
    </div>
  );
}
