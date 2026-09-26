"""Pages students use to take a quiz through a share link.

Students don't sign in, so these views are exempt from the site's login
requirement. Each browser remembers the attempts it submitted (in the session),
so a student can see their own result and nobody else's.
"""

from django.contrib.auth.decorators import login_not_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from .grading import answers_from_post, submit_attempt
from .models import Assignment

SESSION_KEY = "quizbank_attempts"  # {share code: attempt id}


def remembered_attempt(request, assignment):
    """The attempt this browser submitted for an assignment, if any."""
    pk = request.session.get(SESSION_KEY, {}).get(assignment.code)
    return assignment.attempts.filter(pk=pk).first() if pk else None


def remember_attempt(request, assignment, attempt):
    attempts = request.session.get(SESSION_KEY, {})
    if attempt:
        attempts[assignment.code] = attempt.pk
    else:
        attempts.pop(assignment.code, None)
    request.session[SESSION_KEY] = attempts


class StudentPage(View):
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.assignment = get_object_or_404(Assignment.objects.select_related("test__course"), code=kwargs["code"])
        self.quiz = self.assignment.test


@method_decorator(login_not_required, name="dispatch")
class TakeQuizView(StudentPage):
    """The quiz itself. Answers stay hidden from the page until after submitting."""

    def items(self):
        return list(self.quiz.items.select_related("question").prefetch_related("question__options"))

    def render_quiz(self, request, **extra):
        items = self.items()
        return render(request, "bank/take.html", {
            "assignment": self.assignment,
            "quiz": self.quiz,
            "course": self.quiz.course,
            "items": items,
            "total_points": sum(item.question.points for item in items),
            **extra,
        })

    def get(self, request, code):
        # "Not you?" on the result page starts over on a shared computer.
        if request.GET.get("new"):
            remember_attempt(request, self.assignment, None)
            return redirect("bank:take", code=code)
        if remembered_attempt(request, self.assignment):
            return redirect("bank:take_done", code=code)
        return self.render_quiz(request)

    def post(self, request, code):
        if remembered_attempt(request, self.assignment):
            return redirect("bank:take_done", code=code)
        if not self.assignment.is_open:
            return self.render_quiz(request)
        name = " ".join(request.POST.get("student_name", "").split())[:100]
        if not name:
            return self.render_quiz(request, name_error="Enter your name so your instructor knows whose test this is.")

        questions = [item.question for item in self.items()]
        attempt = submit_attempt(self.assignment, name, answers_from_post(request.POST, questions))
        remember_attempt(request, self.assignment, attempt)
        return redirect("bank:take_done", code=code)


@method_decorator(login_not_required, name="dispatch")
class TakeDoneView(StudentPage):
    """The student's score, and their marked answers if the instructor allows it."""

    def get(self, request, code):
        attempt = remembered_attempt(request, self.assignment)
        if not attempt:
            return redirect("bank:take", code=code)
        responses = []
        if self.assignment.show_answers:
            responses = attempt.responses.select_related("question").prefetch_related("question__options", "selected")
        return render(request, "bank/take_done.html", {
            "assignment": self.assignment,
            "quiz": self.quiz,
            "course": self.quiz.course,
            "attempt": attempt,
            "pending": attempt.responses.filter(points__isnull=True).count(),
            "responses": responses,
        })
