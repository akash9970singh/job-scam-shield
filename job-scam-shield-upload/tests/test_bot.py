import io
import zipfile

from app.bot import ScamShieldBot

USER = {"id": 111, "first_name": "Rahul"}


def make_bot(files=None):
    sent = []
    bot = ScamShieldBot(
        send=lambda chat_id, text: sent.append(text),
        fetch_file=lambda file_id: files[file_id],
        online=False,
    )
    return bot, sent


def update(text=None, forwarded_from=None, document=None):
    message = {"chat": {"id": 42}, "from": USER}
    if text is not None:
        message["text"] = text
    if forwarded_from:
        message["forward_origin"] = {"type": "user", "sender_user": forwarded_from}
    if document:
        message["document"] = document
    return {"update_id": 1, "message": message}


SCAMMER = {"id": 999, "first_name": "Mentor Anjali"}


def test_help():
    bot, sent = make_bot()
    bot.handle_update(update("/start"))
    assert "forward" in sent[0].lower()


def test_pasted_message_is_checked_immediately():
    bot, sent = make_bot()
    bot.handle_update(update("Internship selected! Pay registration fee Rs 999 to hr.desk@ybl today"))
    assert sent[0].startswith("🔴 HIGH RISK")


def test_forwarded_messages_are_buffered_until_check():
    bot, sent = make_bot()
    for text in [
        "You completed 3 free tasks and received Rs 450",
        "Deposit Rs 2000 for the VIP task",
        "Your account is frozen. Pay tax to withdraw.",
    ]:
        bot.handle_update(update(text, forwarded_from=SCAMMER))
    bot.handle_update(update("How do I withdraw?", forwarded_from=USER))  # the student's own message
    assert len(sent) == 1 and "/check" in sent[0]

    bot.handle_update(update("/check"))
    assert "HIGH RISK" in sent[-1]
    assert "Pressure to pay more to withdraw" in sent[-1]
    assert 42 not in bot.sessions  # buffer is cleared after checking


def test_check_with_empty_buffer():
    bot, sent = make_bot()
    bot.handle_update(update("/check"))
    assert "Nothing to check" in sent[0]


def test_whatsapp_zip_export():
    chat = (
        "5/21/26, 7:11 PM - HR: Part time job, earn Rs 3000 per day\n"
        "5/21/26, 7:12 PM - HR: Deposit Rs 5000 for the merchant task\n"
        "5/21/26, 7:13 PM - HR: Pay Rs 8000 tax to withdraw\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("WhatsApp Chat with HR.txt", chat)
    bot, sent = make_bot(files={"f1": buf.getvalue()})
    bot.handle_update(update(document={"file_id": "f1", "file_name": "WhatsApp Chat.zip", "file_size": 500}))
    assert "HIGH RISK" in sent[0]


def test_offer_letter_pdf():
    from tests.letter_factory import FAKE_LETTER, build_letter

    bot, sent = make_bot(files={"p1": build_letter(FAKE_LETTER, producer="Canva")})
    bot.handle_update(update(document={"file_id": "p1", "file_name": "Offer Letter.pdf", "file_size": 5000}))
    assert "HIGH RISK" in sent[0]
    assert "Canva" in sent[0]


def test_rejects_other_file_types():
    bot, sent = make_bot()
    bot.handle_update(update(document={"file_id": "x", "file_name": "photo.jpg", "file_size": 10}))
    assert ".txt or .zip" in sent[0]
