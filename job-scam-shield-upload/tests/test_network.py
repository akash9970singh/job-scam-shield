import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import admin, auth, db
from app.checks.payment import check_payment
from app.main import app

client = TestClient(app)
PASSWORD = "correct-horse-battery"


@pytest.fixture
def network():
    admin.add_college("Demo Institute of Technology", "DIT")
    admin.add_college("Sample Engineering College", "SEC")
    admin.add_user("Asha", "officer@dit.example", PASSWORD, "officer", "DIT")
    admin.add_user("Vikram", "officer@sec.example", PASSWORD, "officer", "SEC")
    admin.add_user("Admin", "admin@network.example", PASSWORD, "admin")


def login(email):
    resp = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def report(value="scam.hr@ybl", college="DIT", kind="upi", scam_type="fee_demand"):
    resp = client.post("/api/reports", json={"kind": kind, "value": value, "scam_type": scam_type,
                                             "college_code": college, "note": "asked Rs 999"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_password_hashing():
    stored = auth.hash_password(PASSWORD)
    assert stored.startswith("scrypt$") and PASSWORD not in stored
    assert auth.verify_password(PASSWORD, stored)
    assert not auth.verify_password("wrong-password", stored)


def test_login_me_logout(network):
    assert client.post("/api/auth/login", json={"email": "officer@dit.example", "password": "nope"}).status_code == 401
    headers = login("OFFICER@dit.example")  # emails are case-insensitive
    assert client.get("/api/auth/me", headers=headers).json()["college"] == "Demo Institute of Technology"
    assert client.post("/api/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_officer_routes_need_login():
    for path in ["/api/officer/reports", "/api/officer/stats", "/api/network/feed", "/api/network/feed.csv"]:
        assert client.get(path).status_code == 401


def test_officers_only_see_and_review_their_own_college(network):
    dit_report = report(college="DIT")
    sec_report = report(college="SEC")
    dit = login("officer@dit.example")

    assert [r["id"] for r in client.get("/api/officer/reports", headers=dit).json()] == [dit_report]
    resp = client.post(f"/api/officer/reports/{sec_report}/review", json={"decision": "verified"}, headers=dit)
    assert resp.status_code == 404

    everyone = login("admin@network.example")
    ids = {r["id"] for r in client.get("/api/officer/reports", headers=everyone).json()}
    assert ids == {dit_report, sec_report}


def test_verification_flows_into_scam_checks(network):
    text = "Internship selected! Pay registration fee Rs 999 to scam.hr@ybl"
    first, second = report(college="DIT"), report(college="SEC")

    pending = {s.code for s in check_payment(text).signals}
    assert "reported_upi_unverified" in pending

    client.post(f"/api/officer/reports/{first}/review", json={"decision": "verified"},
                headers=login("officer@dit.example"))
    client.post(f"/api/officer/reports/{second}/review", json={"decision": "verified"},
                headers=login("officer@sec.example"))

    flag = next(s for s in check_payment(text).signals if s.code == "reported_upi")
    assert "2 college(s)" in flag.message


def test_report_validation(network):
    cases = [
        {"kind": "phone", "value": "12345"},
        {"kind": "upi", "value": "not a upi"},
        {"kind": "domain", "value": "gmail.com"},
        {"kind": "email", "value": "nobody"},
        {"kind": "upi", "value": "x.y@ybl", "college_code": "NOPE"},
        {"kind": "upi", "value": "x.y@ybl", "scam_type": "made_up"},
    ]
    for body in cases:
        assert client.post("/api/reports", json=body).status_code == 422, body


def test_report_rate_limit():
    for i in range(auth.report_limiter.limit):
        assert client.post("/api/reports", json={"kind": "upi", "value": f"spam{i}@ybl"}).status_code == 201
    assert client.post("/api/reports", json={"kind": "upi", "value": "one.more@ybl"}).status_code == 429


def test_stats_feed_and_csv(network):
    verified = report(value="feed.scam@ybl", scam_type="task_scam")
    report(value="still.pending@ybl")
    rejected = report(value="mistake@ybl")
    dit = login("officer@dit.example")
    client.post(f"/api/officer/reports/{verified}/review", json={"decision": "verified"}, headers=dit)
    client.post(f"/api/officer/reports/{rejected}/review", json={"decision": "rejected"}, headers=dit)

    stats = client.get("/api/officer/stats", headers=dit).json()
    assert (stats["pending"], stats["verified"], stats["rejected"], stats["verified_last_30_days"]) == (1, 1, 1, 1)
    assert {i["label"] for i in stats["by_scam_type"]} == {"task_scam", "fee_demand"}  # rejected excluded

    feed = client.get("/api/network/feed", headers=dit).json()
    assert [(f["value"], f["scam_types"], f["colleges"]) for f in feed] == [("feed.scam@ybl", ["task_scam"], 1)]
    csv_text = client.get("/api/network/feed.csv", headers=dit).text
    assert "feed.scam@ybl" in csv_text and "still.pending" not in csv_text


def test_login_rate_limit(network):
    for _ in range(auth.login_limiter.limit):
        client.post("/api/auth/login", json={"email": "officer@dit.example", "password": "guess"})
    resp = client.post("/api/auth/login", json={"email": "officer@dit.example", "password": PASSWORD})
    assert resp.status_code == 429


def test_old_database_is_upgraded(tmp_path, monkeypatch):
    path = tmp_path / "phase1.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE reports (id INTEGER PRIMARY KEY, kind TEXT, value TEXT, note TEXT, created_at TEXT)")
        conn.execute("INSERT INTO reports (kind, value, created_at) VALUES ('upi', 'old@ybl', '2026-01-01')")
    monkeypatch.setenv("SHIELD_DB_PATH", str(path))
    summary = db.report_summary("upi", "old@ybl")
    assert (summary.pending, summary.verified) == (1, 0)  # never reviewed, so pending


def test_admin_cli(capsys):
    assert admin.main(["add-college", "Test College", "tc"]) == 0
    assert admin.main(["add-officer", "--college", "TC", "--name", "T", "--email", "t@tc.example",
                       "--generate-password"]) == 0
    assert "Generated password" in capsys.readouterr().out
    assert admin.main(["add-college", "Again", "TC"]) == 1  # duplicate code
    assert admin.main(["add-officer", "--name", "X", "--email", "x@x.example", "--generate-password"]) == 1
