"""Telegram bot: students forward or paste suspicious job messages and get a scam verdict.

Run:  put TELEGRAM_BOT_TOKEN=... (from @BotFather) in .env, then  python -m app.bot
Set SHIELD_USE_LLM=1 to also label chats with the Claude API (needs ANTHROPIC_API_KEY).

Forwarded messages are held in memory only until /check (or 30 minutes), never written to disk.
"""

import io
import logging
import os
import time
import zipfile
from dataclasses import dataclass, field
from typing import Callable

import httpx

from app.checks.offer_letter import UnreadablePdf, check_offer_letter
from app.env import load_env
from app.main import MAX_PDF_BYTES, analyze
from app.schemas import MAX_CHAT_CHARS, AnalysisResponse, AnalyzeRequest
from app.scoring import combine

log = logging.getLogger("scam_shield_bot")

TELEGRAM_API = "https://api.telegram.org"
BUFFER_TTL_SECONDS = 30 * 60
MAX_BUFFERED_MESSAGES = 300
MAX_FILE_BYTES = 2_000_000
MAX_REPLY_CHARS = 4000  # Telegram's limit is 4096
MAX_FLAGS_SHOWN = 6
ME = "Me"

LEVEL_LABELS = {"high": "🔴 HIGH RISK", "medium": "🟠 SUSPICIOUS", "low": "🟢 LOW RISK"}

HELP_TEXT = """👋 I check job and internship messages for scams.

• Paste a message → I check it right away.
• Forward several messages from a chat → then send /check to analyse them together.
• Send a WhatsApp chat export (.txt or .zip, "Without media") → I analyse the whole chat.
• Send an offer letter PDF → I check it for signs of forgery.

/check – analyse the forwarded messages
/clear – forget the forwarded messages
/help – show this message

I don't store your messages. Report fraud at cybercrime.gov.in or call 1930."""


@dataclass
class Session:
    lines: list[str] = field(default_factory=list)
    updated: float = field(default_factory=time.monotonic)


class ScamShieldBot:
    def __init__(
        self,
        send: Callable[[int, str], None],
        fetch_file: Callable[[str], bytes],
        use_llm: bool = False,
        online: bool = True,
    ):
        self.send = send
        self.fetch_file = fetch_file
        self.use_llm = use_llm
        self.online = online
        self.sessions: dict[int, Session] = {}

    def handle_update(self, update: dict) -> None:
        message = update.get("message")
        if not message:
            return
        chat_id = message["chat"]["id"]
        self._expire_sessions()
        text = (message.get("text") or message.get("caption") or "").strip()
        command = text.split()[0].split("@")[0].lower() if text.startswith("/") else None
        # Log only the kind of message, never its content.
        kind = command or ("file" if message.get("document") else "forward" if _is_forwarded(message) else "text")
        log.info("Received %s", kind)

        if command in ("/start", "/help"):
            self.send(chat_id, HELP_TEXT)
        elif command == "/check":
            self._check_buffer(chat_id)
        elif command == "/clear":
            self.sessions.pop(chat_id, None)
            self.send(chat_id, "Cleared. Nothing is saved.")
        elif command:
            self.send(chat_id, "Unknown command. Send /help to see what I can do.")
        elif message.get("document"):
            self._check_document(chat_id, message["document"])
        elif _is_forwarded(message):
            self._buffer(chat_id, message, text)
        elif text:
            self._reply_with_analysis(chat_id, text)
        else:
            self.send(chat_id, "Please send text, forwarded messages or a chat export (.txt/.zip).")

    def _buffer(self, chat_id: int, message: dict, text: str) -> None:
        if not text:
            return
        session = self.sessions.setdefault(chat_id, Session())
        if len(session.lines) >= MAX_BUFFERED_MESSAGES:
            self.send(chat_id, f"I can hold {MAX_BUFFERED_MESSAGES} messages at a time. Send /check now.")
            return
        sender = _forward_sender(message)
        # "Name: text" lines let the chat parser rebuild the conversation.
        session.lines.append(f"{sender}: {' '.join(text.split())}")
        session.updated = time.monotonic()
        if len(session.lines) == 1:
            self.send(chat_id, "Got it. Forward the rest of the conversation, then send /check.")

    def _check_buffer(self, chat_id: int) -> None:
        session = self.sessions.pop(chat_id, None)
        if not session or not session.lines:
            self.send(chat_id, "Nothing to check yet. Forward some messages first, or just paste one.")
            return
        self._reply_with_analysis(chat_id, "\n".join(session.lines))

    def _check_document(self, chat_id: int, document: dict) -> None:
        name = (document.get("file_name") or "").lower()
        is_pdf = name.endswith(".pdf") or document.get("mime_type") == "application/pdf"
        if not (is_pdf or name.endswith((".txt", ".zip"))):
            self.send(chat_id, "Send an offer letter as PDF, or a WhatsApp export as .txt or .zip.")
            return
        if document.get("file_size", 0) > (MAX_PDF_BYTES if is_pdf else MAX_FILE_BYTES):
            self.send(chat_id, "That file is too large.")
            return
        if is_pdf:
            self._check_offer_letter(chat_id, document["file_id"])
            return
        try:
            data = self.fetch_file(document["file_id"])
            text = _read_chat_export(data, is_zip=name.endswith(".zip"))
        except (httpx.HTTPError, KeyError, ValueError, zipfile.BadZipFile) as exc:
            log.warning("Could not read uploaded file: %s", exc)
            self.send(chat_id, "Sorry, I couldn't read that file. Try exporting the chat again.")
            return
        self._reply_with_analysis(chat_id, text)

    def _check_offer_letter(self, chat_id: int, file_id: str) -> None:
        try:
            data = self.fetch_file(file_id)
            results = check_offer_letter(data, online=self.online, use_llm=self.use_llm)
        except UnreadablePdf as exc:
            self.send(chat_id, f"Sorry, I couldn't read that PDF. {exc}")
            return
        except (httpx.HTTPError, KeyError) as exc:
            log.warning("Could not download PDF: %s", type(exc).__name__)
            self.send(chat_id, "Sorry, I couldn't download that file. Please try again.")
            return
        self.send(chat_id, format_reply(combine(results)))

    def _reply_with_analysis(self, chat_id: int, text: str) -> None:
        if len(text) > MAX_CHAT_CHARS:
            text = text[-MAX_CHAT_CHARS:]  # keep the most recent part of a long chat
        result = analyze(AnalyzeRequest(text=text, user_name=ME, use_llm=self.use_llm, online=self.online))
        self.send(chat_id, format_reply(result))

    def _expire_sessions(self) -> None:
        cutoff = time.monotonic() - BUFFER_TTL_SECONDS
        for chat_id in [c for c, s in self.sessions.items() if s.updated < cutoff]:
            del self.sessions[chat_id]


def _is_forwarded(message: dict) -> bool:
    return "forward_origin" in message or "forward_date" in message


def _forward_sender(message: dict) -> str:
    origin = message.get("forward_origin") or {}
    user = origin.get("sender_user") or message.get("forward_from")
    if user and user.get("id") == (message.get("from") or {}).get("id"):
        return ME
    if user:
        return user.get("first_name") or "Sender"
    chat = origin.get("chat") or origin.get("sender_chat") or message.get("forward_from_chat")
    if chat:
        return chat.get("title") or "Channel"
    return origin.get("sender_user_name") or message.get("forward_sender_name") or "Sender"


def _read_chat_export(data: bytes, is_zip: bool) -> str:
    if is_zip:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            texts = [i for i in archive.infolist() if i.filename.lower().endswith(".txt")]
            if not texts:
                raise ValueError("no .txt file in the zip")
            if texts[0].file_size > MAX_FILE_BYTES:
                raise ValueError("chat file in the zip is too large")
            data = archive.read(texts[0])
    return data.decode("utf-8-sig", errors="replace")


def format_reply(result: AnalysisResponse) -> str:
    lines = [f"{LEVEL_LABELS[result.level]} · {result.score}/100", "", result.verdict]

    chat = next((c for c in result.checks if c.check == "chat_stages"), None)
    if chat and chat.details.get("furthest_stage"):
        from app.checks.chat import STAGES

        lines += ["", "Scam stage reached: " + STAGES[chat.details["furthest_stage"]][1]]
        if chat.details.get("llm_summary"):
            lines.append(chat.details["llm_summary"])

    if result.red_flags:
        lines += ["", "Red flags:"]
        lines += [f"• {flag.message}" for flag in result.red_flags[:MAX_FLAGS_SHOWN]]
    if result.good_signs:
        lines += ["", "Good signs:"]
        lines += [f"• {sign.message}" for sign in result.good_signs]

    reply = "\n".join(lines)
    return reply if len(reply) <= MAX_REPLY_CHARS else reply[: MAX_REPLY_CHARS - 1] + "…"


COMMANDS = [
    {"command": "check", "description": "Analyse the messages you forwarded"},
    {"command": "clear", "description": "Forget the forwarded messages"},
    {"command": "help", "description": "How to use this bot"},
]
DESCRIPTION = ("I check job and internship offers for scams. Paste a message, forward a chat, "
               "or send a WhatsApp export or an offer letter PDF.")


def _register_commands(client: httpx.Client) -> None:
    """Show the commands in Telegram's "/" menu and describe the bot on its start screen."""
    try:
        client.post("setMyCommands", json={"commands": COMMANDS})
        client.post("setMyDescription", json={"description": DESCRIPTION})
        client.post("setMyShortDescription", json={"short_description": "Checks job offers for scams."})
    except httpx.HTTPError as exc:
        log.warning("Couldn't register bot commands: %s", type(exc).__name__)


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # httpx logs every request URL at INFO, and Telegram URLs contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Put TELEGRAM_BOT_TOKEN=... in a .env file (see .env.example), "
                         "or set the environment variable. Get a token from @BotFather on Telegram.")

    client = httpx.Client(base_url=f"{TELEGRAM_API}/bot{token}/", timeout=40)

    def send(chat_id: int, text: str) -> None:
        try:
            client.post("sendMessage", json={"chat_id": chat_id, "text": text})
        except httpx.HTTPError as exc:
            log.warning("sendMessage failed: %s", type(exc).__name__)

    def fetch_file(file_id: str) -> bytes:
        info = client.get("getFile", params={"file_id": file_id}).json()["result"]
        resp = httpx.get(f"{TELEGRAM_API}/file/bot{token}/{info['file_path']}", timeout=30)
        resp.raise_for_status()
        return resp.content

    bot = ScamShieldBot(send, fetch_file, use_llm=os.environ.get("SHIELD_USE_LLM") == "1")
    _register_commands(client)
    log.info("Bot started. Press Ctrl+C to stop.")

    offset = None
    while True:
        try:
            data = client.get("getUpdates", params={"timeout": 30, "offset": offset}).json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("getUpdates failed (%s); retrying in 5s.", type(exc).__name__)
            time.sleep(5)
            continue
        if not data.get("ok"):
            if data.get("error_code") == 401:
                raise SystemExit("Telegram rejected the bot token. Check TELEGRAM_BOT_TOKEN.")
            log.warning("Telegram error: %s", data.get("description"))
            time.sleep(5)
            continue
        for update in data["result"]:
            offset = update["update_id"] + 1
            try:
                bot.handle_update(update)
            except Exception:
                # One bad message must not take the bot down for everyone.
                log.exception("Failed to handle update %s", update.get("update_id"))


if __name__ == "__main__":
    run()
