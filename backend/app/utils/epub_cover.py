"""Extract cover images from EPUB files."""
import logging
import struct
import zipfile
from pathlib import Path

from lxml import etree

logger = logging.getLogger("booksarr.images")

# OPF namespaces
OPF_NS = "http://www.idpf.org/2007/opf"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"

# Common cover image filenames to try as last resort
COVER_CANDIDATES = [
    "cover.jpg", "cover.jpeg", "cover.png",
    "images/cover.jpg", "images/cover.jpeg", "images/cover.png",
    "Images/cover.jpg", "Images/cover.jpeg", "Images/cover.png",
    "OEBPS/cover.jpg", "OEBPS/images/cover.jpg",
    "OEBPS/Images/cover.jpg",
]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def extract_cover(epub_path: Path) -> bytes | None:
    """Extract the cover image from an EPUB file.

    Tries multiple strategies:
    1. OPF manifest item with properties="cover-image"
    2. OPF <meta name="cover"> pointing to a manifest item
    3. Common cover filenames in the ZIP
    4. Largest image file in the EPUB (likely the cover)

    Returns the raw image bytes, or None if no cover found.
    """
    if not epub_path.exists():
        return None

    try:
        with zipfile.ZipFile(str(epub_path), "r") as zf:
            # Find the OPF file path from container.xml
            opf_path = _find_opf_path(zf)

            if opf_path:
                # Strategy 1: cover-image property in manifest
                cover = _extract_by_cover_property(zf, opf_path)
                if cover:
                    return cover

                # Strategy 2: <meta name="cover"> reference
                cover = _extract_by_meta_cover(zf, opf_path)
                if cover:
                    return cover

            # Strategy 3: Common filenames
            names_lower = {n.lower(): n for n in zf.namelist()}
            for candidate in COVER_CANDIDATES:
                real_name = names_lower.get(candidate.lower())
                if real_name:
                    data = zf.read(real_name)
                    if len(data) > 1000:  # skip tiny placeholders
                        return data

            # Strategy 4: Largest image file
            return _extract_largest_image(zf)

    except (zipfile.BadZipFile, Exception) as e:
        logger.debug("Failed to extract cover from %s: %s", epub_path.name, e)
        return None


def _find_opf_path(zf: zipfile.ZipFile) -> str | None:
    """Find the OPF file path from META-INF/container.xml."""
    try:
        container = zf.read("META-INF/container.xml")
        root = etree.fromstring(container)
        rootfile = root.find(f".//{{{CONTAINER_NS}}}rootfile")
        if rootfile is not None:
            return rootfile.get("full-path")
    except Exception:
        pass

    # Fallback: look for any .opf file
    for name in zf.namelist():
        if name.endswith(".opf"):
            return name
    return None


def _extract_by_cover_property(zf: zipfile.ZipFile, opf_path: str) -> bytes | None:
    """Find cover via manifest item with properties='cover-image'."""
    try:
        opf_data = zf.read(opf_path)
        root = etree.fromstring(opf_data)
        opf_dir = str(Path(opf_path).parent)

        for item in root.findall(f".//{{{OPF_NS}}}item"):
            props = item.get("properties", "")
            if "cover-image" in props:
                href = item.get("href", "")
                if href:
                    full_path = f"{opf_dir}/{href}" if opf_dir != "." else href
                    return _read_from_zip(zf, full_path)
    except Exception:
        pass
    return None


def _extract_by_meta_cover(zf: zipfile.ZipFile, opf_path: str) -> bytes | None:
    """Find cover via <meta name='cover' content='item-id'>."""
    try:
        opf_data = zf.read(opf_path)
        root = etree.fromstring(opf_data)
        opf_dir = str(Path(opf_path).parent)

        # Find the cover item ID
        cover_id = None
        for meta in root.findall(f".//{{{OPF_NS}}}metadata/meta"):
            if meta.get("name") == "cover":
                cover_id = meta.get("content")
                break
        # Also check without namespace
        for meta in root.findall(".//meta"):
            if meta.get("name") == "cover":
                cover_id = meta.get("content")
                break

        if not cover_id:
            return None

        # Find the manifest item with this ID
        for item in root.findall(f".//{{{OPF_NS}}}item"):
            if item.get("id") == cover_id:
                href = item.get("href", "")
                if href:
                    full_path = f"{opf_dir}/{href}" if opf_dir != "." else href
                    return _read_from_zip(zf, full_path)
    except Exception:
        pass
    return None


def _extract_largest_image(zf: zipfile.ZipFile) -> bytes | None:
    """Fallback: return the largest image file in the EPUB."""
    best_name = None
    best_size = 0
    for info in zf.infolist():
        ext = Path(info.filename).suffix.lower()
        if ext in IMAGE_EXTENSIONS and info.file_size > best_size:
            best_size = info.file_size
            best_name = info.filename

    if best_name and best_size > 1000:
        return zf.read(best_name)
    return None


def _read_from_zip(zf: zipfile.ZipFile, path: str) -> bytes | None:
    """Read a file from the ZIP, trying exact path and case-insensitive fallback."""
    try:
        return zf.read(path)
    except KeyError:
        # Case-insensitive fallback
        path_lower = path.lower()
        for name in zf.namelist():
            if name.lower() == path_lower:
                return zf.read(name)
    return None


def get_image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Get width x height of a JPEG or PNG image from raw bytes."""
    if not data or len(data) < 24:
        return None

    # PNG: 8-byte signature, then IHDR chunk with width/height at bytes 16-23
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        try:
            width, height = struct.unpack(">II", data[16:24])
            return (width, height)
        except struct.error:
            return None

    # JPEG: scan for SOF0/SOF2 marker
    if data[:2] == b"\xff\xd8":
        try:
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                    height, width = struct.unpack(">HH", data[i + 5:i + 9])
                    return (width, height)
                elif marker == 0xD9:
                    break
                elif marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0x01):
                    i += 2
                else:
                    length = struct.unpack(">H", data[i + 2:i + 4])[0]
                    i += 2 + length
        except (struct.error, IndexError):
            return None

    return None
