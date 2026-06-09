import { type MutableRefObject, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Author } from "../types";
import { useAuthors } from "../api/authors";
import AuthorCard from "../components/AuthorCard";
import MobileAuthorList from "../components/MobileAuthorList";
import AuthorTable from "../components/AuthorTable";
import SortControls from "../components/SortControls";
import SearchBar from "../components/SearchBar";
import ViewToggle from "../components/ViewToggle";
import AddAuthorDialog from "../components/AddAuthorDialog";
import { useIsMobile } from "../hooks/useIsMobile";
import { useElementWidth } from "../hooks/useElementWidth";
import { useWindowVirtualRange } from "../hooks/useWindowVirtualRange";

const SORT_OPTIONS = [
  { value: "name", label: "Name A-Z" },
  { value: "-name", label: "Name Z-A" },
  { value: "-books", label: "Most Books" },
  { value: "-owned", label: "Most Owned" },
];
const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

type AuthorScrollTarget = {
  id: number;
  index: number;
};

function getAuthorInitial(author: Author) {
  const match = author.name.trim().match(/[A-Za-z]/);
  return match ? match[0].toUpperCase() : "";
}

function getAuthorAnchorId(author: Author) {
  return `author-${author.id}`;
}

function getGridColumnCount(width: number) {
  if (width >= 1280) return 6;
  if (width >= 1024) return 5;
  if (width >= 768) return 4;
  if (width >= 640) return 3;
  return 2;
}

function getGridColumnClass(columns: number) {
  switch (columns) {
    case 6:
      return "grid-cols-6";
    case 5:
      return "grid-cols-5";
    case 4:
      return "grid-cols-4";
    case 3:
      return "grid-cols-3";
    default:
      return "grid-cols-2";
  }
}

export default function AuthorsPage() {
  const [sort, setSort] = useState("name");
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"grid" | "table">("grid");
  const [addAuthorOpen, setAddAuthorOpen] = useState(false);
  const [selectedLetter, setSelectedLetter] = useState<string | null>(null);
  const { data: authors, isLoading } = useAuthors(sort, search);
  const isMobile = useIsMobile();
  const scrollToAuthorRef = useRef<((target: AuthorScrollTarget) => void) | null>(null);

  const handleSearch = useCallback((v: string) => setSearch(v), []);
  const letterTargets = useMemo(() => {
    const targets = new Map<string, AuthorScrollTarget>();
    const authorsById = new Map((authors ?? []).map((author, index) => [author.id, index]));
    const sortedAuthors = [...(authors ?? [])].sort((a, b) => a.name.localeCompare(b.name));
    sortedAuthors.forEach((author) => {
      const initial = getAuthorInitial(author);
      const index = authorsById.get(author.id);
      if (initial && index != null && !targets.has(initial)) {
        targets.set(initial, { id: author.id, index });
      }
    });
    return targets;
  }, [authors]);
  const handleLetterSelect = useCallback((letter: string) => {
    const target = letterTargets.get(letter);
    if (target == null) return;
    setSelectedLetter(letter);
    scrollToAuthorRef.current?.(target);
  }, [letterTargets]);
  const authorCount = authors?.length ?? 0;
  const ownedBookCount = authors?.reduce((sum, author) => sum + author.book_count_local, 0) ?? 0;
  const visibleBookCount = authors?.reduce((sum, author) => sum + author.book_count_total, 0) ?? 0;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-slate-400">Loading authors...</div>
      </div>
    );
  }

  return (
    <div>
      <div className={`mb-6 ${isMobile ? "space-y-4" : "flex items-start justify-between gap-4"}`}>
        <div>
          <h2 className={`${isMobile ? "text-xl" : "text-2xl"} font-bold`}>Authors</h2>
          <div className="mt-2 flex flex-wrap gap-4 text-sm text-slate-400">
            <span><span className="font-semibold text-slate-200">{authorCount}</span> authors</span>
            <span><span className="font-semibold text-emerald-400">{ownedBookCount}</span> books owned</span>
            <span><span className="font-semibold text-slate-200">{visibleBookCount}</span> books total</span>
          </div>
        </div>
        <div className={`flex ${isMobile ? "flex-col items-stretch gap-2" : "items-center gap-3"}`}>
          <button
            type="button"
            onClick={() => setAddAuthorOpen(true)}
            className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500"
          >
            Add Author
          </button>
          <SearchBar value={search} onChange={handleSearch} placeholder="Search authors..." />
          {isMobile ? (
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
            >
              {SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          ) : (
            <>
              <SortControls options={SORT_OPTIONS} value={sort} onChange={setSort} />
              <ViewToggle view={view} onChange={setView} />
            </>
          )}
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
      ) : isMobile ? (
        <>
          <div className="pr-7">
            <MobileAuthorList authors={authors} getItemId={getAuthorAnchorId} scrollToAuthorRef={scrollToAuthorRef} />
          </div>
          <AuthorLetterIndex
            targets={letterTargets}
            selectedLetter={selectedLetter}
            onSelect={handleLetterSelect}
            compact
          />
        </>
      ) : view === "table" ? (
        <>
          <div className="pr-8">
            <AuthorTable
              authors={authors}
              getRowId={getAuthorAnchorId}
              initialSort={sort}
              scrollToAuthorRef={scrollToAuthorRef}
            />
          </div>
          <AuthorLetterIndex
            targets={letterTargets}
            selectedLetter={selectedLetter}
            onSelect={handleLetterSelect}
          />
        </>
      ) : (
        <>
          <VirtualAuthorGrid
            authors={authors}
            getItemId={getAuthorAnchorId}
            scrollToAuthorRef={scrollToAuthorRef}
          />
          <AuthorLetterIndex
            targets={letterTargets}
            selectedLetter={selectedLetter}
            onSelect={handleLetterSelect}
          />
        </>
      )}
      <AddAuthorDialog open={addAuthorOpen} onClose={() => setAddAuthorOpen(false)} />
    </div>
  );
}

function AuthorLetterIndex({
  targets,
  selectedLetter,
  onSelect,
  compact = false,
}: {
  targets: Map<string, AuthorScrollTarget>;
  selectedLetter: string | null;
  onSelect: (letter: string) => void;
  compact?: boolean;
}) {
  return (
    <nav
      aria-label="Author letter index"
      className={`fixed right-2 top-1/2 z-30 flex -translate-y-1/2 flex-col rounded-full border border-slate-700 bg-slate-950/90 py-1 shadow-xl shadow-black/30 backdrop-blur ${
        compact ? "max-h-[70vh]" : "max-h-[80vh]"
      }`}
    >
      {LETTERS.map((letter) => {
        const enabled = targets.has(letter);
        const selected = selectedLetter === letter;
        return (
          <button
            key={letter}
            type="button"
            disabled={!enabled}
            aria-label={`Jump to authors starting with ${letter}`}
            onClick={() => onSelect(letter)}
            className={`h-5 w-7 text-[11px] font-semibold leading-5 transition ${
              selected
                ? "text-emerald-300"
                : enabled
                  ? "text-slate-300 hover:text-emerald-300"
                  : "cursor-default text-slate-700"
            }`}
          >
            {letter}
          </button>
        );
      })}
    </nav>
  );
}

function VirtualAuthorGrid({
  authors,
  getItemId,
  scrollToAuthorRef,
}: {
  authors: Author[];
  getItemId: (author: Author) => string;
  scrollToAuthorRef: MutableRefObject<((target: AuthorScrollTarget) => void) | null>;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const width = useElementWidth(containerRef);
  const fallbackWidth = typeof window === "undefined" ? 1280 : window.innerWidth;
  const columns = getGridColumnCount(width || fallbackWidth);
  const gap = 16;
  const cardWidth = width > 0 ? (width - gap * (columns - 1)) / columns : 160;
  const rowHeight = Math.ceil(cardWidth * 4 / 3 + 84 + gap);
  const rowCount = Math.ceil(authors.length / columns);
  const virtualRows = useWindowVirtualRange(containerRef, rowCount, rowHeight, 4);

  useEffect(() => {
    scrollToAuthorRef.current = (target: AuthorScrollTarget) => {
      virtualRows.scrollToIndex(Math.floor(target.index / columns));
    };
    return () => {
      scrollToAuthorRef.current = null;
    };
  }, [columns, scrollToAuthorRef, virtualRows.scrollToIndex]);

  return (
    <div className="pr-8">
      <div ref={containerRef} className="relative" style={{ height: virtualRows.totalSize }}>
        <div
          className="absolute left-0 right-0 space-y-4"
          style={{ transform: `translateY(${virtualRows.offsetTop}px)` }}
        >
          {virtualRows.virtualIndexes.map((rowIndex) => {
            const start = rowIndex * columns;
            const rowAuthors = authors.slice(start, start + columns);
            return (
              <div key={rowIndex} className={`grid ${getGridColumnClass(columns)} gap-4`}>
                {rowAuthors.map((author) => (
                  <AuthorCard key={author.id} id={getItemId(author)} author={author} />
                ))}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
