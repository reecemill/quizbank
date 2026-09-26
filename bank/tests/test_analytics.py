"""Question analytics: the statistics, the simulation, and the analytics page."""

from io import StringIO

import numpy as np
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from bank.analytics import analyze_assignment, histogram
from bank.ml import item_analysis as ia
from bank.ml import simulate
from bank.models import Assignment, Test


class StatisticsTests(TestCase):
    def test_cronbach_alpha_matches_a_hand_calculation(self):
        scores = np.array([[1, 1, 1], [1, 1, 0], [1, 0, 0], [0, 0, 0]], dtype=float)
        # item variances (ddof=1): 0.25, 1/3, 0.25; total variance: 5/3
        expected = 3 / 2 * (1 - (0.25 + 1 / 3 + 0.25) / (5 / 3))
        self.assertAlmostEqual(ia.cronbach_alpha(scores), expected)

    def test_alpha_is_undefined_without_spread(self):
        self.assertIsNone(ia.cronbach_alpha(np.ones((5, 3))))
        self.assertIsNone(ia.cronbach_alpha(np.ones((5, 1))))

    def test_difficulty_and_discrimination(self):
        # Students are ordered strongest first. Question 0 tracks the other
        # questions; question 1 runs backwards (weak students get it right).
        scores = np.array([
            [1, 0, 1, 1, 1],
            [1, 0, 1, 1, 0],
            [1, 0, 1, 0, 0],
            [0, 1, 0, 1, 0],
            [0, 1, 0, 0, 0],
            [0, 1, 0, 0, 0],
        ], dtype=float)
        stats = ia.test_statistics(scores)
        self.assertEqual(stats.difficulty[0], 0.5)
        self.assertGreater(stats.item_rest[0], 0)
        self.assertLess(stats.item_rest[1], 0)

    def test_points_are_scaled_by_each_questions_maximum(self):
        scores = np.array([[2, 1], [0, 1], [2, 0]], dtype=float)
        stats = ia.test_statistics(scores, max_points=np.array([2, 1]))
        self.assertAlmostEqual(stats.difficulty[0], 2 / 3)
        self.assertAlmostEqual(stats.difficulty[1], 2 / 3)

    def test_ungraded_answers_are_left_out(self):
        scores = np.array([[1, np.nan], [0, 1], [1, 0]], dtype=float)
        stats = ia.test_statistics(scores)
        self.assertAlmostEqual(stats.difficulty[1], 0.5)
        self.assertIsNone(stats.alpha)  # only one fully graded question

    def test_groups_are_the_same_size(self):
        top, bottom = ia.groups(np.arange(100))
        self.assertEqual(top.sum(), 27)
        self.assertEqual(bottom.sum(), 27)
        self.assertTrue(top[-1] and bottom[0])

    def test_item_flags(self):
        codes = lambda flags: {f.code for f in flags}
        self.assertEqual(codes(ia.item_flags(0.95, 0.4)), {"too_easy"})
        self.assertEqual(codes(ia.item_flags(0.10, 0.1)), {"weak", "too_hard"})
        self.assertEqual(codes(ia.item_flags(0.5, -0.4, n_students=300)), {"negative"})
        # A small negative correlation in a small class isn't significant.
        self.assertEqual(codes(ia.item_flags(0.5, -0.1, n_students=30)), {"weak"})
        self.assertEqual(codes(ia.item_flags(0.5, -0.1, n_students=30, adaptive=False)), {"negative"})

    def test_option_flags(self):
        top = np.array([True] * 30 + [False] * 70)
        bottom = np.array([False] * 70 + [True] * 30)
        strong_pick = np.array([True] * 30 + [False] * 70)
        flags = ia.option_statistics(strong_pick, False, top, bottom).flags
        self.assertIn("strong_pick", {f.code for f in flags})
        dead = np.zeros(100, bool)
        self.assertIn("dead", {f.code for f in ia.option_statistics(dead, False, top, bottom).flags})
        self.assertEqual(ia.option_statistics(dead, True, top, bottom).flags, [])

    def test_reliability_rating(self):
        self.assertEqual(ia.reliability_rating(0.85), "Good")
        self.assertEqual(ia.reliability_rating(0.5), "Poor")
        self.assertEqual(ia.reliability_rating(None), "Not enough data")


class SimulationTests(TestCase):
    def test_simulation_is_reproducible(self):
        a = simulate.simulate_class(simulate.make_questions(10, np.random.default_rng(1)), 50, np.random.default_rng(2))
        b = simulate.simulate_class(simulate.make_questions(10, np.random.default_rng(1)), 50, np.random.default_rng(2))
        np.testing.assert_array_equal(a.choices, b.choices)

    def test_planted_problems_show_up_in_the_truth(self):
        questions = simulate.make_questions(10, np.random.default_rng(3))
        planted = {problem for q in questions for problem in q.planted}
        self.assertEqual(planted, set(simulate.PROBLEMS))
        for q in questions:
            self.assertTrue(q.planted <= simulate.true_flags(q), q.planted)

    def test_a_miskeyed_question_is_caught_in_a_big_class(self):
        rng = np.random.default_rng(4)
        questions = simulate.make_questions(15, rng)
        sim = simulate.simulate_class(questions, 400, rng)
        found = simulate.detected_flags(sim, questions)
        miskeyed = next(i for i, q in enumerate(questions) if "miskeyed" in q.planted)
        self.assertIn("miskeyed", found[miskeyed])

    def test_flag_accuracy_reports_precision_and_recall(self):
        result = simulate.flag_accuracy(n_tests=3, n_students=60, n_questions=10, seed=0)
        self.assertEqual(set(result), set(simulate.PROBLEMS))
        for scores in result.values():
            self.assertIn("precision", scores)
            self.assertIn("recall", scores)

    def test_histogram_bins(self):
        chart = histogram([0, 5, 10, 95, 100, 100])
        self.assertEqual([bar.count for bar in chart.bars], [2, 1, 0, 0, 0, 0, 0, 0, 0, 3])
        self.assertEqual(chart.bars[9].label, "90–100%")
        self.assertEqual(max(bar.height for bar in chart.bars), 100)


class AnalyticsPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo_data", stdout=StringIO())
        cls.quiz = Test.objects.get(title="Quiz 1: Computing Basics")
        out = StringIO()
        call_command("simulate_class", cls.quiz.pk, "--students", "200", "--seed", "0", stdout=out)
        cls.output = out.getvalue()
        cls.assignment = Assignment.objects.get(test=cls.quiz)
        cls.user = get_user_model().objects.create_user("teacher", password="a-long-password")

    def test_simulated_class_is_marked_and_closed(self):
        self.assertTrue(self.assignment.is_simulated)
        self.assertFalse(self.assignment.is_open)
        self.assertEqual(self.assignment.attempts.count(), 200)
        self.assertFalse(self.assignment.attempts.filter(responses__points__isnull=True).exists())

    def test_the_planted_question_is_flagged(self):
        number = int(self.output.split("Planted problem: question ")[1].split()[0])
        report = analyze_assignment(self.assignment)
        planted = report.items[number - 1]
        self.assertEqual(planted.worst_severity, "critical")
        self.assertIn(planted, report.flagged)

    def test_report_numbers(self):
        report = analyze_assignment(self.assignment)
        self.assertEqual(report.n_students, 200)
        self.assertEqual(len(report.items), 6)
        self.assertIsNotNone(report.alpha)
        self.assertTrue(report.reliable)
        self.assertEqual(sum(bar.count for bar in report.histogram.bars), 200)
        options = report.items[0].options
        self.assertEqual(len(options), 4)
        self.assertEqual(sum(o.is_correct for o in options), 1)

    def test_empty_assignment(self):
        empty = Assignment.objects.create(test=self.quiz)
        report = analyze_assignment(empty)
        self.assertEqual(report.n_students, 0)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("bank:analytics", args=[empty.code])), "No submissions yet")

    def test_analytics_page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("bank:analytics", args=[self.assignment.code]))
        self.assertContains(response, "Simulated class")
        self.assertContains(response, "Check the answer key")
        self.assertContains(response, "Show as a table")
        results = self.client.get(reverse("bank:results", args=[self.assignment.code]))
        self.assertContains(results, reverse("bank:analytics", args=[self.assignment.code]))

    def test_analytics_needs_the_instructor(self):
        response = self.client.get(reverse("bank:analytics", args=[self.assignment.code]))
        self.assertEqual(response.status_code, 302)
