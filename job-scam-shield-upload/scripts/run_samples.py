"""Run every sample message through the analyzer and compare with the expected risk level.

Usage: python scripts/run_samples.py [--online] [path/to/samples.json]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import analyze  # noqa: E402
from app.schemas import AnalyzeRequest  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "test_messages.json"


def main() -> int:
    online = "--online" in sys.argv
    paths = [Path(a) for a in sys.argv[1:] if not a.startswith("--")]
    samples = json.loads((paths[0] if paths else SAMPLES).read_text(encoding="utf-8"))
    mismatches = 0
    for s in samples:
        result = analyze(AnalyzeRequest(
            text=s["text"], sender_email=s["sender_email"],
            claimed_company=s["claimed_company"], online=online,
        ))
        ok = result.level == s["expected"]
        mismatches += not ok
        print(f"{'OK  ' if ok else 'MISS'} {result.score:>3} {result.level:<6} (expected {s['expected']:<6}) {s['id']}")
        if not ok:
            for flag in result.red_flags:
                print(f"         +{flag.points:<3} {flag.message}")
    print(f"\n{len(samples) - mismatches}/{len(samples)} matched the expected level.")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
