"""Check #4: is someone asking for money inside a job/internship conversation?

Finds UPI IDs, upi:// pay links, payment-gateway links, bank details and fee language,
then cross-checks UPI IDs and phone numbers against community reports.
"""

import re
from urllib.parse import parse_qs, urlparse

from app.checks.community import report_signal
from app.checks.recruiter import split_domain
from app.schemas import CheckResult, Signal

# A UPI ID is name@handle where the handle has no dot. The lookahead stops it matching
# the start of an email address (abc@gmail.com) while allowing a sentence-ending period.
UPI_ID_RE = re.compile(r"(?<![\w.\-])([\w.\-]{2,256}@[A-Za-z][A-Za-z0-9]{1,63})(?!\.?[\w\-@])")

KNOWN_UPI_HANDLES = {
    "ybl", "ibl", "axl", "paytm", "ptyes", "ptaxis", "pthdfc", "ptsbi", "okaxis", "okhdfcbank",
    "okicici", "oksbi", "upi", "apl", "yapl", "rapl", "fam", "jupiteraxis", "kotak", "sbi",
    "icici", "hdfcbank", "axisbank", "axisb", "ikwik", "freecharge", "airtel", "jio", "waicici",
    "wahdfcbank", "wasbi", "waaxis", "slc", "naviaxis", "superyes", "pz", "abfspay", "yesbank",
    "yesg", "barodampay", "pnb", "unionbank", "indus", "idfcbank", "aubank", "federal",
    "postbank", "dbs", "citi", "hsbc", "rbl", "kbl", "cnrb", "boi", "mahb",
}

UPI_LINK_RE = re.compile(r"upi://pay\?[^\s\"'<>]+", re.I)
URL_RE = re.compile(r"(?:https?://|www\.)[^\s\"'<>]+|\b[a-z0-9\-]+\.(?:me|io|in|ly|gd|at|gy|com)/[^\s\"'<>]+", re.I)
IFSC_RE = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
ACCOUNT_RE = re.compile(r"\b(?:a/?c|account)\s*(?:no|number|#)?\.?\s*[:\-]?\s*\d{9,18}\b", re.I)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s\-]?)?[6-9]\d{4}[\s\-]?\d{5}(?!\d)")

PAYMENT_LINK_DOMAINS = {
    "razorpay.me", "rzp.io", "razorpay.com", "paytm.me", "instamojo.com", "imjo.in", "payu.in",
    "cashfree.com", "cfre.in", "phon.pe", "paypal.me", "stripe.com",
}
SHORTENER_DOMAINS = {
    "bit.ly", "tinyurl.com", "cutt.ly", "rb.gy", "t.ly", "is.gd", "shorturl.at", "goo.gl", "tiny.cc",
}
MESSAGING_DOMAINS = {"t.me", "telegram.me", "wa.me", "chat.whatsapp.com"}

# "Rs 500", "₹500", "INR 500", "rupees 500", "500 rupees", "500/-"
_MONEY = r"(?:(?:rs\.?|inr|₹|rupees?)\s*\d[\d,]*|\d[\d,]*\s*(?:rupees?|/-))"
MONEY_RE = re.compile(_MONEY, re.I)

# A fee mentioned in a sentence like "we never charge any registration fee" is a disclaimer,
# unless the same sentence also names an amount ("no hidden charges, just pay Rs 500").
NEGATION_RE = re.compile(
    r"\b(?:never|not|no|don't|do\s+not|doesn't|does\s+not|won't|will\s+not|without|free\s+of)\b", re.I
)
SENTENCE_BREAK_RE = re.compile(r"[.!?\n]")

FEE_PATTERNS = {
    "registration fee": r"registration\s+(?:fees?|charges?|amount)",
    "security/refundable deposit": r"(?:security|refundable|caution)\s+(?:deposit|amount|fees?)",
    "'refundable' payment": r"\b(?:fully\s+)?refundable\b",
    "training fee": r"training\s+(?:fees?|charges?|kit|cost)",
    "equipment/kit charge": r"(?:laptop|kit|uniform|id\s*card)\s+(?:fees?|charges?|cost|deposit)",
    "verification fee": r"(?:document|documents|background|police)\s+(?:verification|clearance)\s+(?:fees?|charges?)",
    "processing/joining fee": r"(?:processing|onboarding|joining|application|interview|slot\s+booking|certificate)\s+(?:fees?|charges?)",
    "request to pay an amount": rf"\bpay\s+(?:an?\s+amount\s+of\s+)?{_MONEY}",
    "pay-to-confirm": rf"{_MONEY}\s*(?:only)?\s*(?:to|for)\s+(?:confirm|book|secure|register|block|reserve)",
    "fee request (Hinglish)": r"(?:fees?|paise|payment)\s+(?:bharn[aei]|jama\s+kar|de(?:ni|na|ne)\s+hog[ai])",
}

SENSITIVE_DOC_PATTERNS = {
    "Aadhaar": r"\baadh?aar\b",
    "PAN card": r"\bpan\s*card\b",
    "bank passbook/cheque": r"\bpassbook\b|\bcancell?ed\s+cheque\b",
    "selfie with ID": r"\bselfie\s+(?:holding|with)\b",
}

SECRET_PATTERNS = {
    "OTP": r"\botp\b",
    "UPI/ATM PIN": r"\b(?:upi|atm|card)\s+pin\b",
    "CVV": r"\bcvv\b",
    "banking password": r"\b(?:net\s*banking|internet\s+banking|bank\s+login)\s+password\b",
}

TASK_SCAM_PATTERNS = {
    "paid likes/reviews task": r"(?:lik(?:e|ing)|subscrib(?:e|ing)|rat(?:e|ing)|review(?:ing)?)\s+(?:the\s+|our\s+)?(?:videos?|youtube|hotels?|products?|restaurants?|movies?)",
    "earn-per-day promise": rf"earn\s+(?:up\s+to\s+)?(?:{_MONEY}|\d[\d,]*)\s*(?:per|/|a|every)\s*(?:day|task|hour)",
    "prepaid/VIP task": r"(?:prepaid|merchant|vip|premium)\s+tasks?",
    "daily income promise": r"daily\s+(?:income|earning|payout)",
}

URGENCY_PATTERNS = [
    r"\b(?:within|in)\s+\d+\s*(?:hours?|hrs?|minutes?|mins?)\b",
    r"\b(?:limited|few|only\s+\d+)\s+(?:seats|slots|positions|vacancies)\b",
    r"\b(?:last\s+date|deadline)\s+(?:is\s+)?today\b",
    r"\b(?:immediately|urgent(?:ly)?|asap)\b",
    r"\b(?:aaj\s+hi|jaldi|turant)\b",
]

JOB_CONTEXT_RE = re.compile(
    r"\b(?:job|jobs|internship|intern|offer\s+letter|hiring|recruit\w*|interview|selected|"
    r"shortlisted|stipend|salary|ctc|joining|hr|vacancy|placement|work\s+from\s+home|wfh|part[\s\-]time)\b",
    re.I,
)


def _find(patterns: dict[str, str], text: str, skip_disclaimers: bool = False) -> list[str]:
    found = []
    for name, pattern in patterns.items():
        for match in re.finditer(pattern, text, re.I):
            if not (skip_disclaimers and _is_disclaimer(text, match.start(), match.end())):
                found.append(name)
                break
    return found


def _is_disclaimer(text: str, start: int, end: int) -> bool:
    """True if the match sits in a negated sentence with no amount, e.g. 'we never charge a fee'."""
    breaks_before = [m.end() for m in SENTENCE_BREAK_RE.finditer(text, 0, start)]
    sentence_start = breaks_before[-1] if breaks_before else 0
    next_break = SENTENCE_BREAK_RE.search(text, end)
    sentence = text[sentence_start: next_break.start() if next_break else len(text)]
    return bool(NEGATION_RE.search(text[sentence_start:start])) and not MONEY_RE.search(sentence)


def extract_upi_ids(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for match in UPI_ID_RE.findall(text):
        seen.setdefault(match.lower(), None)
    return list(seen)


def check_payment(text: str) -> CheckResult:
    result = CheckResult(check="payment_request")
    signals = result.signals

    upi_ids = extract_upi_ids(text)
    upi_links = UPI_LINK_RE.findall(text)
    for link in upi_links:
        payee = parse_qs(urlparse(link).query).get("pa", [""])[0].lower()
        if payee and payee not in upi_ids:
            upi_ids.append(payee)

    payment_links, short_links, messaging_links = [], [], []
    for url in URL_RE.findall(text):
        host = urlparse(url if "://" in url else f"https://{url}").hostname or ""
        domain, _ = split_domain(host.removeprefix("www."))
        if domain in PAYMENT_LINK_DOMAINS or host in PAYMENT_LINK_DOMAINS:
            payment_links.append(url)
        elif host in SHORTENER_DOMAINS or domain in SHORTENER_DOMAINS:
            short_links.append(url)
        elif host in MESSAGING_DOMAINS or domain in MESSAGING_DOMAINS:
            messaging_links.append(url)

    has_bank_details = bool(IFSC_RE.search(text) or ACCOUNT_RE.search(text))
    phones = list(dict.fromkeys(re.sub(r"\D", "", p)[-10:] for p in PHONE_RE.findall(text)))
    fees = _find(FEE_PATTERNS, text, skip_disclaimers=True)
    task_scam = _find(TASK_SCAM_PATTERNS, text)
    documents = _find(SENSITIVE_DOC_PATTERNS, text)
    secrets = _find(SECRET_PATTERNS, text, skip_disclaimers=True)
    urgent = any(re.search(p, text, re.I) for p in URGENCY_PATTERNS)
    job_context = bool(JOB_CONTEXT_RE.search(text))

    result.details = {
        "upi_ids": upi_ids,
        "payment_links": payment_links,
        "short_links": short_links,
        "messaging_links": messaging_links,
        "phones": phones,
        "bank_details": has_bank_details,
        "fee_phrases": fees,
        "task_scam_phrases": task_scam,
        "documents_requested": documents,
        "secrets_requested": secrets,
        "job_context": job_context,
    }

    for upi_id in upi_ids:
        handle = upi_id.split("@", 1)[1]
        kind = "UPI ID" if handle in KNOWN_UPI_HANDLES else "possible UPI ID"
        signals.append(Signal(code="upi_id", points=15, message=f"Contains a {kind}: {upi_id}"))
        if reported := report_signal("upi", upi_id, f"UPI ID {upi_id}", "reported_upi"):
            signals.append(reported)

    for phone in phones:
        if reported := report_signal("phone", phone, f"Phone number ending {phone[-4:]}", "reported_phone"):
            signals.append(reported)

    if upi_links:
        signals.append(Signal(code="upi_pay_link", points=20, message="Contains a direct UPI payment link."))
    if payment_links:
        signals.append(Signal(code="payment_link", points=20, message=f"Contains a payment link: {payment_links[0]}"))
    if has_bank_details:
        signals.append(Signal(code="bank_details", points=15, message="Contains bank account / IFSC details to send money to."))
    if short_links:
        signals.append(Signal(code="short_link", points=10, message="Uses a shortened link that hides the real destination."))
    if messaging_links and job_context:
        signals.append(Signal(
            code="moves_to_messaging", points=10,
            message="Asks you to continue on Telegram/WhatsApp. Real companies hire through official channels.",
        ))

    if fees:
        signals.append(Signal(
            code="fee_language", points=min(50, 25 * len(fees)),
            message="Asks for money: " + ", ".join(fees) + ".",
        ))
    if task_scam:
        signals.append(Signal(
            code="task_scam_language", points=min(60, 30 * len(task_scam)),
            message="Matches 'task job' scam patterns: " + ", ".join(task_scam) + ".",
        ))
    if secrets:
        signals.append(Signal(
            code="secret_request", points=40,
            message="Asks for " + ", ".join(secrets) + ". No genuine employer ever needs these.",
        ))
    if documents and job_context:
        signals.append(Signal(
            code="document_request", points=min(30, 10 * len(documents)),
            message="Asks for identity documents (" + ", ".join(documents) + "). Share them only on the "
            "company's official portal after verifying the offer, never over chat.",
        ))
    if urgent:
        signals.append(Signal(code="urgency", points=10, message="Uses pressure tactics (tight deadline / limited seats)."))

    asks_for_money = bool(fees or upi_ids or upi_links or payment_links or has_bank_details)
    if asks_for_money and job_context:
        signals.append(Signal(
            code="money_in_job_context", points=25,
            message="Money is being requested in a job/internship context. Genuine employers never charge candidates.",
        ))
    return result
