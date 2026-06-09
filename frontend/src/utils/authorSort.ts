import type { Author } from "../types";

const AUTHOR_SUFFIXES = new Set(["jr", "sr", "ii", "iii", "iv", "v", "esq", "md", "m.d", "phd", "ph.d"]);
const SORT_HONORIFICS = new Set(["sir", "dame", "lord", "lady", "dr", "mr", "mrs", "ms", "rev", "prof"]);

export function authorSortKey(name: string | null | undefined): string {
  const text = (name ?? "").trim().replace(/\s+/g, " ");
  if (!text) return "";

  if (text.includes(" & ")) {
    return authorSortKey(text.split(" & ", 1)[0]);
  }

  if (text.includes(",")) {
    let chunks = text.split(",").map((chunk) => chunk.trim()).filter(Boolean);
    let strippedSuffix = false;
    while (chunks.length > 1 && isAuthorSuffixChunk(chunks[chunks.length - 1])) {
      chunks = chunks.slice(0, -1);
      strippedSuffix = true;
    }
    if (strippedSuffix && chunks.length === 1) {
      return authorSortKey(chunks[0]);
    }
    return chunks.join(", ").toLowerCase();
  }

  let parts = text.split(" ");
  while (parts.length > 1 && isAuthorSuffixChunk(parts[parts.length - 1])) {
    parts = parts.slice(0, -1);
  }
  while (parts.length > 1 && SORT_HONORIFICS.has(normalizedNameToken(parts[0]))) {
    parts = parts.slice(1);
  }
  if (parts.length === 0) return text.toLowerCase();

  const surname = parts[parts.length - 1].toLowerCase();
  const rest = parts.slice(0, -1).join(" ").toLowerCase();
  return rest ? `${surname}, ${rest}` : surname;
}

export function compareAuthorsBySortName(left: Author, right: Author): number {
  return authorSortKey(left.name).localeCompare(authorSortKey(right.name)) || left.name.localeCompare(right.name);
}

export function authorSortInitial(author: Author): string {
  const match = authorSortKey(author.name).match(/[a-z]/i);
  return match ? match[0].toUpperCase() : "";
}

function normalizedNameToken(value: string): string {
  return value.toLowerCase().replace(/\.+$/, "");
}

function isAuthorSuffixChunk(value: string): boolean {
  const tokens = value.split(/\s+/).map(normalizedNameToken).filter(Boolean);
  return tokens.length > 0 && tokens.every((token) => AUTHOR_SUFFIXES.has(token));
}
