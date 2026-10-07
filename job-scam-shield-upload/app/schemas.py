from typing import Literal

from pydantic import BaseModel, Field


class Signal(BaseModel):
    """One piece of evidence. Positive points raise the risk, negative points lower it."""

    code: str
    points: int
    message: str


class CheckResult(BaseModel):
    check: str
    signals: list[Signal] = []
    details: dict = {}


class AnalysisResponse(BaseModel):
    score: int = Field(ge=0, le=100)
    level: Literal["low", "medium", "high"]
    verdict: str
    red_flags: list[Signal]
    good_signs: list[Signal]
    checks: list[CheckResult]


class RecruiterRequest(BaseModel):
    sender_email: str = Field(max_length=320)
    claimed_company: str | None = Field(default=None, max_length=200)
    online: bool = True


class PaymentRequest(BaseModel):
    text: str = Field(max_length=50_000)


MAX_CHAT_CHARS = 200_000  # a few months of WhatsApp export


class AnalyzeRequest(BaseModel):
    text: str = Field(default="", max_length=MAX_CHAT_CHARS)
    sender_email: str | None = Field(default=None, max_length=320)
    claimed_company: str | None = Field(default=None, max_length=200)
    user_name: str | None = Field(default=None, max_length=100, description="Your own name in the chat, to skip your messages")
    use_llm: bool = Field(default=False, description="Also label the chat with the Claude API (sends the text to Anthropic)")
    online: bool = True


class ChatRequest(BaseModel):
    text: str = Field(max_length=MAX_CHAT_CHARS)
    user_name: str | None = Field(default=None, max_length=100)
    use_llm: bool = False


ReportKind = Literal["upi", "domain", "email", "phone"]
ScamType = Literal[
    "fee_demand", "task_scam", "fake_offer_letter", "identity_theft", "fake_recruiter", "other"
]
ReportState = Literal["pending", "verified", "rejected"]


class ReportRequest(BaseModel):
    kind: ReportKind
    value: str = Field(min_length=3, max_length=320)
    scam_type: ScamType = "other"
    college_code: str | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=500, description="Seen only by your college's officers")


class ReportCreated(BaseModel):
    id: int
    kind: ReportKind
    value: str
    status: ReportState
    college: str | None


class ReportStatus(BaseModel):
    kind: ReportKind
    value: str
    verified_count: int
    pending_count: int
    colleges: int


class College(BaseModel):
    code: str
    name: str


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class UserOut(BaseModel):
    name: str
    email: str
    role: Literal["officer", "admin"]
    college: str | None


class LoginResponse(BaseModel):
    token: str
    user: UserOut


class ReportOut(BaseModel):
    id: int
    kind: ReportKind
    value: str
    scam_type: ScamType
    note: str | None
    status: ReportState
    college: str | None
    created_at: str
    reviewed_at: str | None
    network_verified: int = Field(description="Verified reports of this identifier across all colleges")
    network_colleges: int


class ReviewRequest(BaseModel):
    decision: Literal["verified", "rejected"]


class CountItem(BaseModel):
    label: str
    count: int


class Stats(BaseModel):
    scope: str
    pending: int
    verified: int
    rejected: int
    verified_last_30_days: int
    by_scam_type: list[CountItem]
    by_kind: list[CountItem]


class FeedItem(BaseModel):
    kind: ReportKind
    value: str
    scam_types: list[ScamType]
    verified_reports: int
    colleges: int
    first_verified: str
    last_verified: str
