import { useState } from "react";
import { Link } from "react-router-dom";
import { useUnmatchedFiles } from "../api/books";
import SearchBar from "../components/SearchBar";
import type { UnmatchedLocalFile } from "../types";

const FORMAT_STYLES: Record<string, string> = {
  epub: "bg-emerald-500/15 text-emerald-300",
  mobi: "bg-blue-500/15 text-blue-300",
  pdf: "bg-amber-500/15 text-amber-300",
  audiobook: "bg-purple-500/15 text-purple-300",
};

function formatFileSize(size: number | null): string {
  if (size == null || Number.isNaN(size)) return "";
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

function FormatTag({ format }: { format: string | null }) {
  const key = (format || "").toLowerCase();
  const label = key === "audiobook" ? "AUDIO" : (key || "FILE").toUpperCase();
  const colorClass = FORMAT_STYLES[key] ?? "bg-slate-700 text-slate-300";
  return (
    <span className={`inline-flex flex-shrink-0 items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${colorClass}`}>
      {label}
    </span>
  );
}

function groupByAuthor(files: UnmatchedLocalFile[]): { authorId: number | null; authorName: string; files: UnmatchedLocalFile[] }[] {
  const map = new Map<number | null, { authorId: number | null; authorName: string; files: UnmatchedLocalFile[] }>();
  for (const file of files) {
    const key = file.author_id;
    if (!map.has(key)) {
      map.set(key, { authorId: key, authorName: file.author_name ?? "Unknown", files: [] });
    }
    map.get(key)!.files.push(file);
  }
  return Array.from(map.values());
}

export default function UnmatchedFilesPage() {
  const { data: files = [], isLoading } = useUnmatchedFiles();
  const [search, setSearch] = useState("");

  const filtered = search.trim()
    ? files.filter(
        (f) =>
          f.file_path.toLowerCase().includes(search.toLowerCase()) ||
          (f.author_name ?? "").toLowerCase().includes(search.toLowerCase()),
      )
    : files;

  const groups = groupByAuthor(filtered);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Unmatched Files</h1>
          <p className="mt-1 text-sm text-slate-400">
            Files on disk not linked to any visible book.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {files.length > 0 && (
            <span className="rounded-full bg-amber-500/15 px-3 py-1 text-sm font-medium text-amber-300">
              {files.length} file{files.length !== 1 ? "s" : ""}
            </span>
          )}
          <SearchBar value={search} onChange={setSearch} placeholder="Search files or authors..." />
        </div>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-16">
          <div className="text-slate-400">Loading...</div>
        </div>
      )}

      {!isLoading && filtered.length === 0 && (
        <div className="flex items-center justify-center py-16">
          <p className="text-slate-400">{search ? "No matching files." : "No unmatched files found."}</p>
        </div>
      )}

      {!isLoading && groups.length > 0 && (
        <div className="space-y-4">
          {groups.map(({ authorId, authorName, files: groupFiles }) => (
            <div key={authorId ?? "unknown"} className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3">
              <div className="mb-2 flex items-center gap-2">
                {authorId ? (
                  <Link
                    to={`/authors/${authorId}`}
                    className="text-sm font-semibold text-slate-200 hover:text-emerald-400 transition-colors"
                  >
                    {authorName}
                  </Link>
                ) : (
                  <span className="text-sm font-semibold text-slate-200">{authorName}</span>
                )}
                <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-medium text-amber-300">
                  {groupFiles.length}
                </span>
              </div>
              <div className="divide-y divide-slate-700/50">
                {groupFiles.map((file) => (
                  <div key={file.file_path} className="flex items-center gap-2 py-1.5">
                    <FormatTag format={file.file_format} />
                    <code className="min-w-0 flex-1 truncate text-xs text-slate-300">{file.file_path}</code>
                    {file.linked_book_title && (
                      <span className="shrink-0 text-[11px] text-amber-400">hidden: {file.linked_book_title}</span>
                    )}
                    <span className="shrink-0 text-xs text-slate-500">{formatFileSize(file.file_size)}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
