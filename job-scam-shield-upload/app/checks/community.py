"""Signals from the college network's scam reports (#5).

Verified reports are strong evidence. Pending reports count for little, so one false or
malicious report can't brand a genuine recruiter as a scammer.
"""

from app import db
from app.schemas import Signal

VERIFIED_POINTS = 50
PENDING_POINTS = 15


def report_signal(kind: str, value: str, label: str, code: str) -> Signal | None:
    summary = db.report_summary(kind, value)
    if summary.verified:
        where = f"by {summary.colleges} college(s)" if summary.colleges else "by placement officers"
        return Signal(
            code=code, points=VERIFIED_POINTS,
            message=f"{label} is a verified scam: confirmed {where} in the network "
            f"({summary.verified} verified report(s)).",
        )
    if summary.pending:
        return Signal(
            code=f"{code}_unverified", points=PENDING_POINTS,
            message=f"{label} was reported as a scam by {summary.pending} student(s); not yet verified.",
        )
    return None
