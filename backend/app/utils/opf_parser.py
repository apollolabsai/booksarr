from dataclasses import dataclass, field
from pathlib import Path
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
