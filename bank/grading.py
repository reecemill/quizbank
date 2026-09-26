"""Automatic grading for quizzes students take online.

Objective questions are scored the way Canvas Classic Quizzes scores them:

* Multiple choice and true/false: full points for the correct choice.
* Multiple selection: partial credit. The points are split evenly across the
  correct choices. Each correct choice selected earns a share, each wrong
  choice selected takes a share away, and the score never goes below zero.
* Fill in the blank: full points when the answer matches an accepted answer,
  ignoring capitalization and extra spaces.

Essays, and question types imported as text only, need a person. They stay
ungraded (points = None) unless they were left blank, which scores zero.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from .models import Assignment, Attempt, Question, Response

CHOICE_TYPES = {Question.Type.MULTIPLE_CHOICE, Question.Type.TRUE_FALSE, Question.Type.MULTIPLE_SELECT}
TEXT_TYPES = {Question.Type.FILL_IN_BLANK, Question.Type.ESSAY, Question.Type.OTHER}
HAND_GRADED_TYPES = {Question.Type.ESSAY, Question.Type.OTHER}

CENT = Decimal("0.01")
MAX_TEXT = 10_000


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def grade(question: Question, selected: set[int], text: str) -> Decimal | None:
    """Points earned for one answer, or None if a person has to grade it.
    `selected` holds the chosen AnswerOption ids; `text` is a typed answer."""
    points = Decimal(question.points)
    options = list(question.options.all())
    correct = {option.pk for option in options if option.is_correct}
    kind = question.question_type

    if kind in (Question.Type.MULTIPLE_CHOICE, Question.Type.TRUE_FALSE):
        return points if len(selected) == 1 and selected <= correct else Decimal(0)

    if kind == Question.Type.MULTIPLE_SELECT:
        if not correct:
            return Decimal(0)
        share = points / len(correct)
        earned = share * len(selected & correct) - share * len(selected - correct)
        return max(Decimal(0), earned).quantize(CENT, ROUND_HALF_UP)

    if kind == Question.Type.FILL_IN_BLANK:
        accepted = {normalize(option.text) for option in options if option.is_correct}
        return points if normalize(text) in accepted else Decimal(0)

    return Decimal(0) if not text.strip() else None


@transaction.atomic
def submit_attempt(assignment: Assignment, student_name: str,
                   answers: dict[int, tuple[set[int], str]]) -> Attempt:
    """Save a student's answers and grade everything that can be graded.

    `answers` maps question id to (chosen option ids, typed text). Choices that
    don't belong to the question are ignored, and missing answers count as blank.
    """
    items = list(assignment.test.items.select_related("question").prefetch_related("question__options"))
    attempt = Attempt.objects.create(
        assignment=assignment,
        student_name=student_name,
        max_score=sum((Decimal(item.question.points) for item in items), Decimal(0)),
    )
    for item in items:
        question = item.question
        selected, text = answers.get(question.pk, (set(), ""))
        selected = selected & {option.pk for option in question.options.all()}
        text = text[:MAX_TEXT]
        response = Response.objects.create(
            attempt=attempt,
            question=question,
            order=item.order,
            text=text,
            points=grade(question, selected, text),
        )
        if selected:
            response.selected.set(selected)
    attempt.update_score()
    return attempt


def answers_from_post(post, questions) -> dict[int, tuple[set[int], str]]:
    """Read a submitted quiz form. Each question's field is named q<id>: radio
    buttons or checkboxes hold option ids, text boxes hold the typed answer."""
    answers = {}
    for question in questions:
        key = f"q{question.pk}"
        if question.question_type in CHOICE_TYPES:
            selected = {int(value) for value in post.getlist(key) if value.isdigit()}
            answers[question.pk] = (selected, "")
        else:
            answers[question.pk] = (set(), post.get(key, "").strip())
    return answers
