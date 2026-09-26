"""Group a course's questions into topics (or every course's)."""

from django.core.management.base import BaseCommand, CommandError

from bank.models import Course
from bank.topics import MIN_QUESTIONS, build_topics


class Command(BaseCommand):
    help = "Group questions into topics with sentence embeddings and k-means, and tag each question."

    def add_arguments(self, parser):
        parser.add_argument("--course", help="A course code, like 'CS 101'. Leave out for every course.")

    def handle(self, *args, **options):
        courses = Course.objects.all()
        if options["course"]:
            courses = courses.filter(code=options["course"])
            if not courses.exists():
                raise CommandError(f"No course with code {options['course']!r}.")
        for course in courses:
            topics = build_topics(course)
            if not topics:
                self.stdout.write(f"{course.code}: fewer than {MIN_QUESTIONS} questions, so no topics.")
                continue
            self.stdout.write(self.style.SUCCESS(f"{course.code}: {len(topics)} topics"))
            for topic in topics:
                self.stdout.write(f"  {topic.size:>4}  {topic.label}")
