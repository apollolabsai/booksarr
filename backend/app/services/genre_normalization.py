import re
import unicodedata
from collections.abc import Iterable


_BISAC_CODE_RE = re.compile(r"^[A-Z]{3}\d{6}$")
_NON_GENRE_EXACT = {
    "all",
    "allon",
    "anthology",
    "audiobook",
    "audiobooks",
    "audio book",
    "audio books",
    "book",
    "books",
    "ebook",
    "ebooks",
    "etc",
    "fiction",
    "format",
    "general",
    "kindle",
    "literature",
    "nonfiction",
    "novel",
    "novels",
    "read",
    "reading",
    "story",
    "stories",
}
_FORMAT_EXACT = {
    "comic",
    "comic book",
    "comic books",
    "comics",
}


_CANONICAL_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Science Fiction", (
        r"\bscience fiction\b",
        r"\bsci fi\b",
        r"\bscifi\b",
        r"\bsf\b",
        r"\bspace opera\b",
        r"\bcyberpunk\b",
        r"\bdystopian\b",
        r"\bpost apocalyptic\b",
        r"\bapocalyptic\b",
    )),
    ("Historical Fiction", (
        r"\bhistorical fiction\b",
        r"\bhistorical novels?\b",
        r"\bhistorical stories\b",
    )),
    ("Young Adult", (
        r"\byoung adult\b",
        r"\bteen fiction\b",
        r"\bya fiction\b",
    )),
    ("Children's", (
        r"\bchildren s\b",
        r"\bchildrens\b",
        r"\bjuvenile literature\b",
        r"\bjuvenile\b",
        r"\bmiddle grade\b",
        r"\bpicture books?\b",
    )),
    ("Comics & Graphic Novels", (
        r"\bcomics and graphic novels\b",
        r"\bgraphic novels?\b",
        r"\bmanga\b",
    )),
    ("True Crime", (
        r"\btrue crime\b",
    )),
    ("Short Stories", (
        r"\bshort stories\b",
        r"\bshort story\b",
        r"\bshort fiction\b",
    )),
    ("Self-Help", (
        r"\bself help\b",
        r"\bself improvement\b",
        r"\bpersonal development\b",
    )),
    ("Cookbook", (
        r"\bcookbooks?\b",
        r"\bcooking\b",
        r"\bfood\b",
    )),
    ("Literary Fiction", (
        r"\bliterary fiction\b",
        r"\bliterary\b",
    )),
    ("Mystery", (
        r"\bmystery\b",
        r"\bmysteries\b",
        r"\bdetective and mystery\b",
        r"\bdetective stories\b",
        r"\bcozy mysteries\b",
        r"\bcosy mysteries\b",
    )),
    ("Thriller", (
        r"\bthrillers?\b",
        r"\bthriller fiction\b",
        r"\bsuspense\b",
        r"\bspy stories\b",
        r"\bspy fiction\b",
        r"\bpsychological fiction\b",
    )),
    ("Fantasy", (
        r"\bfantasy\b",
        r"\bparanormal\b",
        r"\burban fantasy\b",
        r"\bepic fantasy\b",
        r"\bsupernatural\b",
    )),
    ("Romance", (
        r"\bromance\b",
        r"\bromantic\b",
        r"\blove stories\b",
    )),
    ("Horror", (
        r"\bhorror\b",
        r"\bghost stories\b",
        r"\boccult fiction\b",
    )),
    ("Crime", (
        r"\bcrime\b",
        r"\bnoir\b",
        r"\bpolice procedural\b",
    )),
    ("War", (
        r"\bwar\b",
        r"\bmilitary fiction\b",
    )),
    ("Adventure", (
        r"\badventure\b",
        r"\baction and adventure\b",
    )),
    ("Western", (
        r"\bwestern\b",
        r"\bwesterns\b",
    )),
    ("Drama", (
        r"\bdrama\b",
        r"\bplays\b",
        r"\btheater\b",
        r"\btheatre\b",
    )),
    ("Humor", (
        r"\bhumou?r\b",
        r"\bhumorous\b",
        r"\bcomedy\b",
        r"\bsatire\b",
    )),
    ("Poetry", (
        r"\bpoetry\b",
        r"\bpoems?\b",
    )),
    ("Biography", (
        r"\bbiograph",
        r"\bautobiograph",
        r"\bmemoirs?\b",
    )),
    ("History", (
        r"\bhistory\b",
        r"\bhistorical\b",
    )),
    ("Philosophy", (
        r"\bphilosophy\b",
        r"\bethics\b",
    )),
    ("Religion", (
        r"\breligion\b",
        r"\breligious\b",
        r"\bchristian\b",
        r"\bspirituality\b",
        r"\btheology\b",
        r"\bbible\b",
    )),
    ("Science", (
        r"\bscience\b",
        r"\bphysics\b",
        r"\bbiology\b",
        r"\bchemistry\b",
        r"\bmathematics\b",
        r"\bmath\b",
        r"\bnature\b",
    )),
    ("Technology", (
        r"\btechnology\b",
        r"\bcomputers?\b",
        r"\bprogramming\b",
        r"\bsoftware\b",
    )),
    ("Business", (
        r"\bbusiness\b",
        r"\beconomics\b",
        r"\bfinance\b",
        r"\bmanagement\b",
        r"\bentrepreneurship\b",
    )),
    ("Travel", (
        r"\btravel\b",
    )),
    ("Art", (
        r"\bart\b",
        r"\barchitecture\b",
        r"\bdesign\b",
        r"\bphotography\b",
    )),
    ("Music", (
        r"\bmusic\b",
        r"\bmusicians?\b",
    )),
    ("Sports", (
        r"\bsports?\b",
        r"\bbaseball\b",
        r"\bbasketball\b",
        r"\bfootball\b",
        r"\bsoccer\b",
        r"\bgolf\b",
    )),
    ("Politics", (
        r"\bpolitics\b",
        r"\bpolitical\b",
        r"\bgovernment\b",
        r"\bpublic policy\b",
    )),
    ("Education", (
        r"\beducation\b",
        r"\bteaching\b",
        r"\bschools?\b",
    )),
    ("Reference", (
        r"\breference\b",
        r"\bdictionaries\b",
        r"\bencyclopedias\b",
        r"\bmanuals?\b",
        r"\bhandbooks?\b",
    )),
)


def normalize_genres(raw_genres: Iterable[object]) -> list[str]:
    genres: list[str] = []
    seen: set[str] = set()
    for raw_genre in raw_genres:
        genre = normalize_genre(raw_genre)
        if genre is None:
            continue
        key = genre.casefold()
        if key in seen:
            continue
        seen.add(key)
        genres.append(genre)
    return genres


def normalize_genre(raw_genre: object) -> str | None:
    if not isinstance(raw_genre, str):
        return None

    genre = unicodedata.normalize("NFKC", raw_genre).strip()
    genre = re.sub(r"\s+", " ", genre)
    if not genre:
        return None

    if "(fictitious character)" in genre.casefold():
        return None
    if _BISAC_CODE_RE.fullmatch(genre):
        return None
    if "/" in genre or ":" in genre:
        return None
    if _contains_non_latin_letters(genre):
        return None

    key = _match_key(genre)
    if key in _NON_GENRE_EXACT or key in _FORMAT_EXACT:
        return None

    for canonical, patterns in _CANONICAL_RULES:
        if any(re.search(pattern, key) for pattern in patterns):
            return canonical

    return None


def _match_key(value: str) -> str:
    value = value.replace("&", " and ")
    value = value.replace("’", "'")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _contains_non_latin_letters(value: str) -> bool:
    return any(ord(char) > 127 and unicodedata.category(char).startswith("L") for char in value)
