"""Page tests: every screen renders, filters work, and uploads import."""

import shutil
import tempfile
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from bank.models import AnswerOption, Course, Question, Test
from bank.templatetags.bank_ui import points, question_html

from . import fixtures

MEDIA = tempfile.mkdtemp(prefix="quizbank-test-media-")


def load_demo_data():
    call_command("load_demo_data", stdout=StringIO())


class LoginTests(TestCase):
    def test_pages_require_login(self):
        response = self.client.get(reverse("bank:dashboard"))
        self.assertRedirects(response, "/login/?next=/")

    def test_login_page_renders(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Sign In")

    def test_login_page_hides_demo_account_by_default(self):
        response = self.client.get(reverse("login"))
        self.assertNotContains(response, "public demo")

    @override_settings(QUIZBANK_DEMO_USERNAME="demo", QUIZBANK_DEMO_PASSWORD="demo-password")
    def test_login_page_shows_and_fills_in_demo_account(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "public demo")
        self.assertContains(response, 'value="demo"')
        self.assertContains(response, 'value="demo-password"')

    def test_logout_signs_out(self):
        user = get_user_model().objects.create_user("teacher", password="a-long-password")
        self.client.force_login(user)
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))
        self.assertRedirects(self.client.get("/"), "/login/?next=/")


@override_settings(MEDIA_ROOT=MEDIA)
class PageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        load_demo_data()
        cls.user = get_user_model().objects.create_user("teacher", password="a-long-password")
        cls.course = Course.objects.get(code="CS 101")
        cls.quiz = Test.objects.get(title="Quiz 1: Computing Basics")
        cls.question = Question.objects.get(text="What does CPU stand for?")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.client.force_login(self.user)

    def test_every_page_renders(self):
        urls = [
            reverse("bank:dashboard"),
            reverse("bank:questions"),
            reverse("bank:course", args=[self.course.pk]),
            reverse("bank:course_quizzes", args=[self.course.pk]),
            reverse("bank:question", args=[self.question.pk]),
            reverse("bank:quiz", args=[self.quiz.pk]),
            reverse("bank:import"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_unknown_ids_are_404(self):
        for name in ["bank:course", "bank:course_quizzes", "bank:question", "bank:quiz"]:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name, args=[9999])).status_code, 404)

    def test_dashboard_shows_course_cards(self):
        response = self.client.get(reverse("bank:dashboard"))
        self.assertContains(response, "Intro to Computing")
        self.assertContains(response, "13 questions · 2 quizzes")

    def test_search_matches_question_text(self):
        response = self.client.get(reverse("bank:questions"), {"q": "cpu"})
        self.assertEqual(list(response.context["questions"]), [self.question])
        self.assertContains(response, "1 result for “cpu”")

    def test_type_filter(self):
        response = self.client.get(reverse("bank:course", args=[self.course.pk]), {"type": "TF"})
        questions = list(response.context["questions"])
        self.assertEqual(len(questions), 2)
        self.assertTrue(all(q.question_type == "TF" for q in questions))

    def test_unknown_type_filter_is_ignored(self):
        response = self.client.get(reverse("bank:course", args=[self.course.pk]), {"type": "ZZ"})
        self.assertEqual(len(response.context["questions"]), self.course.questions.count())

    def test_course_page_only_lists_that_course(self):
        response = self.client.get(reverse("bank:course", args=[self.course.pk]))
        self.assertTrue(all(q.course == self.course for q in response.context["questions"]))

    def test_quiz_page_lists_questions_in_order_and_marks_answers(self):
        response = self.client.get(reverse("bank:quiz", args=[self.quiz.pk]))
        items = response.context["items"]
        self.assertEqual([item.order for item in items], list(range(1, 7)))
        correct_choices = AnswerOption.objects.filter(
            question__tests=self.quiz, question__question_type__in=["MC", "TF", "MS"], is_correct=True,
        ).count()
        self.assertContains(response, "Correct answer", count=correct_choices)
        self.assertContains(response, "Question 6")

    def test_tab_bar_marks_the_current_tab(self):
        response = self.client.get(reverse("bank:dashboard"))
        self.assertContains(response, f'<a class="tab" href="{reverse("bank:dashboard")}" aria-current="page">', html=False)
        response = self.client.get(reverse("bank:questions"))
        self.assertContains(response, f'<a class="tab" href="{reverse("bank:questions")}" aria-current="page">', html=False)

    def test_courses_menu_shows_the_current_course(self):
        response = self.client.get(reverse("bank:quiz", args=[self.quiz.pk]))
        self.assertContains(response, '<span class="nav-pill-text">CS 101</span>')
        response = self.client.get(reverse("bank:dashboard"))
        self.assertContains(response, '<span class="nav-pill-text">Courses</span>')

    def test_admin_link_is_for_staff_only(self):
        self.assertNotContains(self.client.get(reverse("bank:dashboard")), "Admin site")
        staff = get_user_model().objects.create_user("admin", password="a-long-password", is_staff=True)
        self.client.force_login(staff)
        self.assertContains(self.client.get(reverse("bank:dashboard")), "Admin site")

    def test_every_page_has_the_search_palette(self):
        for url in [reverse("bank:dashboard"), reverse("bank:quiz", args=[self.quiz.pk]), reverse("bank:import")]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, "data-palette")
                self.assertContains(response, f'action="{reverse("bank:questions")}"')

    def test_question_page_links_to_its_quiz(self):
        response = self.client.get(reverse("bank:question", args=[self.question.pk]))
        self.assertContains(response, reverse("bank:quiz", args=[self.quiz.pk]))

    def test_import_prefills_the_course(self):
        response = self.client.get(reverse("bank:import"), {"course": "CS 101"})
        self.assertEqual(response.context["form"].initial["course_name"], "Intro to Computing")

    def test_import_upload(self):
        upload = SimpleUploadedFile("export.zip", fixtures.build_export().read(), "application/zip")
        response = self.client.post(
            reverse("bank:import"),
            {"file": upload, "course_code": "CS 499", "course_name": "Senior Design"},
            follow=True,
        )
        course = Course.objects.get(code="CS 499")
        self.assertRedirects(response, reverse("bank:course", args=[course.pk]))
        self.assertEqual(course.questions.count(), 6)
        self.assertContains(response, "Imported “Quiz 1: Computing Basics” with 6 questions.")
        self.assertContains(response, "Some questions need a look")

    def test_import_rejects_a_file_that_is_not_a_zip(self):
        upload = SimpleUploadedFile("export.zip", b"not a zip", "application/zip")
        response = self.client.post(reverse("bank:import"), {"file": upload, "course_code": "CS 499"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("isn't a zip archive", response.context["form"].errors["file"][0])
        self.assertFalse(Course.objects.filter(code="CS 499").exists())

    def test_import_rejects_other_file_types(self):
        upload = SimpleUploadedFile("export.txt", b"hello", "text/plain")
        response = self.client.post(reverse("bank:import"), {"file": upload, "course_code": "CS 499"})
        self.assertIn("file", response.context["form"].errors)

    def test_demo_data_is_safe_to_load_twice(self):
        before = Question.objects.count()
        load_demo_data()
        self.assertEqual(Question.objects.count(), before)


class TemplateHelperTests(TestCase):
    def test_question_html_removes_scripts_and_images(self):
        question = Question(text_html='<p><strong>Hi</strong><script>alert(1)</script><img src="x" onerror="alert(1)">'
                                      '<a href="javascript:alert(1)">link</a></p>')
        html = question_html(question)
        self.assertIn("<strong>Hi</strong>", html)
        self.assertNotIn("script", html)
        self.assertNotIn("<img", html)
        self.assertNotIn("javascript:", html)

    def test_question_html_falls_back_to_escaped_text(self):
        self.assertEqual(question_html(Question(text="a < b")), "<p>a &lt; b</p>")

    def test_points(self):
        self.assertEqual(points(1), "1 pt")
        self.assertEqual(points("2.00"), "2 pts")
        self.assertEqual(points("1.50"), "1.5 pts")
        self.assertEqual(points("10.00"), "10 pts")
        self.assertEqual(points(None), "0 pts")
