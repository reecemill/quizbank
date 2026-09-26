"""Topic tags: the clustering, labeling, caching, and course pages.

Tests run with the offline "hashing" embedder (see settings), so topics here
reflect shared words rather than meaning; that's enough to test the plumbing."""

from io import StringIO

import numpy as np
import pandas as pd
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from bank.management.commands.load_sciq import COURSE_CODE, create_sciq_course
from bank.ml import topics
from bank.models import Course, Question, QuestionEmbedding
from bank.topics import MIN_QUESTIONS, build_topics, question_vectors


def blobs(k=4, per=30, dim=16, seed=0):
    """Well-separated clusters of unit vectors."""
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(k, dim)) * 5
    points = np.concatenate([c + rng.normal(size=(per, dim)) for c in centers])
    return points / np.linalg.norm(points, axis=1, keepdims=True), np.repeat(np.arange(k), per)


class ClusteringTests(TestCase):
    def test_choose_k_finds_well_separated_groups(self):
        vectors, _ = blobs(k=4)
        k, scores = topics.choose_k(vectors, 2, 8)
        self.assertEqual(k, 4)
        self.assertEqual(set(scores), set(range(2, 9)))

    def test_kmeans_recovers_the_groups(self):
        from sklearn.metrics import adjusted_rand_score

        vectors, truth = blobs(k=3)
        self.assertGreater(adjusted_rand_score(truth, topics.kmeans(vectors, 3)), 0.95)

    def test_labels_use_distinctive_words_not_question_words(self):
        texts = ["Which of the following describes photosynthesis in plants?",
                 "Which statement best explains photosynthesis and chlorophyll?",
                 "Which of the following is true about electrons and atoms?",
                 "Which statement describes protons, electrons, and atoms?"]
        labels = np.array([0, 0, 1, 1])
        names = topics.label_clusters(texts, labels, top_n=2)
        self.assertIn("photosynthesis", names[0])
        self.assertIn("atoms", names[1])
        for words in names.values():
            self.assertFalse({"following", "statement", "describes", "best"} & set(words))

    def test_labels_survive_empty_text(self):
        self.assertEqual(topics.label_clusters(["", ""], np.array([0, 1])), {0: [], 1: []})

    def test_find_topics_caps_k_for_small_banks(self):
        vectors, _ = blobs(k=3, per=5)
        result = topics.find_topics([f"q{i}" for i in range(15)], vectors, k_max=15)
        self.assertLessEqual(result.k, 15 // 4 if 15 // 4 >= 2 else 2)
        self.assertEqual(len(result.labels), 15)


class CourseTopicTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo_data", stdout=StringIO())
        cls.course = Course.objects.get(code="CS 101")  # 13 questions
        cls.teacher = get_user_model().objects.create_user("teacher", password="a-long-password")

    def test_build_topics_tags_every_question(self):
        new = build_topics(self.course)
        self.assertGreaterEqual(len(new), 2)
        self.assertFalse(self.course.questions.filter(topic__isnull=True).exists())
        self.assertEqual(sum(t.size for t in new), self.course.questions.count())
        self.assertTrue(all(t.label for t in new))

    def test_rebuilding_replaces_old_topics(self):
        build_topics(self.course)
        first = set(self.course.topics.values_list("pk", flat=True))
        build_topics(self.course)
        self.assertFalse(first & set(self.course.topics.values_list("pk", flat=True)))

    def test_small_courses_get_no_topics(self):
        small = Course.objects.get(code="HIST 201")
        self.assertLess(small.questions.count(), MIN_QUESTIONS)
        self.assertEqual(build_topics(small), [])

    def test_embeddings_are_cached_and_refreshed_when_text_changes(self):
        questions = list(self.course.questions.order_by("pk"))
        first = question_vectors(questions)
        self.assertEqual(QuestionEmbedding.objects.count(), len(questions))
        again = question_vectors(questions)
        np.testing.assert_array_equal(first, again)
        edited = questions[0]
        edited.text = "A completely different question about photosynthesis"
        edited.save()
        refreshed = question_vectors(questions)
        self.assertFalse(np.array_equal(first[0], refreshed[0]))
        np.testing.assert_array_equal(first[1:], refreshed[1:])

    def test_topic_filter_on_the_course_page(self):
        build_topics(self.course)
        topic = self.course.topics.first()
        self.client.force_login(self.teacher)
        url = reverse("bank:course", args=[self.course.pk])
        page = self.client.get(url)
        self.assertContains(page, "Refresh topics")
        self.assertContains(page, topic.label)
        filtered = self.client.get(url, {"topic": topic.pk})
        self.assertEqual(len(filtered.context["questions"]), topic.size)
        self.assertTrue(all(q.topic == topic for q in filtered.context["questions"]))
        other_course = Course.objects.get(code="BIO 110")
        ignored = self.client.get(reverse("bank:course", args=[other_course.pk]), {"topic": topic.pk})
        self.assertIsNone(ignored.context["topic"])

    def test_find_topics_button(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse("bank:find_topics", args=[self.course.pk]), follow=True)
        self.assertContains(response, "Grouped 13 questions into")
        self.assertTrue(self.course.topics.exists())
        small = Course.objects.get(code="HIST 201")
        response = self.client.post(reverse("bank:find_topics", args=[small.pk]), follow=True)
        self.assertContains(response, "Topics need between")

    def test_build_topics_command(self):
        out = StringIO()
        call_command("build_topics", "--course", "CS 101", stdout=out)
        self.assertIn("CS 101:", out.getvalue())

    def test_question_page_shows_its_topic(self):
        build_topics(self.course)
        question = self.course.questions.first()
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(reverse("bank:question", args=[question.pk])), question.topic.label)


class SciQImportTests(TestCase):
    def test_import_makes_multiple_choice_questions(self):
        df = pd.DataFrame({
            "question": [f"Question {i}?" for i in range(5)],
            "correct_answer": [f"right {i}" for i in range(5)],
            "distractor1": ["a"] * 5, "distractor2": ["b"] * 5, "distractor3": ["c"] * 5,
            "support": [""] * 5,
        })
        course, added = create_sciq_course(df, limit=3)
        self.assertEqual((course.code, added), (COURSE_CODE, 3))
        question = course.questions.first()
        self.assertEqual(question.question_type, Question.Type.MULTIPLE_CHOICE)
        self.assertEqual(question.options.count(), 4)
        self.assertEqual(question.options.filter(is_correct=True).count(), 1)
        _, again = create_sciq_course(df, limit=3)
        self.assertEqual(again, 0)  # same sample, already imported
