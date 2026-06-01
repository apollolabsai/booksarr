import { useEffect, useMemo, useState } from "react";
import { useApplyOpfBookMetadata, useBookMetadataInfo, useUpdateBookMetadata, useWriteOpfBookMetadata } from "../api/books";
import type { BookMetadataField, BookMetadataValues } from "../types";

const FIELD_LABELS: Record<BookMetadataField, string> = {
  title: "Title",
  author_name: "Author",
  isbn: "ISBN",
  publisher: "Publisher",
  description: "Description",
  release_date: "Release Date",
  language: "Language",
  series_name: "Series",
  series_position: "Series Position",
};

const FIELD_ORDER: BookMetadataField[] = [
  "title",
  "author_name",
  "isbn",
  "publisher",
  "description",
  "release_date",
  "language",
  "series_name",
  "series_position",
];

type WriteSource = "current" | "original" | "manual" | "form";

function stringifyValue(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function emptyMetadataValues(): BookMetadataValues {
  return {
    title: "",
    author_name: "",
    isbn: "",
    publisher: "",
    description: "",
    release_date: "",
    language: "",
    series_name: "",
    series_position: null,
  };
}

export default function MetadataInfoDialog({
  bookId,
  title,
  open,
  onClose,
}: {
  bookId: number | null;
  title: string;
  open: boolean;
  onClose: () => void;
}) {
  const { data, isLoading, isError } = useBookMetadataInfo(bookId, open);
  const updateMetadata = useUpdateBookMetadata();
  const applyOpfMetadata = useApplyOpfBookMetadata();
  const writeOpfMetadata = useWriteOpfBookMetadata();
  const [selectedFileId, setSelectedFileId] = useState<number | null>(null);
  const [selectedFields, setSelectedFields] = useState<Set<BookMetadataField>>(new Set());
  const [selectedWriteFields, setSelectedWriteFields] = useState<Set<BookMetadataField>>(new Set());
  const [writeSource, setWriteSource] = useState<WriteSource>("current");
  const [deleteBackupAfterRepair, setDeleteBackupAfterRepair] = useState(false);
  const [formValues, setFormValues] = useState<BookMetadataValues>(() => emptyMetadataValues());
  const [clearFields, setClearFields] = useState<Set<BookMetadataField>>(new Set());
  const [saveError, setSaveError] = useState<string | null>(null);
  const [opfRepairMessage, setOpfRepairMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    setSelectedFileId(data.files[0]?.id ?? null);
    setSelectedFields(new Set());
    setSelectedWriteFields(new Set());
    setWriteSource("current");
    setDeleteBackupAfterRepair(false);
    setClearFields(new Set());
    setSaveError(null);
    setOpfRepairMessage(null);
    setFormValues({
      title: data.manual.title ?? "",
      author_name: data.manual.author_name ?? "",
      isbn: data.manual.isbn ?? "",
      publisher: data.manual.publisher ?? "",
      description: data.manual.description ?? "",
      release_date: data.manual.release_date ?? "",
      language: data.manual.language ?? "",
      series_name: data.manual.series_name ?? "",
      series_position: data.manual.series_position,
    });
  }, [data]);

  useEffect(() => {
    if (!open) {
      setSaveError(null);
      setOpfRepairMessage(null);
      setSelectedFields(new Set());
      setSelectedWriteFields(new Set());
      setDeleteBackupAfterRepair(false);
      setClearFields(new Set());
    }
  }, [open]);

  const selectedFile = useMemo(
    () => data?.files.find((file) => file.id === selectedFileId) ?? data?.files[0] ?? null,
    [data?.files, selectedFileId],
  );

  if (!open || !bookId) return null;

  const getOpfValue = (field: BookMetadataField): string | number | null => {
    if (!selectedFile) return null;
    if (field === "author_name") return selectedFile.opf_author;
    if (field === "release_date") return selectedFile.opf_date;
    if (field === "series_name") return selectedFile.opf_series;
    if (field === "series_position") return selectedFile.opf_series_index;
    return selectedFile[`opf_${field}` as keyof typeof selectedFile] as string | number | null;
  };

  const toggleSelectedField = (field: BookMetadataField) => {
    setSelectedFields((current) => {
      const next = new Set(current);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return next;
    });
  };

  const toggleClearField = (field: BookMetadataField) => {
    setClearFields((current) => {
      const next = new Set(current);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return next;
    });
  };

  const toggleWriteField = (field: BookMetadataField) => {
    setSelectedWriteFields((current) => {
      const next = new Set(current);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return next;
    });
  };

  const getWriteValues = (): BookMetadataValues => {
    if (!data) return emptyMetadataValues();
    if (writeSource === "original") return data.original;
    if (writeSource === "manual") return data.manual;
    if (writeSource === "form") return formValues;
    return data.current;
  };

  const handleApplyOpf = async () => {
    if (!selectedFile || selectedFields.size === 0) return;
    setSaveError(null);
    try {
      await applyOpfMetadata.mutateAsync({
        bookId,
        bookFileId: selectedFile.id,
        fields: Array.from(selectedFields),
      });
      setSelectedFields(new Set());
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to apply OPF metadata.");
    }
  };

  const handleSave = async () => {
    setSaveError(null);
    try {
      await updateMetadata.mutateAsync({
        bookId,
        values: formValues,
        clearFields: Array.from(clearFields),
      });
      setClearFields(new Set());
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save metadata.");
    }
  };

  const handleWriteOpf = async () => {
    if (!selectedFile || selectedWriteFields.size === 0) return;
    setSaveError(null);
    setOpfRepairMessage(null);
    try {
      const result = await writeOpfMetadata.mutateAsync({
        bookId,
        bookFileId: selectedFile.id,
        fields: Array.from(selectedWriteFields),
        values: getWriteValues(),
        deleteBackup: deleteBackupAfterRepair,
      });
      setSelectedWriteFields(new Set());
      setOpfRepairMessage(result.backup_path ? `EPUB OPF repaired. Backup: ${result.backup_path}` : "EPUB OPF repaired. Backup deleted.");
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to repair EPUB OPF metadata.");
    }
  };

  const isSaving = updateMetadata.isPending || applyOpfMetadata.isPending || writeOpfMetadata.isPending;
  const writeValues = getWriteValues();
  const selectedFileSupportsOpfRepair = (selectedFile?.file_format || "").toLowerCase() === "epub";

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/80 px-4 py-6">
      <div className="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex shrink-0 items-start justify-between border-b border-slate-700 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">Metadata Info</h2>
            <p className="mt-1 text-sm text-slate-400">{title}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-700"
          >
            Close
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {isLoading && <p className="text-sm text-slate-400">Loading metadata...</p>}
          {isError && <p className="text-sm text-rose-300">Failed to load metadata.</p>}

          {data && (
            <div className="space-y-6">
              <div className="rounded-lg border border-slate-700 bg-slate-800/50">
                <div className="border-b border-slate-700 px-4 py-3">
                  <h3 className="text-sm font-semibold text-slate-200">Current and OPF Data</h3>
                </div>
                <div className="border-b border-slate-700 px-4 py-3">
                  <label className="text-xs font-medium text-slate-400">
                    Local file
                    <select
                      value={selectedFile?.id ?? ""}
                      onChange={(event) => setSelectedFileId(Number(event.target.value))}
                      className="mt-1 block w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-200"
                    >
                      {data.files.map((file) => (
                        <option key={file.id} value={file.id}>{file.file_path}</option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-slate-900/60 text-[11px] uppercase tracking-wide text-slate-500">
                      <tr>
                        <th className="px-4 py-2">Apply</th>
                        <th className="px-4 py-2">Field</th>
                        <th className="px-4 py-2">Current</th>
                        <th className="px-4 py-2">Original</th>
                        <th className="px-4 py-2">Manual</th>
                        <th className="px-4 py-2">OPF</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-700">
                      {FIELD_ORDER.map((field) => (
                        <tr key={field}>
                          <td className="px-4 py-2">
                            <input
                              type="checkbox"
                              checked={selectedFields.has(field)}
                              disabled={!selectedFile || getOpfValue(field) == null || getOpfValue(field) === ""}
                              onChange={() => toggleSelectedField(field)}
                              className="rounded border-slate-600 bg-slate-700 text-emerald-500 focus:ring-emerald-500"
                            />
                          </td>
                          <td className="whitespace-nowrap px-4 py-2 font-medium text-slate-200">{FIELD_LABELS[field]}</td>
                          <td className="max-w-xs px-4 py-2 text-slate-300">{stringifyValue(data.current[field])}</td>
                          <td className="max-w-xs px-4 py-2 text-slate-400">{stringifyValue(data.original[field])}</td>
                          <td className="max-w-xs px-4 py-2 text-amber-200">{stringifyValue(data.manual[field])}</td>
                          <td className="max-w-xs px-4 py-2 text-emerald-200">{stringifyValue(getOpfValue(field))}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="flex justify-end border-t border-slate-700 px-4 py-3">
                  <button
                    type="button"
                    onClick={handleApplyOpf}
                    disabled={isSaving || selectedFields.size === 0 || !selectedFile}
                    className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Apply Selected OPF Fields
                  </button>
                </div>
              </div>

              <div className="rounded-lg border border-slate-700 bg-slate-800/50">
                <div className="border-b border-slate-700 px-4 py-3">
                  <h3 className="text-sm font-semibold text-slate-200">Manual Overrides</h3>
                </div>
                <div className="grid gap-4 p-4 md:grid-cols-2">
                  {FIELD_ORDER.map((field) => {
                    const isLong = field === "description";
                    const value = formValues[field];
                    return (
                      <div key={field} className={isLong ? "md:col-span-2" : ""}>
                        <div className="mb-1 flex items-center justify-between gap-3">
                          <label className="text-xs font-medium text-slate-400">{FIELD_LABELS[field]}</label>
                          <label className="flex items-center gap-1.5 text-[11px] text-slate-400">
                            <input
                              type="checkbox"
                              checked={clearFields.has(field)}
                              onChange={() => toggleClearField(field)}
                              className="rounded border-slate-600 bg-slate-700 text-amber-500 focus:ring-amber-500"
                            />
                            Clear override
                          </label>
                        </div>
                        {isLong ? (
                          <textarea
                            value={String(value ?? "")}
                            placeholder={stringifyValue(data.current[field])}
                            onChange={(event) => setFormValues((current) => ({ ...current, [field]: event.target.value }))}
                            rows={5}
                            disabled={clearFields.has(field)}
                            className="w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
                          />
                        ) : (
                          <input
                            type={field === "series_position" ? "number" : "text"}
                            step={field === "series_position" ? "0.1" : undefined}
                            value={value == null ? "" : String(value)}
                            placeholder={stringifyValue(data.current[field])}
                            onChange={(event) => {
                              const nextValue = field === "series_position"
                                ? (event.target.value === "" ? null : Number(event.target.value))
                                : event.target.value;
                              setFormValues((current) => ({ ...current, [field]: nextValue }));
                            }}
                            disabled={clearFields.has(field)}
                            className="w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
                          />
                        )}
                      </div>
                    );
                  })}
                </div>
                <div className="flex items-center justify-between border-t border-slate-700 px-4 py-3">
                  {saveError ? <p className="text-sm text-rose-300">{saveError}</p> : <span />}
                  <button
                    type="button"
                    onClick={handleSave}
                    disabled={isSaving}
                    className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Save Metadata
                  </button>
                </div>
              </div>

              <div className="rounded-lg border border-slate-700 bg-slate-800/50">
                <div className="border-b border-slate-700 px-4 py-3">
                  <h3 className="text-sm font-semibold text-slate-200">Repair EPUB OPF</h3>
                </div>
                <div className="space-y-4 p-4">
                  <div className="grid gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
                    <label className="text-xs font-medium text-slate-400">
                      Write values from
                      <select
                        value={writeSource}
                        onChange={(event) => setWriteSource(event.target.value as WriteSource)}
                        className="mt-1 block w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-200"
                      >
                        <option value="current">Current metadata</option>
                        <option value="original">Original matched metadata</option>
                        <option value="manual">Saved manual overrides</option>
                        <option value="form">Manual edit form</option>
                      </select>
                    </label>
                    <div>
                      <div className="mb-2 text-xs font-medium text-slate-400">Fields to write into the selected EPUB</div>
                      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                        {FIELD_ORDER.map((field) => {
                          const value = writeValues[field];
                          const hasValue = value !== null && value !== undefined && value !== "";
                          return (
                            <label
                              key={field}
                              className={`flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${
                                selectedWriteFields.has(field)
                                  ? "border-emerald-500/60 bg-emerald-500/10 text-slate-100"
                                  : "border-slate-700 bg-slate-900/60 text-slate-300"
                              } ${!hasValue ? "opacity-50" : ""}`}
                            >
                              <input
                                type="checkbox"
                                checked={selectedWriteFields.has(field)}
                                disabled={!hasValue}
                                onChange={() => toggleWriteField(field)}
                                className="mt-0.5 rounded border-slate-600 bg-slate-700 text-emerald-500 focus:ring-emerald-500"
                              />
                              <span className="min-w-0">
                                <span className="block font-medium">{FIELD_LABELS[field]}</span>
                                <span className="block truncate text-xs text-slate-500">{stringifyValue(value)}</span>
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                  {!selectedFileSupportsOpfRepair && (
                    <p className="text-sm text-amber-300">OPF repair is only available for EPUB files.</p>
                  )}
                  <label className="flex items-center gap-2 text-sm text-slate-300">
                    <input
                      type="checkbox"
                      checked={deleteBackupAfterRepair}
                      onChange={() => setDeleteBackupAfterRepair((current) => !current)}
                      className="rounded border-slate-600 bg-slate-700 text-amber-500 focus:ring-amber-500"
                    />
                    Delete backup after successful repair
                  </label>
                  {opfRepairMessage && <p className="text-sm text-emerald-300">{opfRepairMessage}</p>}
                </div>
                <div className="flex justify-end border-t border-slate-700 px-4 py-3">
                  <button
                    type="button"
                    onClick={handleWriteOpf}
                    disabled={isSaving || !selectedFileSupportsOpfRepair || selectedWriteFields.size === 0 || !selectedFile}
                    className="rounded-md bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-500 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Write Selected Fields to EPUB OPF
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
