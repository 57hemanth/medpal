import pytest

from services.platform.phi.recognizers import verhoeff_check_digit
from services.records.ingest import UploadRejected, chunk_text, extract_text, validate_upload


def test_text_upload_extracts_and_chunks_without_local_files():
    content = b"LDL 162 mg/dL\n\nHbA1c 6.8 percent"

    validate_upload(content, "text/plain")
    extracted = extract_text(content, "text/plain")

    assert extracted.status == "ready"
    assert extracted.text == "LDL 162 mg/dL\n\nHbA1c 6.8 percent"
    assert chunk_text(extracted.text) == ["LDL 162 mg/dL\n\nHbA1c 6.8 percent"]


def test_pdf_without_extractor_is_parked_for_review():
    extracted = extract_text(b"%PDF-1.7", "application/pdf")

    assert extracted.status == "needs_review"
    assert extracted.error == "ocr_unavailable"
    assert extracted.text is None


@pytest.mark.parametrize("content_type", ["image/png", "application/octet-stream"])
def test_upload_rejects_unsupported_types(content_type):
    with pytest.raises(UploadRejected, match="unsupported_type"):
        validate_upload(b"x", content_type)


def test_upload_blocks_aadhaar_before_storage():
    aadhaar = "23412341234" + verhoeff_check_digit("23412341234")
    with pytest.raises(UploadRejected, match="blocked_identifier"):
        validate_upload(f"My Aadhaar is {aadhaar}".encode(), "text/plain")
