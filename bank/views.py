"""Pages for browsing the question bank, importing Canvas quizzes, and giving
quizzes to students. The pages students use are in student_views.py."""

import csv
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.defaultfilters import pluralize
from django.urls import reverse
from django.utils.text import slugify
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView

from .forms import ImportForm
from .grading import CENT, HAND_GRADED_TYPES
from .importer import import_qti
from .models import Assignment, Course, Question, Response, Test
from .qti import QTIError
from .templatetags.bank_ui import num


def course_crumbs(course, *rest):
    """Breadcrumbs that start Dashboard › <course code>."""
    return [
        ("Dashboard", reverse("bank:dashboard")),
        (course.code, reverse("bank:course", args=[course.pk])),
        *rest,
    ]


class PageMixin:
    """What every page's template needs: a title, breadcrumbs, and which
    tab (or, on course pages, which course) the tab bar should highlight.

    `crumbs` is a list of (label, url) pairs; the last one is the page itself.
    """

    title = ""
    nav = ""

    def get_title(self):
        return self.title

    def get_subtitle(self):
        return ""

    def get_crumbs(self):
        return [("Dashboard", reverse("bank:dashboard")), (self.get_title(), None)]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        crumbs = self.get_crumbs()
        context.update(
            title=self.get_title(),
            subtitle=self.get_subtitle(),
            nav=self.nav,
            crumbs=crumbs,
            back=crumbs[-2] if len(crumbs) > 1 else None,
        )
        return context


class DashboardView(PageMixin, TemplateView):
    template_name = "bank/dashboard.html"
    title = "Dashboard"
    nav = "dashboard"

    def get_crumbs(self):
        return [("Dashboard", None)]

    def get_context_data(self, **kwargs):
        courses = Course.objects.annotate(
            num_questions=Count("questions", distinct=True),
            num_quizzes=Count("tests", distinct=True),
        )
        return super().get_context_data(courses=courses, **kwargs)


class QuestionListView(PageMixin, ListView):
    """Every question, or one course's questions (the course home page).

    Filters: ?q= matches question text, ?type= is a Question.Type code.
    """

    template_name = "bank/question_list.html"
    context_object_name = "questions"
    paginate_by = 50

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.course = get_object_or_404(Course, pk=kwargs["pk"]) if "pk" in kwargs else None
        self.nav = "course" if self.course else "questions"
        self.query = request.GET.get("q", "").strip()
        type_code = request.GET.get("type", "")
        self.type_code = type_code if type_code in Question.Type.values else ""

    def get_queryset(self):
        questions = Question.objects.select_related("course")
        if self.course:
            questions = questions.filter(course=self.course)
        if self.query:
            # A plain text match for now. Semantic search (stage 2) replaces this.
            questions = questions.filter(text__icontains=self.query)
        if self.type_code:
            questions = questions.filter(question_type=self.type_code)
        return questions

    def get_title(self):
        return self.course.code if self.course else "All Questions"

    def get_subtitle(self):
        return self.course.name if self.course else "Every course in your bank"

    def get_crumbs(self):
        return course_crumbs(self.course) if self.course else super().get_crumbs()

    def query_string(self, **changes):
        """This page's query string with some parameters changed. Changing a
        filter always goes back to the first page."""
        params = self.request.GET.copy()
        params.pop("page", None)
        for key, value in changes.items():
            if value:
                params[key] = value
            else:
                params.pop(key, None)
        return params.urlencode()

    def get_context_data(self, **kwargs):
        chips = [
            {
                "label": label,
                "url": f"?{qs}" if (qs := self.query_string(type=code)) else self.request.path,
                "selected": code == self.type_code,
            }
            for code, label in [("", "All"), *Question.Type.choices]
        ]
        return super().get_context_data(
            course=self.course,
            query=self.query,
            type_code=self.type_code,
            type_chips=chips,
            page_query=self.query_string(),
            **kwargs,
        )


class QuestionDetailView(PageMixin, DetailView):
    template_name = "bank/question_detail.html"
    context_object_name = "question"
    queryset = Question.objects.select_related("course").prefetch_related("options", "tests")
    title = "Question"
    nav = "course"

    def get_subtitle(self):
        return f"{self.object.course.code} · {self.object.get_question_type_display()}"

    def get_crumbs(self):
        return course_crumbs(self.object.course, ("Question", None))

    def get_context_data(self, **kwargs):
        return super().get_context_data(course=self.object.course, **kwargs)


class QuizListView(PageMixin, ListView):
    """One course's quizzes. The model calls them tests; Canvas calls them quizzes."""

    template_name = "bank/quiz_list.html"
    context_object_name = "quizzes"
    nav = "course"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.course = get_object_or_404(Course, pk=kwargs["pk"])

    def get_queryset(self):
        return self.course.tests.annotate(
            num_questions=Count("items"),
            total_points=Sum("items__question__points"),
        )

    def get_title(self):
        return self.course.code

    def get_subtitle(self):
        return self.course.name

    def get_crumbs(self):
        return course_crumbs(self.course, ("Quizzes", None))

    def get_context_data(self, **kwargs):
        return super().get_context_data(course=self.course, **kwargs)


class QuizDetailView(PageMixin, DetailView):
    template_name = "bank/quiz_detail.html"
    context_object_name = "quiz"
    queryset = Test.objects.select_related("course")
    nav = "course"

    def get_title(self):
        return self.object.title

    def get_crumbs(self):
        course = self.object.course
        quizzes_url = reverse("bank:course_quizzes", args=[course.pk])
        return course_crumbs(course, ("Quizzes", quizzes_url), (self.object.title, None))

    def get_context_data(self, **kwargs):
        items = list(self.object.items.select_related("question").prefetch_related("question__options"))
        return super().get_context_data(
            course=self.object.course,
            items=items,
            total_points=sum(item.question.points for item in items),
            assignments=self.object.assignments.annotate(num_attempts=Count("attempts")),
            **kwargs,
        )


class ImportView(PageMixin, FormView):
    """Upload a Canvas QTI export. ?course=<code> pre-fills the course."""

    template_name = "bank/import.html"
    form_class = ImportForm
    title = "Import"
    nav = "import"

    def get_subtitle(self):
        return "Add quizzes from a Canvas export"

    def get_initial(self):
        code = self.request.GET.get("course", "").strip()
        course = Course.objects.filter(code=code).first() if code else None
        return {"course_code": code, "course_name": course.name if course else ""}

    def get_context_data(self, **kwargs):
        course_codes = Course.objects.values_list("code", flat=True)
        return super().get_context_data(course_codes=course_codes, **kwargs)

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            summary = import_qti(data["file"], data["course_code"], data["course_name"])
        except QTIError as exc:
            form.add_error("file", str(exc))
            return self.form_invalid(form)

        course = Course.objects.get(code=data["course_code"])
        created, count = summary.tests_created, summary.questions_created
        if len(created) == 1:
            messages.success(self.request, f"Imported “{created[0]}” with {count} question{pluralize(count)}.")
        elif created:
            messages.success(self.request, f"Imported {len(created)} quizzes with {count} question{pluralize(count)}.")
        if summary.tests_skipped:
            skipped = ", ".join(f"“{title}”" for title in summary.tests_skipped)
            messages.info(self.request, f"Already in {course.code}, so skipped: {skipped}.")
        if summary.warnings:
            messages.warning(self.request, "Some questions need a look:\n" + "\n".join(summary.warnings))
        return redirect("bank:course", pk=course.pk)


# --------------------------------------------------------------------------
# Giving a quiz to students, and seeing the results
# --------------------------------------------------------------------------

class GiveQuizView(View):
    """Make a share link for a quiz. Students open the link, type their name,
    and take the quiz; objective questions are graded when they submit."""

    def post(self, request, pk):
        quiz = get_object_or_404(Test, pk=pk)
        assignment = Assignment.objects.create(test=quiz)
        messages.success(request, "Your quiz link is ready. Share it with your students.")
        return redirect("bank:results", code=assignment.code)


class AssignmentMixin(PageMixin):
    """Pages about one share link: its results, and one student's attempt."""

    nav = "course"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.assignment = get_object_or_404(Assignment.objects.select_related("test__course"), code=kwargs["code"])
        self.quiz = self.assignment.test
        self.course = self.quiz.course

    def quiz_crumbs(self, *rest):
        return course_crumbs(
            self.course,
            ("Quizzes", reverse("bank:course_quizzes", args=[self.course.pk])),
            (self.quiz.title, reverse("bank:quiz", args=[self.quiz.pk])),
            *rest,
        )

    def get_context_data(self, **kwargs):
        return super().get_context_data(assignment=self.assignment, quiz=self.quiz, course=self.course, **kwargs)


def attempts_with_pending(assignment):
    """An assignment's attempts, each with num_pending: answers still to grade."""
    return assignment.attempts.annotate(num_pending=Count("responses", filter=Q(responses__points__isnull=True)))


class ResultsView(AssignmentMixin, TemplateView):
    template_name = "bank/results.html"
    title = "Results"

    def get_subtitle(self):
        return self.quiz.title

    def get_crumbs(self):
        return self.quiz_crumbs(("Results", None))

    def get_context_data(self, **kwargs):
        attempts = list(attempts_with_pending(self.assignment))

        # How the class did on each question, from the answers graded so far.
        graded = (
            Response.objects.filter(attempt__assignment=self.assignment, points__isnull=False)
            .values("question_id")
            .annotate(earned=Sum("points"), count=Count("id"))
        )
        by_question = {row["question_id"]: row for row in graded}
        breakdown = []
        for number, item in enumerate(self.quiz.items.select_related("question"), start=1):
            question, row = item.question, by_question.get(item.question_id)
            percent = round(row["earned"] / (row["count"] * question.points) * 100) if row and question.points else None
            breakdown.append({"number": number, "question": question, "percent": percent})

        return super().get_context_data(
            attempts=attempts,
            share_url=self.request.build_absolute_uri(reverse("bank:take", args=[self.assignment.code])),
            average=round(sum(a.percent for a in attempts) / len(attempts)) if attempts else None,
            to_grade=sum(a.num_pending for a in attempts),
            breakdown=breakdown,
            **kwargs,
        )


class AssignmentSettingsView(View):
    """Turn a share link's switches on or off: open for submissions, and
    showing students the answers after they submit."""

    fields = {"is_open", "show_answers"}

    def post(self, request, code):
        assignment = get_object_or_404(Assignment, code=code)
        field = request.POST.get("field")
        if field in self.fields:
            setattr(assignment, field, request.POST.get("value") == "1")
            assignment.save(update_fields=[field])
        return redirect("bank:results", code=code)


def spreadsheet_safe(value: str) -> str:
    """Stop spreadsheet apps from running a student-typed name as a formula."""
    return f"'{value}" if value[:1] in ("=", "+", "-", "@") else value


class ResultsCSVView(View):
    def get(self, request, code):
        assignment = get_object_or_404(Assignment.objects.select_related("test"), code=code)
        filename = f"{slugify(assignment.test.title) or 'quiz'}-results.csv"
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        writer = csv.writer(response)
        writer.writerow(["Student", "Submitted (UTC)", "Score", "Out of", "Percent", "Answers to grade"])
        for attempt in attempts_with_pending(assignment).order_by("student_name"):
            writer.writerow([
                spreadsheet_safe(attempt.student_name),
                attempt.submitted_at.strftime("%Y-%m-%d %H:%M"),
                num(attempt.score),
                num(attempt.max_score),
                attempt.percent,
                attempt.num_pending,
            ])
        return response


class AttemptView(AssignmentMixin, TemplateView):
    """One student's answers, marked. Essay answers get a points box so the
    instructor can grade them."""

    template_name = "bank/attempt.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.attempt = get_object_or_404(self.assignment.attempts, pk=kwargs["attempt_pk"])

    def get_title(self):
        return self.attempt.student_name

    def get_subtitle(self):
        return f"{num(self.attempt.score)} / {num(self.attempt.max_score)} points · {self.attempt.percent}%"

    def get_crumbs(self):
        return self.quiz_crumbs(
            ("Results", reverse("bank:results", args=[self.assignment.code])),
            (self.attempt.student_name, None),
        )

    def get_context_data(self, **kwargs):
        responses = list(
            self.attempt.responses.select_related("question").prefetch_related("question__options", "selected")
        )
        return super().get_context_data(
            attempt=self.attempt,
            responses=responses,
            has_hand_graded=any(r.question.question_type in HAND_GRADED_TYPES for r in responses),
            **kwargs,
        )

    def post(self, request, *args, **kwargs):
        changed, errors = [], []
        for response in self.attempt.responses.select_related("question"):
            key = f"points-{response.pk}"
            if response.question.question_type not in HAND_GRADED_TYPES or key not in request.POST:
                continue
            raw = request.POST[key].strip()
            if not raw:
                response.points = None
            else:
                most = response.question.points
                try:
                    value = Decimal(raw)
                except InvalidOperation:
                    value = None
                if value is None or not value.is_finite() or not 0 <= value <= most:
                    errors.append(f"Question {response.order}: enter a number from 0 to {num(most)}.")
                    continue
                response.points = value.quantize(CENT)
            changed.append(response)

        if errors:
            messages.error(request, "Grades not saved.\n" + "\n".join(errors))
            return redirect(request.path)
        for response in changed:
            response.save(update_fields=["points"])
        self.attempt.update_score()
        messages.success(request, f"Saved grades for {self.attempt.student_name}.")
        return redirect("bank:results", code=self.assignment.code)
