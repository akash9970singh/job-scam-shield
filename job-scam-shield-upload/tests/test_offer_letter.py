from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.checks import llm
from app.checks.offer_letter import UnreadablePdf, check_offer_letter, gstin_checksum_ok
from app.main import app
from app.scoring import combine
from tests.letter_factory import FAKE_LETTER, GENUINE_LETTER, build_letter, edit_later

client = TestClient(app)


def analyse(data, **kwargs):
    return combine(check_offer_letter(data, online=False, **kwargs))


def codes(analysis):
    return {s.code for s in analysis.red_flags}


def test_gstin_checksum_matches_published_example():
    # Sample GSTIN used in GST documentation.
    assert gstin_checksum_ok("27AAPFU0939F1ZV")
    assert not gstin_checksum_ok("27AAPFU0939F1ZW")


def test_fake_letter_is_high_risk():
    analysis = analyse(build_letter(FAKE_LETTER, producer="Canva", creator="Canva"))
    assert analysis.level == "high"
    assert {
        "made_with_editor", "invalid_cin", "invalid_gstin", "generic_salutation",
        "whatsapp_contact", "lookalike_link", "fee_language", "free_email_claims_company",
    } <= codes(analysis)


def test_genuine_letter_is_low_risk():
    analysis = analyse(build_letter(GENUINE_LETTER))
    assert analysis.level == "low", [f.message for f in analysis.red_flags]
    assert analysis.red_flags == []


def test_later_edits_are_detected():
    analysis = analyse(edit_later(build_letter(GENUINE_LETTER)))
    assert {"incremental_edits", "modified_after_creation", "made_with_editor"} <= codes(analysis)


def test_clickable_link_to_lookalike_site():
    data = build_letter(GENUINE_LETTER[:3], link="https://infosys-onboarding.co/join")
    assert "lookalike_link" in codes(analyse(data))


def test_gstin_of_an_individual():
    from tests.letter_factory import gstin

    data = build_letter([f"GSTIN: {gstin('27ABCPK1234L1Z')}", "Dear Rahul Verma,"])
    assert "gstin_of_individual" in codes(analyse(data))


def test_scanned_letter_without_text():
    analysis = analyse(build_letter([]))
    assert "no_text" in codes(analysis)


def test_not_a_pdf():
    with pytest.raises(UnreadablePdf):
        check_offer_letter(b"hello, I am not a PDF", online=False)


def test_ai_review_adds_signal(monkeypatch):
    review = llm.OfferLetterAssessment(
        verdict="likely_fake", claimed_company="TCS",
        red_flags=["Logo is blurry", "Asks for a deposit"], summary="Looks forged.",
    )
    seen = {}

    def fake_parse(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=review)

    fake_client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=fake_parse)))
    monkeypatch.setattr(llm, "_get_client", lambda: fake_client)

    analysis = analyse(build_letter([]), use_llm=True)
    assert "ai_likely_fake" in codes(analysis)
    document = seen["messages"][0]["content"][0]
    assert document["type"] == "document" and document["source"]["media_type"] == "application/pdf"


def test_upload_endpoint():
    data = build_letter(FAKE_LETTER, producer="Canva")
    resp = client.post(
        "/api/check/offer-letter",
        files={"file": ("offer.pdf", data, "application/pdf")},
        data={"online": "false"},
    )
    assert resp.status_code == 200
    assert resp.json()["level"] == "high"


def test_upload_endpoint_rejects_non_pdf():
    resp = client.post("/api/check/offer-letter", files={"file": ("a.pdf", b"nope", "application/pdf")})
    assert resp.status_code == 400
