"""Extract supported document formats without treating binary files as prose."""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from threading import Lock
from zipfile import BadZipFile, ZipFile

import pypdfium2 as pdfium
from bs4 import BeautifulSoup
from defusedxml.ElementTree import fromstring
from defusedxml.common import DefusedXmlException
from striprtf.striprtf import rtf_to_text
from xml.etree.ElementTree import ParseError

MAX_TEXT_LENGTH = 60_000
MAX_ARCHIVE_BYTES = 48 * 1024 * 1024
MAX_XML_BYTES = 12 * 1024 * 1024
TEXT_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".tex", ".csv", ".json", ".log", ".xml"}
ALLOWED_EXTENSIONS = TEXT_EXTENSIONS | {".doc", ".docx", ".pdf", ".rtf", ".odt"}
WORD_NAMESPACES = {
    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}",
    "{http://purl.oclc.org/ooxml/wordprocessingml/main}",
}
ODT_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
ODT_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
PDFIUM_LOCK = Lock()


class DocumentError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def allowed_file(filename):
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def check_text_length(text):
    if len(text) > MAX_TEXT_LENGTH:
        raise DocumentError(f"Documents are limited to {MAX_TEXT_LENGTH:,} characters. Split the document and try again.", 413)
    return text


def decode_text(data):
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252")
    if any(ord(char) < 32 and char not in "\t\n\r\f" for char in text):
        raise DocumentError("The file contains binary data or uses an unsupported text encoding.")
    return text


def read_package(path, extension):
    with ZipFile(path) as package:
        entries = package.infolist()
        if len(entries) > 2_000 or sum(entry.file_size for entry in entries) > MAX_ARCHIVE_BYTES:
            raise DocumentError("The document archive exceeds the extraction limit.", 413)
        if extension == ".docx":
            return docx_text(package)
        if package.read("mimetype") != b"application/vnd.oasis.opendocument.text":
            raise DocumentError("The file is not an OpenDocument text document.")
        return odt_text(read_xml(package, "content.xml"))


def read_xml(package, name):
    if package.getinfo(name).file_size > MAX_XML_BYTES:
        raise DocumentError("A document section exceeds the extraction limit.", 413)
    return fromstring(package.read(name))


def preserve_link(label, target):
    if target.startswith(("https://", "http://")) and target not in label:
        return f"{label} ({target})" if label else target
    return label


def document_links(package, part):
    rels = f"word/_rels/{part}.xml.rels"
    if rels not in package.namelist():
        return {}
    return {
        node.get("Id"): node.get("Target", "")
        for node in read_xml(package, rels)
        if node.get("TargetMode") == "External" and node.get("Type", "").endswith("/hyperlink")
    }


def word_paragraph(paragraph, namespace, links):
    pieces = []
    for child in paragraph:
        if child.tag == namespace + "t":
            pieces.append(child.text or "")
        elif child.tag == namespace + "tab":
            pieces.append("\t")
        elif child.tag in {namespace + "br", namespace + "cr"}:
            pieces.append("\n")
        elif child.tag in {namespace + "footnoteReference", namespace + "endnoteReference"}:
            number = child.get(namespace + "id", "")
            if number.isdecimal():
                pieces.append(f"[{number}]")
        elif child.tag not in {namespace + "p", namespace + "del", namespace + "moveFrom"}:
            text = word_paragraph(child, namespace, links)
            if child.tag == namespace + "hyperlink":
                key = next((value for attr, value in child.attrib.items() if attr.endswith("/relationships}id")), None)
                text = preserve_link(text, links.get(key, ""))
            pieces.append(text)
    return "".join(pieces)


def docx_text(package):
    document = read_xml(package, "word/document.xml")
    namespace = document.tag.split("}")[0] + "}"
    body = document.find(namespace + "body")
    if namespace not in WORD_NAMESPACES or body is None:
        raise DocumentError("The file is not a Word text document.")
    links = document_links(package, "document")
    paragraphs = [word_paragraph(p, namespace, links) for p in body.iter(namespace + "p")]
    notes = []
    for kind in ("footnote", "endnote"):
        part = f"word/{kind}s.xml"
        if part not in package.namelist():
            continue
        root = read_xml(package, part)
        note_links = document_links(package, f"{kind}s")
        for note in root.iter(namespace + kind):
            number = note.get(namespace + "id", "")
            if not number.isdecimal() or note.get(namespace + "type"):
                continue
            content = "\n".join(word_paragraph(p, namespace, note_links) for p in note.iter(namespace + "p")).strip()
            if content:
                notes.append(f"[{number}] {content}")
    if notes:
        paragraphs.extend(["Notes", *notes])
    return "\n\n".join(paragraphs)


def odt_inline(element):
    if element.tag == ODT_TEXT + "s":
        spaces = int(element.get(ODT_TEXT + "c", "1"))
        return " " * max(1, min(MAX_TEXT_LENGTH + 1, spaces))
    if element.tag == ODT_TEXT + "tab":
        return "\t"
    if element.tag == ODT_TEXT + "line-break":
        return "\n"
    pieces = [element.text or ""]
    length = len(pieces[0])
    for child in element:
        child_text = odt_inline(child) + (child.tail or "")
        length += len(child_text)
        if length > MAX_TEXT_LENGTH:
            raise DocumentError("The ODT text exceeds the document limit.", 413)
        pieces.append(child_text)
    text = "".join(pieces)
    if element.tag == ODT_TEXT + "a":
        return preserve_link(text, element.get(XLINK_HREF, ""))
    return text


def odt_text(root):
    body = root.find(ODT_OFFICE + "body/" + ODT_OFFICE + "text")
    if body is None:
        raise DocumentError("The ODT file has no text document body.")
    paragraphs = []
    length = 0
    for element in body.iter():
        if element.tag in {ODT_TEXT + "p", ODT_TEXT + "h"}:
            paragraph = odt_inline(element)
            length += len(paragraph) + 2
            if length > MAX_TEXT_LENGTH + 2:
                raise DocumentError("The ODT text exceeds the document limit.", 413)
            paragraphs.append(paragraph)
    return "\n\n".join(paragraphs)


def legacy_word(path):
    with path.open("rb") as source:
        signature = source.read(8)
    if signature.startswith(b"{\\rtf"):
        return rtf_to_text(path.read_bytes().decode("latin-1"))
    if signature != bytes.fromhex("D0CF11E0A1B11AE1"):
        raise DocumentError("The file is not a supported legacy Word document.")
    program = shutil.which("antiword")
    if not program:
        raise DocumentError("Legacy DOC extraction requires Antiword. You can also save the document as DOCX.", 503)
    result = subprocess.run(
        [program, "-m", "UTF-8.txt", str(path)], capture_output=True, timeout=12, check=False,
    )
    if result.returncode:
        raise DocumentError("The DOC file could not be read. Save it as DOCX and try again.")
    return result.stdout.decode("utf-8")


def ocr_page(page, timeout):
    program = shutil.which("tesseract")
    if not program:
        raise DocumentError("Scanned PDF extraction requires Tesseract OCR on the server.", 503)
    if timeout <= 0:
        raise DocumentError("OCR exceeded the time limit. Split the scanned PDF and try again.")
    longest = max(page.get_width(), page.get_height(), 1)
    scale = min(250 / 72, 2_400 / longest)
    bitmap = page.render(scale=scale, grayscale=True)
    try:
        # Grayscale PDFium renders use one byte per pixel, with optional row padding.
        pixels = bytes(bitmap.buffer)
        raw = b"".join(
            pixels[row:row + bitmap.width] for row in range(0, len(pixels), bitmap.stride)
        )
        image = f"P5\n{bitmap.width} {bitmap.height}\n255\n".encode() + raw
    finally:
        bitmap.close()
    result = subprocess.run(
        [program, "stdin", "stdout", "-l", os.environ.get("EDUCHECK_OCR_LANG", "eng")],
        input=image, capture_output=True, timeout=min(10, timeout), check=False,
        env={**os.environ, "OMP_THREAD_LIMIT": "1"},
    )
    if result.returncode:
        raise DocumentError("OCR could not read a scanned page. Check the server OCR language configuration.")
    return result.stdout.decode("utf-8").strip()


def pdf_text(path):
    pages_text = []
    warnings = []
    scanned = 0
    length = 0
    deadline = time.monotonic() + 45
    with PDFIUM_LOCK, pdfium.PdfDocument(path) as pdf:
        if len(pdf) > 120:
            raise DocumentError("PDFs are limited to 120 pages. Split the document and try again.", 413)
        for index in range(len(pdf)):
            page = pdf[index]
            try:
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_bounded().strip()
                finally:
                    textpage.close()
                if len(text) < 100 and any(page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE])):
                    scanned += 1
                    if scanned > 20:
                        raise DocumentError("PDFs are limited to 20 scanned pages per upload.", 413)
                    recognized = ocr_page(page, deadline - time.monotonic())
                    if recognized:
                        text = recognized
                    else:
                        warnings.append(f"OCR found no readable text on page {index + 1}.")
                length += len(text) + 2
                if length > MAX_TEXT_LENGTH + 2:
                    raise DocumentError("The PDF text exceeds the document limit.", 413)
                pages_text.append(text)
            finally:
                page.close()
    return "\n\n".join(part for part in pages_text if part), {"ocr_pages": scanned, "warnings": warnings}


def extract_document(filepath, extension=None):
    path = Path(filepath)
    extension = extension or path.suffix.lower()
    metadata = {"ocr_pages": 0, "warnings": []}
    try:
        if extension == ".pdf":
            text, metadata = pdf_text(path)
        elif extension in {".docx", ".odt"}:
            text = read_package(path, extension)
        elif extension == ".doc":
            text = legacy_word(path)
        elif extension == ".rtf":
            content = path.read_bytes().decode("latin-1")
            if not content.lstrip().startswith("{\\rtf"):
                raise DocumentError("The file is not a valid RTF document.")
            text = rtf_to_text(content)
        elif extension in TEXT_EXTENSIONS:
            text = decode_text(path.read_bytes())
            if extension in {".html", ".htm"}:
                soup = BeautifulSoup(text, "html.parser")
                for element in soup(["script", "style", "template", "noscript"]):
                    element.decompose()
                for anchor in soup.find_all("a", href=True):
                    anchor.replace_with(preserve_link(anchor.get_text(" ", strip=True), anchor["href"]))
                text = (soup.body or soup).get_text(separator="\n", strip=True)
        else:
            raise DocumentError("Unsupported document format.", 415)
    except subprocess.TimeoutExpired as error:
        raise DocumentError("Document extraction timed out. Split the file and try again.") from error
    except (BadZipFile, DefusedXmlException, ParseError, pdfium.PdfiumError, UnicodeError,
            KeyError, ValueError, RecursionError, OSError) as error:
        raise DocumentError("The file could not be read. Check its format and remove any password protection.") from error

    text = text.strip().replace("\r\n", "\n").replace("\r", "\n")
    if not text:
        raise DocumentError("No readable text was found in the document.")
    return check_text_length(text), metadata


def extract_text_from_file(filepath):
    return extract_document(filepath)[0]
