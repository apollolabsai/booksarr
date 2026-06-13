import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import type { BookInAuthor, Book } from "../types";
import { getBookCoverPresentation, getImageUrl } from "../types";
import CoverPickerDialog from "./CoverPickerDialog";
import IrcSearchDialog from "./IrcSearchDialog";
import { useRefreshBook, useSetBookVisibility } from "../api/books";
import BookDownloadSelector from "./BookDownloadSelector";
import MetadataInfoDialog from "./MetadataInfoDialog";

type BookLike = BookInAuthor | Book;
type MenuPosition = {
  left: number;
  top: number;
};

const ACTION_MENU_WIDTH = 224;
const ACTION_MENU_GAP = 8;
const ACTION_MENU_MARGIN = 8;
const ACTION_MENU_ESTIMATED_HEIGHT = 224;

function isFullBook(book: BookLike): book is Book {
  return "author_name" in book;
}

function OwnedBadge({ count }: { count: number }) {
  if (count > 1) {
    return (
      <div
        className="absolute top-2 right-2 min-w-6 rounded-full bg-emerald-500 px-1.5 py-0.5 text-center text-xs font-semibold text-white"
        title={`${count} owned copies`}
      >
        {count}
      </div>
    );
  }

  return (
    <div className="absolute top-2 right-2 rounded-full bg-emerald-500 p-1" title="Owned">
      <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
        <path
          fillRule="evenodd"
          d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
          clipRule="evenodd"
        />
      </svg>
    </div>
  );
}

export default function BookCard({
  book,
  onClick,
  showAuthor = false,
  authorName = null,
  selected = false,
  onToggleSelected,
}: {
  book: BookLike;
  onClick?: () => void;
  showAuthor?: boolean;
  authorName?: string | null;
  selected?: boolean;
  onToggleSelected?: () => void;
}) {
  const refreshBook = useRefreshBook();
  const setBookVisibility = useSetBookVisibility();
  const [coverPickerOpen, setCoverPickerOpen] = useState(false);
  const [ircSearchOpen, setIrcSearchOpen] = useState(false);
  const [metadataInfoOpen, setMetadataInfoOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState<MenuPosition | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuContentRef = useRef<HTMLDivElement | null>(null);
  const imgUrl = getImageUrl(
    book.cover_image_cached_path,
    "cover_image_url" in book ? book.cover_image_url : null
  );
  const coverPresentation = getBookCoverPresentation(book.cover_aspect_ratio);

  const hardcoverUrl = book.hardcover_slug
    ? `https://hardcover.app/books/${book.hardcover_slug}`
    : null;

  const handleClick = () => {
    if (hardcoverUrl) {
      window.open(hardcoverUrl, "_blank", "noopener,noreferrer");
    } else if (onClick) {
      onClick();
    }
  };

  const updateMenuPosition = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;

    const rect = trigger.getBoundingClientRect();
    const menuHeight = menuContentRef.current?.offsetHeight || ACTION_MENU_ESTIMATED_HEIGHT;
    const maxLeft = Math.max(ACTION_MENU_MARGIN, window.innerWidth - ACTION_MENU_WIDTH - ACTION_MENU_MARGIN);
    const left = Math.min(Math.max(ACTION_MENU_MARGIN, rect.left), maxLeft);
    const hasRoomBelow = window.innerHeight - rect.bottom >= menuHeight + ACTION_MENU_GAP + ACTION_MENU_MARGIN;
    const preferredTop = hasRoomBelow
      ? rect.bottom + ACTION_MENU_GAP
      : rect.top - menuHeight - ACTION_MENU_GAP;
    const maxTop = Math.max(ACTION_MENU_MARGIN, window.innerHeight - menuHeight - ACTION_MENU_MARGIN);
    const top = Math.min(Math.max(ACTION_MENU_MARGIN, preferredTop), maxTop);

    setMenuPosition({ left, top });
  }, []);

  useEffect(() => {
    if (!menuOpen) return;

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        menuRef.current?.contains(target)
        || menuContentRef.current?.contains(target)
      ) {
        return;
      }
      setMenuOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
      }
    };
    const handleViewportChange = () => setMenuOpen(false);

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("scroll", handleViewportChange, true);
    window.addEventListener("resize", handleViewportChange);
    updateMenuPosition();
    const frame = window.requestAnimationFrame(updateMenuPosition);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("scroll", handleViewportChange, true);
      window.removeEventListener("resize", handleViewportChange);
      window.cancelAnimationFrame(frame);
    };
  }, [menuOpen, updateMenuPosition]);

  const closeMenu = () => setMenuOpen(false);

  return (
    <>
      <div
        className="group cursor-pointer"
        onClick={handleClick}
      >
        <div
          className={`relative rounded-lg overflow-hidden border transition-all ${
            selected
              ? "border-emerald-500 shadow-[0_0_0_1px_rgba(16,185,129,0.45)]"
              : "border-slate-600 group-hover:border-emerald-500/50"
          } ${coverPresentation.frameClassName}`}
          style={coverPresentation.frameStyle}
        >
          {onToggleSelected && (
            <div className="absolute left-2 top-2 z-20">
              <label
                className="flex h-6 w-6 items-center justify-center rounded-md border border-slate-500/70 bg-slate-950/80"
                onClick={(e) => e.stopPropagation()}
              >
                <input
                  type="checkbox"
                  checked={selected}
                  onChange={() => onToggleSelected()}
                  aria-label={`Select ${book.title}`}
                  className="h-4 w-4 rounded border-slate-500 bg-slate-800 text-emerald-500 focus:ring-emerald-500"
                />
              </label>
            </div>
          )}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setMetadataInfoOpen(true);
            }}
            className="absolute right-2 top-10 z-[80] flex h-7 w-7 items-center justify-center rounded-md border border-slate-500/70 bg-slate-950/80 text-sm font-semibold leading-none text-slate-100 opacity-0 transition-opacity hover:bg-slate-800/90 group-hover:opacity-100"
            title="Metadata info"
            aria-label="Metadata info"
          >
            i
          </button>
          {imgUrl ? (
            coverPresentation.innerClassName ? (
              <div className={coverPresentation.innerClassName}>
                <img
                  src={imgUrl}
                  alt={book.title}
                  className={coverPresentation.imageClassName}
                  loading="lazy"
                />
              </div>
            ) : (
              <img
                src={imgUrl}
                alt={book.title}
                className={coverPresentation.imageClassName}
                loading="lazy"
              />
            )
          ) : (
            <div className="w-full h-full flex items-center justify-center p-2 text-center text-sm text-slate-400">
              {book.title}
            </div>
          )}
          <div ref={menuRef} className="absolute bottom-2 left-2 right-2">
            <button
              ref={triggerRef}
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setMenuOpen((current) => !current);
              }}
              className={`rounded-md border border-slate-500/60 bg-slate-900/70 px-1.5 py-1 text-slate-100 transition-opacity hover:bg-slate-800/90 ${
                menuOpen ? "opacity-100" : "opacity-0 group-hover:opacity-100"
              }`}
              title="Book actions"
            >
              <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
                <circle cx="5" cy="12" r="1.75" />
                <circle cx="12" cy="12" r="1.75" />
                <circle cx="19" cy="12" r="1.75" />
              </svg>
            </button>
            {menuOpen && menuPosition && createPortal(
              <div
                ref={menuContentRef}
                className="fixed z-[140] w-56 max-w-[calc(100vw-1rem)] rounded-lg border border-slate-600 bg-slate-900/95 p-1 shadow-2xl shadow-black/40 ring-1 ring-black/30"
                style={{
                  left: menuPosition.left,
                  top: menuPosition.top,
                }}
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  type="button"
                  onClick={() => {
                    closeMenu();
                    setMetadataInfoOpen(true);
                  }}
                  className="flex w-full items-center whitespace-nowrap rounded-md px-3 py-2 text-sm text-slate-200 transition-colors hover:bg-slate-800"
                >
                  Metadata Info
                </button>
                <button
                  type="button"
                  onClick={() => {
                    closeMenu();
                    setCoverPickerOpen(true);
                  }}
                  className="flex w-full items-center whitespace-nowrap rounded-md px-3 py-2 text-sm text-slate-200 transition-colors hover:bg-slate-800"
                >
                  Choose Poster
                </button>
                <button
                  type="button"
                  onClick={() => {
                    closeMenu();
                    setIrcSearchOpen(true);
                  }}
                  className="flex w-full items-center whitespace-nowrap rounded-md px-3 py-2 text-sm text-slate-200 transition-colors hover:bg-slate-800"
                >
                  Search IRC
                </button>
                <button
                  type="button"
                  onClick={() => {
                    closeMenu();
                    refreshBook.mutate(book.id);
                  }}
                  disabled={refreshBook.isPending}
                  className="flex w-full items-center whitespace-nowrap rounded-md px-3 py-2 text-sm text-slate-200 transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Refresh
                </button>
                <BookDownloadSelector
                  bookId={book.id}
                  localFiles={book.local_files}
                  disabled={!book.is_owned}
                  align="left"
                  direction="down"
                  wrapperClassName="flex w-full"
                  menuWidthClassName="w-[18rem]"
                  onDownloadStart={closeMenu}
                  renderTrigger={({ toggle, disabled, hasMultiple }) => (
                    <button
                      type="button"
                      onClick={toggle}
                      disabled={disabled}
                      className="flex w-full items-center whitespace-nowrap rounded-md px-3 py-2 text-sm text-slate-200 transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {hasMultiple ? "Download..." : "Download Book"}
                    </button>
                  )}
                />
                <button
                  type="button"
                  onClick={() => {
                    closeMenu();
                    setBookVisibility.mutate({ bookId: book.id, action: "hide" });
                  }}
                  disabled={setBookVisibility.isPending}
                  className="flex w-full items-center whitespace-nowrap rounded-md px-3 py-2 text-sm text-rose-300 transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Hide Book
                </button>
              </div>,
              document.body,
            )}
          </div>
          {book.is_owned && <OwnedBadge count={book.owned_copy_count} />}
        </div>
        <div className="mt-2">
          <p className="text-sm font-medium text-slate-200 truncate group-hover:text-emerald-400 transition-colors">
            {book.title}
          </p>
          {showAuthor && isFullBook(book) && (
            <Link
              to={`/authors/${book.author_id}`}
              className="block text-xs text-slate-500 hover:text-emerald-400 truncate"
              onClick={(e) => e.stopPropagation()}
            >
              {book.author_name}
            </Link>
          )}
          {book.release_date && (
            <p className="text-xs text-slate-500 mt-0.5">
              {book.release_date.substring(0, 4)}
            </p>
          )}
        </div>
      </div>
      <CoverPickerDialog
        bookId={book.id}
        title={book.title}
        open={coverPickerOpen}
        onClose={() => setCoverPickerOpen(false)}
      />
      <IrcSearchDialog
        bookId={book.id}
        title={book.title}
        authorName={isFullBook(book) ? book.author_name : authorName}
        open={ircSearchOpen}
        onClose={() => setIrcSearchOpen(false)}
      />
      <MetadataInfoDialog
        bookId={book.id}
        title={book.title}
        open={metadataInfoOpen}
        onClose={() => setMetadataInfoOpen(false)}
      />
    </>
  );
}
