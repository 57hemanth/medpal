"""Bounded, in-boundary PDF extraction and OCR with page-preserving citations."""

import shutil
import subprocess
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from services.platform.phi.scrubber import BlockedIdentifier, assert_clean, tokenise

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_PAGES = 40
MAX_TEXT_CHARS = 500_000
SUPPORTED_TYPES = frozenset({"text/plain", "application/pdf"})


class UploadRejected(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ExtractedText:
    text: str | None
    status: str
    error: str | None = None
    pages: tuple[str, ...] = ()


def _ocr_page(content: bytes, page: int) -> str:
    # Only local binaries see the PDF. The private temporary directory is removed on all paths.
    renderer, recognizer = shutil.which("pdftoppm"), shutil.which("tesseract")
    if not renderer or not recognizer:
        raise FileNotFoundError("local OCR tools are unavailable")
    with TemporaryDirectory(prefix="medpal-ocr-") as directory:
        source = Path(directory) / "record.pdf"
        source.write_bytes(content)
        output = Path(directory) / "page"
        subprocess.run(  # noqa: S603
            [
                renderer,
                "-f",
                str(page),
                "-l",
                str(page),
                "-scale-to",
                "2400",
                "-singlefile",
                "-png",
                str(source),
                str(output),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        result = subprocess.run(  # noqa: S603
            [recognizer, str(output.with_suffix(".png")), "stdout", "-l", "eng+hin"],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return result.stdout.decode("utf-8")


def extract_text(content: bytes, content_type: str) -> ExtractedText:
    try:
        if content_type == "text/plain":
            pages = [content.decode("utf-8")]
        else:
            reader = PdfReader(BytesIO(content))
            if reader.is_encrypted:
                return ExtractedText(None, "needs_review", "encrypted_pdf")
            if len(reader.pages) > MAX_PAGES:
                raise UploadRejected("too_many_pages")
            pages = []
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                if not text.strip():
                    try:
                        text = _ocr_page(content, number)
                    except (OSError, subprocess.SubprocessError):
                        return ExtractedText(None, "needs_review", "ocr_unavailable")
                pages.append(text)
                if sum(map(len, pages)) > MAX_TEXT_CHARS:
                    raise UploadRejected("extracted_text_too_large")
        if sum(map(len, pages)) > MAX_TEXT_CHARS:
            raise UploadRejected("extracted_text_too_large")
        if not pages or not all(page.strip() for page in pages):
            return ExtractedText(None, "needs_review", "empty_document")
        return ExtractedText("\n\n".join(pages), "ready", pages=tuple(pages))
    except (PdfReadError, UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, UploadRejected):
            raise
        return ExtractedText(None, "needs_review", "invalid_document")


def validate_upload(content: bytes, content_type: str) -> None:
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadRejected("file_too_large")
    if content_type not in SUPPORTED_TYPES:
        raise UploadRejected("unsupported_type")
    effective_type = "application/pdf" if content.startswith(b"%PDF") else content_type
    extracted = extract_text(content, effective_type)
    # Unreadable files cannot be checked for blocked identifiers, so never persist them.
    if extracted.text is None:
        raise UploadRejected(extracted.error or "extraction_failed")
    try:
        tokenised = tokenise(extracted.text)
    except BlockedIdentifier as exc:
        raise UploadRejected("blocked_identifier") from exc
    assert_clean(tokenised.text)


def chunk_text(text: str, *, target_chars: int = 1200) -> list[str]:
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs or [text.strip()]:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= target_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = paragraph
    if current:
        chunks.append(current)
    return chunks
