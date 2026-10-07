from app.schemas import AnalysisResponse, CheckResult

HIGH_RISK_AT = 60
MEDIUM_RISK_AT = 30

VERDICTS = {
    "high": "High risk: this looks like a scam. Do not pay anything or share documents. "
    "Report it at cybercrime.gov.in or call 1930.",
    "medium": "Suspicious: verify the recruiter through the company's official careers page "
    "before replying or sharing anything.",
    "low": "No major red flags found. Stay careful: a genuine employer never asks you to pay.",
}


def combine(results: list[CheckResult]) -> AnalysisResponse:
    signals = [s for r in results for s in r.signals]
    score = max(0, min(100, sum(s.points for s in signals)))
    if score >= HIGH_RISK_AT:
        level = "high"
    elif score >= MEDIUM_RISK_AT:
        level = "medium"
    else:
        level = "low"
    return AnalysisResponse(
        score=score,
        level=level,
        verdict=VERDICTS[level],
        red_flags=sorted((s for s in signals if s.points > 0), key=lambda s: -s.points),
        good_signs=[s for s in signals if s.points < 0],
        checks=results,
    )
