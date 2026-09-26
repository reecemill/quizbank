"""Giving a quiz to students: automatic grading, the student pages, and results."""

from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from bank.grading import grade, normalize, submit_attempt
from bank.models import Assignment, Attempt, Question, Test


def option_ids(question, *texts):
    return {question.options.get(text=text).pk for text in texts}


class GradingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo_data", stdout=StringIO())
        cls.mc = Question.objects.get(text="What does CPU stand for?")                     # 2 pts
        cls.tf = Question.objects.get(text__startswith="RAM keeps its contents")           # 1 pt, False
        cls.ms = Question.objects.get(text__startswith="Which of these are input devices")  # 2 pts, 3 correct
        cls.fb = Question.objects.get(text__startswith="In DNA, adenine pairs with")       # thymine or T
        cls.es = Question.objects.get(text__startswith="Explain the difference between hardware")

    def test_multiple_choice(self):
        self.assertEqual(grade(self.mc, option_ids(self.mc, "Central Processing Unit"), ""), 2)
        self.assertEqual(grade(self.mc, option_ids(self.mc, "Computer Power Unit"), ""), 0)
        self.assertEqual(grade(self.mc, set(), ""), 0)

    def test_true_false(self):
        self.assertEqual(grade(self.tf, option_ids(self.tf, "False"), ""), 1)
        self.assertEqual(grade(self.tf, option_ids(self.tf, "True"), ""), 0)

    def test_picking_every_choice_is_not_full_credit(self):
        all_options = {option.pk for option in self.mc.options.all()}
        self.assertEqual(grade(self.mc, all_options, ""), 0)

    def test_multiple_selection_gives_partial_credit(self):
        right = ("Keyboard", "Microphone", "Mouse")
        self.assertEqual(grade(self.ms, option_ids(self.ms, *right), ""), 2)
        self.assertEqual(grade(self.ms, option_ids(self.ms, "Keyboard", "Mouse"), ""), Decimal("1.33"))
        # Two right (+2/3 each) and one wrong (-2/3) leaves 2/3 of a point.
        self.assertEqual(grade(self.ms, option_ids(self.ms, "Keyboard", "Mouse", "Monitor"), ""), Decimal("0.67"))
        # Never below zero.
        self.assertEqual(grade(self.ms, option_ids(self.ms, "Monitor", "Printer"), ""), 0)

    def test_fill_in_the_blank_ignores_case_and_spacing(self):
        self.assertEqual(grade(self.fb, set(), "  Thymine "), 1)
        self.assertEqual(grade(self.fb, set(), "t"), 1)
        self.assertEqual(grade(self.fb, set(), "cytosine"), 0)
        self.assertEqual(normalize("  Two   Words "), "two words")

    def test_essays_wait_for_a_person_unless_blank(self):
        self.assertIsNone(grade(self.es, set(), "Hardware is the physical part."))
        self.assertEqual(grade(self.es, set(), "   "), 0)

    def test_submit_attempt_scores_and_ignores_choices_from_other_questions(self):
        quiz = Test.objects.get(title="Quiz 1: Computing Basics")
        assignment = Assignment.objects.create(test=quiz)
        stray = option_ids(self.tf, "False")  # an option that belongs to a different question
        attempt = submit_attempt(assignment, "Jordan Lee", {
            self.mc.pk: (option_ids(self.mc, "Central Processing Unit") | stray, ""),
            self.es.pk: (set(), "Hardware is physical; software is code."),
        })
        self.assertEqual(attempt.max_score, 12)
        self.assertEqual(attempt.score, 2)
        self.assertEqual(attempt.responses.count(), 6)
        self.assertEqual(attempt.responses.filter(points__isnull=True).count(), 1)
        self.assertEqual(attempt.responses.get(question=self.mc).selected.count(), 1)


class GivingQuizTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo_data", stdout=StringIO())
        cls.teacher = get_user_model().objects.create_user("teacher", password="a-long-password")
        cls.quiz = Test.objects.get(title="Quiz 1: Computing Basics")
        cls.mc = Question.objects.get(text="What does CPU stand for?")
        cls.tf = Question.objects.get(text__startswith="RAM keeps its contents")
        cls.fb = Question.objects.get(text__startswith="The binary number")
        cls.es = Question.objects.get(text__startswith="Explain the difference between hardware")

    def setUp(self):
        self.client.force_login(self.teacher)
        self.student = Client()

    def give(self):
        response = self.client.post(reverse("bank:give", args=[self.quiz.pk]))
        assignment = Assignment.objects.get(test=self.quiz)
        self.assertRedirects(response, reverse("bank:results", args=[assignment.code]))
        return assignment

    def take(self, assignment, name="Jordan Lee", **extra):
        answers = {
            "student_name": name,
            f"q{self.mc.pk}": str(self.mc.options.get(text="Central Processing Unit").pk),  # 2 of 2
            f"q{self.tf.pk}": str(self.tf.options.get(text="True").pk),                     # 0 of 1
            f"q{self.fb.pk}": " 10 ",                                                       # 1 of 1
            f"q{self.es.pk}": "Hardware is the physical parts; software is the programs.",
            **extra,
        }
        return self.student.post(reverse("bank:take", args=[assignment.code]), answers)

    def test_giving_a_quiz_makes_a_share_link(self):
        assignment = self.give()
        self.assertTrue(assignment.is_open)
        response = self.client.get(reverse("bank:results", args=[assignment.code]))
        self.assertContains(response, f"/take/{assignment.code}/")
        self.assertContains(response, "No submissions yet")
        quiz_page = self.client.get(reverse("bank:quiz", args=[self.quiz.pk]))
        self.assertContains(quiz_page, assignment.code)

    def test_students_take_the_quiz_without_signing_in(self):
        assignment = self.give()
        page = self.student.get(reverse("bank:take", args=[assignment.code]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Computer Power Unit")
        self.assertContains(page, 'name="student_name"')

    def test_the_quiz_page_does_not_give_away_answers(self):
        assignment = self.give()
        page = self.student.get(reverse("bank:take", args=[assignment.code])).content.decode()
        self.assertNotIn("is-correct", page)
        self.assertNotIn("Correct answer", page)
        self.assertNotIn("Accepted answers", page)

    def test_submitting_grades_the_quiz(self):
        assignment = self.give()
        response = self.take(assignment)
        self.assertRedirects(response, reverse("bank:take_done", args=[assignment.code]))
        attempt = Attempt.objects.get()
        self.assertEqual(attempt.student_name, "Jordan Lee")
        self.assertEqual(attempt.score, 3)            # MC 2 + FB 1; T/F wrong; the essay waits
        self.assertEqual(attempt.max_score, 12)
        done = self.student.get(response.url)
        self.assertContains(done, "Thanks, Jordan Lee")
        self.assertContains(done, "still has to grade 1 written answer")

    def test_students_only_see_answers_when_allowed(self):
        assignment = self.give()
        self.take(assignment)
        done_url = reverse("bank:take_done", args=[assignment.code])
        self.assertNotContains(self.student.get(done_url), 'id="response-')
        assignment.show_answers = True
        assignment.save()
        self.assertContains(self.student.get(done_url), 'id="response-', count=6)

    def test_a_browser_submits_once_unless_it_starts_over(self):
        assignment = self.give()
        self.take(assignment)
        again = self.take(assignment, name="Someone Else")
        self.assertRedirects(again, reverse("bank:take_done", args=[assignment.code]))
        self.assertEqual(Attempt.objects.count(), 1)
        self.student.get(reverse("bank:take", args=[assignment.code]) + "?new=1")
        self.take(assignment, name="Sam Ortiz")
        self.assertEqual(Attempt.objects.count(), 2)

    def test_other_browsers_cannot_see_a_students_result(self):
        assignment = self.give()
        self.take(assignment)
        stranger = Client()
        response = stranger.get(reverse("bank:take_done", args=[assignment.code]))
        self.assertRedirects(response, reverse("bank:take", args=[assignment.code]))

    def test_a_name_is_required(self):
        assignment = self.give()
        response = self.take(assignment, name="   ")
        self.assertContains(response, "Enter your name")
        self.assertFalse(Attempt.objects.exists())

    def test_closed_quizzes_take_no_answers(self):
        assignment = self.give()
        self.client.post(reverse("bank:assignment_settings", args=[assignment.code]), {"field": "is_open", "value": "0"})
        assignment.refresh_from_db()
        self.assertFalse(assignment.is_open)
        response = self.take(assignment)
        self.assertContains(response, "This quiz is closed")
        self.assertFalse(Attempt.objects.exists())

    def test_instructor_grades_the_essay(self):
        assignment = self.give()
        self.take(assignment)
        attempt = Attempt.objects.get()
        essay = attempt.responses.get(question=self.es)
        url = reverse("bank:attempt", args=[assignment.code, attempt.pk])

        page = self.client.get(url)
        self.assertContains(page, "Hardware is the physical parts")
        self.assertContains(page, f'name="points-{essay.pk}"')

        too_many = self.client.post(url, {f"points-{essay.pk}": "9"})
        self.assertRedirects(too_many, url)
        essay.refresh_from_db()
        self.assertIsNone(essay.points)

        self.client.post(url, {f"points-{essay.pk}": "4.5"})
        attempt.refresh_from_db()
        self.assertEqual(attempt.score, Decimal("7.5"))
        self.assertFalse(attempt.responses.filter(points__isnull=True).exists())

    def test_results_page_and_csv(self):
        assignment = self.give()
        self.take(assignment, name="=HYPERLINK(1)")
        results = self.client.get(reverse("bank:results", args=[assignment.code]))
        self.assertContains(results, "=HYPERLINK(1)")
        self.assertContains(results, "1 to grade")

        csv = self.client.get(reverse("bank:results_csv", args=[assignment.code]))
        self.assertEqual(csv["Content-Type"], "text/csv")
        lines = csv.content.decode().splitlines()
        self.assertEqual(lines[0], "Student,Submitted (UTC),Score,Out of,Percent,Answers to grade")
        self.assertTrue(lines[1].startswith("'=HYPERLINK(1),"))  # can't run as a formula
        self.assertIn(",3,12,25,1", lines[1])

    def test_results_pages_need_the_instructor(self):
        assignment = self.give()
        for url in [reverse("bank:results", args=[assignment.code]),
                    reverse("bank:results_csv", args=[assignment.code])]:
            with self.subTest(url=url):
                self.assertEqual(self.student.get(url).status_code, 302)
