"""Save parsed Canvas quizzes into the question bank."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import BinaryIO

from django.core.files.base import ContentFile
from django.db import transaction

from .models import AnswerOption, Course, Question, Test, TestQuestion
from .qti import ParseResult, parse_qti_zip


@dataclass
class ImportSummary:
    tests_created: list[str] = field(default_factory=list)
    tests_skipped: list[str] = field(default_factory=list)
    questions_created: int = 0
    warnings: list[str] = field(default_factory=list)


@transaction.atomic
def save_parse_result(result: ParseResult, course: Course) -> ImportSummary:
    """Write every parsed quiz to the database, all or nothing.

    A quiz already imported into this course (same Canvas id) is skipped, so
    importing the same export twice doesn't duplicate anything.
    """
    summary = ImportSummary(warnings=list(result.warnings))

    for assessment in result.assessments:
        if assessment.ident and course.tests.filter(source_ident=assessment.ident).exists():
            summary.tests_skipped.append(assessment.title)
            continue

        test = Test.objects.create(
            course=course,
            title=assessment.title,
            instructions=assessment.instructions,
            source_ident=assessment.ident,
        )
        for order, parsed in enumerate(assessment.questions, start=1):
            question = Question.objects.create(
                course=course,
                question_type=parsed.question_type,
                text=parsed.text,
                text_html=parsed.text_html,
                points=parsed.points,
                source_ident=parsed.ident,
                source_type=parsed.source_type,
            )
            if parsed.image is not None:
                question.image.save(parsed.image.filename, ContentFile(parsed.image.data), save=True)
            AnswerOption.objects.bulk_create(
                AnswerOption(question=question, text=o.text, is_correct=o.is_correct, order=i)
                for i, o in enumerate(parsed.options)
            )
            TestQuestion.objects.create(test=test, question=question, order=order)
            summary.questions_created += 1

        summary.tests_created.append(test.title)

    return summary


def import_qti(source: str | BinaryIO, course_code: str, course_name: str = "") -> ImportSummary:
    """Parse a Canvas QTI export and add it to the given course."""
    result = parse_qti_zip(source)  # raises QTIError before anything is written
    course, _ = Course.objects.get_or_create(code=course_code, defaults={"name": course_name})
    return save_parse_result(result, course)
