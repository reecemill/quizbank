"""Import a sample of SciQ science questions as a demo course.

SciQ (Welbl, Liu & Gardner, 2017) is licensed CC BY-NC 3.0; it's downloaded
from Hugging Face on first run and not stored in this repository. Each question
becomes a multiple-choice question with its correct answer and three real
distractors, in a shuffled order. A bigger bank makes topic tags meaningful.
"""

import numpy as np
from django.core.management.base import BaseCommand
from django.db import transaction

from bank.ml import datasets
from bank.models import AnswerOption, Course, Question

COURSE_CODE = "SCI 110"
COURSE_NAME = "Science questions (SciQ sample)"


@transaction.atomic
def create_sciq_course(df, limit: int = 1000, seed: int = 0) -> tuple[Course, int]:
    """Add `limit` random SciQ questions to the SciQ demo course. Questions
    already in the course (same text) are skipped. Returns (course, added)."""
    rng = np.random.default_rng(seed)
    course, _ = Course.objects.get_or_create(code=COURSE_CODE, defaults={"name": COURSE_NAME})
    existing = set(course.questions.values_list("text", flat=True))
    sample = df.sample(n=min(limit, len(df)), random_state=seed)
    added = 0
    for row in sample.itertuples():
        text = " ".join(str(row.question).split())
        if not text or text in existing:
            continue
        question = Question.objects.create(course=course, question_type=Question.Type.MULTIPLE_CHOICE,
                                           text=text, points=1, source_type="sciq")
        options = [(str(row.correct_answer), True)] + [(str(d), False) for d in
                                                        (row.distractor1, row.distractor2, row.distractor3)]
        for order, index in enumerate(rng.permutation(len(options))):
            option_text, correct = options[index]
            AnswerOption.objects.create(question=question, text=option_text, is_correct=correct, order=order)
        existing.add(text)
        added += 1
    return course, added


class Command(BaseCommand):
    help = "Import a sample of SciQ science questions (CC BY-NC 3.0) as a demo course."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=1000)
        parser.add_argument("--seed", type=int, default=0)

    def handle(self, *args, **options):
        from django.conf import settings

        course, added = create_sciq_course(datasets.load_sciq(settings.QUIZBANK_DATA_DIR),
                                           options["limit"], options["seed"])
        self.stdout.write(self.style.SUCCESS(
            f"Added {added} SciQ questions to {course.code}. Run: python manage.py build_topics --course \"{course.code}\""
        ))
