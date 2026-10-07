"""Builds offer-letter PDFs for tests and demos. Every company detail in them is fictional or fake."""

import io
from datetime import datetime, timedelta, timezone

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.checks.offer_letter import GSTIN_CHARS, gstin_checksum_ok


def gstin(first14: str, valid: bool = True) -> str:
    """Complete a GSTIN with a correct (or deliberately wrong) checksum character."""
    for char in GSTIN_CHARS:
        if gstin_checksum_ok(first14 + char) == valid:
            return first14 + char
    raise AssertionError("unreachable")


FAKE_LETTER = [
    "Tata Consultancy Services Pvt Ltd",
    f"CIN: U72900MH2026PTC99999X   GSTIN: {gstin('27AACCT1234A1Z', valid=False)}",
    "",
    "Dear Candidate,",
    "",
    "We are pleased to offer you the position of Assistant System Engineer at TCS",
    "with an annual CTC of Rs 7,20,000. Your joining date is 15 November 2026.",
    "",
    "Before joining, you must pay a refundable laptop security deposit of Rs 8,500",
    "to tcs.onboarding@ybl within 48 hours, or this offer will be cancelled.",
    "",
    "For queries, contact HR on WhatsApp or write to tcs.hr.onboarding@gmail.com",
    "Portal: https://tcs-careers-portal.in/joining",
    "",
    "HR Department",
]

GENUINE_LETTER = [
    "Northwind Software Limited",
    f"CIN: L72200KA2004PLC034567   GSTIN: {gstin('29AABCN1234C1Z')}",
    "",
    "Dear Priya Sharma,",
    "",
    "We are pleased to offer you the position of Graduate Engineer Trainee",
    "with an annual CTC of Rs 6,00,000, starting on 1 December 2026.",
    "",
    "Please accept this offer on our careers portal within 10 working days.",
    "Northwind never charges candidates any fee at any stage of hiring.",
    "",
    "For questions, write to campus.hiring@northwind-software.example",
    "",
    "Head of Talent Acquisition",
]


def build_letter(lines: list[str], producer: str = "Workday", creator: str = "Workday",
                 link: str | None = None) -> bytes:
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.setCreator(creator)
    pdf.setProducer(producer)
    y = 800
    for line in lines:
        pdf.drawString(60, y, line)
        y -= 18
    if link:
        pdf.drawString(60, y - 10, "Click here to complete joining formalities")
        pdf.linkURL(link, (60, y - 14, 320, y), relative=0)
    pdf.save()
    return buf.getvalue()


def edit_later(data: bytes, days: int = 20) -> bytes:
    """Append an incremental update that bumps the modification date, like re-saving in an editor."""
    reader = PdfReader(io.BytesIO(data))
    created = reader.metadata.creation_date or datetime.now(timezone.utc)
    writer = PdfWriter(io.BytesIO(data), incremental=True)
    stamp = (created + timedelta(days=days)).strftime("D:%Y%m%d%H%M%S+00'00'")
    writer.add_metadata({"/ModDate": stamp, "/Producer": "iLovePDF"})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
