"""College threat-intel network (#5): student reports, officer review, and the shared feed.

Students report without an account. Placement officers verify or reject reports from their own
college; admins see every college. Verified identifiers are shared across the whole network.
Notes stay inside the reporting college; the network feed shares only the identifier.
"""

import csv
import io
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import PlainTextResponse

from app import auth, db
from app.auth import User, current_user
from app.checks.recruiter import EMAIL_RE, FREE_EMAIL_PROVIDERS
from app.schemas import (
    College,
    CountItem,
    FeedItem,
    LoginRequest,
    LoginResponse,
    ReportCreated,
    ReportKind,
    ReportOut,
    ReportRequest,
    ReportState,
    ReportStatus,
    ReviewRequest,
    Stats,
    UserOut,
)

FEED_LIMIT = 200
REPORT_LIST_LIMIT = 300
UPI_RE = re.compile(r"^[\w.\-]{2,256}@[a-z][a-z0-9]{1,63}$")
PHONE_RE = re.compile(r"^[6-9]\d{9}$")
DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

router = APIRouter(prefix="/api")


# ---------- validation ----------

def validate_identifier(kind: str, value: str) -> str:
    """Return the normalized identifier, or raise ValueError with a message for the student."""
    normalized = db.normalize(kind, value)
    if kind == "upi" and not UPI_RE.match(normalized):
        raise ValueError("That doesn't look like a UPI ID (for example name@ybl).")
    if kind == "phone" and not PHONE_RE.match(normalized):
        raise ValueError("Enter a 10-digit Indian mobile number.")
    if kind == "email" and not EMAIL_RE.fullmatch(normalized):
        raise ValueError("That doesn't look like an email address.")
    if kind == "domain":
        if not DOMAIN_RE.match(normalized):
            raise ValueError("That doesn't look like a website domain (for example fake-hr.in).")
        if normalized in FREE_EMAIL_PROVIDERS:
            raise ValueError(f"Report the full email address, not {normalized} itself.")
    return normalized


# ---------- data access ----------

def list_colleges() -> list[College]:
    with db.connect() as conn:
        rows = conn.execute("SELECT code, name FROM colleges ORDER BY name").fetchall()
    return [College(code=r["code"], name=r["name"]) for r in rows]


def college_by_code(code: str) -> tuple[int, str] | None:
    with db.connect() as conn:
        row = conn.execute("SELECT id, name FROM colleges WHERE code = ?", (code.strip().upper(),)).fetchone()
    return (row["id"], row["name"]) if row else None


def _scope(user: User, alias: str = "r") -> tuple[str, tuple]:
    """SQL filter limiting an officer to their own college. Admins see everything."""
    if user.is_admin:
        return "1 = 1", ()
    return f"{alias}.college_id = ?", (user.college_id,)


REPORT_SELECT = """
    SELECT r.id, r.kind, r.value, r.scam_type, r.note, r.status, r.created_at, r.reviewed_at,
           c.name AS college,
           (SELECT COUNT(*) FROM reports v
             WHERE v.kind = r.kind AND v.value = r.value AND v.status = 'verified') AS network_verified,
           (SELECT COUNT(DISTINCT v.college_id) FROM reports v
             WHERE v.kind = r.kind AND v.value = r.value AND v.status = 'verified') AS network_colleges
    FROM reports r LEFT JOIN colleges c ON c.id = r.college_id
"""


def list_reports(user: User, state: ReportState | None) -> list[ReportOut]:
    where, params = _scope(user)
    if state:
        where += " AND r.status = ?"
        params += (state,)
    with db.connect() as conn:
        rows = conn.execute(
            f"{REPORT_SELECT} WHERE {where} ORDER BY r.created_at DESC LIMIT ?",
            (*params, REPORT_LIST_LIMIT),
        ).fetchall()
    return [ReportOut(**dict(r)) for r in rows]


def review_report(user: User, report_id: int, decision: str) -> ReportOut:
    where, params = _scope(user)
    with db.connect() as conn:
        found = conn.execute(f"SELECT r.id FROM reports r WHERE r.id = ? AND {where}", (report_id, *params)).fetchone()
        if not found:
            # Same answer for "doesn't exist" and "another college's report".
            raise HTTPException(status_code=404, detail="Report not found.")
        conn.execute(
            "UPDATE reports SET status = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?",
            (decision, user.id, db.now(), report_id),
        )
        row = conn.execute(f"{REPORT_SELECT} WHERE r.id = ?", (report_id,)).fetchone()
    return ReportOut(**dict(row))


def college_stats(user: User) -> Stats:
    where, params = _scope(user)
    month_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    with db.connect() as conn:
        totals = conn.execute(
            f"""SELECT SUM(status = 'pending') AS pending, SUM(status = 'verified') AS verified,
                       SUM(status = 'rejected') AS rejected,
                       SUM(status = 'verified' AND COALESCE(reviewed_at, created_at) >= ?) AS recent
                FROM reports r WHERE {where}""",
            (month_ago, *params),
        ).fetchone()

        def breakdown(column: str) -> list[CountItem]:
            rows = conn.execute(
                f"""SELECT {column} AS label, COUNT(*) AS count FROM reports r
                    WHERE {where} AND status != 'rejected' GROUP BY {column} ORDER BY count DESC""",
                params,
            ).fetchall()
            return [CountItem(label=r["label"], count=r["count"]) for r in rows]

        by_type, by_kind = breakdown("scam_type"), breakdown("kind")
    return Stats(
        scope="All colleges" if user.is_admin else (user.college_name or "Your college"),
        pending=totals["pending"] or 0,
        verified=totals["verified"] or 0,
        rejected=totals["rejected"] or 0,
        verified_last_30_days=totals["recent"] or 0,
        by_scam_type=by_type,
        by_kind=by_kind,
    )


def network_feed(limit: int = FEED_LIMIT) -> list[FeedItem]:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT kind, value, GROUP_CONCAT(DISTINCT scam_type) AS scam_types,
                      COUNT(*) AS verified_reports, COUNT(DISTINCT college_id) AS colleges,
                      MIN(COALESCE(reviewed_at, created_at)) AS first_verified,
                      MAX(COALESCE(reviewed_at, created_at)) AS last_verified
               FROM reports WHERE status = 'verified'
               GROUP BY kind, value ORDER BY last_verified DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [FeedItem(**{**dict(r), "scam_types": r["scam_types"].split(",")}) for r in rows]


# ---------- public routes ----------

@router.get("/colleges", response_model=list[College])
def colleges() -> list[College]:
    return list_colleges()


@router.post("/reports", response_model=ReportCreated, status_code=201,
             dependencies=[Depends(auth.report_limiter)])
def create_report(req: ReportRequest) -> ReportCreated:
    try:
        value = validate_identifier(req.kind, req.value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    college = college_by_code(req.college_code) if req.college_code else None
    if req.college_code and not college:
        raise HTTPException(status_code=422, detail="Unknown college code.")
    report_id = db.add_report(
        req.kind, value, (req.note or "").strip() or None, req.scam_type, college[0] if college else None,
    )
    return ReportCreated(id=report_id, kind=req.kind, value=value, status="pending",
                         college=college[1] if college else None)


@router.get("/reports/{kind}/{value}", response_model=ReportStatus)
def report_status(kind: ReportKind, value: str) -> ReportStatus:
    summary = db.report_summary(kind, value)
    return ReportStatus(kind=kind, value=db.normalize(kind, value), verified_count=summary.verified,
                        pending_count=summary.pending, colleges=summary.colleges)


# ---------- officer routes ----------

def _user_out(user: User) -> UserOut:
    return UserOut(name=user.name, email=user.email, role=user.role, college=user.college_name)


@router.post("/auth/login", response_model=LoginResponse, dependencies=[Depends(auth.login_limiter)])
def login(req: LoginRequest) -> LoginResponse:
    result = auth.login(req.email, req.password)
    if not result:
        raise HTTPException(status_code=401, detail="Wrong email or password.")
    token, user = result
    return LoginResponse(token=token, user=_user_out(user))


@router.post("/auth/logout", status_code=204)
def logout(_user: User = Depends(current_user), credentials=Depends(auth.bearer)) -> Response:
    auth.logout(credentials.credentials)
    return Response(status_code=204)


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return _user_out(user)


@router.get("/officer/reports", response_model=list[ReportOut])
def officer_reports(
    state: Literal["pending", "verified", "rejected", "all"] = "pending", user: User = Depends(current_user)
) -> list[ReportOut]:
    return list_reports(user, None if state == "all" else state)


@router.post("/officer/reports/{report_id}/review", response_model=ReportOut)
def officer_review(report_id: int, req: ReviewRequest, user: User = Depends(current_user)) -> ReportOut:
    return review_report(user, report_id, req.decision)


@router.get("/officer/stats", response_model=Stats)
def officer_stats(user: User = Depends(current_user)) -> Stats:
    return college_stats(user)


@router.get("/network/feed", response_model=list[FeedItem])
def feed(_user: User = Depends(current_user)) -> list[FeedItem]:
    return network_feed()


@router.get("/network/feed.csv", response_class=PlainTextResponse)
def feed_csv(_user: User = Depends(current_user)) -> PlainTextResponse:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["kind", "value", "scam_types", "verified_reports", "colleges", "first_verified", "last_verified"])
    for item in network_feed():
        # A leading = + - @ makes Excel treat the cell as a formula.
        value = f"'{item.value}" if item.value[:1] in "=+-@" else item.value
        writer.writerow([item.kind, value, ";".join(item.scam_types), item.verified_reports,
                         item.colleges, item.first_verified, item.last_verified])
    return PlainTextResponse(
        out.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="scam-feed.csv"'},
    )
