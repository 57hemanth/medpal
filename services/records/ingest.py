"""Record extraction and chunking.

The first implementation is intentionally conservative: text uploads are indexed immediately, PDFs
without an extractor/OCR adapter are parked for review with a reason code and no document text in logs.
"""

from dataclasses import dataclass

from services.platform.phi.scrubber import BlockedIdentifier, assert_clean, tokenise

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
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


def validate_upload(content: bytes, content_type: str) -> None:
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadRejected("file_too_large")
    if content_type not in SUPPORTED_TYPES:
        raise UploadRejected("unsupported_type")
    try:
        tokenised = tokenise(content.decode("utf-8", errors="ignore"))
    except BlockedIdentifier as exc:
        raise UploadRejected("blocked_identifier") from exc
    assert_clean(tokenised.text)


def extract_text(content: bytes, content_type: str) -> ExtractedText:
    if content_type == "text/plain":
        return ExtractedText(text=content.decode("utf-8"), status="ready")
    return ExtractedText(text=None, status="needs_review", error="ocr_unavailable")


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
