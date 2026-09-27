"""Build a complete public demo: the demo account, sample courses, the SciQ
course, topic tags, and a simulated class on the first CS 101 quiz.

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

from bank.models import Test


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
        User.objects.create_user(username=username, password=password)
        self.stdout.write(self.style.SUCCESS(f"Demo ready. Sign in as {username!r}."))
