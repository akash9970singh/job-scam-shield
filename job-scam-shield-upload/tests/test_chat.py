from types import SimpleNamespace

from app.checks import llm
from app.checks.chat import check_chat, looks_like_chat, parse_chat
from app.scoring import combine

WHATSAPP_ANDROID = """5/21/26, 7:11 PM - Messages and calls are end-to-end encrypted.
5/21/26, 7:11 PM - +91 90000 00001: Hi, we found your profile on Naukri. Part time job, earn Rs 3000 per day!
5/21/26, 7:12 PM - Rahul: what is the work?
5/21/26, 7:13 PM - +91 90000 00001: Join our Telegram group: https://t.me/daily_tasks_hr
5/22/26, 10:02 AM - +91 90000 00001: You completed 3 tasks and received Rs 450. Great work!
5/22/26, 10:05 AM - +91 90000 00001: Now deposit Rs 5,000 for the VIP task
and you will get Rs 6,500 back.
5/23/26, 9:00 AM - Rahul: I want to withdraw my money
5/23/26, 9:01 AM - +91 90000 00001: Your account is frozen. Pay Rs 8,000 tax to withdraw."""

WHATSAPP_IOS = """[21/05/26, 7:11:03 PM] HR Neha: Hello, flexible part-time job available
[21/05/26, 7:12:10 PM] HR Neha: Simple work: like YouTube videos, Rs 50 each"""


def stage_by_preview(result, snippet):
    return next(t["stage"] for t in result.details["timeline"] if snippet in t["preview"])


def test_parses_android_export_with_continuation_lines():
    messages = parse_chat(WHATSAPP_ANDROID)
    assert len(messages) == 7  # the system line is dropped
    assert messages[0].sender == "+91 90000 00001"
    assert "you will get Rs 6,500 back" in messages[4].text


def test_parses_ios_export():
    messages = parse_chat(WHATSAPP_IOS)
    assert [m.sender for m in messages] == ["HR Neha", "HR Neha"]


def test_single_message_is_not_a_chat():
    assert not looks_like_chat("Dear Candidate,\nYou are selected.\nRegards,\nHR")


def test_full_task_scam_reaches_pressure_stage():
    result = check_chat(WHATSAPP_ANDROID, user_name="Rahul")
    assert result.details["furthest_stage"] == "pressure"
    assert stage_by_preview(result, "deposit Rs 5,000") == "money_ask"
    codes = {s.code for s in result.signals}
    assert {"chat_stage_pressure", "scam_script_progression"} <= codes
    assert combine([result]).level == "high"


def test_users_own_messages_are_ignored():
    result = check_chat(WHATSAPP_ANDROID, user_name="Rahul")
    assert all(t["sender"] != "Rahul" for t in result.details["timeline"])


def test_early_stage_chat_is_not_high_risk():
    result = check_chat(WHATSAPP_IOS)
    assert result.details["furthest_stage"] == "trust_task"
    assert combine([result]).level == "low"


def test_llm_labels_override_rules(monkeypatch):
    chat = "Neha: Hello dear\nNeha: Please send 2000 to unlock your earnings"
    parsed = SimpleNamespace(
        labels=[SimpleNamespace(index=1, stage="pressure", reason="demands money to release earnings")],
        summary="Asks for money to release earnings.",
    )
    fake_client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(
        parse=lambda **kwargs: SimpleNamespace(stop_reason="end_turn", parsed_output=parsed),
    )))
    monkeypatch.setattr(llm, "_get_client", lambda: fake_client)

    result = check_chat(chat, use_llm=True)
    assert result.details["llm_used"]
    assert result.details["furthest_stage"] == "pressure"
    assert result.details["timeline"][1]["source"] == "claude"


def test_llm_failure_falls_back_to_rules(monkeypatch):
    def broken_client():
        raise TypeError("Could not resolve authentication method")

    monkeypatch.setattr(llm, "_get_client", broken_client)
    result = check_chat(WHATSAPP_ANDROID, user_name="Rahul", use_llm=True)
    assert not result.details["llm_used"]
    assert result.details["furthest_stage"] == "pressure"
