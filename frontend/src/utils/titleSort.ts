const LEADING_ARTICLE_RE = /^(?:the|a|an)\s+/i;
const DIGIT_RE = /\d+/g;

export function titleSortKey(title: string | null | undefined): string {
  const stripped = stripEdgeNonAlnum((title ?? "").trim());
  const withoutArticle = stripped.replace(LEADING_ARTICLE_RE, "");
  return withoutArticle
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim()
    .replace(DIGIT_RE, (match) => match.padStart(12, "0"));
}

export function compareTitles(left: string | null | undefined, right: string | null | undefined): number {
  return titleSortKey(left).localeCompare(titleSortKey(right)) || (left ?? "").localeCompare(right ?? "");
}

export function titleSortInitial(title: string | null | undefined): string {
  const key = titleSortKey(title);
  const first = key.match(/[a-z0-9]/i)?.[0] ?? "";
  if (!first) return "";
  return /\d/.test(first) ? "#" : first.toUpperCase();
}

function stripEdgeNonAlnum(value: string): string {
  const chars = Array.from(value);
  const start = chars.findIndex((char) => /[\p{L}\p{N}]/u.test(char));
  if (start === -1) return "";
  let end = chars.length;
  for (let index = chars.length - 1; index >= start; index -= 1) {
    if (/[\p{L}\p{N}]/u.test(chars[index])) {
      end = index + 1;
      break;
    }
  }
  return chars.slice(start, end).join("");
}
