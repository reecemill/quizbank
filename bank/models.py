"""Question bank data model.

Adapted from the SPG8 / QuizPress senior design schema. The core is kept
(courses, questions, answer options, tests, and the test-question link); the
publisher, template, cover-page, and feedback tables were only used by the old
dashboards and are dropped.

Assignment, Attempt, and Response are new: they let students take a quiz online
through a share link, with objective questions graded automatically.
"""

import secrets

from django.db import models


class Course(models.Model):
    code = models.CharField(max_length=50, unique=True, help_text="e.g. CS 499")
    name = models.CharField(max_length=250, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}" if self.name else self.code


class Question(models.Model):
    class Type(models.TextChoices):
        MULTIPLE_CHOICE = "MC", "Multiple choice"
        TRUE_FALSE = "TF", "True/false"
        MULTIPLE_SELECT = "MS", "Multiple selection"
        FILL_IN_BLANK = "FB", "Fill in the blank"
        ESSAY = "ES", "Essay"
        OTHER = "OT", "Other"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="questions")
    question_type = models.CharField(max_length=2, choices=Type.choices)

    # Canvas stores prompts as HTML. The plain-text copy is what search,
    # duplicate detection, and tagging work on.
    text = models.TextField(help_text="Prompt as plain text.")
    text_html = models.TextField(blank=True, help_text="Prompt as imported (HTML).")

    points = models.DecimalField(max_digits=6, decimal_places=2, default=1)
    image = models.ImageField(upload_to="question_images/", blank=True)

    # Canvas's own item id, so re-importing the same export can be detected.
    source_ident = models.CharField(max_length=100, blank=True, db_index=True)
    # Original Canvas type name, kept when it maps to OTHER so nothing is lost.
    source_type = models.CharField(max_length=50, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"[{self.question_type}] {self.text[:60]}"


class AnswerOption(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    text = models.TextField()
    is_correct = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{'✓' if self.is_correct else '·'} {self.text[:60]}"


class Test(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="tests")
    title = models.CharField(max_length=200)
    instructions = models.TextField(blank=True)
    source_ident = models.CharField(max_length=100, blank=True, db_index=True)
    questions = models.ManyToManyField(Question, through="TestQuestion", related_name="tests")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["course", "title"]

    def __str__(self) -> str:
        return f"{self.title} ({self.course.code})"


class TestQuestion(models.Model):
    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="items")
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    order = models.PositiveIntegerField()

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(fields=["test", "question"], name="unique_question_per_test"),
        ]

    def __str__(self) -> str:
        return f"Q{self.order} in {self.test.title}"


# --------------------------------------------------------------------------
# Giving a quiz to students
# --------------------------------------------------------------------------

# Share codes avoid look-alike characters (0/o, 1/l/i) so they're easy to read aloud.
CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def new_share_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))


class Assignment(models.Model):
    """A quiz handed out to students through a share link. Anyone with the
    link can take it while it's open; no student accounts are needed."""

    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="assignments")
    code = models.CharField(max_length=16, unique=True, default=new_share_code)
    is_open = models.BooleanField(default=True, help_text="Students can only submit while this is on.")
    show_answers = models.BooleanField(
        default=False, help_text="After submitting, students see which answers were right."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.test.title} ({self.code})"


class Attempt(models.Model):
    """One student's submitted answers to an assignment."""

    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="attempts")
    student_name = models.CharField(max_length=100)
    submitted_at = models.DateTimeField(auto_now_add=True)
    # Points so far. Essay answers count once the instructor grades them.
    score = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    max_score = models.DecimalField(max_digits=7, decimal_places=2, default=0)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self) -> str:
        return f"{self.student_name}: {self.assignment.test.title}"

    @property
    def percent(self) -> int:
        return round(self.score / self.max_score * 100) if self.max_score else 0

    def update_score(self) -> None:
        self.score = sum(r.points for r in self.responses.all() if r.points is not None)
        self.save(update_fields=["score"])


class Response(models.Model):
    """A student's answer to one question. `points` is empty until the answer
    is graded; objective questions are graded on submit, essays by hand."""

    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="responses")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="responses")
    order = models.PositiveIntegerField(default=0)
    selected = models.ManyToManyField(AnswerOption, blank=True)
    text = models.TextField(blank=True)
    points = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(fields=["attempt", "question"], name="one_response_per_question"),
        ]

    def __str__(self) -> str:
        return f"{self.attempt.student_name}, Q{self.order}"

    @property
    def needs_grading(self) -> bool:
        return self.points is None

    @property
    def status(self) -> str:
        """'pending', 'full', 'partial', or 'zero', for showing how it went."""
        if self.points is None:
            return "pending"
        if self.points >= self.question.points:
            return "full"
        return "partial" if self.points > 0 else "zero"
