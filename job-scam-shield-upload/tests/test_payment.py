from app import db
from app.checks.payment import check_payment, extract_upi_ids
from app.scoring import combine

SCAM_OFFER = """Congratulations! You are selected for the Data Analyst internship.
To confirm your seat, pay a registration fee of Rs 1,999 (fully refundable) to hrdesk@ybl
within 24 hours. Limited seats."""

TASK_SCAM = """Part time job! Earn Rs 3000 per day by liking YouTube videos.
Join our Telegram: https://t.me/earn_daily_tasks for VIP tasks."""

GENUINE = """Hi, thanks for applying to the Software Engineer role. Your interview is
scheduled for Monday at 11 AM. Please bring a copy of your resume."""


def codes(result):
    return {s.code for s in result.signals}


def test_upi_ids_are_found_but_emails_are_not():
    text = "Pay to rahul.k@okaxis or mail hr@infosys.com. Backup: 98765@ybl."
    assert extract_upi_ids(text) == ["rahul.k@okaxis", "98765@ybl"]


def test_classic_fee_scam_is_high_risk():
    result = check_payment(SCAM_OFFER)
    assert {"upi_id", "fee_language", "urgency", "money_in_job_context"} <= codes(result)
    assert combine([result]).level == "high"


def test_task_scam_is_flagged():
    result = check_payment(TASK_SCAM)
    assert {"task_scam_language", "moves_to_messaging"} <= codes(result)
    assert combine([result]).level in {"medium", "high"}


def test_genuine_interview_mail_is_low_risk():
    analysis = combine([check_payment(GENUINE)])
    assert analysis.level == "low"
    assert analysis.red_flags == []


def test_upi_pay_link_payee_is_extracted():
    result = check_payment("Internship fee: upi://pay?pa=fakehr@paytm&am=499")
    assert "fakehr@paytm" in result.details["upi_ids"]
    assert "upi_pay_link" in codes(result)


def test_verified_upi_report_raises_score():
    db.add_report("upi", "HRDESK@ybl", status="verified")
    result = check_payment(SCAM_OFFER)
    assert "reported_upi" in codes(result)


def test_unverified_upi_report_counts_for_little():
    db.add_report("upi", "hrdesk@ybl")
    result = check_payment(SCAM_OFFER)
    flag = next(s for s in result.signals if s.code == "reported_upi_unverified")
    assert flag.points < 20
    assert "reported_upi" not in codes(result)


def test_rejected_report_is_ignored():
    db.add_report("upi", "hrdesk@ybl", status="rejected")
    assert not {"reported_upi", "reported_upi_unverified"} & codes(check_payment(SCAM_OFFER))


def test_fee_disclaimer_is_not_a_fee_request():
    result = check_payment("Selected for the job. We never ask for any registration fee or training fee.")
    assert "fee_language" not in codes(result)


def test_negation_with_an_amount_is_still_a_fee_request():
    result = check_payment("No hidden charges for this internship, just a registration fee of Rs 500.")
    assert "fee_language" in codes(result)


def test_hinglish_fee_and_urgency():
    result = check_payment("Job ke liye 1500 rupees fees bharni hogi, aaj hi karna hai")
    assert {"fee_language", "urgency", "money_in_job_context"} <= codes(result)


def test_identity_documents_and_otp_requests():
    result = check_payment("For your internship offer letter send Aadhaar, PAN card and the OTP you receive.")
    assert {"document_request", "secret_request"} <= codes(result)


def test_reported_phone_matches_with_country_code():
    db.add_report("phone", "9876543210", status="verified")
    result = check_payment("Call HR on +91 98765 43210 for the internship")
    assert "reported_phone" in codes(result)
