"""Parser tests. Pure Python: no database needed."""

import io
import zipfile
from unittest import TestCase

from bank.qti import QTIError, html_to_text, parse_qti_zip

from . import fixtures


def by_ident(result):
    return {q.ident: q for a in result.assessments for q in a.questions}


class ParseExportTests(TestCase):
    def setUp(self):
        self.result = parse_qti_zip(fixtures.build_export())
        self.questions = by_ident(self.result)

    def test_reads_quiz_title_and_instructions_from_metadata(self):
        [quiz] = self.result.assessments
        self.assertEqual(quiz.title, "Quiz 1: Computing Basics")
        self.assertEqual(quiz.instructions, "Answer all questions.")

    def test_skips_text_only_blocks(self):
        self.assertNotIn("q_txt", self.questions)
        self.assertEqual(self.result.question_count, 6)

    def test_maps_canvas_types_to_codes(self):
        types = {ident: q.question_type for ident, q in self.questions.items()}
        self.assertEqual(types, {"q_mc": "MC", "q_tf": "TF", "q_ms": "MS",
                                 "q_fb": "FB", "q_es": "ES", "q_ma": "OT"})

    def test_prompt_html_becomes_plain_text(self):
        q = self.questions["q_mc"]
        self.assertEqual(q.text, "What does CPU stand for?")
        self.assertIn("<strong>CPU</strong>", q.text_html)

    def test_points_are_read(self):
        self.assertEqual(self.questions["q_mc"].points, 2.0)
        self.assertEqual(self.questions["q_es"].points, 10.0)

    def test_multiple_choice_correct_answer_ignores_feedback_rules(self):
        options = self.questions["q_mc"].options
        self.assertEqual([o.text for o in options if o.is_correct], ["Central Processing Unit"])
        self.assertEqual(len(options), 3)

    def test_true_false_correct_answer(self):
        options = self.questions["q_tf"].options
        self.assertEqual([o.text for o in options if o.is_correct], ["True"])

    def test_multiple_answers_excludes_negated_choices(self):
        options = self.questions["q_ms"].options
        self.assertEqual(sorted(o.text for o in options if o.is_correct), ["Python", "Rust"])

    def test_fill_in_blank_keeps_every_accepted_answer(self):
        options = self.questions["q_fb"].options
        self.assertEqual(sorted(o.text for o in options), ["DEF", "def"])
        self.assertTrue(all(o.is_correct for o in options))

    def test_embedded_image_is_extracted(self):
        image = self.questions["q_mc"].image
        self.assertIsNotNone(image)
        self.assertEqual(image.filename, "cpu diagram.png")
        self.assertEqual(image.data, fixtures.PNG_BYTES)

    def test_unsupported_type_is_kept_and_warned(self):
        self.assertEqual(self.questions["q_ma"].text, "Match each term to its definition.")
        self.assertTrue(any("matching_question" in w for w in self.result.warnings))


class ParseEdgeCaseTests(TestCase):
    def test_metadata_order_does_not_matter(self):
        # The old importer read metadata by position and broke on this.
        export = fixtures.build_export([("quiz1", "Q", [fixtures.multiple_choice_item(reverse_meta=True)])])
        [q] = by_ident(parse_qti_zip(export)).values()
        self.assertEqual(q.question_type, "MC")
        self.assertEqual(q.points, 2.0)

    def test_missing_image_file_is_not_an_error(self):
        export = fixtures.build_export(include_image=False)
        self.assertIsNone(by_ident(parse_qti_zip(export))["q_mc"].image)

    def test_multiple_quizzes_in_one_export(self):
        export = fixtures.build_export([
            ("quiz1", "First", [fixtures.true_false_item()]),
            ("quiz2", "Second", [fixtures.essay_item(), fixtures.short_answer_item()]),
        ])
        result = parse_qti_zip(export)
        self.assertEqual(sorted(a.title for a in result.assessments), ["First", "Second"])
        self.assertEqual(result.question_count, 3)

    def test_rejects_non_zip(self):
        with self.assertRaisesRegex(QTIError, "isn't a zip"):
            parse_qti_zip(io.BytesIO(b"not a zip"))

    def test_rejects_zip_without_quizzes(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("notes.txt", "hello")
        buf.seek(0)
        with self.assertRaisesRegex(QTIError, "No quizzes"):
            parse_qti_zip(buf)

    def test_rejects_malformed_xml(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("quiz1/quiz1.xml", "<questestinterop><assessment>")
        buf.seek(0)
        with self.assertRaisesRegex(QTIError, "Malformed XML"):
            parse_qti_zip(buf)


class HtmlToTextTests(TestCase):
    def test_collapses_whitespace_and_tags(self):
        self.assertEqual(html_to_text("<p>Hello\n  <b>world</b></p><p>again</p>"), "Hello world again")

    def test_empty(self):
        self.assertEqual(html_to_text(""), "")
