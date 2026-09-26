"""AI score suggestions for written answers: the database side.

The grader (bank.ml.essay_grader) is trained by `manage.py train_essay_grader`
and saved in QUIZBANK_DATA_DIR. Suggestions are computed the first time the
grading page shows an answer, never while a student is submitting, and saved
on the response.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from .grading import HAND_GRADED_TYPES
from .ml.essay_grader import EssayGrader, scale_to_points

GRADER_FILE = "essay_grader.joblib"


@lru_cache(maxsize=2)
def _load(path: str, modified: float) -> EssayGrader:
    return EssayGrader.load(Path(path))


def get_grader() -> EssayGrader | None:
    """The trained grader, or None if it hasn't been trained yet. Reloads if the file changes."""
    path = Path(settings.QUIZBANK_DATA_DIR) / GRADER_FILE
    if not path.exists():
        return None
    return _load(str(path), path.stat().st_mtime)


def needs_suggestion(response) -> bool:
    question = response.question
    return (question.question_type in HAND_GRADED_TYPES and response.suggested_points is None
            and bool(response.text.strip()) and bool(question.reference_answer.strip()))


def fill_suggestions(responses) -> EssayGrader | None:
    """Compute and save suggestions for any written answers that need one.
    Returns the grader (None if there isn't one)."""
    grader = get_grader()
    todo = [r for r in responses if needs_suggestion(r)]
    if grader is None or not todo:
        return grader
    scores = grader.predict_scores(
        [r.question.text for r in todo],
        [r.question.reference_answer for r in todo],
        [r.text for r in todo],
    )
    for response, score in zip(todo, scores):
        points = scale_to_points(float(score), float(response.question.points))
        response.suggested_points = Decimal(str(points))
        response.save(update_fields=["suggested_points"])
    return grader
