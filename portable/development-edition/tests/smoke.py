"""End-to-end API smoke for a fresh portable instance."""

from __future__ import annotations

import json
import secrets
import sys
import urllib.error
import urllib.request


BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787"


def request(method: str, path: str, body=None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"{method} {path} returned {exc.code}: {detail}") from exc


def main() -> None:
    status = request("GET", "/api/setup/status")
    assert status == {"setup_required": True, "catalog_competencies": 6, "catalog_questions": 84}

    admin_password = "Aa1!" + secrets.token_urlsafe(18)
    bootstrap = request(
        "POST",
        "/api/setup/admin",
        {"full_name": "Portable Admin", "email": "admin@example.com", "password": admin_password},
    )
    admin_token = bootstrap["access_token"]
    assert bootstrap["user"]["role"] == "admin"

    access = request("GET", "/api/competencies/access", token=admin_token)
    assert access == {"development_enabled": True, "constructor_enabled": True, "is_admin": True}

    catalog = request("GET", "/api/competencies/my", token=admin_token)["competencies"]
    assert len(catalog) == 6
    assert sum(item["questions_count"] for item in catalog) == 84

    attempt = request("POST", f"/api/competencies/my/{catalog[0]['id']}/start", {}, admin_token)
    assert len(attempt["questions"]) == 14
    for question in attempt["questions"]:
        request(
            "POST",
            f"/api/competencies/attempts/{attempt['attempt_id']}/answer",
            {
                "question_id": question["id"],
                "choice_id": question["choices"][0]["id"],
                "time_spent_seconds": 1,
                "timed_out": False,
            },
            admin_token,
        )
    result = request("POST", f"/api/competencies/attempts/{attempt['attempt_id']}/finish", {}, admin_token)
    assert result["status"] == "completed"
    assert result["score_ib"] is not None

    plan = request(
        "POST",
        "/api/competencies/development-plan/my",
        {
            "competency_id": catalog[0]["id"],
            "source_attempt_id": attempt["attempt_id"],
            "goal": "Проверить переносимый ИПР",
            "action_text": "Выполнить одно проверяемое действие",
            "expected_result": "Действие отражено в плане",
        },
        admin_token,
    )
    request("PATCH", f"/api/competencies/development-plan/my/{plan['id']}", {"status": "done"}, admin_token)
    report = request("GET", "/api/competencies/development-plan/my/report", token=admin_token)
    assert report["completed_assessments_count"] == 1
    assert report["plan_done"] == 1

    employee_password = "Bb2!" + secrets.token_urlsafe(18)
    employee = request(
        "POST",
        "/api/users",
        {
            "full_name": "Portable Employee",
            "email": "employee@example.com",
            "password": employee_password,
            "role": "executor",
            "competency_constructor_enabled": False,
        },
        admin_token,
    )

    custom = request(
        "POST",
        "/api/competencies/constructor",
        {
            "title": "Проверочная компетенция",
            "description": "Создана smoke-тестом",
            "visibility": "assigned",
            "questions": [
                {
                    "text": "Как проявляется проверяемое поведение?",
                    "question_type": "custom",
                    "choices": [
                        {"text": "Никогда", "value": 1},
                        {"text": "Редко", "value": 2},
                        {"text": "Иногда", "value": 3},
                        {"text": "Часто", "value": 4},
                        {"text": "Всегда", "value": 5},
                    ],
                }
            ],
            "interpretations": [{"min_score_ib": 0, "max_score_ib": 100, "text": "Проверено"}],
        },
        admin_token,
    )
    request(
        "PUT",
        f"/api/competencies/constructor/{custom['id']}/assignments",
        {"target_user_ids": [employee["id"]], "visibility": "assigned"},
        admin_token,
    )

    login = request(
        "POST",
        "/api/auth/login",
        {"email": "employee@example.com", "password": employee_password},
    )
    employee_catalog = request("GET", "/api/competencies/my", token=login["access_token"])["competencies"]
    assert len(employee_catalog) == 7
    assert any(item["id"] == custom["id"] for item in employee_catalog)

    request("DELETE", f"/api/competencies/development-plan/my/{plan['id']}", token=admin_token)
    print("portable development smoke: PASS")


if __name__ == "__main__":
    main()
