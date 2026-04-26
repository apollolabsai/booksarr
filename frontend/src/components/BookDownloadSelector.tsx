import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { LocalBookFile } from "../types";

const DOWNLOAD_FORMAT_ORDER: Record<string, number> = {
  epub: 0,
  mobi: 1,
  pdf: 2,
  audiobook: 3,
};

const FORMAT_STYLES: Record<string, string> = {
  epub: "bg-emerald-500/15 text-emerald-300",
  mobi: "bg-blue-500/15 text-blue-300",
  pdf: "bg-amber-500/15 text-amber-300",
  audiobook: "bg-purple-500/15 text-purple-300",
};

function formatFileSize(size: number | null): string {
  if (size == null || Number.isNaN(size)) return "Unknown size";
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB"];
  let value = size / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 100 ? 0 : value >= 10 ? 1 : 2)} ${units[unitIndex]}`;
}

function FileFormatTag({ format }: { format: string | null }) {
  const key = (format || "").toLowerCase();
  const label = key === "audiobook" ? "AUDIO" : (key ? key.toUpperCase() : "FILE");
  const colorClass = FORMAT_STYLES[key] ?? "bg-slate-700 text-slate-300";
  return (
    <span className={`inline-flex flex-shrink-0 items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${colorClass}`}>
      {label}
    </span>
  );
}

export function downloadBookFile(bookId: number, fileId?: number, target: "window" | "location" = "window") {
  const qs = fileId ? `?file_id=${fileId}` : "";
  const url = `/api/books/${bookId}/download${qs}`;
  if (target === "location") {
    window.location.assign(url);
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

function sortDownloadFiles(localFiles: LocalBookFile[]) {
  return [...localFiles].sort((a, b) => {
    const formatA = (a.file_format || "").toLowerCase();
    const formatB = (b.file_format || "").toLowerCase();
    const formatDiff = (DOWNLOAD_FORMAT_ORDER[formatA] ?? 999) - (DOWNLOAD_FORMAT_ORDER[formatB] ?? 999);
    if (formatDiff !== 0) return formatDiff;
    return a.file_path.localeCompare(b.file_path);
  });
}

export default function BookDownloadSelector({
  bookId,
  localFiles,
  disabled = false,
  target = "window",
  align = "right",
  direction = "up",
  wrapperClassName = "",
  menuWidthClassName = "w-80",
  onDownloadStart,
  renderTrigger,
}: {
  bookId: number;
  localFiles: LocalBookFile[];
  disabled?: boolean;
  target?: "window" | "location";
  align?: "left" | "right";
  direction?: "up" | "down";
  wrapperClassName?: string;
  menuWidthClassName?: string;
  onDownloadStart?: () => void;
  renderTrigger: (args: { open: boolean; toggle: () => void; disabled: boolean; hasMultiple: boolean }) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const downloadFiles = useMemo(() => sortDownloadFiles(localFiles), [localFiles]);
  const hasMultiple = downloadFiles.length > 1;
  const isDisabled = disabled || downloadFiles.length === 0;

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [open]);

  const handleDownload = (fileId?: number) => {
    onDownloadStart?.();
    setOpen(false);
    downloadBookFile(bookId, fileId, target);
  };

  const handleToggle = () => {
    if (isDisabled) return;
    if (!hasMultiple) {
      handleDownload(downloadFiles[0]?.id);
      return;
    }
    setOpen((current) => !current);
  };

  const positionClassName = direction === "down" ? "top-full mt-2" : "bottom-full mb-2";
  const alignClassName = align === "left" ? "left-0" : "right-0";

  return (
    <div
      ref={wrapperRef}
      className={wrapperClassName ? `relative ${wrapperClassName}` : "relative inline-flex"}
      onClick={(event) => event.stopPropagation()}
    >
      {renderTrigger({ open, toggle: handleToggle, disabled: isDisabled, hasMultiple })}
      {open && hasMultiple && (
        <div
          className={`absolute ${positionClassName} ${alignClassName} z-40 max-w-[min(20rem,calc(100vw-2rem))] overflow-hidden rounded-2xl border border-slate-500 bg-slate-950 shadow-[0_18px_50px_rgba(2,6,23,0.65)] ring-1 ring-black/35 ${menuWidthClassName}`}
        >
          <div className="bg-slate-900 px-3 py-2.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-300">
            Choose File to Download
          </div>
          <div className="max-h-72 space-y-1.5 overflow-y-auto bg-slate-950 p-2">
            {downloadFiles.map((file) => (
              <button
                key={file.id}
                type="button"
                onClick={() => handleDownload(file.id)}
                className="flex w-full items-start gap-3 rounded-xl border border-slate-800 bg-slate-900 px-3 py-2.5 text-left transition-colors hover:border-slate-700 hover:bg-slate-800"
              >
                <FileFormatTag format={file.file_format} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-xs font-medium text-slate-100">{file.file_name}</div>
                  <div className="truncate text-[11px] text-slate-400">{file.file_path}</div>
                </div>
                <div className="shrink-0 whitespace-nowrap text-[11px] text-slate-500">
                  {formatFileSize(file.file_size)}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
