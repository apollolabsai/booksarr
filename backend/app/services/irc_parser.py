import re
import zipfile
from pathlib import Path


RESULT_ARCHIVE_PREFIX = "SearchBot_results_for_"


def normalize_query_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def normalize_query_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def build_search_command(query_text: str) -> str:
    return f"@search {normalize_query_text(query_text)}"


def build_expected_result_filename(query_text: str) -> str:
    query = normalize_query_text(query_text)
    return f"{RESULT_ARCHIVE_PREFIX}{query}.txt.zip"


def result_archive_matches_query(filename: str, query_text: str) -> bool:
    normalized_query = normalize_query_key(query_text)
    normalized_filename = normalize_query_key(filename)
    if not normalized_query or not normalized_filename:
        return False

    query_tokens = [token for token in normalized_query.split() if token]
    return all(token in normalized_filename for token in query_tokens)


def command_matches_filename(command_text: str, filename: str) -> bool:
    normalized_command = normalize_query_key(command_text)
    normalized_filename = normalize_query_key(Path(filename).name)
    if not normalized_command or not normalized_filename:
        return False

    filename_tokens = [token for token in normalized_filename.split() if token]
    command_tokens = set(token for token in normalized_command.split() if token)
    return all(token in command_tokens for token in filename_tokens)


def parse_search_result_line(raw_line: str) -> dict[str, str | None] | None:
    line = raw_line.strip()
    if not line.startswith("!"):
        return None

    command = line.split("::INFO::", 1)[0].split("::HASH::", 1)[0].strip()
    if not command or not command.startswith("!"):
        return None

    info_match = re.search(r"::INFO::\s*([^:]+?)(?:\s+::HASH::.*)?$", line)
    size_text = info_match.group(1).strip() if info_match else None

    command_body = command[1:]
    if " " in command_body:
        bot_name, remainder = command_body.split(" ", 1)
    else:
        bot_name, remainder = command_body, ""

    display_name = remainder.strip()
    if " | " in display_name:
        display_name = display_name.split(" | ", 1)[1].strip()
    elif " " in display_name:
        first_token, rest = display_name.split(" ", 1)
        if " - " in rest and re.fullmatch(r"[%A-Za-z0-9/+=_.-]{6,}", first_token):
            display_name = rest.strip()
    elif " - " in display_name:
        first_segment, rest = display_name.split(" - ", 1)
        if re.fullmatch(r"[A-Za-z0-9/+=_.-]{6,}", first_segment):
            display_name = rest.strip()

    display_name = display_name.lstrip("- ").strip()

    file_format = None
    filename_match = re.search(r"\.([A-Za-z0-9]{2,6})$", command)
    if filename_match:
        file_format = filename_match.group(1).lower()

    normalized_author = None
    normalized_title = None
    candidate_text = display_name
    candidate_text = re.sub(r"\.[A-Za-z0-9]{2,6}$", "", candidate_text)
    if " - " in candidate_text:
        author_part, title_part = candidate_text.split(" - ", 1)
        normalized_author = normalize_query_text(author_part)
        normalized_title = normalize_query_text(title_part)
    elif candidate_text:
        normalized_title = normalize_query_text(candidate_text)

    return {
        "raw_line": line,
        "download_command": command,
        "bot_name": bot_name or None,
        "display_name": display_name or command,
        "file_format": file_format,
        "file_size_text": size_text,
        "normalized_author": normalized_author,
        "normalized_title": normalized_title,
    }


def parse_search_results_text(text: str) -> list[dict[str, str | None]]:
    results: list[dict[str, str | None]] = []
    for line in text.splitlines():
        parsed = parse_search_result_line(line)
        if parsed:
            results.append(parsed)
    return results


def parse_search_results_archive(archive_path: Path, extract_dir: Path) -> tuple[Path, list[dict[str, str | None]]]:
    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path) as archive:
        text_members = [member for member in archive.namelist() if member.lower().endswith(".txt")]
        if not text_members:
            raise ValueError("Search results archive did not contain a .txt file")

        first_text = text_members[0]
        extracted_path = Path(archive.extract(first_text, path=extract_dir))
        text = extracted_path.read_text(encoding="utf-8", errors="replace")

    return extracted_path, parse_search_results_text(text)
