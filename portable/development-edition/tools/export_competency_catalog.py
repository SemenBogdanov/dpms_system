"""Export only active competency definitions from a DPMS database.

The output deliberately excludes users, assignments, attempts, answers and
development plans. Run this script inside the production backend container and
redirect stdout to ``data/competency_catalog.json``.
"""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models.competency import (
    Competency,
    CompetencyQuestion,
)


SOURCE_RELEASE = "2def4d6d1435d643041d6f3edb139f4169684485"


async def export_catalog() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Competency)
            .options(
                selectinload(Competency.questions).selectinload(CompetencyQuestion.choices),
                selectinload(Competency.interpretations),
            )
            .where(Competency.is_active.is_(True))
            .order_by(Competency.source, Competency.title, Competency.version)
        )

        competencies = []
        for competency in result.scalars().unique().all():
            questions = []
            for question in sorted(
                (item for item in competency.questions if item.is_active),
                key=lambda item: item.position,
            ):
                questions.append(
                    {
                        "id": str(question.id),
                        "text": question.text,
                        "question_type": question.question_type,
                        "position": question.position,
                        "choices": [
                            {
                                "id": str(choice.id),
                                "text": choice.text,
                                "value": choice.value,
                                "position": choice.position,
                            }
                            for choice in sorted(question.choices, key=lambda item: item.position)
                        ],
                    }
                )

            competencies.append(
                {
                    "id": str(competency.id),
                    "title": competency.title,
                    "description": competency.description,
                    "source": competency.source,
                    "department": competency.department,
                    "visibility": competency.visibility,
                    "version": competency.version,
                    "questions": questions,
                    "interpretations": [
                        {
                            "id": str(interpretation.id),
                            "min_score_ib": interpretation.min_score_ib,
                            "max_score_ib": interpretation.max_score_ib,
                            "min_score_ich": interpretation.min_score_ich,
                            "max_score_ich": interpretation.max_score_ich,
                            "text": interpretation.text,
                            "overuse_modifier_text": interpretation.overuse_modifier_text,
                            "recommendation_text": interpretation.recommendation_text,
                        }
                        for interpretation in sorted(
                            competency.interpretations,
                            key=lambda item: (item.min_score_ib, item.max_score_ib),
                        )
                    ],
                }
            )

    payload = {
        "schema_version": 1,
        "source": {
            "system": "DPMS production",
            "release_sha": SOURCE_RELEASE,
        },
        "competencies": competencies,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(export_catalog())
