from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.env import load_env

load_env()  # secrets such as ANTHROPIC_API_KEY from a local .env file

from app import network  # noqa: E402
from app.checks.chat import check_chat, looks_like_chat
from app.checks.offer_letter import UnreadablePdf, check_offer_letter
from app.checks.payment import check_payment
from app.checks.recruiter import check_recruiter, extract_emails
from app.schemas import (
    AnalysisResponse,
    AnalyzeRequest,
    ChatRequest,
    PaymentRequest,
    RecruiterRequest,
)
from app.scoring import combine

MAX_EMAILS_PER_ANALYSIS = 5
MAX_PDF_BYTES = 10_000_000
STATIC_DIR = Path(__file__).resolve().parent / "static"
SAMPLE_LETTERS_DIR = Path(__file__).resolve().parent.parent / "samples" / "letters"

app = FastAPI(
    title="Job Scam Shield",
    version="0.6.0",
    description="Detects fake job and internship offers sent to students.",
)
app.include_router(network.router)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Each feature has its own page, all linked from the home page.
PAGES = {
    "/": "index.html",
    "/check": "check.html",
    "/chat": "chat.html",
    "/offer-letter": "letter.html",
    "/report": "report.html",
    "/tools": "tools.html",
    "/dashboard": "dashboard.html",
}


def _page_route(filename: str):
    def page() -> FileResponse:
        return FileResponse(STATIC_DIR / filename)
    return page


for _path, _file in PAGES.items():
    app.add_api_route(_path, _page_route(_file), methods=["GET"], include_in_schema=False)


@app.get("/samples/letters/{name}", include_in_schema=False)
def sample_letter(name: str) -> FileResponse:
    """Demo PDFs for the offer-letter page's "try a sample" buttons."""
    available = {p.name: p for p in SAMPLE_LETTERS_DIR.glob("*.pdf")}
    if name not in available:  # only files that exist in the folder; no path tricks
        raise HTTPException(status_code=404, detail="No such sample.")
    return FileResponse(available[name], media_type="application/pdf")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/check/recruiter", response_model=AnalysisResponse)
def recruiter(req: RecruiterRequest) -> AnalysisResponse:
    return combine([check_recruiter(req.sender_email, req.claimed_company, req.online)])


@app.post("/api/check/payment", response_model=AnalysisResponse)
def payment(req: PaymentRequest) -> AnalysisResponse:
    return combine([check_payment(req.text)])


@app.post("/api/check/chat", response_model=AnalysisResponse)
def chat(req: ChatRequest) -> AnalysisResponse:
    return combine([check_chat(req.text, req.user_name, req.use_llm)])


@app.post("/api/check/offer-letter", response_model=AnalysisResponse)
def offer_letter(
    file: UploadFile = File(..., description="Offer letter PDF, max 10 MB"),
    claimed_company: str | None = Form(None, max_length=200),
    use_llm: bool = Form(False, description="Also review with the Claude API (sends the PDF to Anthropic)"),
    online: bool = Form(True),
) -> AnalysisResponse:
    data = file.file.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="The PDF is larger than 10 MB.")
    try:
        results = check_offer_letter(data, claimed_company or None, online, use_llm)
    except UnreadablePdf as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return combine(results)


@app.post("/api/analyze", response_model=AnalysisResponse)
def analyze(req: AnalyzeRequest) -> AnalysisResponse:
    """Run every check: the sender and any emails mentioned, the content, and (for chats) the scam stage."""
    emails = extract_emails(req.text)
    if req.sender_email:
        emails.insert(0, req.sender_email.strip().lower())
    emails = list(dict.fromkeys(emails))[:MAX_EMAILS_PER_ANALYSIS]

    results = [check_recruiter(e, req.claimed_company, req.online) for e in emails]
    if req.text.strip():
        results.append(check_payment(req.text))
        if looks_like_chat(req.text):
            results.append(check_chat(req.text, req.user_name, req.use_llm))
    return combine(results)
