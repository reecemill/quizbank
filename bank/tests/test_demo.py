"""The public demo's sample class."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from bank.management.commands.setup_demo import SAMPLE_CLASS, create_sample_class
from bank.models import Question, Test


class SampleClassTests(TestCase):
    def setUp(self):
        call_command("load_demo_data", stdout=StringIO())
        self.quiz = Test.objects.get(title="Quiz 1: Computing Basics")

    def test_every_student_submits_with_the_essay_left_to_grade(self):
        assignment = create_sample_class(self.quiz)
        attempts = list(assignment.attempts.all())
        self.assertEqual(len(attempts), len(SAMPLE_CLASS))
        for attempt in attempts:
            essay = attempt.responses.get(question__question_type=Question.Type.ESSAY)
            self.assertTrue(essay.text)
            self.assertIsNone(essay.points)

    def test_objective_answers_follow_each_students_pattern(self):
        assignment = create_sample_class(self.quiz)
        best = assignment.attempts.get(student_name=SAMPLE_CLASS[0][0])
        objective = best.responses.exclude(question__question_type=Question.Type.ESSAY)
        self.assertTrue(all(r.points == r.question.points for r in objective))
        worst = assignment.attempts.get(student_name="Noah Williams")
        self.assertLess(worst.score, best.score)
