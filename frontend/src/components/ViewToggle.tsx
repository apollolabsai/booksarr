export default function ViewToggle({
  view,
  onChange,
}: {
  view: "grid" | "table";
  onChange: (view: "grid" | "table") => void;
}) {
  return (
    <div className="flex bg-slate-700 rounded-lg p-0.5">
      <button
        onClick={() => onChange("grid")}
        className={`px-2 py-1.5 rounded-md transition-colors ${
          view === "grid"
            ? "bg-slate-600 text-emerald-400"
            : "text-slate-400 hover:text-slate-200"
        }`}
        title="Grid view"
      >
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
          <path d="M5 3a2 2 0 00-2 2v2a2 2 0 002 2h2a2 2 0 002-2V5a2 2 0 00-2-2H5zM5 11a2 2 0 00-2 2v2a2 2 0 002 2h2a2 2 0 002-2v-2a2 2 0 00-2-2H5zM11 5a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V5zM11 13a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
        </svg>
      </button>
      <button
        onClick={() => onChange("table")}
        className={`px-2 py-1.5 rounded-md transition-colors ${
          view === "table"
            ? "bg-slate-600 text-emerald-400"
            : "text-slate-400 hover:text-slate-200"
        }`}
        title="Table view"
      >
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M3 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" clipRule="evenodd" />
        </svg>
      </button>
    </div>
  );
}
