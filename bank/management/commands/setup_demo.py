"""Build a complete public demo: the demo account, sample courses, the SciQ
course, topic tags, a simulated class on the first CS 101 quiz, and a small
sample class on the same quiz whose essays are waiting to be graded.

The account comes from QUIZBANK_DEMO_USERNAME and QUIZBANK_DEMO_PASSWORD. It is
a regular user, not staff, so it can use the whole site but not the admin.
Needs the trained essay grader and the SciQ download to be in the data
directory already. Run it on an empty database: it skips everything if the
demo account already exists.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from bank.grading import submit_attempt
from bank.models import Assignment, Question, Test
from bank.suggestions import fill_suggestions

# Hand-written answers to Quiz 1's essay ("Explain the difference between
# hardware and software. Give one example of each."), from excellent to wrong,
# so the grading page shows the AI suggestions doing something. The letters
# say whether each student got the five objective questions right (R) or wrong (W).
SAMPLE_CLASS = [
    ("Jordan Lee", "RRRRR",
     "Hardware is the physical parts of a computer, the things you can actually touch, like the processor, "
     "RAM, or the monitor. Software is the programs and instructions that tell the hardware what to do, like "
     "Windows or Google Chrome."),
    ("Priya Shah", "RRRWR",
     "Hardware is everything physical: the CPU that does the calculations, memory, storage drives, and devices "
     "like a mouse. Software is the instructions the hardware runs, from the operating system (macOS) to apps "
     "like Spotify."),
    ("Marcus Brown", "RWRRR",
     "Hardware is the machine and its parts. Software is the code that runs on it, for example Microsoft Word."),
    ("Sofia Garcia", "RRWRW", "hardware = physical stuff (mouse), software = programs (Excel)"),
    ("Ethan Nguyen", "RWWRR", "Hardware is harder to use and software is easier. A keyboard is hardware."),
    ("Olivia Chen", "WRRWR",
     "Software is the parts inside the computer like the hard drive, and hardware is the apps you download."),
    ("Noah Williams", "WWRWW", "I'm not sure, but computers are really useful for school and games."),
    ("Ava Johnson", "RRRRW",
     "Hardware refers to the physical components, such as a keyboard or a CPU. Software is a set of "
     "programs that run on the hardware, for example a web browser."),
]


def objective_answer(question, right):
    """A right or wrong answer to a choice or fill-in-the-blank question, as (option ids, text)."""
    options = list(question.options.all())
    correct = {o.pk for o in options if o.is_correct}
    wrong = [o.pk for o in options if not o.is_correct]
    if question.question_type == Question.Type.FILL_IN_BLANK:
        accepted = [o.text for o in options if o.is_correct]
        return set(), accepted[0] if right else "2"
    if right:
        return correct, ""
    if question.question_type == Question.Type.MULTIPLE_SELECT:
        return {sorted(correct)[0], wrong[0]}, ""
    return {wrong[0]}, ""


def create_sample_class(quiz):
    """Give `quiz` to the sample class, leaving the essays to grade, and fill
    in the AI suggestions so the grading page opens without waiting for the model."""
    assignment = Assignment.objects.create(test=quiz)
    questions = [item.question for item in quiz.items.select_related("question").prefetch_related("question__options")]
    for name, pattern, essay in SAMPLE_CLASS:
        marks = iter(pattern)
        answers = {}
        for question in questions:
            if question.question_type == Question.Type.ESSAY:
                answers[question.pk] = (set(), essay)
            else:
                answers[question.pk] = objective_answer(question, next(marks) == "R")
        attempt = submit_attempt(assignment, name, answers)
        fill_suggestions(list(attempt.responses.select_related("question")))
    return assignment


class Command(BaseCommand):
    help = "Fill an empty database with everything the public demo shows."

    def handle(self, *args, **options):
        username, password = settings.QUIZBANK_DEMO_USERNAME, settings.QUIZBANK_DEMO_PASSWORD
        if not username or not password:
            raise CommandError("Set QUIZBANK_DEMO_USERNAME and QUIZBANK_DEMO_PASSWORD first.")
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            self.stdout.write(f"Skipped: the demo account {username!r} already exists.")
            return

        call_command("load_demo_data", stdout=self.stdout)
        call_command("load_sciq", stdout=self.stdout)
        call_command("build_topics", stdout=self.stdout)
        quiz = Test.objects.filter(course__code="CS 101").order_by("id").first()
        if quiz:
            call_command("simulate_class", quiz.pk, stdout=self.stdout)
            assignment = create_sample_class(quiz)
            self.stdout.write(f"Gave “{quiz.title}” to {len(SAMPLE_CLASS)} sample students, essays left to grade. "
                              f"Share code: {assignment.code}")
        User.objects.create_user(username=username, password=password)
        self.stdout.write(self.style.SUCCESS(f"Demo ready. Sign in as {username!r}."))
