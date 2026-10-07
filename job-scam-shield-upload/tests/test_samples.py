import json
from pathlib import Path

import pytest

from app.main import analyze
from app.schemas import AnalyzeRequest

SAMPLES = json.loads(
    (Path(__file__).resolve().parent.parent / "samples" / "test_messages.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("sample", SAMPLES, ids=[s["id"] for s in SAMPLES])
def test_sample_gets_expected_risk_level(sample):
    result = analyze(AnalyzeRequest(
        text=sample["text"], sender_email=sample["sender_email"],
        claimed_company=sample["claimed_company"], online=False,
    ))
    assert result.level == sample["expected"], [f.message for f in result.red_flags]
