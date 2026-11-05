"""Synthetic lab reports for the demo identities, loaded by `make seed` through the real upload path.

Every value and name is invented. The reports go through the same validation, privacy scan, storage and
indexing as a patient's upload, so the records page, cited answers and the caregiver view all work after
a fresh seed.
"""

from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

# (title, lab line, sections of (heading, rows of (test, result, reference)))
Report = tuple[str, str, list[tuple[str, list[tuple[str, str, str]]]]]

ASHA_ANNUAL_CHECK: Report = (
    "Annual health check",
    "Sunrise Diagnostics, Baner, Pune  |  Collected 12 Oct 2026, fasting  |  Synthetic demo report",
    [
        (
            "Lipid profile",
            [
                ("Total cholesterol", "238 mg/dL  HIGH", "below 200"),
                ("LDL cholesterol", "162 mg/dL  HIGH", "below 100"),
                ("HDL cholesterol", "41 mg/dL  LOW", "above 50"),
                ("Triglycerides", "175 mg/dL  HIGH", "below 150"),
            ],
        ),
        (
            "Diabetes panel",
            [
                ("HbA1c", "6.8 percent  HIGH", "below 5.7"),
                ("Fasting plasma glucose", "126 mg/dL  HIGH", "70 to 99"),
            ],
        ),
        (
            "Thyroid and vitamins",
            [
                ("TSH", "5.9 mIU/L  HIGH", "0.4 to 4.0"),
                ("Vitamin D (25-OH)", "18 ng/mL  LOW", "30 to 100"),
                ("Vitamin B12", "410 pg/mL", "200 to 900"),
            ],
        ),
    ],
)

LATA_BLOOD_AND_KIDNEY: Report = (
    "Blood count and kidney function",
    "Sunrise Diagnostics, Aundh, Pune  |  Collected 28 Oct 2026  |  Synthetic demo report",
    [
        (
            "Complete blood count",
            [
                ("Haemoglobin", "10.9 g/dL  LOW", "12.0 to 15.0"),
                ("White cell count", "7,200 per microlitre", "4,000 to 11,000"),
                ("Platelets", "2.4 lakh per microlitre", "1.5 to 4.0 lakh"),
            ],
        ),
        (
            "Kidney function",
            [
                ("Creatinine", "1.1 mg/dL", "0.6 to 1.1"),
                ("eGFR", "68 mL/min/1.73m2  LOW", "above 90"),
                ("Urea", "34 mg/dL", "15 to 40"),
            ],
        ),
    ],
)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def report_pdf(report: Report) -> bytes:
    """A one-page-per-section PDF with a real text layer (so it is indexed and cited by page)."""
    title, lab, sections = report
    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    bold = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica-Bold"),
            }
        )
    )
    for page_number, (heading, rows) in enumerate(sections, start=1):
        lines = [
            f"BT /F2 18 Tf 50 740 Td ({_escape(title)}) Tj ET",
            f"BT /F1 10 Tf 50 720 Td ({_escape(lab)}) Tj ET",
            f"BT /F2 14 Tf 50 680 Td ({_escape(heading)}) Tj ET",
            "BT /F2 10 Tf 50 655 Td (Test) Tj 200 0 Td (Result) Tj 170 0 Td (Reference range) Tj ET",
        ]
        y = 635
        for test, result, reference in rows:
            lines.append(
                f"BT /F1 11 Tf 50 {y} Td ({_escape(test)}) Tj 200 0 Td ({_escape(result)}) Tj"
                f" 170 0 Td ({_escape(reference)}) Tj ET"
            )
            y -= 22
        lines.append(
            f"BT /F1 9 Tf 50 60 Td (Page {page_number} of {len(sections)}. Results are for your doctor to"
            " interpret. Synthetic data, not a real person.) Tj ET"
        )
        page = writer.add_blank_page(width=612, height=792)
        stream = DecodedStreamObject()
        stream.set_data("\n".join(lines).encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font, NameObject("/F2"): bold})}
        )
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


async def load_sample_records(settings: object, people: list[tuple[str, str, Report]]) -> int:
    """Upload and index each (user_id, patient_id, report) as that patient would. Returns the count."""
    from services.platform.auth import AuthContext
    from services.platform.db import app_pool
    from services.records.service import ingest_record, upload_record
    from services.records.storage import build_object_store

    pool = app_pool(settings)  # type: ignore[arg-type]
    await pool.open()
    store = build_object_store(settings)  # type: ignore[arg-type]
    try:
        for user_id, patient_id, report in people:
            auth = AuthContext(user_id=user_id, role="patient", acting_for_patient_id=patient_id)
            uploaded = await upload_record(
                pool,
                store,
                auth,
                patient_id=patient_id,
                filename=f"{report[0]}.pdf",
                content=report_pdf(report),
                content_type="application/pdf",
                doc_type="lab_report",
            )
            await ingest_record(pool, store, doc_id=uploaded.doc_id)
    finally:
        await pool.close()
    return len(people)
