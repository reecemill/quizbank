from django.core.management.base import BaseCommand, CommandError

from bank.importer import import_qti
from bank.qti import QTIError


class Command(BaseCommand):
    help = "Import a Canvas QTI quiz export (.zip) into the question bank."

    def add_arguments(self, parser):
        parser.add_argument("zip_path", help="Path to the Canvas QTI export .zip")
        parser.add_argument("--course", required=True, help="Course code, e.g. 'CS 499'")
        parser.add_argument("--course-name", default="", help="Course name (used when creating the course)")

    def handle(self, *args, zip_path, course, course_name, **options):
        try:
            summary = import_qti(zip_path, course, course_name)
        except FileNotFoundError as exc:
            raise CommandError(f"File not found: {zip_path}") from exc
        except QTIError as exc:
            raise CommandError(str(exc)) from exc

        for title in summary.tests_created:
            self.stdout.write(self.style.SUCCESS(f"Imported: {title}"))
        for title in summary.tests_skipped:
            self.stdout.write(f"Skipped (already imported): {title}")
        for warning in summary.warnings:
            self.stdout.write(self.style.WARNING(warning))
        self.stdout.write(f"{summary.questions_created} question(s) added to {course}.")
