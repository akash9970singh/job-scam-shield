"""Check #1: which stage of the job/task-scam script has a conversation reached?

Task scams follow a script: contact -> move to Telegram/WhatsApp -> small paid "trust" tasks ->
deposit request -> "pay more to withdraw". Single messages look harmless; the sequence does not.

Rules work offline. With use_llm=True the Claude API labels messages the rules miss.
"""

import re
from dataclasses import dataclass, field

from app.schemas import CheckResult, Signal

# Ordered: a later stage means the scam is further along.
STAGES = {
    "contact": (1, "Unsolicited job offer / hook"),
    "off_platform": (2, "Moved to Telegram or WhatsApp"),
    "trust_task": (3, "Small paid task to build trust"),
    "money_ask": (4, "Asked to deposit or pay"),
    "pressure": (5, "Pressure to pay more to withdraw"),
}

STAGE_PATTERNS = {
    "pressure": [
        r"\bwithdraw(?:al)?\b",
        r"\b(?:tax|clearance|unfreeze|frozen|penalty|credit\s+score|upgrade\s+fee)\b",
        r"\b(?:one\s+more|remaining|combo|final)\s+tasks?\b",
        r"\bpay\s+(?:again|more|the\s+difference)\b",
        r"\blose\s+(?:your|all|the)\s+(?:money|amount|commission|deposit)\b",
        r"\blegal\s+action\b",
    ],
    "money_ask": [
        r"\b(?:deposit|top[\s\-]?up|recharge|invest)\b",
        r"\b(?:prepaid|merchant|vip|premium)\s+tasks?\b",
        r"\b(?:registration|joining|processing|activation)\s+(?:fees?|charges?)\b",
        r"\bpay\s+(?:rs\.?|inr|₹)?\s*\d",
        r"\bupi://pay\b",
        r"[\w.\-]{2,}@(?:ybl|ibl|axl|paytm|okaxis|okhdfcbank|okicici|oksbi|upi|apl)\b",
        r"\bactivate\s+(?:your\s+)?(?:account|id|wallet)\b",
    ],
    "trust_task": [
        r"\b(?:free|trial|simple|first|demo)\s+tasks?\b",
        r"\bcompleted?\s+\d+\s+tasks?\b",
        r"\b(?:received|credited|got)\s+(?:rs\.?|inr|₹)?\s*\d",
        r"\bcommission\b",
        r"\b(?:send|share)\s+(?:the\s+)?screenshots?\b",
        r"\b(?:lik(?:e|ing)|subscrib(?:e|ing)|rat(?:e|ing)|review(?:ing)?)\s+(?:the\s+|our\s+)?(?:videos?|youtube|hotels?|products?|restaurants?|movies?)",
    ],
    "off_platform": [
        r"\b(?:t\.me|telegram\.me|wa\.me|chat\.whatsapp\.com)/",
        r"\b(?:join|add\s+you\s+to)\s+(?:our|the|a|my)\s+(?:telegram|whatsapp)?\s*(?:group|channel)\b",
        r"\b(?:contact|message|text)\s+(?:our\s+|my\s+)?(?:hr|mentor|receptionist|teacher|manager)\s+on\s+(?:telegram|whatsapp)\b",
        r"\b(?:on|via)\s+telegram\b",
    ],
    "contact": [
        r"\b(?:found|saw|got)\s+your\s+(?:profile|resume|cv|number)\b",
        r"\bpart[\s\-]?time\s+(?:job|role|work|opportunity)\b",
        r"\bwork\s+from\s+home\b",
        r"\bearn\s+(?:up\s+to\s+)?(?:rs\.?|inr|₹)?\s*\d[\d,]*\s*(?:per|/|a|every)\s*(?:day|task|hour)\b",
        r"\b(?:we\s+are\s+)?hiring\b",
        r"\b(?:flexible|easy|simple)\s+(?:job|work|role)\b",
    ],
}

# WhatsApp exports: Android "5/21/26, 7:11 PM - Name: text", iOS "[21/05/26, 7:11:03 PM] Name: text".
WHATSAPP_LINE_RE = re.compile(
    r"^\[?(?P<date>\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}),?\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AaPp]\.?[Mm]\.?)?)\]?"
    r"\s*[-–]?\s*(?P<rest>.*)$"
)
# Plain copy-paste such as "Mentor Anjali: text".
NAMED_LINE_RE = re.compile(r"^(?P<sender>[^:\n]{1,40}?):\s+(?P<text>.+)$")
MIN_MESSAGES_FOR_CHAT = 2


@dataclass
class ChatMessage:
    sender: str | None
    text: str
    stage: str | None = None
    reason: str = ""
    labels: list[str] = field(default_factory=list)


def parse_chat(raw: str) -> list[ChatMessage]:
    """Split a chat export or pasted conversation into messages. Unrecognised text is one message."""
    lines = raw.splitlines()
    if any(WHATSAPP_LINE_RE.match(line) for line in lines):
        return _parse_whatsapp(lines)

    named = [NAMED_LINE_RE.match(line) for line in lines if line.strip()]
    if len(named) >= MIN_MESSAGES_FOR_CHAT and sum(m is not None for m in named) >= len(named) / 2:
        messages: list[ChatMessage] = []
        for line in lines:
            match = NAMED_LINE_RE.match(line)
            if match:
                messages.append(ChatMessage(sender=match["sender"].strip(), text=match["text"].strip()))
            elif line.strip() and messages:
                messages[-1].text += "\n" + line.strip()
        return messages

    return [ChatMessage(sender=None, text=raw.strip())] if raw.strip() else []


def _parse_whatsapp(lines: list[str]) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for line in lines:
        match = WHATSAPP_LINE_RE.match(line)
        if not match:
            if messages and line.strip():
                messages[-1].text += "\n" + line.strip()
            continue
        sender, sep, text = match["rest"].partition(": ")
        if not sep:
            # System line ("Messages are end-to-end encrypted", "X joined"): skip, but don't
            # let its continuation lines attach to the previous message.
            messages.append(ChatMessage(sender="__system__", text=""))
            continue
        messages.append(ChatMessage(sender=sender.strip(), text=text.strip()))
    return [m for m in messages if m.sender != "__system__" and m.text and m.text != "<Media omitted>"]


def label_with_rules(message: ChatMessage) -> None:
    """Assign the most advanced stage whose patterns match."""
    for stage in sorted(STAGES, key=lambda s: -STAGES[s][0]):
        for pattern in STAGE_PATTERNS[stage]:
            if re.search(pattern, message.text, re.I):
                message.stage = stage
                message.reason = "matched rule"
                message.labels.append("rules")
                return


def check_chat(text: str, user_name: str | None = None, use_llm: bool = False) -> CheckResult:
    result = CheckResult(check="chat_stages")
    messages = parse_chat(text)
    me = user_name.strip().lower() if user_name else None
    # Only the other party's messages count: the student asking "how do I withdraw?" is not the scam.
    theirs = [m for m in messages if not (me and m.sender and m.sender.lower() == me)]

    for message in theirs:
        label_with_rules(message)

    llm_summary = None
    if use_llm and theirs:
        from app.checks import llm  # imported lazily so the rules work without the SDK or a key

        llm_summary = llm.label_messages(theirs)

    stages = [m.stage for m in theirs if m.stage]
    reached = max(stages, key=lambda s: STAGES[s][0]) if stages else None
    result.details = {
        "message_count": len(messages),
        "timeline": [
            {"sender": m.sender, "stage": m.stage, "source": m.labels[-1] if m.labels else None,
             "reason": m.reason, "preview": m.text[:120]}
            for m in theirs
        ],
        "stages_seen": list(dict.fromkeys(stages)),
        "furthest_stage": reached,
        "llm_used": llm_summary is not None,
        "llm_summary": llm_summary,
    }

    if not reached:
        return result
    level, label = STAGES[reached]
    points = {1: 5, 2: 10, 3: 20, 4: 35, 5: 45}[level]
    signals = result.signals
    if level == 5:
        message = ("The chat has reached the 'pay more to withdraw' stage. Stop paying: money sent "
                   "now is almost never returned. Report at cybercrime.gov.in or call 1930.")
    elif level == 4:
        message = "The chat has reached the money-request stage. Do not deposit or pay anything."
    else:
        message = f"Furthest scam stage reached: {label}."
    signals.append(Signal(code=f"chat_stage_{reached}", points=points, message=message))

    if _follows_script(stages):
        signals.append(Signal(
            code="scam_script_progression", points=20,
            message="The conversation follows the known task-scam script: "
            + " → ".join(STAGES[s][1] for s in result.details["stages_seen"]) + ".",
        ))
    return result


def _follows_script(stages: list[str]) -> bool:
    """At least three distinct stages, first seen in (mostly) increasing order."""
    order = [STAGES[s][0] for s in dict.fromkeys(stages)]
    if len(order) < 3:
        return False
    rises = sum(b > a for a, b in zip(order, order[1:]))
    return rises >= len(order) - 2


def looks_like_chat(text: str) -> bool:
    return len(parse_chat(text)) >= MIN_MESSAGES_FOR_CHAT
