"""Fail closed if the portable seed contains personal or response data."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


FORBIDDEN_FRAGMENTS = (
    "answer",
    "assignment",
    "attempt",
    "created_by",
    "email",
    "full_name",
    "password",
    "plan_item",
    "result",
    "target_user",
    "user_id",
)


def walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_keys(child)


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/competency_catalog.json")
    raw = path.read_bytes()
    payload = json.loads(raw)
    if payload.get("schema_version") != 1 or not isinstance(payload.get("competencies"), list):
        raise SystemExit("invalid catalog schema")

    forbidden = sorted(
        key for key in set(walk_keys(payload))
        if any(fragment in key.lower() for fragment in FORBIDDEN_FRAGMENTS)
    )
    if forbidden:
        raise SystemExit(f"forbidden fields: {', '.join(forbidden)}")

    competencies = payload["competencies"]
    questions = [question for competency in competencies for question in competency.get("questions", [])]
    choices = [choice for question in questions for choice in question.get("choices", [])]
    interpretations = [item for competency in competencies for item in competency.get("interpretations", [])]
    if not competencies or not questions or not choices or not interpretations:
        raise SystemExit("catalog is incomplete")
    if any(len(question.get("choices", [])) < 2 for question in questions):
        raise SystemExit("a question has fewer than two choices")

    print(json.dumps({
        "sha256": hashlib.sha256(raw).hexdigest(),
        "competencies": len(competencies),
        "questions": len(questions),
        "choices": len(choices),
        "interpretations": len(interpretations),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
