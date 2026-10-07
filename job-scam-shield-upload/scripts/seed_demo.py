"""Fill the local database with demo colleges, officer accounts and scam reports.

Usage: python scripts/seed_demo.py

LOCAL DEMO ONLY. These passwords are public (they're in this file). Never run this on a server
that real colleges use; create real accounts with `python -m app.admin` instead.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import admin, db  # noqa: E402

COLLEGES = [("Demo Institute of Technology", "DIT"), ("Sample Engineering College", "SEC")]

DEMO_USERS = [
    # name, email, password, role, college
    ("Asha Rao (Placement Officer)", "officer@dit.example", "demo-officer-dit", "officer", "DIT"),
    ("Vikram Shah (Placement Officer)", "officer@sec.example", "demo-officer-sec", "officer", "SEC"),
    ("Network Admin", "admin@network.example", "demo-admin-network", "admin", None),
]

# kind, value, scam_type, college, status, note
DEMO_REPORTS = [
    ("upi", "vipmerchant77@axl", "task_scam", "DIT", "verified", "Telegram task group, lost Rs 2000"),
    ("upi", "vipmerchant77@axl", "task_scam", "SEC", "verified", "Same UPI in a YouTube-likes scam"),
    ("domain", "tcs-careers-portal.in", "fake_offer_letter", "DIT", "verified", "Fake TCS offer letter link"),
    ("email", "tcs.hr.onboarding@gmail.com", "fake_recruiter", "SEC", "verified", "Asked for laptop deposit"),
    ("phone", "9000000001", "task_scam", "DIT", "pending", "WhatsApp 'part time job' message"),
    ("upi", "brightwave.hr@ybl", "fee_demand", "DIT", "pending", "Offer letter asked Rs 6500 deposit"),
    ("domain", "infosys-onboarding.co", "fake_offer_letter", "DIT", "pending", None),
    ("email", "hr.recruit.desk@yahoo.com", "fee_demand", "SEC", "pending", "Registration fee for internship"),
    ("upi", "genuine.shop@okaxis", "other", "DIT", "rejected", "Student's own shop UPI, reported by mistake"),
]


def main() -> None:
    for name, code in COLLEGES:
        try:
            admin.add_college(name, code)
        except sqlite3.IntegrityError:
            pass  # already seeded
    for name, email, password, role, college in DEMO_USERS:
        try:
            admin.add_user(name, email, password, role, college)
        except sqlite3.IntegrityError:
            pass

    with db.connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM reports WHERE note LIKE '%[demo]%'").fetchone()[0]:
            print("Demo reports already present.")
            ids = {}
        else:
            ids = {r["code"]: r["id"] for r in conn.execute("SELECT id, code FROM colleges")}
    for kind, value, scam_type, college, status, note in DEMO_REPORTS if ids else []:
        db.add_report(kind, value, f"{note or ''} [demo]".strip(), scam_type, ids[college], status)

    print(f"Seeded {len(COLLEGES)} colleges, {len(DEMO_USERS)} demo accounts, {len(DEMO_REPORTS) if ids else 0} reports.")
    print("Demo logins are listed in scripts/seed_demo.py (local demo only).")


if __name__ == "__main__":
    main()
