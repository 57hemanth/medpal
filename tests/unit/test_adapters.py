from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from services.platform.config import Settings
from services.platform.phi.recognizers import verhoeff_check_digit
from services.records import ingest
from services.records.storage import FileObjectStore, S3ObjectStore
from services.scribe import speech


def pdf_bytes(texts):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 10 700 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {
                        NameObject("/F1"): writer._add_object(
                            DictionaryObject(
                                {
                                    NameObject("/Type"): NameObject("/Font"),
                                    NameObject("/Subtype"): NameObject("/Type1"),
                                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                                }
                            )
                        )
                    }
                )
            }
        )
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_pages_and_ocr_keep_citation_page_numbers(monkeypatch):
    ocr = Mock(return_value="HbA1c 6.8 percent")
    monkeypatch.setattr(ingest, "_ocr_page", ocr)
    content = pdf_bytes(["LDL 162 mg/dL", ""])
    extracted = ingest.extract_text(content, "application/pdf")
    assert extracted.status == "ready"
    assert len(extracted.pages) == 2
    assert "LDL 162" in extracted.pages[0]
    assert "HbA1c 6.8" in extracted.pages[1]
    ocr.assert_called_once_with(content, 2)


def test_pdf_identifier_is_blocked_after_extraction():
    aadhaar = "23412341234" + verhoeff_check_digit("23412341234")
    with pytest.raises(ingest.UploadRejected, match="blocked_identifier"):
        ingest.validate_upload(pdf_bytes([f"Aadhaar {aadhaar}"]), "application/pdf")


def test_unreadable_scan_is_never_accepted_for_storage(monkeypatch):
    monkeypatch.setattr(ingest, "_ocr_page", Mock(side_effect=FileNotFoundError))
    with pytest.raises(ingest.UploadRejected, match="ocr_unavailable"):
        ingest.validate_upload(pdf_bytes([""]), "application/pdf")


async def test_file_storage_survives_recreation_and_rejects_cross_bucket_reads(tmp_path):
    uri = await FileObjectStore(tmp_path).put("patients/test/record", b"clinical text", "text/plain")
    assert await FileObjectStore(tmp_path).get(uri) == b"clinical text"
    for bad in ["s3://other/key", "s3://medpal-records/../secret", "s3://medpal-records//absolute"]:
        with pytest.raises(ValueError):
            await FileObjectStore(tmp_path).get(bad)


async def test_s3_encryption_and_response_body_cleanup():
    client = Mock()
    body = BytesIO(b"record")
    client.get_object.return_value = {"Body": body}
    store = S3ObjectStore(client, "private-records")
    uri = await store.put("key", b"record", "application/pdf")
    assert client.put_object.call_args.kwargs["ServerSideEncryption"] == "AES256"
    assert await store.get(uri) == b"record"
    assert body.closed
    with pytest.raises(ValueError):
        await store.get("s3://another-bucket/key")
    assert client.get_object.call_count == 1


def wav_bytes():
    import wave

    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        handle.writeframes(b"\x00\x00" * 16000)
    return buffer.getvalue()


async def test_local_speech_uses_in_memory_audio(monkeypatch):
    model = Mock()
    model.transcribe.return_value = ([SimpleNamespace(text=" Review this transcript. ")], None)
    monkeypatch.setattr(speech, "_model", lambda path: model)
    result = await speech.LocalSpeechTranscriber("/local/model").transcribe(wav_bytes())
    assert result == "Review this transcript."
    assert isinstance(model.transcribe.call_args.args[0], BytesIO)


async def test_speech_rejects_invalid_audio_and_unconfigured_model():
    transcriber = speech.LocalSpeechTranscriber(None)
    with pytest.raises(ValueError):
        await transcriber.transcribe(b"not audio")
    with pytest.raises(speech.SpeechUnavailable):
        await transcriber.transcribe(wav_bytes())


def test_production_rejects_non_persistent_storage():
    with pytest.raises(ValueError, match="object_store_backend=s3"):
        Settings(env="prod", auth_mode="oidc", chat_provider="openai", object_store_backend="memory")


async def test_audio_endpoint_is_doctor_only_and_streams_without_multipart_storage():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from services.api.routers.scribe import router

    app = FastAPI()
    app.include_router(router)
    transcriber = Mock()

    async def transcribe(content):
        assert content == b"raw wav bytes"
        return "review transcript"

    transcriber.transcribe = transcribe
    app.state.speech_transcriber = transcriber
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        headers = {"X-Dev-User-Id": "test-doctor", "X-Dev-Role": "doctor", "content-type": "audio/wav"}
        response = await client.post("/api/scribe/transcribe", headers=headers, content=b"raw wav bytes")
        assert response.status_code == 200
        assert response.json() == {"transcript": "review transcript"}
        headers["X-Dev-Role"] = "desk"
        response = await client.post("/api/scribe/transcribe", headers=headers, content=b"raw wav bytes")
        assert response.status_code == 403
