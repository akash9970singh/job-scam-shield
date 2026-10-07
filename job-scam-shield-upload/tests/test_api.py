from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_analyze_combines_checks():
    resp = client.post("/api/analyze", json={
        "text": "You are selected for internship at TCS. Pay registration fee Rs 999 to tcs.hr@ybl",
        "sender_email": "tcs.recruit@gmail.com",
        "claimed_company": "TCS",
        "online": False,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["level"] == "high"
    assert {c["check"] for c in data["checks"]} == {"recruiter_identity", "payment_request"}


def test_report_roundtrip():
    resp = client.post("/api/reports", json={"kind": "upi", "value": "Scam@YBL"})
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"
    status = client.get("/api/reports/upi/scam@ybl").json()
    assert (status["pending_count"], status["verified_count"]) == (1, 0)


def test_report_rejects_unknown_kind():
    assert client.post("/api/reports", json={"kind": "bitcoin", "value": "abc123"}).status_code == 422
