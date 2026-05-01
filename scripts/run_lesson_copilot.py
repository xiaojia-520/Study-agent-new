from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from web.backend.app.services.lesson_copilot_service import lesson_copilot_service


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the minimal lesson copilot agent.")
    parser.add_argument("--course-id", required=True, help="Lesson course_id")
    parser.add_argument("--lesson-id", required=True, help="Lesson lesson_id")
    parser.add_argument(
        "--message",
        default="Help me review this lesson.",
        help="User message passed to the agent.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = lesson_copilot_service.run(
        course_id=args.course_id,
        lesson_id=args.lesson_id,
        message=args.message,
    )
    print(result.answer)


if __name__ == "__main__":
    main()
