"""Give a quiz to a simulated class, so the analytics page has data to show.

Each simulated student has an ability, and each question gets a difficulty and
discrimination (see bank.ml.simulate). Answers go through the same
submit_attempt as real students, so they're graded exactly like real ones.
The share link is marked as simulated and closed, and the results pages say so.

By default one multiple-choice question is secretly miskeyed (the students'
real right answer isn't the one in the key), to show that the analytics page
catches it. Pass --no-problems to leave the quiz as it is.
"""

from decimal import Decimal

import numpy as np
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bank.grading import submit_attempt
from bank.ml.simulate import expit
from bank.models import Assignment, Question, Test

WRONG_BLANKS = ["", "not sure", "?"]


class Command(BaseCommand):
    help = "Give a quiz to a class of simulated students, for demos and for testing the analytics."

    def add_arguments(self, parser):
        parser.add_argument("quiz", type=int, help="The quiz's id (it's in the quiz page's address).")
        parser.add_argument("--students", type=int, default=300)
        parser.add_argument("--seed", type=int, default=0)
        parser.add_argument("--no-problems", action="store_true", help="Don't plant a miskeyed question.")

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            quiz = Test.objects.get(pk=options["quiz"])
        except Test.DoesNotExist:
            raise CommandError(f"No quiz with id {options['quiz']}.")
        items = list(quiz.items.select_related("question").prefetch_related("question__options"))
        if not items:
            raise CommandError("That quiz has no questions.")

        rng = np.random.default_rng(options["seed"])
        params = []
        for item in items:
            question = item.question
            opts = list(question.options.all())
            params.append({
                "question": question,
                "options": opts,
                "a": rng.lognormal(0.0, 0.3),
                "b": rng.normal(-0.3, 1.0),
                "truth": {o.pk for o in opts if o.is_correct},
                "attract": rng.dirichlet(np.full(max(len(opts), 1), 4.0)),
            })

        planted = None
        if not options["no_problems"]:
            candidates = [p for p in params if p["question"].question_type == Question.Type.MULTIPLE_CHOICE
                          and len(p["options"]) >= 3 and p["truth"]]
            if candidates:
                planted = candidates[int(rng.integers(len(candidates)))]
                wrong = [o for o in planted["options"] if not o.is_correct]
                planted["truth"] = {wrong[int(rng.integers(len(wrong)))].pk}
                planted["b"] = -0.5

        assignment = Assignment.objects.create(test=quiz, is_simulated=True, is_open=False)
        width = len(str(options["students"]))
        for n in range(options["students"]):
            theta = rng.normal()
            answers, essay_scores = {}, {}
            for p in params:
                question, kind = p["question"], p["question"].question_type
                n_options = max(len(p["options"]), 2)
                guess = 0.8 / n_options if kind in (Question.Type.MULTIPLE_CHOICE, Question.Type.TRUE_FALSE) else 0.0
                p_right = guess + (1 - guess) * expit(p["a"] * (theta - p["b"]))

                if kind in (Question.Type.MULTIPLE_CHOICE, Question.Type.TRUE_FALSE):
                    if rng.random() < p_right:
                        pick = next(iter(p["truth"]))
                    else:
                        wrong = [(o, w) for o, w in zip(p["options"], p["attract"]) if o.pk not in p["truth"]]
                        weights = np.array([w for _, w in wrong])
                        pick = wrong[rng.choice(len(wrong), p=weights / weights.sum())][0].pk
                    answers[question.pk] = ({pick}, "")
                elif kind == Question.Type.MULTIPLE_SELECT:
                    picks = {o.pk for o, w in zip(p["options"], p["attract"])
                             if (o.pk in p["truth"] and rng.random() < p_right)
                             or (o.pk not in p["truth"] and rng.random() < (1 - p_right) * min(1.0, 2 * w))}
                    answers[question.pk] = (picks, "")
                elif kind == Question.Type.FILL_IN_BLANK:
                    accepted = [o.text for o in p["options"] if o.is_correct]
                    right = accepted and rng.random() < p_right
                    answers[question.pk] = (set(), accepted[0] if right else WRONG_BLANKS[int(rng.integers(3))])
                else:
                    answers[question.pk] = (set(), "(Simulated written answer.)")
                    raw = float(question.points) * float(np.clip(p_right + rng.normal(0, 0.1), 0, 1))
                    essay_scores[question.pk] = Decimal(str(round(raw * 2) / 2))

            attempt = submit_attempt(assignment, f"Simulated student {n + 1:0{width}d}", answers)
            if essay_scores:
                for response in attempt.responses.filter(question_id__in=essay_scores):
                    response.points = essay_scores[response.question_id]
                    response.save(update_fields=["points"])
                attempt.update_score()

        self.stdout.write(self.style.SUCCESS(
            f"Gave “{quiz.title}” to {options['students']} simulated students. Share code: {assignment.code}"
        ))
        if planted:
            number = next(i for i, p in enumerate(params, start=1) if p is planted)
            self.stdout.write(f"Planted problem: question {number} is miskeyed (students' real answer isn't the key).")
