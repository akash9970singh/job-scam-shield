from app import db
from app.checks.recruiter import check_recruiter, extract_emails


def codes(result):
    return {s.code for s in result.signals}


def test_official_domain_is_a_good_sign():
    result = check_recruiter("talent@careers.infosys.com", "Infosys", online=False)
    assert codes(result) == {"official_domain"}


def test_free_email_claiming_company():
    result = check_recruiter("infosys.hr.team@gmail.com", "Infosys", online=False)
    assert "free_email_claims_company" in codes(result)


def test_lookalike_domain_for_claimed_company():
    result = check_recruiter("hr@infosys-careers.co", "Infosys", online=False)
    assert "lookalike_domain" in codes(result)


def test_typosquat_is_caught_without_claimed_company():
    result = check_recruiter("hr@lnfosys.com", online=False)
    assert "impersonation_suspected" in codes(result)


def test_unrelated_domain_for_claimed_company():
    result = check_recruiter("jobs@quickhire-solutions.in", "TCS", online=False)
    assert "domain_mismatch" in codes(result)


def test_short_keyword_does_not_match_inside_words():
    result = check_recruiter("hello@ltcsolutions.com", online=False)
    assert "impersonation_suspected" not in codes(result)


def test_hiring_platform_is_not_flagged_as_mismatch():
    result = check_recruiter("no-reply@myworkday.com", "Accenture", online=False)
    assert "domain_mismatch" not in codes(result)


def test_reported_domain():
    db.add_report("domain", "https://www.fake-hr-portal.in/apply", status="verified")
    result = check_recruiter("hr@fake-hr-portal.in", online=False)
    assert "reported_sender" in codes(result)


def test_free_provider_domain_reports_are_ignored():
    db.add_report("domain", "gmail.com", status="verified")
    result = check_recruiter("someone@gmail.com", online=False)
    assert "reported_sender" not in codes(result)


def test_extract_emails_dedupes():
    text = "Mail HR@Wipro.com or hr@wipro.com, cc careers@tcs.com."
    assert extract_emails(text) == ["hr@wipro.com", "careers@tcs.com"]
