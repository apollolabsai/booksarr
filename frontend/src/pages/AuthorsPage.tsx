import { useState, useCallback } from "react";
import { useAuthors } from "../api/authors";
import AuthorCard from "../components/AuthorCard";
import AuthorTable from "../components/AuthorTable";
import SortControls from "../components/SortControls";
import SearchBar from "../components/SearchBar";
import ViewToggle from "../components/ViewToggle";

const SORT_OPTIONS = [
  { value: "name", label: "Name A-Z" },
  { value: "-name", label: "Name Z-A" },
  { value: "-books", label: "Most Books" },
  { value: "-owned", label: "Most Owned" },
];

export default function AuthorsPage() {
  const [sort, setSort] = useState("name");
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"grid" | "table">("grid");
  const { data: authors, isLoading } = useAuthors(sort, search);

  const handleSearch = useCallback((v: string) => setSearch(v), []);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-slate-400">Loading authors...</div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Authors</h2>
        <div className="flex items-center gap-3">
          <SearchBar value={search} onChange={handleSearch} placeholder="Search authors..." />
          <SortControls options={SORT_OPTIONS} value={sort} onChange={setSort} />
          <ViewToggle view={view} onChange={setView} />
        </div>
      </div>

      {!authors || authors.length === 0 ? (
        <div className="text-center py-16">
          <svg className="w-16 h-16 mx-auto text-slate-600 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
          </svg>
          <p className="text-slate-400 text-lg mb-2">No authors found</p>
          <p className="text-slate-500 text-sm">
            Go to <a href="/settings" className="text-emerald-400 hover:underline">Settings</a> to configure your API key and scan your library.
          </p>
        </div>
      ) : view === "table" ? (
        <AuthorTable authors={authors} />
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
          {authors.map((author) => (
            <AuthorCard key={author.id} author={author} />
          ))}
        </div>
      )}
    </div>
  );
}
