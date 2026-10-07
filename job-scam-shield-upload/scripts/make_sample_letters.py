"""Write demo offer-letter PDFs to samples/letters/ for trying the offer letter check.

Usage: python scripts/make_sample_letters.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import io  # noqa: E402

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from tests.letter_factory import FAKE_LETTER, GENUINE_LETTER, build_letter, edit_later, gstin  # noqa: E402

OUT = ROOT / "samples" / "letters"
WATERMARK = "SAMPLE - for scam-detection testing - fictional company"


def build_styled_scam_letter() -> bytes:
    """A realistic-looking forged offer from a fictional company, with typical scam signs."""
    buf = io.BytesIO()
    width, height = A4
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.setCreator("Canva")
    pdf.setProducer("Canva")
    pdf.setTitle("Offer Letter")

    # Letterhead
    pdf.setFillColor(colors.HexColor("#1f3c88"))
    pdf.rect(0, height - 95, width, 95, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawString(50, height - 50, "BRIGHTWAVE TECHNOLOGIES PVT. LTD.")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(50, height - 68, "Plot 42, Cyber Park, Sector 5, Gurugram, Haryana 122001")
    pdf.drawString(50, height - 81, f"CIN: U72900HR2031PTC12345   GSTIN: {gstin('06AABCB1234Q1Z', valid=False)}")

    pdf.setFillColor(colors.black)
    y = height - 130
    lines = [
        ("Helvetica", 10, "Ref: BWT/HR/2026/OFF/0917                                              Date: 08-10-2026"),
        ("Helvetica", 10, ""),
        ("Helvetica-Bold", 12, "OFFER OF EMPLOYMENT - WORK FROM HOME"),
        ("Helvetica", 10, ""),
        ("Helvetica", 10, "Dear Candidate,"),
        ("Helvetica", 10, ""),
        ("Helvetica", 10, "Congratulations! With reference to your online interview, we are pleased to offer you the"),
        ("Helvetica", 10, "position of Junior Data Analyst (Remote) at Brightwave Technologies Pvt. Ltd."),
        ("Helvetica", 10, ""),
        ("Helvetica-Bold", 10, "Compensation"),
        ("Helvetica", 10, "   Monthly salary: Rs 45,000 (fixed) + performance bonus"),
        ("Helvetica", 10, "   Joining bonus: Rs 10,000 (paid with first salary)"),
        ("Helvetica", 10, "   Joining date: 20 October 2026"),
        ("Helvetica", 10, ""),
        ("Helvetica-Bold", 10, "Onboarding formalities"),
        ("Helvetica", 10, "To confirm your seat, you must pay a refundable training kit and laptop security deposit"),
        ("Helvetica", 10, "of Rs 6,500 to our onboarding account brightwave.hr@ybl within 24 hours of receiving"),
        ("Helvetica", 10, "this letter. Failing this, the offer will be cancelled and given to a waitlisted candidate."),
        ("Helvetica", 10, ""),
        ("Helvetica", 10, "After payment, send the screenshot along with your Aadhaar card, PAN card and a cancelled"),
        ("Helvetica", 10, "cheque to our HR manager on WhatsApp: +91 90000 00002."),
        ("Helvetica", 10, ""),
        ("Helvetica", 10, "For any queries, email brightwave.hr.desk@gmail.com"),
        ("Helvetica", 10, "Complete your joining form here: https://bit.ly/bwt-joining-form"),
        ("Helvetica", 10, ""),
        ("Helvetica", 10, "We look forward to welcoming you to the Brightwave family."),
        ("Helvetica", 10, ""),
        ("Helvetica", 10, "Warm regards,"),
        ("Helvetica", 10, ""),
        ("Helvetica-Oblique", 14, "R. Malhotra"),
        ("Helvetica-Bold", 10, "Rohit Malhotra"),
        ("Helvetica", 10, "Senior HR Manager, Brightwave Technologies Pvt. Ltd."),
    ]
    for font, size, text in lines:
        pdf.setFont(font, size)
        pdf.drawString(50, y, text)
        y -= size + 6

    # "Company seal"
    pdf.setStrokeColor(colors.HexColor("#1f3c88"))
    pdf.circle(width - 120, 130, 38, stroke=1, fill=0)
    pdf.setFont("Helvetica-Bold", 7)
    pdf.drawCentredString(width - 120, 133, "BRIGHTWAVE")
    pdf.drawCentredString(width - 120, 123, "HR DEPT.")

    # Testing watermark so the file can't pass as a real letter
    pdf.setFillColor(colors.HexColor("#c62828"))
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawCentredString(width / 2, 25, WATERMARK)
    pdf.saveState()
    pdf.setFillColor(colors.Color(0.78, 0.16, 0.16, alpha=0.12))
    pdf.setFont("Helvetica-Bold", 60)
    pdf.translate(width / 2, height / 2)
    pdf.rotate(35)
    pdf.drawCentredString(0, 0, "SAMPLE")
    pdf.restoreState()

    pdf.save()
    return buf.getvalue()


LETTERS = {
    "fake_tcs_offer_canva.pdf": build_letter(FAKE_LETTER, producer="Canva", creator="Canva"),
    "genuine_style_offer.pdf": build_letter(GENUINE_LETTER),
    "genuine_letter_edited_later.pdf": edit_later(build_letter(GENUINE_LETTER)),
    "fake_offer_brightwave.pdf": build_styled_scam_letter(),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in LETTERS.items():
        (OUT / name).write_bytes(data)
        print(f"wrote samples/letters/{name}")


if __name__ == "__main__":
    main()
