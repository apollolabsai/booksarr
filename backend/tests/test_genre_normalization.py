from backend.app.services.genre_normalization import normalize_genre, normalize_genres


def test_normalize_genres_collapses_common_variants():
    assert normalize_genres([
        "Adventure",
        "Adventure fiction",
        "Adventure stories",
        "Science fiction",
        "Sci-Fi",
        "Detective and mystery stories",
        "Mystery",
    ]) == ["Adventure", "Science Fiction", "Mystery"]


def test_normalize_genres_drops_subject_code_language_and_format_noise():
    assert normalize_genres([
        "FIC009020",
        "General",
        "Etc",
        "Allon",
        "Sherlock Holmes (Fictitious character)",
        "Fantasy / Epic",
        "Subject: Junk",
        "Audiobook",
        "Comics",
        "Ciencia ficción",
        "冒険",
        "",
        42,
        None,
    ]) == []


def test_normalize_genres_maps_only_supported_comics_terms():
    assert normalize_genre("Comics") is None
    assert normalize_genre("Graphic Novel") == "Comics & Graphic Novels"
    assert normalize_genre("Comics & Graphic Novels") == "Comics & Graphic Novels"


def test_normalize_genres_keeps_canonical_taxonomy_order_and_dedupes():
    assert normalize_genres([
        "Historical Fiction",
        "History",
        "Young adult fiction",
        "Juvenile fiction",
        "Biography",
        "Memoir",
        "Self improvement",
        "Self-Help",
    ]) == [
        "Historical Fiction",
        "History",
        "Young Adult",
        "Children's",
        "Biography",
        "Self-Help",
    ]
