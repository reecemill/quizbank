"""AI essay grading: the dataset parser, the model, and suggestions in the app.

Everything here uses the "hashing" embedder, so no model is downloaded."""

import io
import shutil
import tempfile
import zipfile
from decimal import Decimal
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from bank.grading import submit_attempt
from bank.ml import datasets
from bank.ml import essay_grader as eg
from bank.models import Assignment, Question, Test
from bank.suggestions import GRADER_FILE


def unt_zip() -> bytes:
    """A tiny archive laid out like the UNT dataset: one assignment question,
    one exam question (graders out of 10), and one question marked '#' (ignored)."""
    files = {
        "data/raw/questions": "1.1 What is a variable?\n12.1 What is a stack?\n1.2 Put these in order.\n",
        "data/raw/answers": "1.1 A named location in memory that stores a value.\n12.1 A last-in, first-out list.\n1.2 x\n",
        "data/docs/files": "1.1\n12.1\n#1.2\n",
        "data/raw/1.1": "1.1 A place in memory<br>that holds a value.\n1.1 A number.\n",
        "data/scores/1.1/ave": "5\n1.5\n",
        "data/scores/1.1/me": "5\n2\n",
        "data/scores/1.1/other": "5\n1\n",
        "data/raw/12.1": "12.1 Last in first out.\n",
        "data/scores/12.1/ave": "4.5\n",
        "data/scores/12.1/me": "10\n",
        "data/scores/12.1/other": "8\n",
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr("ShortAnswerGrading_v2.0/" + name, text)
    return buffer.getvalue()


def synthetic_answers(n_questions=6, per_question=12, seed=0) -> pd.DataFrame:
    """Answers whose score depends on how many model-answer words they reuse."""
    rng = np.random.default_rng(seed)
    vocab = [f"word{i}" for i in range(200)]
    rows = []
    for q in range(n_questions):
        reference = rng.choice(vocab, 8, replace=False).tolist()
        for _ in range(per_question):
            k = int(rng.integers(0, 9))
            words = reference[:k] + rng.choice(vocab, 4).tolist()
            rows.append({"question_id": f"q{q}", "question": f"Question {q} about {reference[0]}",
                         "reference": " ".join(reference), "answer": " ".join(words),
                         "score": 5 * k / 8, "score_1": 5 * k / 8, "score_2": 5 * k / 8})
    return pd.DataFrame(rows)


class DatasetTests(TestCase):
    def test_parse_unt(self):
        df = datasets.parse_unt_bytes(unt_zip())
        self.assertEqual(df["question_id"].tolist(), ["1.1", "1.1", "12.1"])
        first = df.iloc[0]
        self.assertEqual(first["answer"], "A place in memory that holds a value.")
        self.assertEqual(first["reference"], "A named location in memory that stores a value.")
        self.assertEqual(first["score"], 5)
        # Exam graders scored out of 10; they're put on the 0-5 scale.
        exam = df.iloc[2]
        self.assertEqual((exam["score_1"], exam["score_2"]), (5.0, 4.0))

    def test_download_uses_the_cached_file(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder)
        path = folder / "file.zip"
        path.write_bytes(b"cached")
        self.assertEqual(datasets.download("https://example.invalid/file.zip", path), path)


class ModelTests(TestCase):
    def test_metrics(self):
        perfect = eg.metrics(np.array([0, 1, 2, 3, 4, 5]), np.array([0, 1, 2, 3, 4, 5]))
        self.assertAlmostEqual(perfect["pearson"], 1)
        self.assertAlmostEqual(perfect["qwk"], 1)
        self.assertEqual(perfect["rmse"], 0)
        constant = eg.metrics(np.array([0, 5, 3]), np.array([3, 3, 3]))
        self.assertEqual(constant["pearson"], 0)

    def test_content_words(self):
        self.assertEqual(eg.content_words("The variables are stored"), {"variabl", "stor"})

    def test_scale_to_points(self):
        self.assertEqual(eg.scale_to_points(4.0, 5), 4.0)
        self.assertEqual(eg.scale_to_points(3.3, 10), 6.5)
        self.assertEqual(eg.scale_to_points(5.0, 2), 2.0)

    def test_cross_validation_is_grouped_by_question(self):
        df = synthetic_answers()
        folds, predictions = eg.cross_validate(df, embedder="hashing", n_splits=3)
        self.assertEqual(set(folds["model"]), set(eg.candidate_models()))
        self.assertFalse(predictions.isna().any().any())
        # On data where the score is word overlap, the model beats the average.
        full = eg.metrics(df["score"], predictions[eg.FINAL_MODEL])
        base = eg.metrics(df["score"], predictions["Average score"])
        self.assertGreater(full["pearson"], 0.5)
        self.assertLess(full["rmse"], base["rmse"])

    def test_trained_grader_predicts_and_round_trips(self):
        df = synthetic_answers()
        grader = eg.train(df, embedder="hashing", evaluation={"pearson": 0.5})
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder)
        grader.save(folder / "g.joblib")
        loaded = eg.EssayGrader.load(folder / "g.joblib")
        row = df.iloc[0]
        scores = loaded.predict_scores([row.question] * 2, [row.reference] * 2, [row.reference, "  "])
        self.assertGreater(scores[0], 3)
        self.assertEqual(scores[1], 0)
        self.assertEqual(loaded.evaluation["pearson"], 0.5)


class SuggestionPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo_data", stdout=StringIO())
        cls.teacher = get_user_model().objects.create_user("teacher", password="a-long-password", is_staff=True)
        cls.quiz = Test.objects.get(title="Quiz 1: Computing Basics")
        cls.essay = Question.objects.get(text__startswith="Explain the difference between hardware")

    def setUp(self):
        self.data_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.data_dir)
        settings = override_settings(QUIZBANK_DATA_DIR=self.data_dir, QUIZBANK_EMBEDDER="hashing")
        settings.enable()
        self.addCleanup(settings.disable)
        self.client.force_login(self.teacher)
        self.assignment = Assignment.objects.create(test=self.quiz)
        self.attempt = submit_attempt(self.assignment, "Jordan Lee", {
            self.essay.pk: (set(), "Hardware is the physical parts of a computer; software is the programs."),
        })
        self.url = reverse("bank:attempt", args=[self.assignment.code, self.attempt.pk])

    def train(self):
        eg.train(synthetic_answers(), embedder="hashing",
                 evaluation={"pearson": 0.55, "human_pearson": 0.6, "questions": 81, "qwk": 0.4, "mae": 0.7},
                 ).save(self.data_dir / GRADER_FILE)

    def test_demo_essays_have_model_answers(self):
        self.assertTrue(self.essay.reference_answer)

    def test_no_trained_model_means_no_suggestion(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, "AI suggestion")
        self.assertNotContains(response, "Add a model answer")

    def test_suggestion_is_shown_and_saved(self):
        self.train()
        response = self.client.get(self.url)
        self.assertContains(response, "AI suggestion")
        self.assertContains(response, "data-use-suggestion")
        self.assertContains(response, "agreed with human graders at r = 0.55")
        essay_response = self.attempt.responses.get(question=self.essay)
        self.assertIsNotNone(essay_response.suggested_points)
        self.assertTrue(0 <= essay_response.suggested_points <= self.essay.points)

    def test_changing_the_model_answer_clears_old_suggestions(self):
        self.train()
        self.client.get(self.url)
        self.essay.reference_answer = "Something else entirely."
        self.essay.save()
        self.assertIsNone(self.attempt.responses.get(question=self.essay).suggested_points)

    def test_no_model_answer_asks_for_one(self):
        self.train()
        Question.objects.filter(pk=self.essay.pk).update(reference_answer="")
        response = self.client.get(self.url)
        self.assertContains(response, "Add a model answer")
        self.assertNotContains(response, "data-use-suggestion")

    def test_students_never_see_suggestions(self):
        self.train()
        self.client.get(self.url)
        self.assignment.show_answers = True
        self.assignment.save()
        student = Client()
        session = student.session
        session["quizbank_attempts"] = {self.assignment.code: self.attempt.pk}
        session.save()
        done = student.get(reverse("bank:take_done", args=[self.assignment.code]))
        self.assertEqual(done.status_code, 200)
        self.assertNotContains(done, "AI suggestion")

    def test_question_page_shows_the_model_answer(self):
        response = self.client.get(reverse("bank:question", args=[self.essay.pk]))
        self.assertContains(response, "Model answer")
        self.assertContains(response, "physical parts of a computer")
