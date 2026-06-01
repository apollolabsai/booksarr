from dataclasses import dataclass, field
from pathlib import Path
import shutil
import tempfile
import zipfile

from lxml import etree


OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
CALIBRE_NS = "http://calibre.kovidgoyal.net/2009/metadata"

NSMAP = {
    "opf": OPF_NS,
    "dc": DC_NS,
}


@dataclass
class OPFMetadata:
    title: str = ""
    author: str = ""
    author_sort: str = ""
    isbn: str = ""
    description: str = ""
    publisher: str = ""
    date: str = ""
    language: str = ""
    series: str = ""
    series_index: float | None = None
    calibre_id: int | None = None
    cover_href: str = ""
    subjects: list[str] = field(default_factory=list)


def parse_opf(opf_path: Path) -> OPFMetadata | None:
    try:
        tree = etree.parse(str(opf_path))
    except Exception:
        return None

    return _parse_opf_root(tree.getroot())


def parse_epub_opf(epub_path: Path) -> OPFMetadata | None:
    try:
        with zipfile.ZipFile(str(epub_path), "r") as zf:
            container = zf.read("META-INF/container.xml")
            container_root = etree.fromstring(container)
            rootfile = container_root.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
            opf_path = rootfile.get("full-path") if rootfile is not None else None
            if not opf_path:
                return None
            opf_data = zf.read(opf_path)
            opf_root = etree.fromstring(opf_data)
    except Exception:
        return None

    return _parse_opf_root(opf_root)


def write_epub_opf_metadata(epub_path: Path, values: dict[str, str | float | None]) -> tuple[OPFMetadata, Path]:
    backup_path = _next_backup_path(epub_path)
    shutil.copy2(epub_path, backup_path)

    with zipfile.ZipFile(str(epub_path), "r") as source_zip:
        container = source_zip.read("META-INF/container.xml")
        container_root = etree.fromstring(container)
        rootfile = container_root.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
        opf_path = rootfile.get("full-path") if rootfile is not None else None
        if not opf_path:
            raise ValueError("EPUB container does not reference an OPF file")

        opf_root = etree.fromstring(source_zip.read(opf_path))
        _update_opf_root(opf_root, values)
        updated_opf = etree.tostring(opf_root, encoding="utf-8", xml_declaration=True, pretty_print=True)

        temp_file = tempfile.NamedTemporaryFile(prefix=f"{epub_path.name}.", suffix=".tmp", dir=epub_path.parent, delete=False)
        temp_path = Path(temp_file.name)
        temp_file.close()

        try:
            with zipfile.ZipFile(str(temp_path), "w") as target_zip:
                for item in source_zip.infolist():
                    payload = updated_opf if item.filename == opf_path else source_zip.read(item.filename)
                    target_zip.writestr(item, payload)
            temp_path.replace(epub_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    parsed = parse_epub_opf(epub_path)
    if parsed is None:
        raise ValueError("Updated EPUB OPF metadata could not be parsed")
    return parsed, backup_path


def _parse_opf_root(root) -> OPFMetadata:
    meta = OPFMetadata()

    # Title
    el = root.find(f".//{{{DC_NS}}}title")
    if el is not None and el.text:
        meta.title = el.text.strip()

    # Author
    el = root.find(f".//{{{DC_NS}}}creator")
    if el is not None:
        if el.text:
            meta.author = el.text.strip()
        file_as = el.get(f"{{{OPF_NS}}}file-as", "")
        if file_as:
            meta.author_sort = file_as.strip()

    # ISBN - check all identifiers
    for ident in root.findall(f".//{{{DC_NS}}}identifier"):
        scheme = ident.get(f"{{{OPF_NS}}}scheme", "").upper()
        if scheme == "ISBN" and ident.text:
            meta.isbn = ident.text.strip()
            break

    # Calibre ID
    for ident in root.findall(f".//{{{DC_NS}}}identifier"):
        scheme = ident.get(f"{{{OPF_NS}}}scheme", "").lower()
        if scheme == "calibre" and ident.text:
            try:
                meta.calibre_id = int(ident.text.strip())
            except ValueError:
                pass
            break

    # Description
    el = root.find(f".//{{{DC_NS}}}description")
    if el is not None and el.text:
        meta.description = el.text.strip()

    # Publisher
    el = root.find(f".//{{{DC_NS}}}publisher")
    if el is not None and el.text:
        meta.publisher = el.text.strip()

    # Date
    el = root.find(f".//{{{DC_NS}}}date")
    if el is not None and el.text:
        meta.date = el.text.strip()

    # Language
    el = root.find(f".//{{{DC_NS}}}language")
    if el is not None and el.text:
        meta.language = el.text.strip()

    # Subjects
    for el in root.findall(f".//{{{DC_NS}}}subject"):
        if el.text:
            meta.subjects.append(el.text.strip())

    # Calibre series metadata
    for m in root.findall(".//{%s}metadata/meta" % OPF_NS):
        name = m.get("name", "")
        content = m.get("content", "")
        if name == "calibre:series" and content:
            meta.series = content
        elif name == "calibre:series_index" and content:
            try:
                meta.series_index = float(content)
            except ValueError:
                pass

    # Cover reference
    guide = root.find(f".//{{{OPF_NS}}}guide")
    if guide is not None:
        for ref in guide.findall(f"{{{OPF_NS}}}reference"):
            if ref.get("type") == "cover":
                meta.cover_href = ref.get("href", "")
                break

    return meta


def _next_backup_path(epub_path: Path) -> Path:
    backup_path = epub_path.with_name(f"{epub_path.name}.bak")
    if not backup_path.exists():
        return backup_path

    index = 1
    while True:
        candidate = epub_path.with_name(f"{epub_path.name}.bak.{index}")
        if not candidate.exists():
            return candidate
        index += 1


def _update_opf_root(root, values: dict[str, str | float | None]) -> None:
    metadata = root.find(f".//{{{OPF_NS}}}metadata")
    if metadata is None:
        metadata = root.find("metadata")
    if metadata is None:
        metadata = etree.SubElement(root, f"{{{OPF_NS}}}metadata")

    field_to_dc_tag = {
        "title": "title",
        "author_name": "creator",
        "isbn": "identifier",
        "publisher": "publisher",
        "description": "description",
        "release_date": "date",
        "language": "language",
    }

    for field_name, tag_name in field_to_dc_tag.items():
        if field_name not in values:
            continue
        value = _metadata_text(values[field_name])
        if not value:
            continue
        if field_name == "isbn":
            _set_isbn(metadata, value)
        else:
            _set_dc_text(metadata, tag_name, value)

    if "series_name" in values:
        value = _metadata_text(values["series_name"])
        if value:
            _set_meta_content(metadata, "calibre:series", value)
    if "series_position" in values:
        value = _metadata_text(values["series_position"])
        if value:
            _set_meta_content(metadata, "calibre:series_index", value)


def _metadata_text(value: str | float | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _find_dc_elements(metadata, tag_name: str):
    elements = metadata.findall(f".//{{{DC_NS}}}{tag_name}")
    elements.extend(metadata.findall(f".//dc:{tag_name}", namespaces={"dc": DC_NS}))
    return elements


def _set_dc_text(metadata, tag_name: str, value: str) -> None:
    elements = _find_dc_elements(metadata, tag_name)
    element = elements[0] if elements else etree.SubElement(metadata, f"{{{DC_NS}}}{tag_name}")
    element.text = value


def _set_isbn(metadata, value: str) -> None:
    identifiers = _find_dc_elements(metadata, "identifier")
    isbn_identifier = None
    for identifier in identifiers:
        scheme = (
            identifier.get(f"{{{OPF_NS}}}scheme")
            or identifier.get("scheme")
            or ""
        ).upper()
        if scheme == "ISBN":
            isbn_identifier = identifier
            break

    if isbn_identifier is None:
        isbn_identifier = etree.SubElement(metadata, f"{{{DC_NS}}}identifier")
        isbn_identifier.set(f"{{{OPF_NS}}}scheme", "ISBN")
        isbn_identifier.set("id", "booksarr-isbn")

    isbn_identifier.text = value


def _meta_elements(metadata):
    elements = metadata.findall(f".//{{{OPF_NS}}}meta")
    elements.extend(metadata.findall(".//meta"))
    return elements


def _set_meta_content(metadata, name: str, value: str) -> None:
    target = None
    for element in _meta_elements(metadata):
        if element.get("name") == name:
            target = element
            break

    if target is None:
        target = etree.SubElement(metadata, f"{{{OPF_NS}}}meta")
        target.set("name", name)

    target.set("content", value)
