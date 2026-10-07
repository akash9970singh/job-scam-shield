"""Load settings from a local `.env` file (KEY=value per line) into the environment.

`.env` holds secrets such as TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY. It's git-ignored and must
never be uploaded. Variables already set in the real environment win over the file.
"""

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path = ENV_FILE) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
