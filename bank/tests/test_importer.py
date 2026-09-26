"""Importer tests: parsed quizzes end up correctly in the database."""

import io
import shutil
import tempfile
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from bank.importer import import_qti
from bank.models import AnswerOption, Course, Question, Test
from bank.qti import QTIError

from . import fixtures

MEDIA = tempfile.mkdtemp(prefix="quizbank-test-media-")


@override_settings(MEDIA_ROOT=MEDIA)
class ImportTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def test_imports_test_questions_and_options(self):
        summary = import_qti(fixtures.build_export(), "CS 101", "Intro to Computing")

        self.assertEqual(summary.tests_created, ["Quiz 1: Computing Basics"])
        self.assertEqual(summary.questions_created, 6)

        course = Course.objects.get(code="CS 101")
        self.assertEqual(course.name, "Intro to Computing")
        test = Test.objects.get(course=course)
        self.assertEqual(test.instructions, "Answer all questions.")
        self.assertEqual(
            list(test.items.values_list("question__source_ident", flat=True)),
            ["q_mc", "q_tf", "q_ms", "q_fb", "q_es", "q_ma"],
        )

        mc = Question.objects.get(source_ident="q_mc")
        self.assertEqual(mc.question_type, Question.Type.MULTIPLE_CHOICE)
        self.assertEqual(mc.points, 2)
        self.assertEqual(
            [(o.text, o.is_correct) for o in mc.options.all()],
            [("Central Processing Unit", True), ("Computer Power Unit", False),
             ("Central Program Utility", False)],
        )
        self.assertTrue(mc.image.name.startswith("question_images/"))

        other = Question.objects.get(source_ident="q_ma")
        self.assertEqual(other.question_type, Question.Type.OTHER)
        self.assertEqual(other.source_type, "matching_question")

    def test_reimporting_the_same_export_is_skipped(self):
        import_qti(fixtures.build_export(), "CS 101")
        summary = import_qti(fixtures.build_export(), "CS 101")

        self.assertEqual(summary.tests_created, [])
        self.assertEqual(summary.tests_skipped, ["Quiz 1: Computing Basics"])
        self.assertEqual(Question.objects.count(), 6)

    def test_same_export_into_another_course_is_allowed(self):
        import_qti(fixtures.build_export(), "CS 101")
        import_qti(fixtures.build_export(), "CS 102")
        self.assertEqual(Test.objects.count(), 2)

    def test_bad_file_writes_nothing(self):
        with self.assertRaises(QTIError):
            import_qti(io.BytesIO(b"junk"), "CS 101")
        self.assertFalse(Course.objects.exists())
        self.assertFalse(AnswerOption.objects.exists())


@override_settings(MEDIA_ROOT=MEDIA)
class ImportCommandTests(TestCase):
    def test_command_imports_a_file(self):
        with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
            tmp.write(fixtures.build_export().getvalue())
            tmp.flush()
            out = StringIO()
            call_command("import_qti", tmp.name, "--course", "CS 101", stdout=out)
        self.assertIn("Imported: Quiz 1: Computing Basics", out.getvalue())
        self.assertIn("6 question(s) added", out.getvalue())

    def test_command_reports_missing_file(self):
        with self.assertRaisesRegex(CommandError, "File not found"):
            call_command("import_qti", "/nope/missing.zip", "--course", "CS 101")
