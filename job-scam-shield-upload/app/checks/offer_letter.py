"""Check #3: does this offer letter PDF look forged?

Looks at how the file was made (metadata, later edits), the company identifiers printed on it
(CIN, GSTIN), its contacts and links, and its wording. The text also goes through the payment
check (#4) and its email addresses through the recruiter check (#2).
"""

import io
import re
from datetime import datetime, timezone

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.checks.payment import check_payment
from app.checks.recruiter import (
    HIRING_PLATFORM_DOMAINS,
    check_recruiter,
    extract_emails,
    find_company,
    load_companies,
    looks_like,
    split_domain,
)
from app.schemas import CheckResult, Signal

MAX_PAGES = 10
MAX_EMAILS = 5
EDITED_AFTER_DAYS = 1

# Tools that make it easy to fake a letter. Real HR systems generate offers from templates
# (Workday, SuccessFactors, DocuSign, Word exports...), so these are signs, not proof.
EDITOR_TOOLS = {
    "canva": ("Canva (a design tool)", 25),
    "ilovepdf": ("iLovePDF (an online PDF editor)", 20),
    "smallpdf": ("Smallpdf (an online PDF editor)", 20),
    "sejda": ("Sejda (an online PDF editor)", 20),
    "pdfescape": ("PDFescape (an online PDF editor)", 20),
    "pdf candy": ("PDF Candy (an online PDF editor)", 20),
    "pdfcandy": ("PDF Candy (an online PDF editor)", 20),
    "sodapdf": ("Soda PDF (an online PDF editor)", 20),
    "pdffiller": ("pdfFiller (an online PDF editor)", 20),
    "dochub": ("DocHub (an online PDF editor)", 20),
    "online2pdf": ("Online2PDF (an online converter)", 15),
    "camscanner": ("CamScanner (a phone scanner app)", 10),
}

URL_RE = re.compile(r"(?:https?://|www\.)[^\s\"'<>)]+", re.I)
GENERIC_SALUTATION_RE = re.compile(r"\bdear\s+(?:candidate|applicant|sir\s*/\s*madam|sir|madam|student)\b", re.I)
WHATSAPP_RE = re.compile(r"\bwhats\s?app\b|\bwa\.me/", re.I)

CIN_LABEL_RE = re.compile(r"\bCIN\b\s*(?:No\.?|Number)?\s*[:\-]?\s*([A-Z0-9]{8,25})\b", re.I)
CIN_RE = re.compile(
    r"^[LU]\d{5}(?P<state>[A-Z]{2})(?P<year>\d{4})"
    r"(?:PLC|PTC|GOI|SGC|NPL|FLC|FTC|GAP|GAT|ULL|ULT|OPC)\d{6}$"
)
CIN_STATES = {
    "AN", "AP", "AR", "AS", "BR", "CH", "CT", "CG", "DN", "DD", "DL", "GA", "GJ", "HR", "HP", "JK",
    "JH", "KA", "KL", "LA", "LD", "MP", "MH", "MN", "ML", "MZ", "NL", "OR", "OD", "PY", "PB", "RJ",
    "SK", "TN", "TG", "TS", "TR", "UP", "UR", "UT", "WB",
}
GSTIN_LABEL_RE = re.compile(r"\bGST(?:IN)?\b\s*(?:No\.?|Number)?\s*[:\-]?\s*([A-Z0-9]{10,20})\b", re.I)
GSTIN_RE = re.compile(r"^(?P<state>\d{2})(?P<pan>[A-Z]{5}\d{4}[A-Z])[1-9A-Z]Z[0-9A-Z]$")
GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_STATE_CODES = {f"{n:02d}" for n in range(1, 39)} | {"97", "99"}


class UnreadablePdf(ValueError):
    """The upload is not a PDF we can open."""


def gstin_checksum_ok(gstin: str) -> bool:
    """GSTIN's 15th character is a mod-36 Luhn checksum of the first 14."""
    total = 0
    for i, char in enumerate(gstin[:14]):
        product = GSTIN_CHARS.index(char) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return GSTIN_CHARS[(36 - total % 36) % 36] == gstin[14]


def check_offer_letter(
    data: bytes, claimed_company: str | None = None, online: bool = True, use_llm: bool = False
) -> list[CheckResult]:
    """Return the offer-letter result plus the payment and recruiter results for its contents."""
    reader = _open(data)
    result = CheckResult(check="offer_letter")
    signals = result.signals

    if reader.is_encrypted:
        signals.append(Signal(
            code="password_protected", points=10,
            message="The PDF is password-protected, so its contents couldn't be checked.",
        ))
        return [result]

    text = "\n".join(_page_text(page) for page in reader.pages[:MAX_PAGES])
    links = _link_targets(reader)
    company = _detect_company(text, claimed_company)
    result.details = {
        "pages": len(reader.pages),
        "text_chars": len(text.strip()),
        "company": company["name"] if company else claimed_company,
        "metadata": _metadata(reader),
        "links": links,
    }

    _check_metadata(result, data)
    _check_identifiers(result, text)
    _check_wording(result, text)
    _check_links(result, links + URL_RE.findall(text), company)
    if use_llm:
        _add_ai_review(result, data)

    if not text.strip():
        signals.append(Signal(
            code="no_text", points=5,
            message="The letter is a scanned image with no readable text. Use AI mode to read it, "
            "or verify it directly with the company.",
        ))
        return [result]

    results = [result, check_payment("\n".join([text, *links]))]
    company_name = company["name"] if company else claimed_company
    for email in extract_emails(text)[:MAX_EMAILS]:
        results.append(check_recruiter(email, company_name, online))
    return results


def _open(data: bytes) -> PdfReader:
    if not data.lstrip()[:5].startswith(b"%PDF"):
        raise UnreadablePdf("This file is not a PDF.")
    try:
        return PdfReader(io.BytesIO(data))
    except (PdfReadError, ValueError, KeyError) as exc:
        raise UnreadablePdf(f"Could not read this PDF ({exc}).") from exc


def _page_text(page) -> str:
    try:
        return page.extract_text() or ""
    except Exception:  # pypdf raises many kinds of errors on malformed pages
        return ""


def _link_targets(reader: PdfReader) -> list[str]:
    targets = []
    for page in reader.pages[:MAX_PAGES]:
        for annot in page.get("/Annots") or []:
            try:
                uri = annot.get_object().get("/A", {}).get("/URI")
            except (AttributeError, PdfReadError):
                continue
            if uri:
                targets.append(str(uri))
    return list(dict.fromkeys(targets))


def _metadata(reader: PdfReader) -> dict:
    meta = reader.metadata
    if not meta:
        return {}

    def safe(getter):
        try:
            value = getter()
        except Exception:  # malformed date strings raise
            return None
        return value.isoformat() if isinstance(value, datetime) else (str(value) if value else None)

    return {
        "producer": safe(lambda: meta.producer),
        "creator": safe(lambda: meta.creator),
        "author": safe(lambda: meta.author),
        "created": safe(lambda: meta.creation_date),
        "modified": safe(lambda: meta.modification_date),
    }


def _check_metadata(result: CheckResult, data: bytes) -> None:
    meta = result.details["metadata"]
    tools = " ".join(filter(None, [meta.get("producer"), meta.get("creator")])).lower()
    for key, (name, points) in EDITOR_TOOLS.items():
        if key in tools:
            result.signals.append(Signal(
                code="made_with_editor", points=points,
                message=f"The PDF was made or edited with {name}. Company offer letters come from HR systems.",
            ))
            break

    created, modified = _parse_date(meta.get("created")), _parse_date(meta.get("modified"))
    if created and modified and (modified - created).days >= EDITED_AFTER_DAYS:
        result.signals.append(Signal(
            code="modified_after_creation", points=10,
            message=f"The PDF was modified {(modified - created).days} day(s) after it was created.",
        ))

    # Each save that appends changes adds another %%EOF. Linearized ("fast web view") files
    # legitimately have two.
    allowed = 2 if b"/Linearized" in data[:2048] else 1
    if data.count(b"%%EOF") > allowed:
        result.signals.append(Signal(
            code="incremental_edits", points=15,
            message="The PDF was edited after it was first saved (it contains later changes layered on top).",
        ))


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _check_identifiers(result: CheckResult, text: str) -> None:
    compact = text.upper()
    identifiers = result.details["identifiers"] = {}

    for cin in dict.fromkeys(CIN_LABEL_RE.findall(compact)):
        match = CIN_RE.match(cin)
        valid = bool(match and match["state"] in CIN_STATES
                     and 1850 <= int(match["year"]) <= datetime.now().year)
        identifiers[f"CIN {cin}"] = "valid format" if valid else "invalid"
        if not valid:
            result.signals.append(Signal(
                code="invalid_cin", points=25,
                message=f"CIN '{cin}' is not a valid Company Identification Number. Real companies print "
                "their exact CIN; look it up on the MCA portal (mca.gov.in).",
            ))

    for gstin in dict.fromkeys(GSTIN_LABEL_RE.findall(compact)):
        match = GSTIN_RE.match(gstin)
        if not (match and match["state"] in GSTIN_STATE_CODES and gstin_checksum_ok(gstin)):
            identifiers[f"GSTIN {gstin}"] = "invalid"
            result.signals.append(Signal(
                code="invalid_gstin", points=30,
                message=f"GSTIN '{gstin}' fails the official checksum, so it was made up or mistyped.",
            ))
            continue
        identifiers[f"GSTIN {gstin}"] = "valid format"
        # The 4th character of the embedded PAN says who holds it: C = company, P = person.
        if match["pan"][3] == "P":
            result.signals.append(Signal(
                code="gstin_of_individual", points=15,
                message=f"GSTIN '{gstin}' belongs to an individual, not a company.",
            ))


def _check_wording(result: CheckResult, text: str) -> None:
    if GENERIC_SALUTATION_RE.search(text):
        result.signals.append(Signal(
            code="generic_salutation", points=10,
            message="Addressed to 'Dear Candidate/Sir/Madam'. Real offer letters use your full name.",
        ))
    if WHATSAPP_RE.search(text):
        result.signals.append(Signal(
            code="whatsapp_contact", points=10,
            message="Asks you to contact HR on WhatsApp. Real offers point to official email or portals.",
        ))


def _check_links(result: CheckResult, urls: list[str], company: dict | None) -> None:
    for url in dict.fromkeys(urls):
        host = re.sub(r"^(?:https?://)?(?:www\.)?", "", url.lower()).split("/")[0].split(":")[0]
        domain, label = split_domain(host)
        if not label or domain in HIRING_PLATFORM_DOMAINS:
            continue
        candidates = [company] if company else load_companies()
        for c in candidates:
            if domain not in c["domains"] and looks_like(label, c):
                result.signals.append(Signal(
                    code="lookalike_link", points=40,
                    message=f"The letter links to {domain}, which imitates {c['name']} "
                    f"(official: {', '.join(c['domains'])}).",
                ))
                return


AI_VERDICT_POINTS = {"likely_fake": 40, "suspicious": 20, "likely_genuine": 0}


def _add_ai_review(result: CheckResult, data: bytes) -> None:
    from app.checks import llm  # imported lazily so the rules work without the SDK or a key

    review = llm.assess_offer_letter(data)
    result.details["ai_review"] = review.model_dump() if review else None
    if review is None or not AI_VERDICT_POINTS[review.verdict]:
        return
    flags = "; ".join(review.red_flags[:5])
    result.signals.append(Signal(
        code=f"ai_{review.verdict}", points=AI_VERDICT_POINTS[review.verdict],
        message=f"AI review: {review.summary}" + (f" Red flags: {flags}." if flags else ""),
    ))


def _detect_company(text: str, claimed_company: str | None) -> dict | None:
    if claimed_company:
        return find_company(claimed_company)
    lowered = text.lower()
    best, best_hits = None, 0
    for company in load_companies():
        names = {company["name"].lower(), *company["aliases"]}
        hits = sum(len(re.findall(rf"\b{re.escape(n)}\b", lowered)) for n in names if len(n) >= 3)
        if hits > best_hits:
            best, best_hits = company, hits
    return best
