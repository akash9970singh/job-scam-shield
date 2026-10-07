"""Check #2: does the recruiter's email really belong to the company they claim?

Offline signals: free email provider, lookalike/impersonating domain, punycode.
Online signals (online=True): domain age via RDAP, and MX/SPF/DMARC via DNS.
"""

import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import dns.exception
import dns.resolver
import httpx
import tldextract
from rapidfuzz import fuzz

from app.checks.community import report_signal
from app.schemas import CheckResult, Signal

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# suffix_list_urls=() uses the bundled public-suffix snapshot instead of downloading it.
_extract = tldextract.TLDExtract(suffix_list_urls=())

EMAIL_RE = re.compile(r"[\w.+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")

FREE_EMAIL_PROVIDERS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in", "ymail.com",
    "outlook.com", "hotmail.com", "live.com", "msn.com", "rediffmail.com", "rediff.com",
    "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "mail.com",
    "zohomail.in", "yandex.com", "tutanota.com",
}

# Legitimate applicant-tracking systems that send mail on behalf of employers.
HIRING_PLATFORM_DOMAINS = {
    "myworkday.com", "myworkdayjobs.com", "greenhouse.io", "lever.co", "smartrecruiters.com",
    "icims.com", "successfactors.com", "taleo.net", "naukri.com", "linkedin.com",
    "internshala.com", "unstop.com", "hirist.tech", "instahyre.com",
}

NEW_DOMAIN_DAYS = 180
YOUNG_DOMAIN_DAYS = 365


@lru_cache
def load_companies() -> list[dict]:
    return json.loads((DATA_DIR / "companies.json").read_text(encoding="utf-8"))


def find_company(name: str) -> dict | None:
    key = re.sub(r"\s+", " ", name.strip().lower())
    for company in load_companies():
        if key == company["name"].lower() or key in company["aliases"]:
            return company
    return None


def extract_emails(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for match in EMAIL_RE.findall(text):
        seen.setdefault(match.lower().rstrip("."), None)
    return list(seen)


def split_domain(host: str) -> tuple[str, str]:
    """Return (registered domain, its main label), e.g. careers.infosys.com -> (infosys.com, infosys)."""
    ext = _extract(host)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}", ext.domain
    return host, host.split(".")[0]


def looks_like(label: str, company: dict) -> bool:
    """True if a domain label imitates a company: contains its name, or is a near-miss spelling."""
    compact = re.sub(r"[^a-z0-9]", "", label)
    tokens = set(re.split(r"[^a-z]+", label))
    for keyword in company["keywords"]:
        # Short names like "tcs" must be a whole token, or "ltcsolutions" would match.
        if keyword in tokens or (len(keyword) >= 5 and keyword in compact):
            return True
    for official in company["domains"]:
        _, official_label = split_domain(official)
        if label != official_label and fuzz.ratio(label, official_label) >= 85:
            return True
    return False


def domain_age_days(domain: str) -> int | None:
    try:
        resp = httpx.get(f"https://rdap.org/domain/{domain}", follow_redirects=True, timeout=6)
        if resp.status_code != 200:
            return None
        for event in resp.json().get("events", []):
            if event.get("eventAction") == "registration":
                registered = datetime.fromisoformat(event["eventDate"].replace("Z", "+00:00"))
                if registered.tzinfo is None:
                    registered = registered.replace(tzinfo=timezone.utc)
                return (datetime.now(timezone.utc) - registered).days
    except (httpx.HTTPError, ValueError, KeyError):
        return None
    return None


def email_dns_records(domain: str) -> dict:
    """MX/SPF/DMARC presence. A value of None means the lookup itself failed."""
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 4
    records: dict = {"exists": None, "mx": None, "spf": None, "dmarc": None}

    try:
        records["mx"] = len(resolver.resolve(domain, "MX")) > 0
        records["exists"] = True
    except dns.resolver.NXDOMAIN:
        records.update(exists=False, mx=False)
        return records
    except dns.resolver.NoAnswer:
        records.update(exists=True, mx=False)
    except dns.exception.DNSException:
        pass

    records["spf"] = _has_txt(resolver, domain, "v=spf1")
    records["dmarc"] = _has_txt(resolver, f"_dmarc.{domain}", "v=dmarc1")
    return records


def _has_txt(resolver: dns.resolver.Resolver, name: str, prefix: str) -> bool | None:
    try:
        answers = resolver.resolve(name, "TXT")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return False
    except dns.exception.DNSException:
        return None
    return any(
        b"".join(r.strings).decode(errors="ignore").lower().startswith(prefix) for r in answers
    )


def check_recruiter(
    sender_email: str, claimed_company: str | None = None, online: bool = True
) -> CheckResult:
    email = sender_email.strip().lower()
    result = CheckResult(check="recruiter_identity", details={"email": email})
    signals = result.signals

    if not EMAIL_RE.fullmatch(email):
        signals.append(Signal(code="invalid_email", points=0, message=f"'{email}' is not a valid email address."))
        return result

    host = email.split("@", 1)[1]
    domain, label = split_domain(host)
    company = find_company(claimed_company) if claimed_company else None
    result.details.update(domain=domain, claimed_company=company["name"] if company else claimed_company)

    # A report against gmail.com itself would flag every Gmail user, so only the address counts there.
    reported = report_signal("email", email, email, "reported_sender")
    if not reported and domain not in FREE_EMAIL_PROVIDERS:
        reported = report_signal("domain", domain, f"The domain {domain}", "reported_sender")
    if reported:
        signals.append(reported)

    if domain in FREE_EMAIL_PROVIDERS:
        if claimed_company:
            signals.append(Signal(
                code="free_email_claims_company", points=35,
                message=f"Claims to be from {claimed_company} but uses a free {domain} address. "
                "Real company recruiters use the company's own domain.",
            ))
        else:
            signals.append(Signal(
                code="free_email", points=15,
                message=f"Uses a free {domain} address instead of a company domain.",
            ))
        return result

    if any(part.startswith("xn--") for part in host.split(".")):
        signals.append(Signal(
            code="punycode_domain", points=30,
            message="The domain uses look-alike international characters (punycode), a common impersonation trick.",
        ))

    is_platform = domain in HIRING_PLATFORM_DOMAINS
    if is_platform:
        result.details["hiring_platform"] = True

    if company:
        if domain in company["domains"]:
            signals.append(Signal(
                code="official_domain", points=-25,
                message=f"Email domain {domain} matches {company['name']}'s official domain.",
            ))
            return result
        if not is_platform:
            if looks_like(label, company):
                signals.append(Signal(
                    code="lookalike_domain", points=45,
                    message=f"{domain} imitates {company['name']} but is NOT its official domain "
                    f"({', '.join(company['domains'])}).",
                ))
            else:
                signals.append(Signal(
                    code="domain_mismatch", points=30,
                    message=f"Claims to be from {company['name']} but writes from {domain}, "
                    f"not {', '.join(company['domains'])}.",
                ))

    if not is_platform:
        for other in load_companies():
            if other is company or domain in other["domains"]:
                continue
            if looks_like(label, other):
                signals.append(Signal(
                    code="impersonation_suspected", points=40,
                    message=f"{domain} looks like {other['name']}'s domain but isn't one of its "
                    f"official domains ({', '.join(other['domains'])}).",
                ))
                break

    if online and not is_platform:
        _add_online_signals(result, domain)
    return result


def _add_online_signals(result: CheckResult, domain: str) -> None:
    signals = result.signals

    records = email_dns_records(domain)
    result.details["dns"] = records
    if records["exists"] is False:
        signals.append(Signal(
            code="domain_not_found", points=40,
            message=f"{domain} does not exist. The address is fake or mistyped.",
        ))
        return
    if records["mx"] is False:
        signals.append(Signal(code="no_mx", points=15, message=f"{domain} cannot receive email (no MX record)."))
    if records["spf"] is False:
        signals.append(Signal(code="no_spf", points=5, message=f"{domain} has no SPF record, so anyone can send mail as it."))
    if records["dmarc"] is False:
        signals.append(Signal(code="no_dmarc", points=5, message=f"{domain} has no DMARC policy against spoofing."))

    age = domain_age_days(domain)
    result.details["domain_age_days"] = age
    if age is None:
        return
    if age < NEW_DOMAIN_DAYS:
        signals.append(Signal(
            code="new_domain", points=30,
            message=f"{domain} was registered only {age} days ago. Scam domains are usually new.",
        ))
    elif age < YOUNG_DOMAIN_DAYS:
        signals.append(Signal(code="young_domain", points=15, message=f"{domain} is less than a year old ({age} days)."))
