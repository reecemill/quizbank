"""Fill the bank with sample courses, so the pages have something to show.

Courses that already exist are skipped, so running this twice is safe. Delete
the sample courses in the admin when you're done with them.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.template.defaultfilters import pluralize

from bank.models import AnswerOption, Course, Question, Test, TestQuestion
from bank.qti import QUESTION_TYPES, html_to_text

# Our type code -> the Canvas type name, so the samples look imported.
CANVAS_TYPES = {code: name for name, code in QUESTION_TYPES.items()}


def q(kind, points, html, options=(), canvas_type=""):
    """One sample question. For choice questions, a leading * marks each
    correct option; fill-in-the-blank options are all accepted answers."""
    return {"kind": kind, "points": points, "html": html, "options": options, "canvas_type": canvas_type}


DEMO_COURSES = [
    {
        "code": "CS 101",
        "name": "Intro to Computing",
        "quizzes": [
            ("Quiz 1: Computing Basics", "Answer every question. Calculators aren't allowed.", [
                q("MC", 2, "<p>What does <strong>CPU</strong> stand for?</p>",
                  ["*Central Processing Unit", "Computer Power Unit", "Central Program Utility", "Core Processing Unit"]),
                q("TF", 1, "<p>RAM keeps its contents when the computer is turned off.</p>", ["True", "*False"]),
                q("MS", 2, "<p>Which of these are input devices? Select all that apply.</p>",
                  ["*Keyboard", "*Microphone", "Monitor", "*Mouse", "Printer"]),
                q("FB", 1, "<p>The binary number <code>1010</code> equals ____ in decimal.</p>", ["10"]),
                q("MC", 1, "<p>How many bits are in one byte?</p>", ["4", "*8", "16", "32"]),
                q("ES", 5, "<p>Explain the difference between hardware and software. Give one example of each.</p>"),
            ]),
            ("Quiz 2: Programming Fundamentals", "You may use scratch paper.", [
                q("MC", 2, "<p>What does this Python code print?</p><pre><code>x = 3\nprint(x * 2 + 1)</code></pre>",
                  ["5", "6", "*7", "9"]),
                q("TF", 1, "<p>In Python, one list can hold values of different types.</p>", ["*True", "False"]),
                q("MS", 2, "<p>Which of these are valid Python variable names?</p>",
                  ["*total_count", "2nd_place", "*_temp", "my-name"]),
                q("FB", 1, "<p>The keyword that defines a function in Python is ____.</p>", ["def"]),
                q("MC", 1, "<p>Which data structure is first in, first out (FIFO)?</p>",
                  ["Stack", "*Queue", "Tree", "Set"]),
                q("ES", 5, "<p>Describe what a loop is, and give an example of when you would use one.</p>"),
            ]),
        ],
        "unassigned": [
            q("MC", 1, "<p>Who created the Python programming language?</p>",
              ["*Guido van Rossum", "Dennis Ritchie", "James Gosling", "Bjarne Stroustrup"]),
        ],
    },
    {
        "code": "BIO 110",
        "name": "Principles of Biology",
        "quizzes": [
            ("Cell Structure", "Choose the best answer for each question.", [
                q("MC", 2, "<p>Which organelle makes most of a cell's ATP?</p>",
                  ["Nucleus", "Ribosome", "*Mitochondrion", "Golgi apparatus"]),
                q("TF", 1, "<p>Plant cells have a cell wall; animal cells do not.</p>", ["*True", "False"]),
                q("MS", 2, "<p>Which structures are found in both plant and animal cells?</p>",
                  ["*Nucleus", "*Cell membrane", "Chloroplast", "*Mitochondria", "Cell wall"]),
                q("FB", 1, "<p>Plants turn light into chemical energy through ____.</p>", ["photosynthesis"]),
                q("MC", 1, "<p>Glucose is C<sub>6</sub>H<sub>12</sub>O<sub>6</sub>. "
                           "How many carbon atoms are in one molecule of glucose?</p>", ["1", "*6", "12", "24"]),
                q("ES", 5, "<p>Explain why cells divide, and name the two main types of cell division.</p>"),
            ]),
            ("Genetics", "", [
                q("MC", 2, "<p>In pea plants, purple flowers (<em>P</em>) are dominant over white (<em>p</em>). "
                           "What fraction of the offspring of a <em>Pp</em> × <em>Pp</em> cross will have white flowers?</p>",
                  ["0", "*1/4", "1/2", "3/4"]),
                q("TF", 1, "<p>DNA is built from four bases: adenine, thymine, guanine, and cytosine.</p>",
                  ["*True", "False"]),
                q("FB", 1, "<p>In DNA, adenine pairs with ____.</p>", ["thymine", "T"]),
                q("MS", 2, "<p>Which of these are found in RNA? Select all that apply.</p>",
                  ["*Uracil", "Thymine", "*Ribose", "*Adenine", "Deoxyribose"]),
            ]),
        ],
        "unassigned": [],
    },
    {
        "code": "HIST 201",
        "name": "U.S. History Since 1865",
        "quizzes": [
            ("Reconstruction and the Gilded Age", "Answer all questions. Essay answers should be a paragraph or two.", [
                q("MC", 2, "<p>Which amendment abolished slavery in the United States?</p>",
                  ["*13th", "14th", "15th", "19th"]),
                q("TF", 1, "<p>The first transcontinental railroad was completed in 1869.</p>", ["*True", "False"]),
                q("MS", 2, "<p>Which of these are Reconstruction Amendments?</p>",
                  ["*13th", "*14th", "*15th", "16th", "19th"]),
                q("FB", 1, "<p>The 1896 Supreme Court case that upheld “separate but equal” was "
                           "<em>Plessy v.</em> ____.</p>", ["Ferguson"]),
                q("ES", 10, "<p>How did industrialization change daily life for American workers "
                            "between 1870 and 1900?</p>"),
                q("OT", 3, "<p>Match each inventor to the invention.</p>", canvas_type="matching_question"),
            ]),
        ],
        "unassigned": [
            q("MC", 1, "<p>What did Alexander Graham Bell patent in 1876?</p>",
              ["*The telephone", "The light bulb", "The phonograph", "The telegraph"]),
        ],
    },
]


def create_question(course, spec):
    question = Question.objects.create(
        course=course,
        question_type=spec["kind"],
        text=html_to_text(spec["html"]),
        text_html=spec["html"],
        points=spec["points"],
        source_type=spec["canvas_type"] or CANVAS_TYPES.get(spec["kind"], ""),
    )
    for order, text in enumerate(spec["options"]):
        is_correct = spec["kind"] == "FB" or text.startswith("*")
        AnswerOption.objects.create(question=question, text=text.removeprefix("*"), is_correct=is_correct, order=order)
    return question


class Command(BaseCommand):
    help = "Add sample courses, quizzes, and questions to explore the site with."

    @transaction.atomic
    def handle(self, *args, **options):
        for spec in DEMO_COURSES:
            if Course.objects.filter(code=spec["code"]).exists():
                self.stdout.write(f"Skipped {spec['code']}: that course already exists.")
                continue

            course = Course.objects.create(code=spec["code"], name=spec["name"])
            count = 0
            for title, instructions, questions in spec["quizzes"]:
                test = Test.objects.create(course=course, title=title, instructions=instructions)
                for order, question_spec in enumerate(questions, start=1):
                    TestQuestion.objects.create(test=test, question=create_question(course, question_spec), order=order)
                    count += 1
            for question_spec in spec["unassigned"]:
                create_question(course, question_spec)
                count += 1

            quizzes = len(spec["quizzes"])
            self.stdout.write(self.style.SUCCESS(
                f"Added {course.code}: {quizzes} quiz{pluralize(quizzes, 'zes')}, {count} questions."
            ))
